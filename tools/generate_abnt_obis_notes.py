from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


CLASS_FALLBACKS = {
    "1": "Data",
    "3": "Register",
    "4": "Extended Register",
    "5": "Demand Register",
    "7": "Profile Generic",
    "9": "Script Table",
    "10": "Schedule",
    "11": "Special Days Table",
    "15": "Association LN",
    "22": "Single Action Schedule",
    "23": "IEC HDLC Setup",
    "61": "Register Table",
    "64": "Security Setup",
    "70": "Disconnect Control",
    "122": "Key Expiration Control Function",
    "128": "SCHC-LoRaWAN Setup",
}


MEDIUM_BY_A = {
    "0": "general",
    "1": "ac_electricity",
    "2": "dc_electricity",
    "4": "hca",
    "6": "thermal_energy",
    "7": "gas",
    "8": "water",
    "9": "hot_water",
}


def slugify(value: str, *, limit: int = 96) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return (value[:limit].rstrip() or "untitled")


def entry_id_for_obis(obis: str, name: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "-", f"{obis}-{name}").strip("-").upper()
    return f"KB-ABNT-OBIS-{token[:150]}"


def parse_obis_groups(obis: str) -> dict[str, str]:
    first = obis.split()[0]
    match = re.match(r"(?P<A>[^-]+)-(?P<B>[^:]+):(?P<C>[^.]+)\.(?P<D>[^.]+)\.(?P<E>[^.]+)\.(?P<F>.+)", first)
    return match.groupdict() if match else {}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def existing_obis_patterns(kb: dict[str, Any]) -> set[str]:
    return {
        str(entry.get("obis_pattern") or "").strip()
        for entry in kb.get("entries", [])
        if entry.get("type") == "cosem_object_instance"
    }


def class_entries(kb: dict[str, Any]) -> dict[str, str]:
    return {
        str(entry["class_id"]): str(entry.get("name") or CLASS_FALLBACKS.get(str(entry["class_id"]), "COSEM Object"))
        for entry in kb.get("entries", [])
        if entry.get("type") == "cosem_interface_class" and entry.get("class_id") is not None
    }


def class_names(kb: dict[str, Any]) -> dict[str, str]:
    names = dict(CLASS_FALLBACKS)
    names.update(class_entries(kb))
    return names


def class_folder(class_id: str, class_name: str) -> str:
    try:
        prefix = f"{int(class_id):03d}"
    except ValueError:
        prefix = class_id.zfill(3)
    return f"{prefix}-{slugify(class_name, limit=64)}"


