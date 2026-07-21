"""裁决样本库（护城河级组件：专家裁决 → 越用越准的 few-shot 资产）。

专家在批注视图的 accepted/rejected 裁决此前只喂规则建议（review_insights）。本模块把
**被接受的需求**沉淀为黄金范例（公司认可的粒度/写法），按模块+词面相关注入 analyze 富化
prompt（机制与模板知识注入同款：确定性检索、宁漏勿错）；被拒绝的沉淀为负例标题（提示
模型避开同类产出）。跨项目积累：库文件路径由 env RATOMIZER_ADJUDICATION_BANK 指定
（公司资产，不进仓）；未配置 → 一切行为如旧。

用法：python -m adjudication_bank --out <目录> --bank <库.json>   # 收割本目录裁决入库
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

LOGGER = logging.getLogger("requirement_atomizer")

BANK_ENV = "RATOMIZER_ADJUDICATION_BANK"
BANK_VERSION = 1
EXEMPLAR_TOP_K = 2
EXEMPLAR_MAX_CHARS = 1200
_BANK_LOCKS: dict[Path, RLock] = {}
_BANK_LOCKS_GUARD = RLock()
_BANK_LOCK_TIMEOUT_S = 10.0
_BANK_LOCK_STALE_AFTER_S = 300.0
_BANK_REPLACE_ATTEMPTS = 20
_BANK_REPLACE_RETRY_DELAY_S = 0.05


def load_bank(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return {"version": BANK_VERSION, "accepted": {}, "rejected": {}}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        LOGGER.warning("裁决样本库读取失败，按空库处理：%s", path)
        return {"version": BANK_VERSION, "accepted": {}, "rejected": {}}
    if not isinstance(data, dict):
        return {"version": BANK_VERSION, "accepted": {}, "rejected": {}}
    if not isinstance(data.get("accepted"), dict):
        data["accepted"] = {}
    if not isinstance(data.get("rejected"), dict):
        data["rejected"] = {}
    if not isinstance(data.get("modules"), dict):
        data["modules"] = {}
    # 旧版本改判时未清理对侧桶，可能让 rejected 样本继续作为正例注入。
    # 无可靠时序可恢复时按宁漏勿错处理：重叠 ID 以 rejected 为准。
    for rid in data["accepted"].keys() & data["rejected"].keys():
        data["accepted"].pop(rid, None)
    return data


def update_bank(bank_path: Path, out_dir: Path) -> dict[str, Any]:
    """收割 out_dir 的裁决（accepted→范例 / rejected→负例）合并入库（同 id 最新覆盖）。"""
    from ai_review_actions import read_ai_review_states, source_ai_requirement_id
    from io_utils import read_jsonl

    out_dir = Path(out_dir).expanduser().resolve()
    reqs_path = out_dir / "ai_requirements.jsonl"
    if not reqs_path.exists():
        raise FileNotFoundError(f"ai_requirements.jsonl not found in {out_dir}")
    requirements = read_jsonl(reqs_path)
    states = read_ai_review_states(out_dir)

    bank_path = Path(bank_path).expanduser().resolve()
    with _bank_lock(bank_path):
        bank = load_bank(bank_path)
        added_accepted = added_rejected = 0
        for req in requirements:
            rid = source_ai_requirement_id(req)
            state = states.get(rid)
            status = str((state or {}).get("status") or "")
            if state is not None:
                _remove_module_usage(bank, rid)
            if status == "accepted":
            # 漂移标记/可疑样本不进教材（2026-07-08 审计 B5）：专家 accept 时若 notes 带
            # 漂移标记或 suspicion 未清，样本可能含编造内容——注入 few-shot 会教坏后续富化
                notes = str(req.get("notes") or "")
                if "漂移" in notes or (req.get("suspicion_reasons") or []):
                    bank["accepted"].pop(rid, None)
                    bank["rejected"].pop(rid, None)
                    continue
                module = str((state or {}).get("module_override") or req.get("module") or "").strip()
                bank["rejected"].pop(rid, None)
                bank["accepted"][rid] = {
                    "module": module,
                    "title": str(req.get("title") or ""),
                    "description": str(req.get("description") or ""),
                    "sub_items": req.get("sub_items") or [],
                    "acceptance_criteria": req.get("acceptance_criteria") or [],
                    "source_quote": str(req.get("source_quote") or "")[:200],
                    "adjudicated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                }
                if module:
                    _add_module_usage(bank, module, rid)
                added_accepted += 1
            elif status == "rejected":
                bank["accepted"].pop(rid, None)
                bank["rejected"][rid] = {
                    "module": str(req.get("module") or ""),
                    "title": str(req.get("title") or ""),
                    "reason": str((state or {}).get("reason") or ""),
                }
                added_rejected += 1
            elif state is not None:
                bank["accepted"].pop(rid, None)
                bank["rejected"].pop(rid, None)

        bank["version"] = BANK_VERSION
        bank["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
        _atomic_write_bank(bank_path, bank)
    return {"bank": str(bank_path), "accepted_total": len(bank["accepted"]),
            "rejected_total": len(bank["rejected"]),
            "modules_total": len(bank.get("modules") or {}),
            "harvested_accepted": added_accepted, "harvested_rejected": added_rejected}


def module_vocabulary(bank: dict[str, Any]) -> list[str]:
    modules = bank.get("modules") or {}
    counts = {
        str(module): int((entry or {}).get("count") or 0)
        for module, entry in modules.items()
        if str(module).strip()
    }
    # Legacy banks already contain cross-document accepted exemplars but no explicit module
    # registry. Surface those modules immediately; future harvests populate exact usage counts.
    for exemplar in (bank.get("accepted") or {}).values():
        module = str((exemplar or {}).get("module") or "").strip()
        if module:
            counts[module] = max(1, counts.get(module, 0))
    return [
        module for module, _count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if str(module).strip()
    ]


def _remove_module_usage(bank: dict[str, Any], requirement_id: str) -> None:
    modules = bank.setdefault("modules", {})
    for module in list(modules):
        entry = modules.get(module) or {}
        ids = [str(value) for value in (entry.get("requirement_ids") or []) if str(value) != requirement_id]
        if ids:
            entry["requirement_ids"] = ids
            entry["count"] = len(ids)
            modules[module] = entry
        else:
            modules.pop(module, None)


def _add_module_usage(bank: dict[str, Any], module: str, requirement_id: str) -> None:
    entry = bank.setdefault("modules", {}).setdefault(module, {})
    ids = list(dict.fromkeys([
        str(value) for value in (entry.get("requirement_ids") or []) if str(value)
    ] + [requirement_id]))
    entry.update({
        "count": len(ids),
        "requirement_ids": ids,
        "last_used": datetime.datetime.now().isoformat(timespec="seconds"),
    })


@contextmanager
def _bank_lock(bank_path: Path):
    bank_path.parent.mkdir(parents=True, exist_ok=True)
    with _BANK_LOCKS_GUARD:
        process_lock = _BANK_LOCKS.setdefault(bank_path, RLock())
    with process_lock:
        lock_path = bank_path.with_suffix(bank_path.suffix + ".lock")
        deadline = time.monotonic() + _BANK_LOCK_TIMEOUT_S
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    stale = time.time() - lock_path.stat().st_mtime >= _BANK_LOCK_STALE_AFTER_S
                except FileNotFoundError:
                    continue
                if stale:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for adjudication bank lock: {lock_path}")
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


def _atomic_write_bank(path: Path, bank: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        for attempt in range(_BANK_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt + 1 >= _BANK_REPLACE_ATTEMPTS:
                    raise
                time.sleep(_BANK_REPLACE_RETRY_DELAY_S)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def select_exemplars(bank: dict[str, Any], module: str, req_text: str,
                     k: int = EXEMPLAR_TOP_K) -> list[dict[str, Any]]:
    """同模块 + 词面相关的已验收范例 top-k（确定性；零重叠不注入——宁漏勿错）。"""
    from requirements_analysis_template import _match_tokens
    req_tokens = _match_tokens(req_text)
    if not req_tokens:
        return []
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for rid, ex in (bank.get("accepted") or {}).items():
        if str(ex.get("module") or "") != module:
            continue
        score = len(req_tokens & _match_tokens(
            " ".join([ex.get("title") or "", ex.get("description") or "",
                      ex.get("source_quote") or ""])))
        if score > 0:
            scored.append((score, rid, ex))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked: list[dict[str, Any]] = []
    used = 0
    for _score, _rid, ex in scored[:k]:
        size = len(ex.get("description") or "")
        if picked and used + size > EXEMPLAR_MAX_CHARS:
            break
        picked.append(ex)
        used += size
    return picked


def render_exemplars(exemplars: list[dict[str, Any]]) -> str:
    """范例渲染为 prompt 文本（同时作缓存指纹基底）。"""
    lines = []
    for ex in exemplars:
        lines.append(f"- 【{ex.get('module')}】{ex.get('title')}：{ex.get('description')}")
        if ex.get("acceptance_criteria"):
            lines.append(f"  验收示例：{'；'.join(str(x) for x in ex['acceptance_criteria'][:2])}")
    return "\n".join(lines)


def resolve_bank_path() -> Path | None:
    import os
    raw = os.environ.get(BANK_ENV, "").strip()
    return Path(raw) if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest expert adjudications into the exemplar bank.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = update_bank(args.bank, args.out)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
