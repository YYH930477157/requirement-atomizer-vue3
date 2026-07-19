"""AI 抽取需求的审核裁决存储（独立于确定性 atomic 的状态机）。

文档批注视图里，专家直接在批注上裁决 AI 抽取出的需求。AI 需求没有 atomic 那套
review_states 状态机，这里给它一套轻量的覆盖式裁决：

- 内容稳定 ID（ai_req_id）：从 source_section + source_quote + title 取指纹，跨复跑稳定
  （merged_spec 里的 REQ-NNN 是位置号，会随抽取结果漂移，不能用作持久裁决主键）。
- ai_review_states.jsonl 追加写、读时取每个 ai_req_id 的最新一行（最近裁决覆盖）。
- 裁决含 status + 可选 module_override（专家改模块）+ reason；纯本地单用户工具，不做状态机约束。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from io_utils import read_jsonl_recover_torn_tail
from requirements_analysis_schema import normalize_ownership

AI_REVIEW_STATES = "ai_review_states.jsonl"
VALID_AI_STATUS = {"accepted", "rejected", "needs_discussion", "expert_pending", "draft"}
_AI_REVIEW_LOCKS: dict[Path, RLock] = {}
_AI_REVIEW_LOCKS_GUARD = RLock()
_AI_REVIEW_LOCK_TIMEOUT_S = 10.0
_AI_REVIEW_LOCK_STALE_AFTER_S = 300.0
LOGGER = logging.getLogger("requirement_atomizer")


def ai_req_id(req: dict[str, Any]) -> str:
    """内容稳定 ID：source_section + source_quote + title 的 sha1 指纹（防 REQ-NNN 位置漂移）。"""
    basis = "|".join([
        str(req.get("source_section") or ""),
        str(req.get("source_quote") or ""),
        str(req.get("title") or ""),
    ])
    return "AIR-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def source_ai_requirement_id(req: dict[str, Any]) -> str:
    """裁决/批注/分析统一的需求主键：行内显式 id 优先，否则内容指纹 ai_req_id。

    唯一权威实现——api_server / ai_extract / requirements_analysis 都用它，三份复制迟早分叉。
    警告：绝不能把位置型编号（make_doc 的 REQ-NNN）写进这些字段，否则复跑后裁决静默失配。
    """
    for key in ("ai_req_id", "stable_req_id", "req_id"):
        explicit = str(req.get(key) or "").strip()
        if explicit:
            return explicit
    return ai_req_id(req)


def read_ai_review_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    """取每个 ai_req_id 的最新裁决，并与追加写使用同一进程锁。"""
    root = Path(out_dir).expanduser().resolve()
    path = root / AI_REVIEW_STATES
    states: dict[str, dict[str, Any]] = {}
    with _ai_review_state_lock(root):
        if not path.exists():
            return states
        try:
            rows = read_jsonl_recover_torn_tail(path)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            # 历史文件可能已有完整换行的坏记录。保留后续有效裁决，但必须告警；
            # 新写入由下方跨进程锁串行化，不再制造交错行。
            rows = []
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning(
                            "skipping corrupt %s record at line %d",
                            AI_REVIEW_STATES,
                            line_number,
                        )
                        continue
                    if not isinstance(row, dict):
                        LOGGER.warning(
                            "skipping non-object %s record at line %d",
                            AI_REVIEW_STATES,
                            line_number,
                        )
                        continue
                    rows.append(row)
        for row in rows:
            rid = str(row.get("ai_req_id") or "")
            if rid:
                states[rid] = row
    return states


@contextmanager
def _ai_review_state_lock(
    out_dir: Path,
    *,
    timeout_s: float = _AI_REVIEW_LOCK_TIMEOUT_S,
    stale_after_s: float = _AI_REVIEW_LOCK_STALE_AFTER_S,
) -> Iterator[None]:
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _ai_process_lock_for(root):
        lock_path = root / "ai_review_states.lock"
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_ai_lock(lock_path, stale_after_s):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for AI review state lock: {lock_path}")
                time.sleep(0.01)
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _ai_process_lock_for(out_dir: Path) -> RLock:
    with _AI_REVIEW_LOCKS_GUARD:
        return _AI_REVIEW_LOCKS.setdefault(out_dir, RLock())


def _remove_stale_ai_lock(lock_path: Path, stale_after_s: float) -> bool:
    if stale_after_s < 0:
        return False
    try:
        age_s = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True
    if age_s < stale_after_s:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    return True


def apply_ai_review_action(
    out_dir: Path,
    ai_req_id_value: str,
    status: str,
    *,
    module_override: str | None = None,
    ownership_override: str | None = None,
    reason: str = "",
    actor: str | None = None,
) -> dict[str, Any]:
    """追加一条 AI 需求裁决，返回写入的 state。"""
    ai_req_id_value = str(ai_req_id_value or "").strip()
    if not ai_req_id_value:
        raise ValueError("ai_req_id is required")
    status = str(status or "").strip()
    if status not in VALID_AI_STATUS:
        raise ValueError(f"invalid status: {status}")
    module = str(module_override or "").strip() or None
    ownership_text = str(ownership_override or "").strip()
    ownership = normalize_ownership(ownership_text) if ownership_text else None
    state = {
        "ai_req_id": ai_req_id_value,
        "status": status,
        "module_override": module,
        "ownership_override": ownership,
        "reason": str(reason or ""),
        "actor": actor,
    }
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with _ai_review_state_lock(out_dir):
        with (out_dir / AI_REVIEW_STATES).open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(state, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return state
