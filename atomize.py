from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


MAJOR_HEADINGS = {
    "scope",
    "normative references",
    "terms and definitions",
    "architecture",
    "communication profile",
    "communication profiles",
    "security",
    "bibliography",
    "figures",
    "tables",
}

DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("communication_profile", ("communication profile", "plc", "prime", "wi-sun", "lorawan", "rf", "network", "media of communication")),
    ("security_policy", ("security", "authenticated", "authentication", "encrypted", "encryption", "hls", "password", "key agreement", "digital signature", "aes-gcm", "ecdsa", "ecdh")),
    ("association", ("association", "sap", "logical device", "client", "server application")),
    ("obis_code", ("obis", "logical name", "code obis")),
    ("cosem_object", ("cosem", "interface class", "class_id", "attribute", "method")),
    ("event", ("event", "events", "event log", "group/subgroup")),
    ("alarm", ("alarm", "alarms")),
    ("error", ("error", "errors")),
    ("register", ("register", "energy register", "demand register")),
    ("billing_profile", ("billing", "periods of billing", "billing profile")),
    ("load_profile", ("load profile", "load curve")),
    ("firmware_update", ("firmware", "update of firmware")),
    ("meter_function", ("smart electricity meter", "meter", "measurement", "measuring")),
    ("power_quality", ("power quality", "qee", "quality of energy", "voltage", "current")),
    ("data_model", ("data model", "objects", "abstract object", "object related")),
]


@dataclass(frozen=True)
class KnowledgeEntry:
    kb_id: str
    entry_id: str
    entry_type: str
    layer: str
    name: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    domain_tags: tuple[str, ...]
    definition: str
    relations: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeBase:
    kb_id: str
    name: str
    version: str
    entries: tuple[KnowledgeEntry, ...]


@dataclass
class SectionState:
    levels: dict[int, str] = field(default_factory=dict)

    def update(self, level: int, title: str) -> list[str]:
        self.levels[level] = title
        for old_level in list(self.levels):
            if old_level > level:
                del self.levels[old_level]
        return self.path()

    def path(self) -> list[str]:
        return [self.levels[level] for level in sorted(self.levels)]


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\u00a0", " ")
    value = value.replace("\uf020", " ")
    value = value.replace("\uf03d", "=")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def iter_body_items(document: DocxDocument) -> Iterable[Paragraph | Table]:
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def is_noise(text: str) -> bool:
    low = text.lower()
    if not text:
        return True
    if "abnt 2022" in low or "all rights reserved" in low:
        return True
    if low in {"abnt", "abnt nbr", "abnt nbr 16968:2022"}:
        return True
    if re.fullmatch(r"\d+\s+pages?", low):
        return True
    if re.fullmatch(r"[ivxlcdm]+", low):
        return True
    if re.fullmatch(r"\d+", text):
        return True
    return False


def detect_heading(text: str, style_name: str) -> tuple[int, str] | None:
    if not text or is_noise(text):
        return None

    style_low = style_name.lower()
    match = re.search(r"heading\s+(\d+)", style_low)
    if match:
        return min(int(match.group(1)), 6), text

    normalized = text.strip().lower().rstrip(":")
    if normalized in MAJOR_HEADINGS:
        return 1, text

    numbered = re.match(r"^(\d+(?:\.\d+)*)(?:\s+|\.\s+)(.{3,})$", text)
    if numbered:
        number, title = numbered.groups()
        title = title.strip()
        if not looks_like_toc_entry(title) and not looks_like_caption(text):
            return min(number.count(".") + 1, 6), f"{number} {title}"

    if style_low == "list paragraph" and len(text) <= 80 and not text.endswith(".") and not looks_like_caption(text):
        if re.search(r"[A-Za-z]", text):
            return 2, text

    return None


def looks_like_toc_entry(text: str) -> bool:
    if re.search(r"\s+\d{1,3}$", text):
        return True
    if text.lower().endswith("page"):
        return True
    return False


