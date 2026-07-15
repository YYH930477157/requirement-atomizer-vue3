from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _normalized_groups(items: list[dict[str, Any]]) -> list[list[str]]:
    return sorted((sorted(str(value) for value in item.get("source_ai_requirement_ids") or []) for item in items), key=lambda row: tuple(row))


def _catalog_case(case: dict[str, Any]) -> tuple[list[str], bool, bool]:
    from functional_catalog import build_function_catalog

    requirements = [dict(row) for row in case.get("requirements") or []]
    expected = case.get("expected") or {}
    items = build_function_catalog(requirements)
    failures: list[str] = []
    if "functional_count" not in expected:
        # C6（0710 评审）：缺省取 len(items) 是自引分母——计数检查恒真。用例必须显式给出。
        failures.append("case missing required expected.functional_count")
        expected_count = -1
    else:
        expected_count = int(expected["functional_count"])
    if expected_count >= 0 and len(items) != expected_count:
        failures.append(f"functional_count expected {expected_count}, got {len(items)}")
    expected_groups = expected.get("groups")
    if expected_groups is not None:
        actual_groups = _normalized_groups(items)
        wanted_groups = sorted((sorted(str(value) for value in group) for group in expected_groups), key=lambda row: tuple(row))
        if actual_groups != wanted_groups:
            failures.append(f"groups expected {wanted_groups}, got {actual_groups}")
    assigned = [rid for item in items for rid in item.get("source_ai_requirement_ids") or []]
    source_ids = [str(row.get("ai_req_id") or "") for row in requirements]
    if sorted(assigned) != sorted(source_ids) or len(assigned) != len(set(assigned)):
        failures.append("source atoms were not assigned exactly once")
    rendered = json.dumps(items, ensure_ascii=False)
    for value in expected.get("protected_values") or []:
        if str(value) not in rendered:
            failures.append(f"protected value lost: {value}")
    expected_variants = {str(value) for value in expected.get("variants") or []}
    if expected_variants:
        actual_variants = {str(variant.get("name") or "") for item in items for variant in item.get("variants") or []}
        if not expected_variants.issubset(actual_variants):
            failures.append(f"variants missing: {sorted(expected_variants - actual_variants)}")
    for value in expected.get("conflict_contains") or []:
        if not any(str(value) in flag for item in items for flag in item.get("conflict_flags") or []):
            failures.append(f"conflict flag missing value: {value}")
    merged = len(items) < len(requirements)
    split = len(items) == len(requirements) and len(requirements) > 1
    return failures, merged, split


def _ownership_case(case: dict[str, Any]) -> tuple[list[str], bool, bool]:
    from requirements_analysis_rules import classify_ownership

    result = classify_ownership(dict((case.get("requirements") or [{}])[0]))
    expected = str((case.get("expected") or {}).get("ownership") or "")
    return ([] if result.get("ownership") == expected else [f"ownership expected {expected}, got {result.get('ownership')}"]), False, False


def _design_guard_case(case: dict[str, Any]) -> tuple[list[str], bool, bool]:
    import ai_extract

    requirement = dict((case.get("requirements") or [{}])[0])
    section = {
        "section_id": "semantic",
        "heading": "semantic",
        "text": str(case.get("source_text") or requirement.get("source_quote") or ""),
        "block_ids": ["B-SEM"],
        "source_blocks": [{"block_id": "B-SEM", "text": str(case.get("source_text") or "")}],
    }
    requirement.setdefault("type", "functional")
    requirement.setdefault("priority", "P1")
    requirement.setdefault("labels", [str(requirement.get("module") or "其它")])
    requirement.setdefault("acceptance_criteria", [])
    result = ai_extract._process_raw_requirements([requirement], section)[0]
    expected = case.get("expected") or {}
    failures: list[str] = []
    if "normative_guidance_count" in expected and len(result.get("dev_guidance") or []) != int(expected["normative_guidance_count"]):
        failures.append("normative guidance count mismatch")
    rendered_options = " ".join(result.get("design_options") or [])
    for value in expected.get("design_options") or []:
        if str(value) not in rendered_options:
            failures.append(f"design option missing: {value}")
    delivery = json.dumps({key: result.get(key) for key in ("description", "dev_guidance", "acceptance_criteria")}, ensure_ascii=False)
    for value in expected.get("forbidden_delivery_values") or []:
        if str(value) in delivery:
            failures.append(f"unsupported delivery value retained: {value}")
    return failures, False, False


