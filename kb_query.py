from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from kb_api import KnowledgeRepository


DEFAULT_KB_FILES = [
    "knowledge_bases/energy_metering.json",
    "knowledge_bases/energy_metering_protocol_layer.json",
    "knowledge_bases/energy_metering_cosem_classes.json",
]


def default_kb_paths() -> list[Path]:
    root = Path(__file__).resolve().parent
    return [root / rel for rel in DEFAULT_KB_FILES]


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the Requirement Atomizer knowledge bases.")
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

    return parser.parse_args()


def main() -> int:
    args = parse_args()
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


if __name__ == "__main__":
    raise SystemExit(main())