def looks_like_caption(text: str) -> bool:
    return bool(re.match(r"^(table|figure)\s+\d+\b", text.strip(), flags=re.I))


def infer_table_title(last_caption: str | None, table_index: int) -> str:
    if last_caption:
        return last_caption
    return f"Table {table_index}"


def unique_headers(raw_headers: list[str], width: int) -> list[str]:
    headers: list[str] = []
    counts: Counter[str] = Counter()
    for index in range(width):
        base = clean_text(raw_headers[index]) if index < len(raw_headers) else ""
        if not base:
            base = f"column_{index + 1}"
        counts[base] += 1
        headers.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return headers


def table_matrix(table: Table) -> list[list[str]]:
    matrix: list[list[str]] = []
    for row in table.rows:
        matrix.append([clean_text(cell.text) for cell in row.cells])
    return matrix


def tag_domains(*texts: str) -> list[str]:
    haystack = " ".join(t for t in texts if t).lower()
    tags: list[str] = []
    for tag, keywords in DOMAIN_RULES:
        if any(keyword in haystack for keyword in keywords):
            tags.append(tag)
    return tags


def load_knowledge_bases(paths: list[Path]) -> list[KnowledgeBase]:
    knowledge_bases: list[KnowledgeBase] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        kb_id = str(payload.get("kb_id") or resolved.stem)
        entries: list[KnowledgeEntry] = []
        for raw in payload.get("entries", []):
            name = clean_text(raw.get("name"))
            known_keys = {
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
            metadata = {key: value for key, value in raw.items() if key not in known_keys}
            keywords = tuple(
                sorted(
                    {
                        normalize_match_term(term)
                        for term in [name, *raw.get("aliases", []), *raw.get("keywords", [])]
                        if len(normalize_match_term(term)) > 1
                    },
                    key=len,
                    reverse=True,
                )
            )
            entries.append(
                KnowledgeEntry(
                    kb_id=kb_id,
                    entry_id=str(raw.get("id") or name),
                    entry_type=str(raw.get("type") or "term"),
                    layer=str(raw.get("layer") or payload.get("layer") or "term"),
                    name=name,
                    aliases=tuple(clean_text(v) for v in raw.get("aliases", [])),
                    keywords=keywords,
                    domain_tags=tuple(str(v) for v in raw.get("domain_tags", [])),
                    definition=clean_text(raw.get("definition")),
                    relations=tuple(raw.get("relations", [])),
                    metadata=metadata,
                )
            )
        knowledge_bases.append(
            KnowledgeBase(
                kb_id=kb_id,
                name=clean_text(payload.get("name")) or kb_id,
                version=str(payload.get("version") or ""),
                entries=tuple(entries),
            )
        )
    return knowledge_bases


def normalize_match_term(value: str | None) -> str:
    value = clean_text(value).lower()
    if not value:
        return ""
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def match_knowledge(knowledge_bases: list[KnowledgeBase], *texts: str) -> list[dict[str, Any]]:
    if not knowledge_bases:
        return []

    haystack = normalize_match_term(" ".join(t for t in texts if t))
    if not haystack:
        return []

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kb in knowledge_bases:
        for entry in kb.entries:
            matched_terms = [term for term in entry.keywords if term and contains_term(haystack, term)]
            if not matched_terms:
                continue
            key = (entry.kb_id, entry.entry_id)
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "kb_id": entry.kb_id,
                    "entry_id": entry.entry_id,
                    "type": entry.entry_type,
                    "layer": entry.layer,
                    "name": entry.name,
                    "matched_terms": matched_terms[:8],
                    "domain_tags": list(entry.domain_tags),
                    "definition": entry.definition,
                    "relations": list(entry.relations),
                    "metadata": entry.metadata,
                }
            )
    matches.sort(key=lambda row: (row["type"], row["name"]))
    return matches


def contains_term(haystack: str, term: str) -> bool:
    if len(term) <= 3 and term.isalpha():
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack))
    return term in haystack


