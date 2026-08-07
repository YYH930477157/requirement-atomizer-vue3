"""Base requirement library (WS-C1).

历史 xlsx 经 A6 管道（``xlsx_requirement_list``）产出 ``base_library_candidates.jsonl``；
本模块负责：

1. 聚合候选视图（按 objective+module+submodule 去重，默认 lifecycle_state=draft）；
2. 提供专家筛选入口 ``confirm_base_library_candidate``，经 ``reviewer_override`` 通道
   （``verification_states.jsonl``，``adopt_source=base_library``）留痕；
3. 入库门禁：``build_base_library`` 只把 lifecycle_state="confirmed" 的候选写入
   ``base_library.jsonl``，未确认候选被拒之门外。
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from xlsx_requirement_list import BASE_LIBRARY_CANDIDATES_FILE


BASE_LIBRARY_SCHEMA = "base-library/v1"
BASE_LIBRARY_FILE = "base_library.jsonl"
BASE_LIBRARY_ADOPT_SOURCE = "base_library"


def _candidate_identity(candidate: dict[str, Any]) -> str:
    """稳定候选身份键：标题/目标 + 模块 + 子模块。"""
    title = str(candidate.get("objective") or candidate.get("title") or "").strip()
    module = str(candidate.get("module") or "").strip()
    submodule = str(candidate.get("submodule") or "").strip()
    return "|".join([title, module, submodule])


def base_library_candidate_id(candidate: dict[str, Any]) -> str:
    """用于 confirmation 跟踪的稳定 ID。"""
    return "BASE-" + sha256(_candidate_identity(candidate).encode("utf-8")).hexdigest()[:16]


def load_candidates(out_dir: Path) -> list[dict[str, Any]]:
    """读取 A6 管道产出的候选文件。"""
    path = Path(out_dir).expanduser().resolve() / BASE_LIBRARY_CANDIDATES_FILE
    if not path.exists():
        return []
    candidates: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return candidates


def aggregate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """聚合候选视图：去重 + 标记来源 + 默认未确认。

    去重键为 ``(objective/title, module, submodule)``；保留首次出现。
    """
    seen: set[str] = set()
    aggregated: list[dict[str, Any]] = []
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        entry: dict[str, Any] = {
            "schema": BASE_LIBRARY_SCHEMA,
            "base_library_candidate_id": base_library_candidate_id(candidate),
            "title": str(candidate.get("title") or candidate.get("objective") or "").strip(),
            "objective": str(candidate.get("objective") or candidate.get("title") or "").strip(),
            "description": str(candidate.get("description") or "").strip(),
            "module": str(candidate.get("module") or "").strip(),
            "submodule": str(candidate.get("submodule") or "").strip(),
            "source_quote": str(candidate.get("source_quote") or "").strip(),
            "acceptance_criteria": list(candidate.get("acceptance_criteria") or []),
            "provenance": BASE_LIBRARY_ADOPT_SOURCE,
            "source_kind": BASE_LIBRARY_ADOPT_SOURCE,
            "candidate_version": str(candidate.get("candidate_version") or ""),
            "lifecycle_state": "draft",
        }
        aggregated.append(entry)
    return aggregated


def read_confirmed_candidate_ids(out_dir: Path) -> set[str]:
    """从 verification_states.jsonl 读取专家已确认的基础库候选 ID。"""
    from review_state import read_verification_states

    root = Path(out_dir).expanduser().resolve()
    states = read_verification_states(root)
    confirmed: set[str] = set()
    for rid, state in states.items():
        if str(state.get("adopt_source") or "").strip() != BASE_LIBRARY_ADOPT_SOURCE:
            continue
        if str(state.get("lifecycle_state") or "draft").strip() == "confirmed":
            confirmed.add(str(rid).strip())
    return confirmed


def confirm_base_library_candidate(
    out_dir: Path,
    candidate_id: str,
    *,
    actor: str,
    reason: str,
    module: str = "",
    ownership: str = "",
) -> dict[str, Any]:
    """专家确认基础库候选；经 reviewer_override 通道留痕。

    actor/reason 必填；module/ownership 可选覆盖。
    """
    from review_state import upsert_verification_state

    root = Path(out_dir).expanduser().resolve()
    cid = str(candidate_id or "").strip()
    actor_s = str(actor or "").strip()
    reason_s = str(reason or "").strip()
    if not cid:
        raise ValueError("candidate_id is required")
    if not actor_s or not reason_s:
        raise ValueError("actor and reason are required for base-library admission")
    record: dict[str, Any] = {
        "requirement_id": cid,
        "schema": "verification-state/v1",
        "lifecycle_state": "confirmed",
        "adopt_source": BASE_LIBRARY_ADOPT_SOURCE,
        "adopt_actor": actor_s,
        "adopt_reason": reason_s,
        "adopt_timestamp": _now_iso(),
    }
    if module:
        record["module_override"] = module
    if ownership:
        record["ownership_override"] = ownership
    return upsert_verification_state(root, cid, record)


def build_base_library(out_dir: Path) -> Path:
    """入库门禁：只把 confirmed 候选写入 base_library.jsonl。

    未确认候选保留在聚合视图中，但不进入正式库。
    """
    root = Path(out_dir).expanduser().resolve()
    candidates = aggregate_candidates(load_candidates(root))
    confirmed_ids = read_confirmed_candidate_ids(root)
    path = root / BASE_LIBRARY_FILE
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for candidate in candidates:
            cid = candidate["base_library_candidate_id"]
            if cid not in confirmed_ids:
                continue
            entry = dict(candidate)
            entry["lifecycle_state"] = "confirmed"
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":  # pragma: no cover - manual utility
    import argparse

    parser = argparse.ArgumentParser(description="Build base requirement library")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_base_library(args.out)
    print(json.dumps({"base_library": str(result)}, ensure_ascii=False))
