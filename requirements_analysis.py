from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_review_actions import ai_req_id as stable_ai_req_id
from io_utils import read_jsonl
from requirements_analysis_excel import write_software_requirements_xlsx
from requirements_analysis_rules import classify_ownership
from requirements_analysis_schema import (
    OWNERSHIP_CO_DESIGN,
    OWNERSHIP_HARDWARE,
    apply_ownership_override,
    build_analysis_id,
    validate_analysis_item,
)
from requirements_analysis_template import extract_template_vocabulary


SCHEMA_VERSION = "requirements-analysis/v1"


def run_requirements_analysis(
    out_dir: Path,
    *,
    route: str = "stub",
    template_path: Path | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    requirements = read_jsonl(out_dir / "ai_requirements.jsonl")
    states = _states_by_ai_req_id(read_jsonl(out_dir / "ai_review_states.jsonl"))
    vocabulary = extract_template_vocabulary(template_path)

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for req in requirements:
        source_id = _source_requirement_id(len(items) + 1, req)
        state = states.get(source_id)
        if _is_rejected(state):
            continue
        reviewed_req = _apply_module_override(req, state)
        item = _base_item(len(items) + 1, reviewed_req, vocabulary)
        item.update(classify_ownership(reviewed_req))
        item = apply_ownership_override(item, state)

        item_issues = validate_analysis_item(item)
        if item_issues:
            issues.append({
                "analysis_id": item.get("analysis_id"),
                "source_requirement_ids": item.get("source_requirement_ids") or [],
                "issues": item_issues,
            })
        items.append(item)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "route": route,
        "items": items,
        "issues": issues,
    }
    (out_dir / "engineering_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_report(
        out_dir / "hardware_items.md",
        [item for item in items if item.get("ownership") == OWNERSHIP_HARDWARE],
        "Hardware Items",
    )
    _write_report(
        out_dir / "co_design_items.md",
        [item for item in items if item.get("ownership") == OWNERSHIP_CO_DESIGN],
        "Co-design Items",
    )
    write_software_requirements_xlsx(items, out_dir / "software_requirements.xlsx")

    return {
        "kind": "requirements_analysis",
        "analysis_count": len(items),
        "issues": len(issues),
    }


def _base_item(index: int, req: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    module = _module_or_unmapped(req, vocabulary)
    source_id = _source_requirement_id(index, req)
    description = str(req.get("title") or req.get("description") or req.get("requirement") or "").strip()
    requirement_text = str(req.get("description") or req.get("requirement") or "").strip()

    return {
        "analysis_id": build_analysis_id(index),
        "source_kind": "ai_requirement",
        "source_requirement_ids": [source_id],
        "source_block_ids": [str(value) for value in _as_list(req.get("source_block_ids"))],
        "module": module,
        "submodule": str(req.get("module") or module),
        "template_match": "matched" if module in vocabulary.get("modules", []) else "unmapped",
        "description": description,
        "requirement": requirement_text,
        "software_requirement_text": "",
        "developer_guidance": [],
        "hardware_dependency": "",
        "acceptance_criteria": [],
        "open_questions": [],
        "notes": [],
        "source_quote": str(req.get("source_quote") or ""),
        "source_section": str(req.get("source_section") or ""),
    }


def _source_requirement_id(index: int, req: dict[str, Any]) -> str:
    explicit_id = str(req.get("ai_req_id") or req.get("stable_req_id") or req.get("req_id") or "").strip()
    if explicit_id:
        return explicit_id
    computed_id = str(stable_ai_req_id(req) or "").strip()
    return computed_id or f"REQ-{index}"


def _is_rejected(state: dict[str, Any] | None) -> bool:
    return str((state or {}).get("status") or "").strip() == "rejected"


def _apply_module_override(req: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    module_override = str((state or {}).get("module_override") or "").strip()
    if not module_override:
        return req
    reviewed_req = dict(req)
    reviewed_req["module"] = module_override
    return reviewed_req


def _module_or_unmapped(req: dict[str, Any], vocabulary: dict[str, Any]) -> str:
    module = str(req.get("module") or "").strip()
    if module in vocabulary.get("modules", []):
        return module
    return module or "unmapped"


def _states_by_ai_req_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for row in rows:
        ai_req_id = str(row.get("ai_req_id") or "").strip()
        if ai_req_id:
            states[ai_req_id] = row
    return states


def _write_report(path: Path, rows: list[dict[str, Any]], title: str) -> None:
    lines = [f"# {title}", ""]
    if not rows:
        lines.extend(["No items.", ""])
    for row in rows:
        lines.extend([
            f"## {row.get('analysis_id')} {row.get('description') or ''}".rstrip(),
            f"- Ownership reason: {row.get('ownership_reason') or ''}",
            f"- Source: {', '.join(str(value) for value in row.get('source_requirement_ids') or [])}",
            f"- Source quote: {row.get('source_quote') or ''}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run requirements analysis agent.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--route", default="stub", choices=["stub", "openai_compatible"])
    parser.add_argument("--template", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_requirements_analysis(args.out, route=args.route, template_path=args.template)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
