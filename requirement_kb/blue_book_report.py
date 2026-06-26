from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .blue_book_catalog import PART1_OBIS_TABLES, PART2_CURRENT_CLASSES


def build_blue_book_coverage_report(kb_path: Path) -> dict[str, Any]:
    payload = json.loads(kb_path.expanduser().resolve().read_text(encoding="utf-8"))
    entries = list(payload.get("entries") or [])
    obis_tables = [entry for entry in entries if entry.get("type") == "obis_table"]
    classes = [entry for entry in entries if entry.get("type") == "cosem_interface_class"]
    object_instances = [entry for entry in entries if entry.get("type") == "cosem_object_instance"]

    table_entries_by_no = {
        int(entry.get("table_no")): entry
        for entry in obis_tables
        if entry.get("table_no") is not None
    }
    class_entries_by_id = {
        int(entry.get("class_id")): entry
        for entry in classes
        if entry.get("class_id") is not None
    }
    class_levels = Counter(class_coverage_level(entry) for entry in classes)
    by_table = Counter(str((entry.get("blue_book_table_ref") or {}).get("table_no") or "") for entry in object_instances)
    by_table.pop("", None)

    return {
        "kb_id": payload.get("kb_id"),
        "entries_total": len(entries),
        "part1_obis_tables": {
            "covered": sum(1 for table_no, _ in PART1_OBIS_TABLES if table_no in table_entries_by_no),
            "total": len(PART1_OBIS_TABLES),
            "missing": [
                {"table_no": table_no, "title": title}
                for table_no, title in PART1_OBIS_TABLES
                if table_no not in table_entries_by_no
            ],
        },
        "part2_interface_classes": {
            "covered": sum(1 for class_id, _, _ in PART2_CURRENT_CLASSES if class_id in class_entries_by_id),
            "total": len(PART2_CURRENT_CLASSES),
            "enriched": class_levels.get("enriched", 0),
            "catalogue_seed": class_levels.get("catalogue_seed", 0),
            "missing": [
                {"class_id": class_id, "version": version, "name": name}
                for class_id, version, name in PART2_CURRENT_CLASSES
                if class_id not in class_entries_by_id
            ],
            "seed_classes": [
                {"class_id": int(entry.get("class_id")), "name": entry.get("name")}
                for entry in sorted(classes, key=lambda item: int(item.get("class_id") or 0))
                if class_coverage_level(entry) == "catalogue_seed"
            ],
        },
        "object_instances": {
            "total": len(object_instances),
            "by_medium": dict(sorted(Counter(str(entry.get("medium") or "unknown") for entry in object_instances).items())),
            "by_class_id": dict(sorted(Counter(str(entry.get("likely_interface_class_id") or "unknown") for entry in object_instances).items())),
            "by_table": dict(sorted(by_table.items(), key=lambda item: int(item[0]))),
        },
    }


def class_coverage_level(entry: dict[str, Any]) -> str:
    explicit = entry.get("coverage_level")
    if explicit:
        return str(explicit)
    if entry.get("methods") or entry.get("access_semantics"):
        return "enriched"
    attributes = entry.get("attributes") or []
    if len(attributes) > 1:
        return "enriched"
    return "catalogue_seed"


def write_blue_book_coverage_report(kb_path: Path, out_path: Path) -> dict[str, Any]:
    report = build_blue_book_coverage_report(kb_path)
    out_path.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report DLMS UA Blue Book coverage in a compiled KB.")
    parser.add_argument("--kb", type=Path, default=Path("knowledge_bases/compiled_from_obsidian.json"))
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.out:
        report = write_blue_book_coverage_report(args.kb, args.out)
    else:
        report = build_blue_book_coverage_report(args.kb)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
