from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "req_id",
    "stable_req_id",
    "source_id",
    "source_type",
    "source_refs",
    "domain",
    "object",
    "requirement_type",
    "requirement",
    "verification_method",
    "ambiguity",
    "confidence",
    "generated_by",
}

REQ_ID_RE = re.compile(r"^AREQ-[0-9]{6}$")
STABLE_REQ_ID_RE = re.compile(r"^SREQ-[0-9A-F]{16}$")


@dataclass(frozen=True)
class AtomicRequirementIssue:
    severity: str
    path: str
    message: str


def validate_atomic_requirements(rows: list[dict[str, Any]]) -> list[AtomicRequirementIssue]:
    issues: list[AtomicRequirementIssue] = []
    seen_req_ids: set[str] = set()
    seen_stable_req_ids: set[str] = set()
    for index, row in enumerate(rows):
        row_path = f"requirements[{index}]"
        issues.extend(validate_atomic_requirement_payload(row, path=row_path))
        req_id = str(row.get("req_id") or "")
        stable_req_id = str(row.get("stable_req_id") or "")
        if req_id:
            if req_id in seen_req_ids:
                issues.append(AtomicRequirementIssue("error", f"{row_path}.req_id", f"duplicate req_id: {req_id}"))
            seen_req_ids.add(req_id)
        if stable_req_id:
            if stable_req_id in seen_stable_req_ids:
                issues.append(
                    AtomicRequirementIssue("error", f"{row_path}.stable_req_id", f"duplicate stable_req_id: {stable_req_id}")
                )
            seen_stable_req_ids.add(stable_req_id)
    return issues


def validate_atomic_requirement_payload(
    row: dict[str, Any],
    *,
    path: str = "requirement",
) -> list[AtomicRequirementIssue]:
    issues: list[AtomicRequirementIssue] = []
    for field in sorted(REQUIRED_FIELDS):
        if field not in row:
            issues.append(AtomicRequirementIssue("error", f"{path}.{field}", f"missing required field: {field}"))

    req_id = row.get("req_id")
    if req_id is not None and not REQ_ID_RE.fullmatch(str(req_id)):
        issues.append(AtomicRequirementIssue("error", f"{path}.req_id", f"invalid req_id: {req_id}"))

    stable_req_id = row.get("stable_req_id")
    if stable_req_id is not None and not STABLE_REQ_ID_RE.fullmatch(str(stable_req_id)):
        issues.append(AtomicRequirementIssue("error", f"{path}.stable_req_id", f"invalid stable_req_id: {stable_req_id}"))

    for field in ("source_id", "source_type", "domain", "requirement_type", "verification_method", "generated_by"):
        value = row.get(field)
        if value is not None and not non_empty_string(value):
            issues.append(AtomicRequirementIssue("error", f"{path}.{field}", f"{field} must be a non-empty string"))

    requirement = row.get("requirement")
    if requirement is not None and not non_empty_string(requirement):
        issues.append(AtomicRequirementIssue("error", f"{path}.requirement", "requirement must be a non-empty string"))

    if "object" in row and not isinstance(row.get("object"), str):
        issues.append(AtomicRequirementIssue("error", f"{path}.object", "object must be a string"))

    source_refs = row.get("source_refs")
    if source_refs is not None:
        if not isinstance(source_refs, list):
            issues.append(AtomicRequirementIssue("error", f"{path}.source_refs", "source_refs must be a list"))
        elif any(not non_empty_string(ref) for ref in source_refs):
            issues.append(
                AtomicRequirementIssue("error", f"{path}.source_refs", "source_refs must contain non-empty strings")
            )

    for field in ("section_path", "domain_tags", "review_questions"):
        value = row.get(field)
        if value is not None:
            validate_string_list(value, f"{path}.{field}", field, issues)

    if "condition" in row and row.get("condition") is not None and not isinstance(row.get("condition"), str):
        issues.append(AtomicRequirementIssue("error", f"{path}.condition", "condition must be a string or null"))

    for field in ("parameters",):
        value = row.get(field)
        if value is not None and not isinstance(value, dict):
            issues.append(AtomicRequirementIssue("error", f"{path}.{field}", f"{field} must be an object"))

    kb_matches = row.get("kb_matches")
    if kb_matches is not None:
        if not isinstance(kb_matches, list):
            issues.append(AtomicRequirementIssue("error", f"{path}.kb_matches", "kb_matches must be a list"))
        elif any(not isinstance(match, dict) for match in kb_matches):
            issues.append(AtomicRequirementIssue("error", f"{path}.kb_matches", "kb_matches must contain objects"))

    source_context = row.get("source_context")
    if source_context is not None:
        if not isinstance(source_context, dict):
            issues.append(AtomicRequirementIssue("error", f"{path}.source_context", "source_context must be an object"))
        else:
            paragraph_text = source_context.get("paragraph_text")
            if paragraph_text is not None and not isinstance(paragraph_text, str):
                issues.append(
                    AtomicRequirementIssue(
                        "error",
                        f"{path}.source_context.paragraph_text",
                        "source_context.paragraph_text must be a string",
                    )
                )
            prev_sentence = source_context.get("prev_sentence")
            if prev_sentence is not None and not isinstance(prev_sentence, str):
                issues.append(
                    AtomicRequirementIssue(
                        "error",
                        f"{path}.source_context.prev_sentence",
                        "source_context.prev_sentence must be a string or null",
                    )
                )

    ambiguity = row.get("ambiguity")
    if ambiguity is not None and not isinstance(ambiguity, bool):
        issues.append(AtomicRequirementIssue("error", f"{path}.ambiguity", "ambiguity must be a boolean"))

    confidence = row.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1:
            issues.append(AtomicRequirementIssue("error", f"{path}.confidence", "confidence must be between 0 and 1"))

    return issues


def validate_string_list(value: Any, path: str, field: str, issues: list[AtomicRequirementIssue]) -> None:
    if not isinstance(value, list):
        issues.append(AtomicRequirementIssue("error", path, f"{field} must be a list"))
        return
    if any(not isinstance(item, str) for item in value):
        issues.append(AtomicRequirementIssue("error", path, f"{field} must contain strings"))


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def validate_atomic_requirement_file(path: Path) -> list[AtomicRequirementIssue]:
    return validate_atomic_requirements(read_jsonl(path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate atomic_requirements.jsonl output.")
    parser.add_argument("path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    issues = validate_atomic_requirement_file(args.path.expanduser().resolve())
    print(json.dumps([issue.__dict__ for issue in issues], ensure_ascii=False, indent=2))
    return 1 if any(issue.severity == "error" for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
