from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .obsidian import FOLDER_BY_LAYER, extract_definition, split_frontmatter


REQUIRED_FRONTMATTER_FIELDS = ("id", "kb_id", "type", "layer", "name")
LIST_FRONTMATTER_FIELDS = ("aliases", "keywords", "domain_tags", "relations")


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    severity: Severity
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity.value,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationReport:
    vault: str
    notes: int
    errors: int
    warnings: int
    issues: tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        return self.errors == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "vault": self.vault,
            "notes": self.notes,
            "errors": self.errors,
            "warnings": self.warnings,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_vault(vault_path: Path) -> ValidationReport:
    vault = vault_path.expanduser().resolve()
    issues: list[Issue] = []
    note_records: list[tuple[Path, dict[str, Any], str]] = []
    ids: dict[str, list[Path]] = {}

    if not vault.exists():
        issues.append(Issue(Severity.ERROR, str(vault), "vault path does not exist"))
        return build_report(vault, 0, issues)
    if not vault.is_dir():
        issues.append(Issue(Severity.ERROR, str(vault), "vault path is not a directory"))
        return build_report(vault, 0, issues)

    for path in sorted(vault.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        rel_path = relative_display_path(path, vault)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            issues.append(Issue(Severity.ERROR, rel_path, f"not valid UTF-8: {exc}"))
            continue

        frontmatter, body, parse_issue = parse_frontmatter(text)
        if parse_issue:
            issues.append(Issue(Severity.ERROR, rel_path, parse_issue))
            continue

        note_records.append((path, frontmatter, body))
        validate_required_fields(frontmatter, rel_path, issues)
        validate_list_fields(frontmatter, rel_path, issues)
        validate_definition(body, rel_path, issues)
        validate_metadata_json(body, rel_path, issues)
        validate_layer_folder(frontmatter, path, vault, rel_path, issues)

        entry_id = clean_scalar(frontmatter.get("id"))
        if entry_id:
            ids.setdefault(entry_id, []).append(path)

    validate_duplicate_ids(ids, vault, issues)
    validate_relation_targets(note_records, ids, vault, issues)
    return build_report(vault, len(note_records), issues)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    if not text.startswith("---\n"):
        return {}, text, "missing YAML frontmatter"
    try:
        frontmatter, body = split_frontmatter(text)
    except yaml.YAMLError as exc:
        return {}, "", f"invalid YAML frontmatter: {exc}"
    if not frontmatter:
        return {}, body, "empty or invalid YAML frontmatter"
    return frontmatter, body, None


def validate_required_fields(frontmatter: dict[str, Any], rel_path: str, issues: list[Issue]) -> None:
    for field in REQUIRED_FRONTMATTER_FIELDS:
        if not clean_scalar(frontmatter.get(field)):
            issues.append(Issue(Severity.ERROR, rel_path, f"missing required field: {field}"))


def validate_list_fields(frontmatter: dict[str, Any], rel_path: str, issues: list[Issue]) -> None:
    for field in LIST_FRONTMATTER_FIELDS:
        if field in frontmatter and not isinstance(frontmatter[field], list):
            issues.append(Issue(Severity.ERROR, rel_path, f"field must be a list: {field}"))


def validate_definition(body: str, rel_path: str, issues: list[Issue]) -> None:
    if not extract_definition(body):
        issues.append(Issue(Severity.ERROR, rel_path, "missing definition in ## Definition section"))


def validate_metadata_json(body: str, rel_path: str, issues: list[Issue]) -> None:
    for raw in iter_metadata_blocks(body):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(Issue(Severity.ERROR, rel_path, f"invalid metadata JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"))
            continue
        if not isinstance(payload, dict):
            issues.append(Issue(Severity.ERROR, rel_path, "metadata JSON must be an object"))


def validate_layer_folder(frontmatter: dict[str, Any], path: Path, vault: Path, rel_path: str, issues: list[Issue]) -> None:
    layer = clean_scalar(frontmatter.get("layer"))
    if not layer:
        return
    expected_folder = FOLDER_BY_LAYER.get(layer)
    if not expected_folder:
        issues.append(Issue(Severity.WARNING, rel_path, f"unknown layer: {layer}"))
        return
    relative_parts = path.relative_to(vault).parts
    if relative_parts and relative_parts[0] != expected_folder:
        issues.append(Issue(Severity.WARNING, rel_path, f"layer {layer} is normally stored under {expected_folder}/"))


def validate_duplicate_ids(ids: dict[str, list[Path]], vault: Path, issues: list[Issue]) -> None:
    for entry_id, paths in sorted(ids.items()):
        if len(paths) <= 1:
            continue
        joined = ", ".join(relative_display_path(path, vault) for path in paths)
        issues.append(Issue(Severity.ERROR, joined, f"duplicate id: {entry_id}"))


def validate_relation_targets(
    note_records: list[tuple[Path, dict[str, Any], str]],
    ids: dict[str, list[Path]],
    vault: Path,
    issues: list[Issue],
) -> None:
    for path, frontmatter, _body in note_records:
        rel_path = relative_display_path(path, vault)
        relations = frontmatter.get("relations") or []
        if not isinstance(relations, list):
            continue
        for index, relation in enumerate(relations, start=1):
            if not isinstance(relation, dict):
                issues.append(Issue(Severity.ERROR, rel_path, f"relation #{index} must be an object"))
                continue
            target = clean_scalar(relation.get("target"))
            relation_name = clean_scalar(relation.get("relation"))
            if not relation_name:
                issues.append(Issue(Severity.ERROR, rel_path, f"relation #{index} missing relation"))
            if not target:
                issues.append(Issue(Severity.ERROR, rel_path, f"relation #{index} missing target"))
                continue
            if target not in ids:
                issues.append(Issue(Severity.WARNING, rel_path, f"relation target not found: {target}"))


def iter_metadata_blocks(body: str) -> list[str]:
    pattern = r"```json\s+metadata\s*(.*?)```"
    return [match.strip() for match in re.findall(pattern, body, flags=re.S) if match.strip()]


def clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def relative_display_path(path: Path, vault: Path) -> str:
    try:
        return path.relative_to(vault).as_posix()
    except ValueError:
        return str(path)


def build_report(vault: Path, notes: int, issues: list[Issue]) -> ValidationReport:
    errors = sum(1 for issue in issues if issue.severity == Severity.ERROR)
    warnings = sum(1 for issue in issues if issue.severity == Severity.WARNING)
    issues.sort(key=lambda issue: (issue.severity.value, issue.path, issue.message))
    return ValidationReport(
        vault=str(vault),
        notes=notes,
        errors=errors,
        warnings=warnings,
        issues=tuple(issues),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Requirement Atomizer Obsidian vault notes.")
    parser.add_argument("--vault", type=Path, default=Path("obsidian-vault"), help="Obsidian vault directory.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def print_text_report(report: ValidationReport) -> None:
    status = "OK" if report.ok else "FAILED"
    print(f"Vault validation {status}")
    print(f"Vault: {report.vault}")
    print(f"Notes: {report.notes}")
    print(f"Errors: {report.errors}")
    print(f"Warnings: {report.warnings}")
    if report.issues:
        print()
        for issue in report.issues:
            print(f"[{issue.severity.value}] {issue.path}: {issue.message}")


def main() -> int:
    args = parse_args()
    report = validate_vault(args.vault)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_text_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