def kb_domain_tags(matches: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for match in matches:
        for tag in match.get("domain_tags", []):
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return tags


def is_requirement_like(text: str) -> bool:
    low = text.lower()
    signals = (
        "shall",
        "must",
        "should",
        "required",
        "requirement",
        "not used, must",
        "is required",
        "are required",
        "only",
        "mandatory",
    )
    return any(signal in low for signal in signals)


def extract_docx(
    input_path: Path,
    knowledge_bases: list[KnowledgeBase] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    knowledge_bases = knowledge_bases or []
    document = Document(input_path)
    sections = SectionState()
    blocks: list[dict[str, Any]] = []
    table_items: list[dict[str, Any]] = []
    last_caption: str | None = None
    table_count = 0
    order = 0

    for item in iter_body_items(document):
        if isinstance(item, Paragraph):
            text = clean_text(item.text)
            if not text:
                continue

            style_name = item.style.name if item.style is not None else ""
            heading = detect_heading(text, style_name)
            block_type = "paragraph"
            if heading:
                level, title = heading
                section_path = sections.update(level, title)
                block_type = "heading"
            else:
                section_path = sections.path()

            order += 1
            block_id = f"BLK-{order:06d}"
            kb_matches = match_knowledge(knowledge_bases, text, " > ".join(section_path))
            domain_tags = merge_tags(tag_domains(text, " > ".join(section_path)), kb_domain_tags(kb_matches))
            block = {
                "block_id": block_id,
                "order": order,
                "type": block_type,
                "style": style_name,
                "text": text,
                "section_path": section_path,
                "domain_tags": domain_tags,
                "kb_matches": kb_matches,
                "requirement_like": is_requirement_like(text),
                "noise": is_noise(text),
            }
            if heading:
                block["heading_level"] = heading[0]
            blocks.append(block)

            if looks_like_caption(text):
                last_caption = text
            elif block_type != "heading" and not is_noise(text):
                # Keep captions available across short spacer paragraphs, but avoid
                # accidentally attaching a distant caption to a later table.
                if last_caption and len(text) > 120:
                    last_caption = None

        elif isinstance(item, Table):
            matrix = table_matrix(item)
            if not matrix:
                continue
            table_count += 1
            table_id = f"TBL-{table_count:06d}"
            table_title = infer_table_title(last_caption, table_count)
            section_path = sections.path()
            width = max((len(row) for row in matrix), default=0)
            height = len(matrix)
            headers = unique_headers(matrix[0] if matrix else [], width)

            order += 1
            block_id = f"BLK-{order:06d}"
            table_text = render_table_text(headers, matrix[1:])
            kb_matches = match_knowledge(knowledge_bases, table_title, table_text, " > ".join(section_path))
            domain_tags = merge_tags(tag_domains(table_title, table_text, " > ".join(section_path)), kb_domain_tags(kb_matches))
            blocks.append(
                {
                    "block_id": block_id,
                    "order": order,
                    "type": "table",
                    "table_id": table_id,
                    "table_title": table_title,
                    "section_path": section_path,
                    "rows": height,
                    "columns": width,
                    "headers": headers,
                    "text": table_text[:5000],
                    "domain_tags": domain_tags,
                    "kb_matches": kb_matches,
                    "requirement_like": is_requirement_like(table_text),
                    "noise": False,
                }
            )

            for row_index, row in enumerate(matrix[1:], start=2):
                if not any(row):
                    continue
                fields = {
                    headers[col_index]: row[col_index] if col_index < len(row) else ""
                    for col_index in range(width)
                }
                compact_fields = {k: v for k, v in fields.items() if v}
                item_text = " | ".join(compact_fields.values())
                item_matches = match_knowledge(knowledge_bases, table_title, item_text, " > ".join(section_path))
                item_tags = merge_tags(tag_domains(table_title, item_text, " > ".join(section_path)), kb_domain_tags(item_matches))
                table_items.append(
                    {
                        "item_id": f"{table_id}-R{row_index:06d}",
                        "type": "table_row",
                        "table_id": table_id,
                        "table_block_id": block_id,
                        "table_title": table_title,
                        "section_path": section_path,
                        "row_index": row_index,
                        "fields": compact_fields,
                        "domain_tags": item_tags,
                        "kb_matches": item_matches,
                        "requirement_like": is_requirement_like(item_text),
                        "noise": False,
                    }
                )
            last_caption = None

    return blocks, table_items


def merge_tags(*tag_lists: Iterable[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag_list in tag_lists:
        for tag in tag_list:
            if tag and tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return tags


def mark_doc_regions(blocks: list[dict[str, Any]], table_items: list[dict[str, Any]]) -> None:
    """Mark blocks as body/front matter so model tasks ignore cover and TOC pages."""
    scope_indexes: list[int] = []
    preface_index: int | None = None
    introduction_index: int | None = None

    for index, block in enumerate(blocks):
        text = normalize_title(block.get("text", ""))
        if block.get("type") == "heading" and text == "scope":
            scope_indexes.append(index)
        if block.get("type") == "heading" and text == "preface" and preface_index is None:
            preface_index = index
        if block.get("type") == "heading" and text == "introduction" and introduction_index is None:
            introduction_index = index

    # Standards often include "The Scope in English..." in the preface before the
    # real normative body. If multiple Scope headings exist, the last one is the
    # safer body start.
    body_start = scope_indexes[-1] if scope_indexes else 0

    for index, block in enumerate(blocks):
        if index >= body_start:
            region = "body"
        elif preface_index is not None and index >= preface_index:
            region = "preface"
        elif introduction_index is not None and index >= introduction_index:
            region = "introduction"
        elif block.get("section_path") and any(normalize_title(p) in {"tables", "figures"} for p in block["section_path"]):
            region = "table_of_contents"
        else:
            region = "front_matter"
        block["doc_region"] = region

    block_region_by_id = {block["block_id"]: block.get("doc_region", "body") for block in blocks}
    for item in table_items:
        item["doc_region"] = block_region_by_id.get(item.get("table_block_id"), "body")


def normalize_title(text: str) -> str:
    text = clean_text(text).lower().rstrip(":")
    text = re.sub(r"\s+", " ", text)
    return text


def render_table_text(headers: list[str], rows: list[list[str]], max_rows: int = 20) -> str:
    lines = [" | ".join(headers)]
    for row in rows[:max_rows]:
        padded = row + [""] * max(0, len(headers) - len(row))
        lines.append(" | ".join(padded[: len(headers)]))
    if len(rows) > max_rows:
        lines.append(f"... {len(rows) - max_rows} more rows")
    return "\n".join(lines)


def build_chunks(
    blocks: list[dict[str, Any]],
    target_chars: int = 3500,
    include_regions: set[str] | None = None,
    keep_noise: bool = False,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    current_section: tuple[str, ...] = tuple()

    def flush() -> None:
        nonlocal current, current_chars, current_section
        if not current:
            return
        chunk_index = len(chunks) + 1
        text_parts: list[str] = []
        source_ids: list[str] = []
        domain_counter: Counter[str] = Counter()
        kb_matches_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        req_like = False
        for block in current:
            source_ids.append(block["block_id"])
            domain_counter.update(block.get("domain_tags", []))
            for match in block.get("kb_matches", []):
                key = (match.get("kb_id", ""), match.get("entry_id", ""))
                if key not in kb_matches_by_key:
                    kb_matches_by_key[key] = match
            req_like = req_like or bool(block.get("requirement_like"))
            if block["type"] == "heading":
                text_parts.append(f"# {block['text']}")
            elif block["type"] == "table":
                text_parts.append(f"[{block.get('table_id')}] {block.get('table_title')}\n{block.get('text', '')}")
            else:
                text_parts.append(block["text"])
        chunks.append(
            {
                "chunk_id": f"CH-{chunk_index:06d}",
                "order": chunk_index,
                "section_path": list(current_section),
                "source_block_ids": source_ids,
                "text": "\n\n".join(text_parts),
                "domain_tags": [tag for tag, _ in domain_counter.most_common()],
                "kb_matches": list(kb_matches_by_key.values())[:40],
                "requirement_like": req_like,
            }
        )
        current = []
        current_chars = 0
        current_section = tuple()

    for block in blocks:
        if include_regions is not None and block.get("doc_region") not in include_regions:
            continue
        if not keep_noise and block.get("noise"):
            continue

        block_section = tuple(block.get("section_path") or [])
        block_text = block.get("text") or ""
        block_size = len(block_text)

        if block["type"] == "heading":
            if current and current_chars >= target_chars * 0.35:
                flush()

        if block["type"] == "table" and current:
            flush()

        if current and block_section != current_section and current_chars >= target_chars * 0.5:
            flush()

        if current and current_chars + block_size > target_chars:
            flush()

        if not current:
            current_section = block_section
        current.append(block)
        current_chars += block_size

        if block["type"] == "table":
            flush()

    flush()
    return chunks


def build_llm_tasks(chunks: list[dict[str, Any]], table_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    for chunk in chunks:
        if not chunk.get("requirement_like") and not chunk.get("domain_tags"):
            continue
        task_id = f"TASK-{len(tasks) + 1:06d}"
        tasks.append(
            {
                "task_id": task_id,
                "task_type": "extract_atomic_requirements",
                "source_type": "chunk",
                "source_id": chunk["chunk_id"],
                "source_refs": chunk["source_block_ids"],
                "section_path": chunk.get("section_path", []),
                "domain_tags": chunk.get("domain_tags", []),
                "kb_matches": chunk.get("kb_matches", []),
                "instruction": atomic_requirement_instruction(),
                "input": chunk["text"],
                "expected_output_schema": atomic_requirement_schema(),
            }
        )

    for item in table_items:
        if not item.get("domain_tags") and not item.get("requirement_like"):
            continue
        task_id = f"TASK-{len(tasks) + 1:06d}"
        tasks.append(
            {
                "task_id": task_id,
                "task_type": "classify_table_atom",
                "source_type": "table_row",
                "source_id": item["item_id"],
                "source_refs": [item["table_block_id"]],
                "section_path": item.get("section_path", []),
                "domain_tags": item.get("domain_tags", []),
                "kb_matches": item.get("kb_matches", []),
                "instruction": table_atom_instruction(),
                "input": {
                    "table_title": item["table_title"],
                    "row_index": item["row_index"],
                    "fields": item["fields"],
                },
                "expected_output_schema": atomic_requirement_schema(),
            }
        )

    return tasks


def atomic_requirement_instruction() -> str:
    return (
        "Extract atomic requirements from this source. Keep each requirement independently testable. "
        "Preserve technical terms such as DLMS/COSEM, OBIS, SAP, HLS, firmware, register, event, alarm, "
        "and measurement units. If the source is contextual rather than normative, mark ambiguity=true "
        "or return an empty requirements list."
    )


def table_atom_instruction() -> str:
    return (
        "Convert this table row into one atomic technical item or requirement. Preserve all codes, group "
        "numbers, event numbers, object names, units, and descriptions exactly enough for traceability. "
        "Classify the domain and suggest a verification method."
    )


def atomic_requirement_schema() -> dict[str, Any]:
    return {
        "requirements": [
            {
                "req_id": "string",
                "source_id": "string",
                "source_refs": ["string"],
                "domain": "string",
                "object": "string",
                "requirement_type": "string",
                "requirement": "string",
                "condition": "string|null",
                "parameters": {},
                "verification_method": "inspection|test|configuration_check|document_review|analysis",
                "ambiguity": "boolean",
                "review_questions": ["string"],
                "confidence": "number",
            }
        ]
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary(
    path: Path,
    manifest: dict[str, Any],
    domain_counts: Counter[str],
    kb_counts: Counter[str],
) -> None:
    lines = [
        "# Requirement Atomizer Summary",
        "",
        f"- Input: `{manifest['input']}`",
        f"- Generated at: `{manifest['generated_at']}`",
        f"- Blocks: `{manifest['counts']['blocks']}`",
        f"- Chunks: `{manifest['counts']['chunks']}`",
        f"- Table items: `{manifest['counts']['table_items']}`",
        f"- LLM tasks: `{manifest['counts']['llm_tasks']}`",
        "",
        "## Top Domain Tags",
        "",
    ]
    for tag, count in domain_counts.most_common(20):
        lines.append(f"- `{tag}`: {count}")
    if kb_counts:
        lines.extend(["", "## Top Knowledge Base Matches", ""])
        for name, count in kb_counts.most_common(30):
            lines.append(f"- `{name}`: {count}")
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "Send `llm_tasks.jsonl` to your model worker. Store model results as `atomic_requirements.jsonl` and keep `source_id` plus `source_refs` for traceability.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atomize a technical DOCX standard for LLM requirement analysis.")
    parser.add_argument("input", type=Path, help="Input .docx file")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    parser.add_argument("--chunk-chars", type=int, default=3500, help="Target character size per retrieval chunk")
    parser.add_argument(
        "--kb",
        type=Path,
        action="append",
        default=[],
        help="External knowledge base JSON file. Can be provided multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    out_dir = args.out.expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"Input file does not exist: {input_path}")
    if input_path.suffix.lower() != ".docx":
        raise SystemExit("Only .docx input is supported in this first version.")

    out_dir.mkdir(parents=True, exist_ok=True)

    knowledge_bases = load_knowledge_bases(args.kb)

    blocks, table_items = extract_docx(input_path, knowledge_bases=knowledge_bases)
    mark_doc_regions(blocks, table_items)
    chunks = build_chunks(blocks, target_chars=args.chunk_chars, include_regions={"body"})
    body_table_items = [item for item in table_items if item.get("doc_region") == "body"]
    llm_tasks = build_llm_tasks(chunks, body_table_items)

    block_count = write_jsonl(out_dir / "blocks.jsonl", blocks)
    chunk_count = write_jsonl(out_dir / "chunks.jsonl", chunks)
    table_count = write_jsonl(out_dir / "table_items.jsonl", table_items)
    task_count = write_jsonl(out_dir / "llm_tasks.jsonl", llm_tasks)

    domain_counts: Counter[str] = Counter()
    kb_counts: Counter[str] = Counter()
    for row in blocks:
        domain_counts.update(row.get("domain_tags", []))
        kb_counts.update(match.get("name", match.get("entry_id", "")) for match in row.get("kb_matches", []))
    for row in table_items:
        domain_counts.update(row.get("domain_tags", []))
        kb_counts.update(match.get("name", match.get("entry_id", "")) for match in row.get("kb_matches", []))

    manifest = {
        "tool": "requirement-atomizer",
        "version": "0.1.0",
        "input": str(input_path),
        "output_dir": str(out_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_bases": [
            {
                "kb_id": kb.kb_id,
                "name": kb.name,
                "version": kb.version,
                "entries": len(kb.entries),
            }
            for kb in knowledge_bases
        ],
        "counts": {
            "blocks": block_count,
            "chunks": chunk_count,
            "table_items": table_count,
            "body_table_items": len(body_table_items),
            "llm_tasks": task_count,
        },
        "files": {
            "blocks": "blocks.jsonl",
            "chunks": "chunks.jsonl",
            "table_items": "table_items.jsonl",
            "llm_tasks": "llm_tasks.jsonl",
            "summary": "summary.md",
        },
    }
    write_json(out_dir / "manifest.json", manifest)
    write_summary(out_dir / "summary.md", manifest, domain_counts, kb_counts)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