def source_ref_strings(obj: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in obj.get("source_refs") or []:
        if value:
            refs.append(str(value))
    for value in obj.get("source_table_ids") or []:
        if value and str(value) not in refs:
            refs.append(str(value))
    return refs


def build_entry(obj: dict[str, Any], class_names_by_id: dict[str, str], relation_class_ids: set[str]) -> dict[str, Any]:
    obis = str(obj.get("obis") or "").strip()
    name = str(obj.get("object") or obis).strip() or obis
    meaning = str(obj.get("meaning") or "").strip()
    class_id = str(obj.get("class_id") or "").strip()
    class_name = class_names_by_id.get(class_id, CLASS_FALLBACKS.get(class_id, f"Class {class_id}"))
    groups = parse_obis_groups(obis)
    medium = MEDIUM_BY_A.get(groups.get("A", ""), "general")
    source_refs = source_ref_strings(obj)
    table_ids = [str(value) for value in (obj.get("source_table_ids") or []) if value]
    source_item_id = str(obj.get("source_item_id") or "").strip()
    table_section = ", ".join([source_item_id, *table_ids]).strip(", ")
    definition_tail = f" {meaning}" if meaning else ""

    value_group_mapping = {
        key: value
        for key, value in {
            "A": groups.get("A"),
            "B": groups.get("B"),
            "C": groups.get("C"),
            "D": groups.get("D"),
            "E": groups.get("E"),
            "F": groups.get("F"),
        }.items()
        if value not in [None, ""]
    }

    relations = []
    if class_id in relation_class_ids:
        relations.append(
            {
                "relation": "instance_of",
                "target": f"KB-L3-IC-{class_id}-{re.sub(r'[^A-Za-z0-9]+', '-', class_name).strip('-').upper()}",
            }
        )

    return {
        "id": entry_id_for_obis(obis, name),
        "type": "cosem_object_instance",
        "layer": "cosem_object_instance",
        "name": name,
        "aliases": [f"OBIS {obis}", *([meaning] if meaning else [])],
        "keywords": [obis, name, *([meaning] if meaning else []), *table_ids],
        "domain_tags": ["cosem_object", medium, "abnt_bulk_import"],
        "definition": (
            f"ABNT Appendix 9 row-level COSEM object `{name}` with OBIS pattern `{obis}` "
            f"and interface class {class_id} ({class_name}).{definition_tail}"
        ),
        "relations": relations,
        "obis_pattern": obis,
        "likely_interface_class_id": int(class_id) if class_id.isdigit() else class_id,
        "likely_interface_class_name": class_name,
        "medium": medium,
        "value_group_mapping": value_group_mapping,
        "source_refs": [
            {
                "source": "ABNT Appendix 9 extracted COSEM object model",
                "section": table_section or ", ".join(source_refs),
            }
        ],
        "applicable_notes": [
            "Bulk-generated from the current ABNT smoke COSEM object model to provide exact OBIS lookup coverage.",
            "Review against Blue Book semantics before treating this row as manually curated.",
        ],
        "bulk_import": {
            "source": "out/abnt_current_kb_smoke/cosem_object_model.json",
            "source_item_id": source_item_id,
            "source_refs": source_refs,
            "source_table_ids": table_ids,
        },
    }


def note_text(entry: dict[str, Any]) -> str:
    frontmatter = {
        "id": entry["id"],
        "kb_id": "obsidian_energy_metering",
        "type": entry["type"],
        "layer": entry["layer"],
        "name": entry["name"],
        "aliases": entry["aliases"],
        "keywords": entry["keywords"],
        "domain_tags": entry["domain_tags"],
        "relations": entry["relations"],
    }
    metadata = {key: value for key, value in entry.items() if key not in frontmatter and key not in {"definition"}}
    lines = [
        "---",
        yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "",
        f"# {entry['name']}",
        "",
        "## Definition",
        "",
        entry["definition"],
        "",
        "## Structured Data",
        "",
        "```json metadata",
        json.dumps(metadata, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Notes",
        "",
    ]
    return "\n".join(lines)


def generate_notes(model_path: Path, kb_path: Path, vault_path: Path) -> list[Path]:
    model = load_json(model_path)
    kb = load_json(kb_path)
    existing = existing_obis_patterns(kb)
    class_names_by_id = class_names(kb)
    relation_class_ids = set(class_entries(kb))
    written: list[Path] = []
    used_paths: set[Path] = set()

    for obj in model.get("objects", []):
        obis = str(obj.get("obis") or "").strip()
        class_id = str(obj.get("class_id") or "").strip()
        if not obis or obis in existing or not class_id:
            continue
        entry = build_entry(obj, class_names_by_id, relation_class_ids)
        folder = vault_path / "04_object_instances" / class_folder(class_id, entry["likely_interface_class_name"])
        filename = f"{slugify(entry['name'])} {slugify(obis, limit=48)}.md"
        out_path = folder / filename
        suffix = 2
        while out_path in used_paths or out_path.exists():
            out_path = folder / f"{slugify(entry['name'])} {slugify(obis, limit=40)} {suffix}.md"
            suffix += 1
        used_paths.add(out_path)
        folder.mkdir(parents=True, exist_ok=True)
        out_path.write_text(note_text(entry), encoding="utf-8")
        written.append(out_path)

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk-generate ABNT row-level OBIS Obsidian notes from object-model smoke output.")
    parser.add_argument("--model", type=Path, default=ROOT / "out" / "abnt_current_kb_smoke" / "cosem_object_model.json")
    parser.add_argument("--kb", type=Path, default=ROOT / "knowledge_bases" / "compiled_from_obsidian.json")
    parser.add_argument("--vault", type=Path, default=ROOT / "obsidian-vault")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    written = generate_notes(args.model, args.kb, args.vault)
    print(json.dumps({"written": len(written), "paths": [str(path) for path in written]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