def _source_mapping_case(case: dict[str, Any]) -> tuple[list[str], bool, bool]:
    import ai_extract

    requirement = dict((case.get("requirements") or [{}])[0])
    section = dict(case.get("section") or {})
    requirement.setdefault("type", "functional")
    requirement.setdefault("priority", "P1")
    requirement.setdefault("labels", [str(requirement.get("module") or "其它")])
    requirement.setdefault("acceptance_criteria", [])
    requirement.setdefault("dev_guidance", [])
    result = ai_extract._process_raw_requirements([requirement], section)[0]
    expected = case.get("expected") or {}
    failures: list[str] = []
    if result.get("source_block_ids") != expected.get("source_block_ids"):
        failures.append(f"source blocks expected {expected.get('source_block_ids')}, got {result.get('source_block_ids')}")
    if result.get("source_mapping") != expected.get("source_mapping"):
        failures.append(f"source mapping expected {expected.get('source_mapping')}, got {result.get('source_mapping')}")
    return failures, False, False


_EVALUATORS = {
    "catalog": _catalog_case,
    "ownership": _ownership_case,
    "design_guard": _design_guard_case,
    "source_mapping": _source_mapping_case,
}


TEST18_SAMPLE_ENV = "RATOMIZER_HISTORICAL_SAMPLE"


def _resolve_historical_sample(path: Path | None) -> Path | None:
    if path is not None:
        return Path(path)
    import os
    raw = os.environ.get(TEST18_SAMPLE_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def evaluate_historical_corpus(path: Path | None = None) -> dict[str, Any]:
    from functional_catalog import build_function_catalog

    # 真实历史抽取样本是客户数据,不进公开仓(0715 用户裁定,与蓝皮书/模板同纪律)——
    # 外置资产经 env 指路;缺失如实上报 available=false,不计违规也不装作跑过
    fixture = _resolve_historical_sample(path)
    if fixture is None or not fixture.is_file():
        return {"available": False, "fixture": str(fixture) if fixture else "",
                "critical_violations": 0}
    payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    items = build_function_catalog(rows)
    groups = [set(item.get("source_ai_requirement_ids") or []) for item in items]
    assigned = [source_id for item in items for source_id in item.get("source_ai_requirement_ids") or []]
    expected_ids = [str(row.get("ai_req_id") or "") for row in rows]
    by_source = {
        source_id: item
        for item in items for source_id in item.get("source_ai_requirement_ids") or []
    }
    known_groups = [
        {"AIR-ee0ae469c177", "AIR-e395f118c4ae"},
        {"AIR-3951515976df", "AIR-2fa24b25867e", "AIR-49faeb877290"},
        {"AIR-b6744a02ac7e", "AIR-1fa0621376ee"},
    ]
    assigned_once = sorted(assigned) == sorted(expected_ids) and len(assigned) == len(set(assigned))
    groups_preserved = all(group in groups for group in known_groups)
    battery_split = (
        by_source.get("AIR-56ccdfac8886", {}).get("functional_requirement_id")
        != by_source.get("AIR-396cd39da293", {}).get("functional_requirement_id")
    )
    violations = sum((not assigned_once, not groups_preserved, not battery_split))
    return {
        "available": True,
        "fixture": str(fixture),
        "source_requirements": len(rows),
        "functional_requirements": len(items),
        "assigned_exactly_once": assigned_once,
        "known_groups_preserved": groups_preserved,
        "opposed_battery_requirements_split": battery_split,
        "critical_violations": violations,
    }

def evaluate_baseline(path: Path) -> dict[str, Any]:
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures: list[dict[str, Any]] = []
    merged_cases = 0
    split_cases = 0
    for case in payload.get("cases") or []:
        evaluator = _EVALUATORS.get(str(case.get("kind") or ""))
        if evaluator is None:
            failures.append({"id": case.get("id"), "issues": [f"unknown case kind: {case.get('kind')}"]})
            continue
        issues, merged, split = evaluator(case)
        merged_cases += int(merged)
        split_cases += int(split)
        if issues:
            failures.append({"id": case.get("id"), "issues": issues})
    total = len(payload.get("cases") or [])
    historical = evaluate_historical_corpus()
    return {
        "schema_version": 1,
        "baseline": str(path),
        "total_cases": total,
        "passed_cases": total - len(failures),
        "failed_cases": len(failures),
        "critical_violations": len(failures) + historical["critical_violations"],
        "historical_corpus": historical,
        "merged_cases": merged_cases,
        "split_cases": split_cases,
        "failures": failures,
    }


def write_report(baseline_path: Path, target: Path) -> dict[str, Any]:
    report = evaluate_baseline(baseline_path)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the executable semantic quality baseline.")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(__file__).resolve().parent / "golden_sets" / "requirements_analysis_semantic_v1.json",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = write_report(args.baseline, args.out) if args.out else evaluate_baseline(args.baseline)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["critical_violations"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())