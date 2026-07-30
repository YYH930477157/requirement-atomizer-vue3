"""Agent evaluation runner (agent-eval-v2).

Phase 0 froze the dataset contract and evaluated only the ``classify`` category.
v2 adds deterministic zero-LLM judges for the remaining three categories per
docs/agent-eval-v2-spec.md:

- ``grouping``: pair-wise same/different-group judgment through the production
  merge path ``functional_catalog.build_function_catalog(chat=None)``;
- ``must_ask``: forbidden defaults must never leak into deterministic
  derivations (tier 1, all cases); cases declaring ``expected.detector`` must
  fire the named production detector whose suspicion policy routes to
  customer/blocking (tier 2); cases without a detector are honestly marked
  ``manual`` and excluded from the automatic pass-rate denominator (tier 3);
- ``hallucination``: every ``expected.forbidden`` token must be caught by the
  production drift guards ``ai_extract.code_drift`` ∪ ``ai_extract.int_drift``.

All judges call production code paths; nothing here re-implements guard logic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

import clarification_report
from agent_policy import AGENT_POLICY_VERSION
from ai_extract import code_drift, int_drift
from atomize import is_requirement_like
from compliance import looks_like_compliance
from cosem_behavior_spec import extract_codes
from extract_guards import (
    foreign_standard_refs,
    produced_ints,
    vague_acceptance,
    values_left_behind,
)
from functional_catalog import build_function_catalog, opposed_qualifiers
from requirements_analysis_rules import classify_ownership


EVAL_RUNNER_VERSION = "agent-eval-v2"
ENVELOPE_SCHEMA_VERSION = "1.0"
CASE_SCHEMA = Path(__file__).resolve().parent / "schemas" / "agent_eval_case.schema.json"
CATEGORIES = ("classify", "grouping", "must_ask", "hallucination")
BASELINE_CATEGORIES = ("classification", "grouping", "must_ask", "hallucination")

_REJECTED_CANDIDATE_PREFIX = "Rejected candidate:"
_REJECTED_MERGE_PREFIX = "Rejected merge:"
# detector 字段 → 该 detector 触发时生产侧登记的 suspicion reason（clarification_report
# 路由表键）。pass 谓词要求该 reason 的策略仍路由为问客户或 blocking。
_DETECTOR_REASONS = {
    "vague_acceptance": "验收不可测",
    "values_left_behind": "原文数值未带全",
}

_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.02


class AgentEvalInputError(ValueError):
    """The requested evaluation dataset cannot be found or is empty."""


class AgentEvalValidationError(ValueError):
    """The evaluation dataset does not satisfy its frozen contract."""


def load_case_schema() -> dict[str, Any]:
    return json.loads(CASE_SCHEMA.read_text(encoding="utf-8"))


def load_cases(eval_dir: Path) -> list[dict[str, Any]]:
    root = Path(eval_dir).expanduser().resolve()
    if not root.is_dir():
        raise AgentEvalInputError(f"Evaluation directory does not exist: {root}")
    case_root = root / "cases"
    case_paths = sorted(case_root.glob("**/*.json")) if case_root.is_dir() else []
    if not case_paths:
        raise AgentEvalInputError(f"No evaluation cases found under: {case_root}")

    validator = Draft202012Validator(load_case_schema(), format_checker=FormatChecker())
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in case_paths:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise AgentEvalValidationError(f"{path}: invalid JSON: {exc}") from exc
        errors = sorted(validator.iter_errors(case), key=lambda error: list(error.absolute_path))
        if errors:
            error = errors[0]
            location = ".".join(str(value) for value in error.absolute_path) or "$"
            raise AgentEvalValidationError(f"{path}: {location}: {error.message}")
        case_id = str(case["case_id"])
        if case_id in seen_ids:
            raise AgentEvalValidationError(f"Duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        cases.append(case)
    return cases


def category_counts(cases: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(case.get("category") or "") for case in cases)
    return {category: counts.get(category, 0) for category in CATEGORIES}


def classify_case(case: dict[str, Any]) -> dict[str, Any]:
    inputs = case["input"]
    text = str(inputs["text"])
    context = str(inputs.get("context") or "")
    combined = "\n".join(value for value in (context, text) if value.strip())

    if looks_like_compliance(combined):
        return {"verdict": "compliance", "reason": "Matched deterministic compliance rules."}
    if not is_requirement_like(combined):
        return {"verdict": "non_requirement", "reason": "No deterministic requirement signal matched."}

    decision = classify_ownership({"source_quote": text, "description": text, "title": context})
    return {
        "verdict": str(decision["ownership"]),
        "reason": str(decision["ownership_reason"]),
    }


def _case_row(case: dict[str, Any]) -> dict[str, Any]:
    """Minimal production-shaped requirement row for the catalog merge path."""
    text = str(case["input"]["text"])
    context = str(case["input"].get("context") or "")
    return {
        "title": context or text[:40],
        "description": text,
        "source_quote": text,
        "module": "",
        "ai_requirement_id": str(case["case_id"]),
    }


def _grouping_results(
    grouping_cases: list[dict[str, Any]], reviewed: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = {str(c["case_id"]): _case_row(c) for c in grouping_cases}
    keys = {str(c["case_id"]): str(c["expected"].get("group_key") or "") for c in grouping_cases}
    pairs: list[dict[str, Any]] = []
    for a, b in combinations(sorted(rows), 2):
        expected_same = keys[a] == keys[b]
        groups = build_function_catalog([rows[a], rows[b]], chat=None)
        merged = len(groups) == 1
        pairs.append({
            "pair": [a, b],
            "expected_same_group": expected_same,
            "merged": merged,
            "merge_method": str(groups[0].get("merge_method") or "") if merged else "",
            "passed": merged == expected_same,
        })
    failing = {case_id for pair in pairs if not pair["passed"] for case_id in pair["pair"]}
    details = [
        {
            "case_id": case_id,
            "group_key": keys[case_id],
            "passed": case_id not in failing,
            "reviewed": case_id in reviewed,
        }
        for case_id in sorted(rows)
    ]
    return pairs, details


def _must_ask_case(case: dict[str, Any], reviewed: set[str]) -> dict[str, Any]:
    text = str(case["input"]["text"])
    context = str(case["input"].get("context") or "")
    forbidden = [str(token) for token in case["expected"].get("forbidden") or []]

    # Tier 1（全部 must_ask 案例）：forbidden 缺省值不得漏进任何确定性派生输出。
    derived: list[str] = []
    classification = classify_case(case)
    derived.extend([classification["verdict"], classification["reason"]])
    for group in build_function_catalog([_case_row(case)], chat=None):
        derived.extend(
            str(group.get(key) or "") for key in ("title", "functional_key", "description")
        )
    leaked = [token for token in forbidden if any(token in value for value in derived)]

    detail: dict[str, Any] = {
        "case_id": str(case["case_id"]),
        "leaked_forbidden": leaked,
        "reviewed": str(case["case_id"]) in reviewed,
    }
    detector = str(case["expected"].get("detector") or "")
    if not detector:
        # Tier 3：语义型陷阱——自动判定只覆盖 tier 1，ask 触发如实标 manual 不进分母。
        detail["judge"] = "manual"
        detail["passed"] = not leaked
        detail["reason"] = "No deterministic detector declared; ask-trigger judged manually."
        return detail

    # Tier 2：声明的 detector 必须触发，且其 suspicion 策略仍路由为问客户或 blocking。
    if detector == "vague_acceptance":
        fired: Any = vague_acceptance({"acceptance_criteria": [text]})
    else:
        if text not in context:
            detail["judge"] = "auto"
            detail["passed"] = False
            detail["reason"] = "Case malformed: input.text is not verbatim inside input.context."
            return detail
        fired = values_left_behind(
            {"source_quote": text, "description": text, "title": ""}, context
        )
    reason_key = _DETECTOR_REASONS[detector]
    policy = clarification_report.suspicion_policy(reason_key)
    policy_ok = bool(policy) and (
        policy[2] == clarification_report.AUDIENCE_CUSTOMER
        or policy[3] == clarification_report.BLOCKER_BLOCKING
    )
    detail["judge"] = "auto"
    detail["detector"] = detector
    detail["detector_fired"] = bool(fired)
    detail["policy_route_ok"] = policy_ok
    detail["passed"] = (not leaked) and bool(fired) and policy_ok
    if not fired:
        detail["reason"] = f"Declared detector {detector} did not fire."
    elif not policy_ok:
        detail["reason"] = f"Suspicion policy for {reason_key} no longer routes to customer/blocking."
    elif leaked:
        detail["reason"] = "Forbidden default leaked into deterministic derivations."
    else:
        detail["reason"] = "Detector fired and policy routes to customer/blocking."
    return detail


def _token_atoms(token: str) -> set[str]:
    """forbidden token 的可判定原子：受保护编码 ∪ 整数（与漂移输出同口径）。"""
    return set(extract_codes(token)) | set(produced_ints(token))


def _hallucination_case(case: dict[str, Any], reviewed: set[str]) -> dict[str, Any]:
    text = str(case["input"]["text"])
    context = str(case["input"].get("context") or "")
    for prefix in (_REJECTED_CANDIDATE_PREFIX, _REJECTED_MERGE_PREFIX):
        if prefix in context:
            candidate = context.split(prefix, 1)[1].strip()
            break
    else:
        candidate = context.strip()
    forbidden = [str(token) for token in case["expected"].get("forbidden") or []]
    requirement = {"title": "", "description": candidate, "acceptance_criteria": []}
    detector = str(case["expected"].get("detector") or "")
    detail: dict[str, Any] = {
        "case_id": str(case["case_id"]),
        "guard_family": detector or "drift_union",
        "reviewed": str(case["case_id"]) in reviewed,
    }
    if detector in ("", "code_drift", "int_drift"):
        caught = set(code_drift(requirement, text)) | set(int_drift(requirement, text))
        missed: list[str] = []
        for token in forbidden:
            atoms = _token_atoms(token)
            if atoms:
                if not atoms <= caught:
                    missed.append(token)
            elif not any(token in value or value in token for value in caught):
                missed.append(token)
        detail["caught_by_guards"] = sorted(caught)
        detail["missed_forbidden"] = missed
        detail["passed"] = not missed and bool(forbidden)
        detail["reason"] = (
            "All forbidden tokens caught by drift guards."
            if detail["passed"]
            else "Forbidden tokens escaped the drift guards."
        )
        return detail
    if detector == "foreign_standard_refs":
        flagged = foreign_standard_refs(requirement, text)
        missed = [
            token
            for token in forbidden
            if not any(token in ref or ref in token for ref in flagged)
        ]
        detail["flagged_foreign_refs"] = flagged
        detail["missed_forbidden"] = missed
        detail["passed"] = bool(flagged) and not missed
        detail["reason"] = (
            "Foreign standard refs caught."
            if detail["passed"]
            else "Foreign standard refs escaped the guard."
        )
        return detail
    # opposed_qualifiers：合并候选抹掉原文的对立限定词，生产合并护栏必须反对这桩合并。
    prevented = opposed_qualifiers({"description": text}, {"description": candidate})
    detail["merge_prevented"] = prevented
    detail["passed"] = prevented
    detail["reason"] = (
        "Opposed-qualifier merge prevented by the catalog guard."
        if prevented
        else "Opposed-qualifier merge was not prevented."
    )
    return detail


def _baseline(details: Sequence[dict[str, Any]]) -> dict[str, Any]:
    evaluated = len(details)
    passed = sum(1 for row in details if row["passed"])
    return {
        "policy_version": AGENT_POLICY_VERSION,
        "runner_version": EVAL_RUNNER_VERSION,
        "evaluated": evaluated,
        "passed": passed,
        "failed": evaluated - passed,
        "pass_rate": round(passed / evaluated, 4) if evaluated else 0.0,
        "failed_case_ids": [row["case_id"] for row in details if not row["passed"]],
    }


def evaluate_cases(
    cases: Sequence[dict[str, Any]], *, reviewed_ids: set[str] | None = None
) -> dict[str, Any]:
    reviewed = set(reviewed_ids or set())
    classification_details: list[dict[str, Any]] = []
    for case in cases:
        if case["category"] != "classify":
            continue
        actual = classify_case(case)
        expected = str(case["expected"]["verdict"])
        classification_details.append({
            "case_id": case["case_id"],
            "expected": expected,
            "actual": actual["verdict"],
            "passed": actual["verdict"] == expected,
            "reason": actual["reason"],
            "reviewed": str(case["case_id"]) in reviewed,
        })

    grouping_cases = [case for case in cases if case["category"] == "grouping"]
    grouping_pairs, grouping_details = _grouping_results(grouping_cases, reviewed)

    must_ask_all = [
        _must_ask_case(case, reviewed) for case in cases if case["category"] == "must_ask"
    ]
    must_ask_auto = [row for row in must_ask_all if row["judge"] == "auto"]
    manual_case_ids = [row["case_id"] for row in must_ask_all if row["judge"] == "manual"]

    hallucination_details = [
        _hallucination_case(case, reviewed)
        for case in cases
        if case["category"] == "hallucination"
    ]

    must_ask_baseline = _baseline(must_ask_auto)
    must_ask_baseline["manual_case_ids"] = manual_case_ids
    return {
        "case_count": len(cases),
        "category_counts": category_counts(cases),
        "classification": _baseline(classification_details),
        "classification_details": classification_details,
        "grouping": _baseline(grouping_details),
        "grouping_details": grouping_details,
        "grouping_pairs": grouping_pairs,
        "must_ask": must_ask_baseline,
        "must_ask_details": must_ask_all,
        "hallucination": _baseline(hallucination_details),
        "hallucination_details": hallucination_details,
        "schema_only_categories": [],
        "unreviewed_case_ids": sorted(
            str(case["case_id"]) for case in cases if str(case["case_id"]) not in reviewed
        ),
    }


def _load_manifest(eval_dir: Path) -> dict[str, Any]:
    path = eval_dir / "manifest.json"
    if not path.exists():
        raise AgentEvalValidationError(f"Evaluation manifest does not exist: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentEvalValidationError(f"Invalid evaluation manifest: {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AgentEvalValidationError(f"Evaluation manifest must be a JSON object: {path}")
    return manifest


def run_evaluation(eval_dir: Path, *, update_baseline: bool = False) -> dict[str, Any]:
    root = Path(eval_dir).expanduser().resolve()
    cases = load_cases(root)
    manifest = _load_manifest(root)
    curation = manifest.get("curation") if isinstance(manifest.get("curation"), dict) else {}
    reviewed = {str(value) for value in curation.get("reviewed_case_ids") or []}
    report = evaluate_cases(cases, reviewed_ids=reviewed)
    if update_baseline:
        _record_manifest_baseline(root, report, manifest)
    return report


def _record_manifest_baseline(
    eval_dir: Path, report: dict[str, Any], manifest: dict[str, Any]
) -> None:
    path = eval_dir / "manifest.json"
    manifest["case_count"] = report["case_count"]
    manifest["category_counts"] = report["category_counts"]
    manifest["classification_baseline"] = report["classification"]
    manifest["grouping_baseline"] = report["grouping"]
    manifest["must_ask_baseline"] = report["must_ask"]
    manifest["hallucination_baseline"] = report["hallucination"]
    _atomic_write_json(path, manifest)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt + 1 >= _REPLACE_ATTEMPTS:
                    raise
                time.sleep(_REPLACE_RETRY_DELAY_S)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the agent evaluation dataset (agent-eval-v2).")
    parser.add_argument("--eval-dir", type=Path, required=True)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Atomically refresh manifest baseline fields; evaluation is read-only by default.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    eval_dir = args.eval_dir.expanduser().resolve()
    try:
        report = run_evaluation(eval_dir, update_baseline=args.update_baseline)
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "agent-eval",
            "ok": True,
            "eval_dir": str(eval_dir),
            "summary": {
                "case_count": report["case_count"],
                "category_counts": report["category_counts"],
                "pass_rates": {
                    category: report[category]["pass_rate"]
                    for category in BASELINE_CATEGORIES
                },
                "schema_only_categories": report["schema_only_categories"],
                "unreviewed_count": len(report["unreviewed_case_ids"]),
            },
            "classification": report["classification"],
            "grouping": report["grouping"],
            "must_ask": report["must_ask"],
            "hallucination": report["hallucination"],
            "details": report["classification_details"],
        }
        code = 0
    except AgentEvalInputError as exc:
        envelope = _error_envelope(eval_dir, "input_error", str(exc))
        code = 2
    except AgentEvalValidationError as exc:
        envelope = _error_envelope(eval_dir, "validation_error", str(exc))
        code = 3
    except Exception as exc:  # pragma: no cover - final CLI safety net
        envelope = _error_envelope(eval_dir, "unexpected_error", str(exc))
        code = 1
    print(json.dumps(envelope, ensure_ascii=False))
    return code


def _error_envelope(eval_dir: Path, error_type: str, message: str) -> dict[str, Any]:
    return {
        "tool": "requirement-atomizer",
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "command": "agent-eval",
        "eval_dir": str(eval_dir),
        "ok": False,
        "error": {"type": error_type, "message": message},
    }


if __name__ == "__main__":
    sys.exit(main())
