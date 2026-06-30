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
from pathlib import Path
from typing import Any

AI_REVIEW_STATES = "ai_review_states.jsonl"
VALID_AI_STATUS = {"accepted", "rejected", "needs_discussion", "expert_pending", "draft"}


def ai_req_id(req: dict[str, Any]) -> str:
    """内容稳定 ID：source_section + source_quote + title 的 sha1 指纹（防 REQ-NNN 位置漂移）。"""
    basis = "|".join([
        str(req.get("source_section") or ""),
        str(req.get("source_quote") or ""),
        str(req.get("title") or ""),
    ])
    return "AIR-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def read_ai_review_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    """取每个 ai_req_id 的最新裁决（最近一行覆盖）。"""
    path = Path(out_dir) / AI_REVIEW_STATES
    states: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return states
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = str(row.get("ai_req_id") or "")
        if rid:
            states[rid] = row  # 最新覆盖
    return states


def apply_ai_review_action(
    out_dir: Path,
    ai_req_id_value: str,
    status: str,
    *,
    module_override: str | None = None,
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
    state = {
        "ai_req_id": ai_req_id_value,
        "status": status,
        "module_override": module,
        "reason": str(reason or ""),
        "actor": actor,
    }
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / AI_REVIEW_STATES).open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(state, ensure_ascii=False) + "\n")
    return state
