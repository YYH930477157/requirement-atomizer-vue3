"""Solution library (WS-C2).

历史项目 ``functional_requirements.json`` / ``ai_requirements.jsonl`` 中的
``design_options`` 沉淀为 ``solution_library.jsonl``。方案库条目默认
lifecycle_state=draft（未 confirmed 隐藏），专家确认后变为 confirmed。

确认动作经 ``reviewer_override`` 通道（``verification_states.jsonl``，
``adopt_source=solution_library``）留痕，与基本需求库同纪律。
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any


from result_package import governed_artifact_path


SOLUTION_LIBRARY_SCHEMA = "solution-library/v1"
SOLUTION_LIBRARY_FILE = "solution_library.jsonl"
SOLUTION_LIBRARY_ADOPT_SOURCE = "solution_library"


def _option_identity(requirement_id: str, option: str) -> str:
    return "|".join([str(requirement_id or "").strip(), str(option or "").strip()])


def solution_library_entry_id(requirement_id: str, option: str) -> str:
    return "SOL-" + sha256(_option_identity(requirement_id, option).encode("utf-8")).hexdigest()[:16]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def collect_design_options(out_dir: Path) -> list[dict[str, Any]]:
    """从项目产物中收集 design_options。优先读 functional_requirements.json，回退 ai_requirements.jsonl。"""
    root = Path(out_dir).expanduser().resolve()
    options: list[dict[str, Any]] = []
    seen: set[str] = set()

    func_path = root / "functional_requirements.json"
    func_data = _read_json(func_path)
    for item in func_data.get("requirements") or []:
        req_id = str(item.get("functional_requirement_id") or item.get("requirement_id") or "").strip()
        module = str(item.get("module") or "").strip()
        objective = str(item.get("objective") or item.get("title") or "").strip()
        for opt in item.get("design_options") or []:
            opt_s = str(opt).strip()
            if not opt_s:
                continue
            key = _option_identity(req_id, opt_s)
            if key in seen:
                continue
            seen.add(key)
            options.append({
                "requirement_id": req_id,
                "module": module,
                "objective": objective,
                "option": opt_s,
            })

    ai_path = governed_artifact_path(root, "ai_requirements.jsonl", category="pipeline", for_write=False)
    for row in _read_jsonl(ai_path):
        req_id = str(row.get("ai_requirement_id") or row.get("requirement_id") or "").strip()
        module = str(row.get("module") or "").strip()
        objective = str(row.get("title") or row.get("description") or "").strip()[:120]
        for opt in row.get("design_options") or []:
            opt_s = str(opt).strip()
            if not opt_s:
                continue
            key = _option_identity(req_id, opt_s)
            if key in seen:
                continue
            seen.add(key)
            options.append({
                "requirement_id": req_id,
                "module": module,
                "objective": objective,
                "option": opt_s,
            })

    return options


def aggregate_solution_entries(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """聚合方案库条目：去重 + 默认未确认。"""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for opt in options:
        req_id = str(opt.get("requirement_id") or "").strip()
        option_text = str(opt.get("option") or "").strip()
        if not option_text:
            continue
        key = _option_identity(req_id, option_text)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "schema": SOLUTION_LIBRARY_SCHEMA,
            "solution_library_entry_id": solution_library_entry_id(req_id, option_text),
            "option": option_text,
            "module": str(opt.get("module") or "").strip(),
            "objective": str(opt.get("objective") or "").strip(),
            "source_requirement_id": req_id,
            "provenance": SOLUTION_LIBRARY_ADOPT_SOURCE,
            "source_kind": SOLUTION_LIBRARY_ADOPT_SOURCE,
            "lifecycle_state": "draft",
        })
    return entries


def read_confirmed_entry_ids(out_dir: Path) -> set[str]:
    """从 verification_states.jsonl 读取专家已确认的方案库条目 ID。"""
    from review_state import read_verification_states

    root = Path(out_dir).expanduser().resolve()
    states = read_verification_states(root)
    confirmed: set[str] = set()
    for rid, state in states.items():
        if str(state.get("adopt_source") or "").strip() != SOLUTION_LIBRARY_ADOPT_SOURCE:
            continue
        if str(state.get("lifecycle_state") or "draft").strip() == "confirmed":
            confirmed.add(str(rid).strip())
    return confirmed


def confirm_solution_library_entry(
    out_dir: Path,
    entry_id: str,
    *,
    actor: str,
    reason: str,
    module: str = "",
) -> dict[str, Any]:
    """专家确认方案库条目；经 reviewer_override 通道留痕。"""
    from review_state import upsert_verification_state

    root = Path(out_dir).expanduser().resolve()
    eid = str(entry_id or "").strip()
    actor_s = str(actor or "").strip()
    reason_s = str(reason or "").strip()
    if not eid:
        raise ValueError("entry_id is required")
    if not actor_s or not reason_s:
        raise ValueError("actor and reason are required for solution-library admission")
    record: dict[str, Any] = {
        "requirement_id": eid,
        "schema": "verification-state/v1",
        "lifecycle_state": "confirmed",
        "adopt_source": SOLUTION_LIBRARY_ADOPT_SOURCE,
        "adopt_actor": actor_s,
        "adopt_reason": reason_s,
        "adopt_timestamp": _now_iso(),
    }
    if module:
        record["module_override"] = module
    return upsert_verification_state(root, eid, record)


def build_solution_library(out_dir: Path) -> Path:
    """入库门禁：只把 confirmed 方案写入 solution_library.jsonl。"""
    root = Path(out_dir).expanduser().resolve()
    entries = aggregate_solution_entries(collect_design_options(root))
    confirmed_ids = read_confirmed_entry_ids(root)
    path = governed_artifact_path(root, SOLUTION_LIBRARY_FILE, category="state", for_write=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            eid = entry["solution_library_entry_id"]
            if eid not in confirmed_ids:
                continue
            confirmed_entry = dict(entry)
            confirmed_entry["lifecycle_state"] = "confirmed"
            handle.write(json.dumps(confirmed_entry, ensure_ascii=False) + "\n")
    return path


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":  # pragma: no cover - manual utility
    import argparse

    parser = argparse.ArgumentParser(description="Build solution library")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_solution_library(args.out)
    print(json.dumps({"solution_library": str(result)}, ensure_ascii=False))
