from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\uf020", " ")
    value = value.replace("\uf03d", "=")
    value = value.replace("\uf03e", ">")
    value = value.replace("", ">")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*_\s*", "_", value)
    value = re.sub(r"\s*-\s*", "-", value)
    return value.strip()


def is_object_header(fields: dict[str, Any]) -> bool:
    return bool(fields.get("Object/attribute name") and fields.get("CL"))


def is_attribute_row(fields: dict[str, Any]) -> bool:
    return bool(fields.get("#") and fields.get("Object/attribute name"))


_CONTINUATION_TITLE_RE = re.compile(
    r"(?:\bcontinued\b|\bcontinuation\b|\bcont\.?\b|\u7eed\u8868)",
    flags=re.IGNORECASE,
)


def _table_title_key(value: Any) -> str:
    title = normalize_name(str(value or "")).casefold()
    title = _CONTINUATION_TITLE_RE.sub("", title)
    return title.strip(" -:()")


def _continues_object_table(
    previous_table_id: str,
    previous_title: str,
    previous_section: tuple[str, ...],
    item: dict[str, Any],
) -> bool:
    """Require explicit table-continuation evidence before carrying an object."""
    table_id = str(item.get("table_id") or "")
    if table_id == previous_table_id:
        return True
    if not table_id or not previous_table_id:
        return not table_id and not previous_table_id

    continued_from = str(
        item.get("continued_from_table_id")
        or item.get("continuation_of_table_id")
        or item.get("continuation_of")
        or ""
    )
    if continued_from and continued_from == previous_table_id:
        return True

    title = normalize_name(str(item.get("table_title") or ""))
    section = tuple(str(value) for value in (item.get("section_path") or []))
    if section != previous_section or not title or not previous_title:
        return False
    same_base_title = _table_title_key(title) == _table_title_key(previous_title)
    return same_base_title and (
        title.casefold() == previous_title.casefold()
        or bool(_CONTINUATION_TITLE_RE.search(title))
    )


def parse_intish(value: Any) -> int | str | None:
    if value is None:
        return None
    text = normalize_name(str(value)).lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    if text in words:
        return words[text]
    if text.isdigit():
        return int(text)
    return normalize_name(str(value))


def extract_instances(table_items_path: Path) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_table_id = ""
    current_table_title = ""
    current_section: tuple[str, ...] = ()

    for item in iter_jsonl(table_items_path):
        fields = item.get("fields", {})
        table_id = str(item.get("table_id") or "")
        table_title = normalize_name(str(item.get("table_title") or ""))
        section = tuple(str(value) for value in (item.get("section_path") or []))

        if current and table_id != current_table_id:
            if _continues_object_table(
                current_table_id, current_table_title, current_section, item,
            ):
                current_table_id = table_id
                current_table_title = table_title
                current_section = section
                source_table_ids = current["source"].setdefault("table_ids", [])
                if table_id and table_id not in source_table_ids:
                    source_table_ids.append(table_id)
            else:
                instances.append(current)
                current = None
                current_table_id = ""
                current_table_title = ""
                current_section = ()

        if is_object_header(fields):
            if current:
                instances.append(current)
            current = {
                "instance_id": f"COSEM-OBJ-{len(instances) + 1:06d}",
                "name": normalize_name(fields.get("Object/attribute name")),
                "class_id": parse_intish(fields.get("CL")),
                "obis": normalize_name(fields.get("Value")),
                "meaning": normalize_name(fields.get("Meaning")),
                "comment": normalize_name(fields.get("Comment")),
                "source": {
                    "table_item_id": item.get("item_id"),
                    "table_id": table_id,
                    "table_ids": [table_id] if table_id else [],
                    "table_title": item.get("table_title"),
                    "section_path": item.get("section_path", []),
                    "row_index": item.get("row_index"),
                },
                "attributes": [],
                "domain_tags": item.get("domain_tags", []),
                "kb_matches": item.get("kb_matches", []),
            }
            current_table_id = table_id
            current_table_title = table_title
            current_section = section
            continue

        if current and is_attribute_row(fields):
            current["attributes"].append(
                {
                    "attribute_id": parse_intish(fields.get("#")),
                    "name": normalize_name(fields.get("Object/attribute name")),
                    "type": normalize_name(fields.get("Type")),
                    "value": normalize_name(fields.get("Value")),
                    "meaning": normalize_name(fields.get("Meaning")),
                    "comment": normalize_name(fields.get("Comment")),
                    "access_rights": normalize_name(fields.get("Access rights RC/PC/SC/LC")),
                    "source": {
                        "table_item_id": item.get("item_id"),
                        "table_id": table_id,
                        "row_index": item.get("row_index"),
                    },
                }
            )

    if current:
        instances.append(current)

    return instances


def build_kb(instances: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for instance in instances:
        class_id = instance.get("class_id")
        name = instance.get("name")
        obis = instance.get("obis")
        keywords = [str(v) for v in [name, obis] if v]
        keywords.extend(attr["name"] for attr in instance.get("attributes", [])[:12] if attr.get("name"))
        entries.append(
            {
                "id": f"KB-DOC-COSEM-{instance['instance_id']}",
                "type": "cosem_object_instance",
                "layer": "cosem_object_instance",
                "name": name,
                "aliases": [],
                "keywords": keywords,
                "domain_tags": ["cosem_object_instance", "cosem_object", "data_model"],
                "definition": f"COSEM object instance from source document: {name} (CL {class_id}, OBIS {obis}).",
                "class_id": class_id,
                "obis": obis,
                "meaning": instance.get("meaning"),
                "comment": instance.get("comment"),
                "attributes": instance.get("attributes", []),
                "source": instance.get("source"),
            }
        )
    return {
        "kb_id": "document_cosem_object_instances",
        "name": "Document COSEM Object Instances",
        "version": "0.1.0",
        "layer": "cosem_object_instance",
        "description": "Generated from table_items.jsonl. Review before treating as authoritative.",
        "entries": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract COSEM object instances from atomizer table_items.jsonl.")
    parser.add_argument("input", type=Path, help="table_items.jsonl or output directory containing table_items.jsonl")
    parser.add_argument("--out", type=Path, default=None, help="Output instances JSON path")
    parser.add_argument("--kb-out", type=Path, default=None, help="Optional generated KB JSON path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    table_items_path = input_path / "table_items.jsonl" if input_path.is_dir() else input_path
    if not table_items_path.exists():
        print(f"Missing table_items.jsonl: {table_items_path}", file=sys.stderr)
        return 2

    instances = extract_instances(table_items_path)
    out_path = args.out.expanduser().resolve() if args.out else table_items_path.parent / "cosem_object_instances.json"
    out_path.write_text(json.dumps(instances, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload: dict[str, Any] = {"output": str(out_path), "instances": len(instances)}
    if args.kb_out:
        kb_path = args.kb_out.expanduser().resolve()
        kb_path.write_text(json.dumps(build_kb(instances), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["kb_output"] = str(kb_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
