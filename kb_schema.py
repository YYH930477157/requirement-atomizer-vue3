from __future__ import annotations

import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_KB_FIELDS = {"kb_id", "name", "version", "entries"}
REQUIRED_ENTRY_FIELDS = {"id", "type", "name", "definition"}
RECOMMENDED_ENTRY_FIELDS = {"layer"}


@dataclass(frozen=True)
class KBSchemaIssue:
    severity: str
    path: str
    message: str


def validate_kb_payload(payload: dict[str, Any]) -> list[KBSchemaIssue]:
    issues: list[KBSchemaIssue] = []
    for field in sorted(REQUIRED_KB_FIELDS):
        if field not in payload:
            issues.append(KBSchemaIssue("error", field, f"missing required KB field: {field}"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        issues.append(KBSchemaIssue("error", "entries", "entries must be a list"))
        return issues
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        entry_path = f"entries[{index}]"
        if not isinstance(entry, dict):
            issues.append(KBSchemaIssue("error", entry_path, "entry must be an object"))
            continue
        for field in sorted(REQUIRED_ENTRY_FIELDS):
            if field not in entry or entry.get(field) in {"", None}:
                issues.append(KBSchemaIssue("error", f"{entry_path}.{field}", f"missing required entry field: {field}"))
        for field in sorted(RECOMMENDED_ENTRY_FIELDS):
            if field not in entry or entry.get(field) in {"", None}:
                issues.append(
                    KBSchemaIssue(
                        "warning",
                        f"{entry_path}.{field}",
                        f"missing recommended entry field: {field}; runtime will fall back to KB-level layer or term",
                    )
                )
        entry_id = str(entry.get("id", ""))
        if entry_id in seen_ids:
            issues.append(KBSchemaIssue("error", f"{entry_path}.id", f"duplicate entry id: {entry_id}"))
        if entry_id:
            seen_ids.add(entry_id)
        relations = entry.get("relations", [])
        if relations and not isinstance(relations, list):
            issues.append(KBSchemaIssue("error", f"{entry_path}.relations", "relations must be a list"))
        elif isinstance(relations, list):
            for relation_index, relation in enumerate(relations):
                relation_path = f"{entry_path}.relations[{relation_index}]"
                if not isinstance(relation, dict):
                    issues.append(KBSchemaIssue("error", relation_path, "relation must be an object"))
                    continue
                for field in ["relation", "target"]:
                    if relation.get(field) in {"", None}:
                        issues.append(KBSchemaIssue("error", f"{relation_path}.{field}", f"missing required relation field: {field}"))
    return issues


def validate_kb_file(path: Path) -> list[KBSchemaIssue]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_kb_payload(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Requirement Atomizer knowledge base JSON file.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    issues = validate_kb_file(args.path.expanduser().resolve())
    print(json.dumps([issue.__dict__ for issue in issues], ensure_ascii=False, indent=2))
    has_errors = any(issue.severity == "error" for issue in issues)
    has_warnings = any(issue.severity == "warning" for issue in issues)
    return 1 if has_errors or (args.strict and has_warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
