from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml


COMMON_KEYS = {
    "id",
    "type",
    "layer",
    "name",
    "aliases",
    "keywords",
    "domain_tags",
    "definition",
    "relations",
}


FOLDER_BY_LAYER = {
    "term": "01_terms",
    "protocol_architecture": "02_protocol_layer",
    "access_model": "02_protocol_layer",
    "object_model": "02_protocol_layer",
    "application_layer": "02_protocol_layer",
    "security_model": "02_protocol_layer",
    "communication_model": "02_protocol_layer",
    "measurement_model": "02_protocol_layer",
    "event_alarm_model": "02_protocol_layer",
    "cosem_class": "03_cosem_classes",
    "cosem_object_instance": "04_object_instances",
}


def slugify(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120] or "untitled"


def folder_for_entry(kb: dict[str, Any], entry: dict[str, Any]) -> Path:
    layer = entry.get("layer") or kb.get("layer") or "term"
    folder = Path(FOLDER_BY_LAYER.get(layer, "99_other"))
    if layer == "cosem_class" and entry.get("class_id") is not None:
        family = f"{int(entry['class_id']):03d}-{slugify(entry.get('name') or entry.get('id') or 'untitled')}"
        return folder / family
    return folder


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    front = text[4:end]
    body = text[end + 4 :].lstrip("\r\n")
    return yaml.safe_load(front) or {}, body


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def yaml_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    return value


def entry_to_markdown(kb: dict[str, Any], entry: dict[str, Any]) -> str:
    layer = entry.get("layer") or kb.get("layer") or "term"
    metadata = {key: value for key, value in entry.items() if key not in COMMON_KEYS}
    frontmatter = {
        "id": entry.get("id"),
        "kb_id": kb.get("kb_id"),
        "kb_name": kb.get("name"),
        "kb_version": kb.get("version"),
        "type": entry.get("type", "term"),
        "layer": layer,
        "name": entry.get("name"),
        "aliases": entry.get("aliases", []),
        "keywords": entry.get("keywords", []),
        "domain_tags": entry.get("domain_tags", []),
        "relations": entry.get("relations", []),
    }
    frontmatter = {key: yaml_safe(value) for key, value in frontmatter.items() if value not in [None, "", []]}

    lines = [
        "---",
        yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "",
        f"# {entry.get('name') or entry.get('id')}",
        "",
        "## Definition",
        "",
        entry.get("definition") or "",
        "",
    ]

    aliases = entry.get("aliases") or []
    if aliases:
        lines.extend(["## Aliases", "", *[f"- {alias}" for alias in aliases], ""])

    tags = entry.get("domain_tags") or []
    if tags:
        lines.extend(["## Domain Tags", "", *[f"- `{tag}`" for tag in tags], ""])

    relations = entry.get("relations") or []
    if relations:
        lines.extend(["## Relations", "", *[f"- `{r.get('relation')}` -> `{r.get('target')}`" for r in relations], ""])

    if metadata:
        lines.extend(
            [
                "## Structured Data",
                "",
                "```json metadata",
                json.dumps(metadata, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )

    lines.extend(["## Notes", "", ""])
    return "\n".join(lines)


def markdown_to_entry(path: Path) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    metadata = extract_json_block(body, "metadata")
    entry = {
        "id": frontmatter.get("id") or path.stem,
        "type": frontmatter.get("type") or "term",
        "layer": frontmatter.get("layer") or "term",
        "name": frontmatter.get("name") or path.stem,
        "aliases": frontmatter.get("aliases") or [],
        "keywords": frontmatter.get("keywords") or [],
        "domain_tags": frontmatter.get("domain_tags") or [],
        "definition": extract_definition(body),
        "relations": frontmatter.get("relations") or [],
    }
    entry.update(metadata)
    kb_id = frontmatter.get("kb_id") or "obsidian_kb"
    return kb_id, entry


def extract_definition(body: str) -> str:
    match = re.search(r"## Definition\s+(.+?)(?:\n## |\Z)", body, flags=re.S)
    if not match:
        return ""
    definition = match.group(1)
    definition = re.sub(r"```.*?```", "", definition, flags=re.S)
    return definition.strip()


def extract_json_block(body: str, label: str) -> dict[str, Any]:
    pattern = rf"```json\s+{re.escape(label)}\s*(.*?)```"
    match = re.search(pattern, body, flags=re.S)
    if not match:
        return {}
    raw = match.group(1).strip()
    if not raw:
        return {}
    return json.loads(raw)


def export_json_to_vault(kb_paths: Iterable[Path], vault_path: Path) -> list[Path]:
    written: list[Path] = []
    vault_path.mkdir(parents=True, exist_ok=True)
    for kb_path in kb_paths:
        kb = read_json(kb_path)
        for entry in kb.get("entries", []):
            folder = folder_for_entry(kb, entry)
            title = slugify(entry.get("name") or entry.get("id") or "untitled")
            out_path = vault_path / folder / f"{title}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(entry_to_markdown(kb, entry), encoding="utf-8")
            written.append(out_path)

    index = vault_path / "README.md"
    index.write_text(
        "# Energy Metering Knowledge Vault\n\n"
        "This Obsidian vault is the source-editing layer for the requirement atomizer knowledge base.\n\n"
        "Edit notes here, then compile the vault back to JSON with `python -m requirement_kb.obsidian compile`.\n",
        encoding="utf-8",
    )
    written.append(index)
    return written


def compile_vault_to_json(vault_path: Path, out_path: Path, kb_id: str = "obsidian_energy_metering") -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(vault_path.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        note_kb_id, entry = markdown_to_entry(path)
        if kb_id == "auto":
            entry["_source_kb_id"] = note_kb_id
        entries.append(entry)

    payload = {
        "kb_id": kb_id if kb_id != "auto" else "obsidian_compiled_kb",
        "name": "Compiled Obsidian Energy Metering Knowledge Base",
        "version": "0.1.0",
        "description": "Compiled from Obsidian Markdown notes.",
        "entries": entries,
    }
    write_json(out_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export/import Obsidian vaults for knowledge bases.")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="Export JSON KB files to Obsidian Markdown")
    export.add_argument("--kb", type=Path, action="append", required=True)
    export.add_argument("--vault", type=Path, required=True)

    compile_cmd = sub.add_parser("compile", help="Compile Obsidian Markdown vault to JSON KB")
    compile_cmd.add_argument("--vault", type=Path, required=True)
    compile_cmd.add_argument("--out", type=Path, required=True)
    compile_cmd.add_argument("--kb-id", default="obsidian_energy_metering")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "export":
        written = export_json_to_vault(args.kb, args.vault)
        print(json.dumps({"vault": str(args.vault.resolve()), "notes": len(written)}, ensure_ascii=False, indent=2))
    elif args.command == "compile":
        payload = compile_vault_to_json(args.vault, args.out, kb_id=args.kb_id)
        print(json.dumps({"output": str(args.out.resolve()), "entries": len(payload["entries"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
