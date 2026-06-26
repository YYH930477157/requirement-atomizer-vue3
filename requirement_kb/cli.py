from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .coverage import build_coverage_report, render_report
from .obsidian import compile_vault_to_json, export_json_to_vault
from .blue_book_report import build_blue_book_coverage_report, write_blue_book_coverage_report
from .repository import KnowledgeRepository
from .schema import validate_kb_file
from .vault import validate_vault


DEFAULT_KB_FILES = [
    "knowledge_bases/energy_metering.json",
    "knowledge_bases/energy_metering_protocol_layer.json",
    "knowledge_bases/energy_metering_cosem_classes.json",
    "knowledge_bases/compiled_from_obsidian.json",
]


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_kb_paths() -> list[Path]:
    kb_home = os.environ.get("REQUIREMENT_KB_HOME") or os.environ.get("RATOMIZER_KB_HOME")
    if kb_home:
        root = Path(kb_home).expanduser().resolve()
        return [root / Path(rel).name for rel in DEFAULT_KB_FILES]
    root = package_root()
    return [root / rel for rel in DEFAULT_KB_FILES]


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query, validate, and compile Requirement Atomizer knowledge bases.")
    parser.add_argument("--kb", type=Path, action="append", default=[], help="Knowledge base JSON file. Can be repeated.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Show loaded KB metadata")

    search = sub.add_parser("search", help="Search KB entries")
    search.add_argument("query")
    search.add_argument("--layer", default=None)
    search.add_argument("--type", dest="entry_type", default=None)
    search.add_argument("--limit", type=int, default=20)

    get = sub.add_parser("get", help="Get one KB entry by id")
    get.add_argument("entry_id")
    get.add_argument("--kb-id", default=None)

    match = sub.add_parser("match", help="Match KB entries against free text")
    match.add_argument("text")
    match.add_argument("--layer", default=None)
    match.add_argument("--type", dest="entry_type", default=None)
    match.add_argument("--limit", type=int, default=50)

    context = sub.add_parser("context", help="Return compact LLM context for free text")
    context.add_argument("text")
    context.add_argument("--limit", type=int, default=20)

    blue_book = sub.add_parser("blue-book-report", help="Report Blue Book coverage in a compiled KB")
    blue_book.add_argument("--kb", type=Path, default=Path("knowledge_bases/compiled_from_obsidian.json"))
    blue_book.add_argument("--out", type=Path, default=None)

    validate = sub.add_parser("validate", help="Validate compiled JSON KB files")
    validate.add_argument("path", type=Path)
    validate.add_argument("--strict", action="store_true", help="Treat warnings as errors.")

    vault_validate = sub.add_parser("validate-vault", help="Validate an Obsidian KB vault")
    vault_validate.add_argument("--vault", type=Path, default=Path("obsidian-vault"))

    vault_export = sub.add_parser("export-vault", help="Export JSON KB files to Obsidian Markdown")
    vault_export.add_argument("--kb", type=Path, action="append", required=True)
    vault_export.add_argument("--vault", type=Path, required=True)

    vault_compile = sub.add_parser("compile-vault", help="Compile Obsidian Markdown vault to JSON KB")
    vault_compile.add_argument("--vault", type=Path, required=True)
    vault_compile.add_argument("--out", type=Path, required=True)
    vault_compile.add_argument("--kb-id", default="obsidian_energy_metering")

    coverage = sub.add_parser("coverage", help="Print Blue Book KB coverage report (Part 1/Part 2/distribution)")
    coverage.add_argument("path", type=Path, help="Compiled KB JSON file")
    coverage.add_argument("--format", choices=["json", "markdown"], default="markdown")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command in {"info", "search", "get", "match", "context"}:
        kb_paths = args.kb or default_kb_paths()
        repo = KnowledgeRepository.from_paths(kb_paths)
        if args.command == "info":
            print_json(repo.info())
        elif args.command == "search":
            print_json(repo.search(args.query, layer=args.layer, entry_type=args.entry_type, limit=args.limit))
        elif args.command == "get":
            print_json(repo.get(args.entry_id, kb_id=args.kb_id))
        elif args.command == "match":
            print_json(repo.match_text(args.text, layer=args.layer, entry_type=args.entry_type, limit=args.limit))
        elif args.command == "context":
            print_json(repo.export_context(args.text, limit=args.limit))
        return 0

    if args.command == "validate":
        issues = validate_kb_file(args.path.expanduser().resolve())
        print_json([issue.__dict__ for issue in issues])
        has_errors = any(issue.severity == "error" for issue in issues)
        has_warnings = any(issue.severity == "warning" for issue in issues)
        return 1 if has_errors or (args.strict and has_warnings) else 0

    if args.command == "validate-vault":
        report = validate_vault(args.vault)
        print_json(report.to_dict())
        return 0 if report.ok else 1

    if args.command == "blue-book-report":
        if args.out:
            print_json(write_blue_book_coverage_report(args.kb, args.out))
        else:
            print_json(build_blue_book_coverage_report(args.kb))
        return 0

    if args.command == "export-vault":
        written = export_json_to_vault(args.kb, args.vault)
        print_json({"vault": str(args.vault.resolve()), "notes": len(written)})
        return 0

    if args.command == "compile-vault":
        payload = compile_vault_to_json(args.vault, args.out, kb_id=args.kb_id)
        print_json({"output": str(args.out.resolve()), "entries": len(payload["entries"])})
        return 0

    if args.command == "coverage":
        report = build_coverage_report(args.path)
        if args.format == "json":
            print_json(report)
        else:
            print(render_report(report))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
