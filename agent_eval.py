"""Phase 0 evaluation runner for the future requirements-analysis agent."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from agent_policy import AGENT_POLICY_VERSION
from atomize import is_requirement_like
from compliance import looks_like_compliance
from requirements_analysis_rules import classify_ownership


EVAL_RUNNER_VERSION = "agent-eval-v1"
ENVELOPE_SCHEMA_VERSION = "1.0"
CASE_SCHEMA = Path(__file__).resolve().parent / "schemas" / "agent_eval_case.schema.json"
CATEGORIES = ("classify", "grouping", "must_ask", "hallucination")

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


def evaluate_cases(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    for case in cases:
        if case["category"] != "classify":
            continue
        actual = classify_case(case)
        expected = str(case["expected"]["verdict"])
        details.append({
            "case_id": case["case_id"],
            "expected": expected,
            "actual": actual["verdict"],
            "passed": actual["verdict"] == expected,
            "reason": actual["reason"],
        })

    passed = sum(1 for row in details if row["passed"])
    evaluated = len(details)
    classification = {
        "policy_version": AGENT_POLICY_VERSION,
        "runner_version": EVAL_RUNNER_VERSION,
        "evaluated": evaluated,
        "passed": passed,
        "failed": evaluated - passed,
        "pass_rate": round(passed / evaluated, 4) if evaluated else 0.0,
        "failed_case_ids": [row["case_id"] for row in details if not row["passed"]],
    }
    return {
        "case_count": len(cases),
        "category_counts": category_counts(cases),
        "classification": classification,
        "classification_details": details,
        "schema_only_categories": ["grouping", "must_ask", "hallucination"],
    }


def run_evaluation(eval_dir: Path) -> dict[str, Any]:
    root = Path(eval_dir).expanduser().resolve()
    cases = load_cases(root)
    report = evaluate_cases(cases)
    _record_manifest_baseline(root, report)
    return report


def _record_manifest_baseline(eval_dir: Path, report: dict[str, Any]) -> None:
    path = eval_dir / "manifest.json"
    if not path.exists():
        raise AgentEvalValidationError(f"Evaluation manifest does not exist: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentEvalValidationError(f"Invalid evaluation manifest: {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AgentEvalValidationError(f"Evaluation manifest must be a JSON object: {path}")
    manifest["case_count"] = report["case_count"]
    manifest["category_counts"] = report["category_counts"]
    manifest["classification_baseline"] = report["classification"]
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
    parser = argparse.ArgumentParser(description="Run the Phase 0 agent evaluation dataset.")
    parser.add_argument("--eval-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    eval_dir = args.eval_dir.expanduser().resolve()
    try:
        report = run_evaluation(eval_dir)
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "agent-eval",
            "ok": True,
            "eval_dir": str(eval_dir),
            "summary": {
                "case_count": report["case_count"],
                "category_counts": report["category_counts"],
                "schema_only_categories": report["schema_only_categories"],
            },
            "classification": report["classification"],
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
        "ok": False,
        "eval_dir": str(eval_dir),
        "error": {"type": error_type, "message": message},
    }


if __name__ == "__main__":
    sys.exit(main())
