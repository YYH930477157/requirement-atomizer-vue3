from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {"task_id", "source_refs", "decision", "confidence"}
VALID_DECISIONS = {"accept", "revise", "split", "merge", "reject", "needs_expert"}


@dataclass(frozen=True)
class LLMReviewIssue:
    severity: str
    path: str
    message: str


def validate_llm_review_results(rows: list[dict[str, Any]]) -> list[LLMReviewIssue]:
    issues: list[LLMReviewIssue] = []
    for index, row in enumerate(rows):
        issues.extend(validate_llm_review_result_payload(row, path=f"reviews[{index}]"))
    return issues


def validate_llm_review_result_payload(
    row: dict[str, Any],
    *,
    path: str = "review",
) -> list[LLMReviewIssue]:
    issues: list[LLMReviewIssue] = []
    for field in sorted(REQUIRED_FIELDS):
        if field not in row:
            issues.append(LLMReviewIssue("error", f"{path}.{field}", f"missing required field: {field}"))

    for field in ("task_id",):
        value = row.get(field)
        if value is not None and not non_empty_string(value):
            issues.append(LLMReviewIssue("error", f"{path}.{field}", f"{field} must be a non-empty string"))

    for field in ("requirement_id", "req_id", "stable_req_id", "revised_requirement"):
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            issues.append(LLMReviewIssue("error", f"{path}.{field}", f"{field} must be a string"))

    source_refs = row.get("source_refs")
    if source_refs is not None:
        validate_string_list(source_refs, f"{path}.source_refs", "source_refs", issues)

    decision = row.get("decision")
    if decision is not None and decision not in VALID_DECISIONS:
        issues.append(LLMReviewIssue("error", f"{path}.decision", f"invalid decision: {decision}"))

    for field in ("review_notes", "expert_questions"):
        value = row.get(field)
        if value is not None:
            validate_string_list(value, f"{path}.{field}", field, issues)

    confidence = row.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1:
            issues.append(LLMReviewIssue("error", f"{path}.confidence", "confidence must be between 0 and 1"))

    return issues


def validate_string_list(value: Any, path: str, field: str, issues: list[LLMReviewIssue]) -> None:
    if not isinstance(value, list):
        issues.append(LLMReviewIssue("error", path, f"{field} must be a list"))
        return
    if any(not isinstance(item, str) for item in value):
        issues.append(LLMReviewIssue("error", path, f"{field} must contain strings"))


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def validate_llm_review_file(path: Path) -> list[LLMReviewIssue]:
    return validate_llm_review_results(read_jsonl(path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate llm_review_results.jsonl output.")
    parser.add_argument("path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    issues = validate_llm_review_file(args.path.expanduser().resolve())
    print(json.dumps([issue.__dict__ for issue in issues], ensure_ascii=False, indent=2))
    return 1 if any(issue.severity == "error" for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
