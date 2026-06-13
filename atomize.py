from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import Counter, defaultdict
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

from atomic_requirement_schema import validate_atomic_requirements
from domain_pack import load_domain_pack
from kb_matching import TEXT_REPLACEMENTS, compile_term_pattern, find_matched_terms, normalize_match_term
from output_writer import build_quality_report, write_json, write_jsonl, write_summary
from table_pattern_engine import load_table_patterns, match_table_pattern
from version import __version__


LOGGER = logging.getLogger("requirement_atomizer")
SUPPORTED_INPUT_FORMATS = (".docx", ".xlsx", ".pdf")


DEFAULT_MAJOR_HEADINGS = (
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
)

DEFAULT_NOISE_PATTERNS = (
    r"abnt 2022",
    r"all rights reserved",
)
DEFAULT_NOISE_EXACT = (
    "abnt",
    "abnt nbr",
    "abnt nbr 16968:2022",
)
DEFAULT_CAPTION_PATTERN = r"^(table|figure)\s+\d+\b"
DEFAULT_BODY_START_HEADING = "scope"

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
DOMAIN_RULE_PATTERNS = [(tag, compile_term_pattern(keywords)) for tag, keywords in DOMAIN_RULES]

OBJECT_NAME_STOPWORDS = {
    "A",
    "An",
    "For",
    "If",
    "In",
    "It",
    "Numbers",
    "O",
    "Only",
    "Table",
    "The",
    "This",
    "To",
    "You",
}

DEFAULT_ACCESS_RIGHT_CLIENTS = {
    "RC": "remote management and measurement client",
    "PC": "read client",
    "SC": "service/local or specialized client depending on table context",
    "LC": "local management and measurement client",
}


class AtomizerInputError(ValueError):
    pass


class AtomizerPipelineError(RuntimeError):
    pass


def normalize_profile_value(text: str) -> str:
    return re.sub(r"\s+", " ", clean_text(text).lower().rstrip(":")).strip()


@dataclass(frozen=True)
class DocumentProfile:
    noise_patterns: tuple[str, ...] = DEFAULT_NOISE_PATTERNS
    noise_exact: tuple[str, ...] = DEFAULT_NOISE_EXACT
    major_headings: tuple[str, ...] = DEFAULT_MAJOR_HEADINGS
    caption_pattern: str = DEFAULT_CAPTION_PATTERN
    body_start_heading: str = DEFAULT_BODY_START_HEADING

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "DocumentProfile":
        if not payload:
            return cls()
        defaults = cls()
        return cls(
            noise_patterns=tuple(str(value) for value in payload.get("noise_patterns", defaults.noise_patterns)),
            noise_exact=tuple(normalize_profile_value(str(value)) for value in payload.get("noise_exact", defaults.noise_exact)),
            major_headings=tuple(normalize_profile_value(str(value)) for value in payload.get("major_headings", defaults.major_headings)),
            caption_pattern=str(payload.get("caption_pattern", defaults.caption_pattern)),
            body_start_heading=normalize_profile_value(str(payload.get("body_start_heading", defaults.body_start_heading))),
        )


DEFAULT_DOCUMENT_PROFILE = DocumentProfile()


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
    match_pattern: re.Pattern[str] | None = field(default=None, compare=False, repr=False)


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
    for source, replacement in TEXT_REPLACEMENTS.items():
        value = value.replace(source, replacement)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def iter_body_items(document: DocxDocument) -> Iterable[Paragraph | Table]:
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def is_noise(text: str, *, document_profile: DocumentProfile | None = None) -> bool:
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    low = text.lower()
    if not text:
        return True
    if any(re.search(pattern, low, flags=re.I) for pattern in profile.noise_patterns):
        return True
    if normalize_profile_value(low) in set(profile.noise_exact):
        return True
    if re.fullmatch(r"\d+\s+pages?", low):
        return True
    if re.fullmatch(r"[ivxlcdm]+", low):
        return True
    if re.fullmatch(r"\d+", text):
        return True
    return False


def has_numbering(paragraph: Paragraph) -> bool:
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.numPr is not None


def detect_heading(
    text: str,
    style_name: str,
    is_list_item: bool = False,
    *,
    document_profile: DocumentProfile | None = None,
) -> tuple[int, str] | None:
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    if not text or is_noise(text, document_profile=profile):
        return None

    style_low = style_name.lower()
    match = re.search(r"heading\s+(\d+)", style_low)
    if match:
        return min(int(match.group(1)), 6), text

    normalized = text.strip().lower().rstrip(":")
    if normalized in set(profile.major_headings):
        return 1, text

    numbered = re.match(r"^(\d+(?:\.\d+)*)(?:\s+|\.\s+)(.{3,})$", text)
    if numbered:
        number, title = numbered.groups()
        title = title.strip()
        if not looks_like_toc_entry(title) and not looks_like_caption(text, document_profile=profile):
            return min(number.count(".") + 1, 6), f"{number} {title}"

    if (
        style_low == "list paragraph"
        and not is_list_item
        and len(text) <= 80
        and not text.endswith(".")
        and not looks_like_caption(text, document_profile=profile)
    ):
        if re.search(r"[A-Za-z]", text):
            return 2, text

    return None


def looks_like_toc_entry(text: str) -> bool:
    if re.search(r"\s+\d{1,3}$", text):
        return True
    if text.lower().endswith("page"):
        return True
    return False


def looks_like_caption(text: str, *, document_profile: DocumentProfile | None = None) -> bool:
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    return bool(re.match(profile.caption_pattern, text.strip(), flags=re.I))


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


def build_table_artifacts(
    matrix: list[list[str]],
    *,
    table_id: str,
    block_id: str,
    order: int,
    table_title: str,
    section_path: list[str],
    knowledge_bases: list[KnowledgeBase],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    table_model = interpret_table_matrix(matrix)
    width = table_model["width"]
    height = table_model["height"]
    header_count = table_model["header_row_count"]
    header_rows = table_model["header_rows"]
    headers = table_model["headers"]
    data_rows = table_model["data_rows"]
    table_text = render_table_text(headers, data_rows)
    kb_matches = match_knowledge(knowledge_bases, table_title, table_text, " > ".join(section_path))
    domain_tags = merge_tags(tag_domains(table_title, table_text, " > ".join(section_path)), kb_domain_tags(kb_matches))
    block = {
        "block_id": block_id,
        "order": order,
        "type": "table",
        "table_id": table_id,
        "table_title": table_title,
        "section_path": section_path,
        "rows": height,
        "columns": width,
        "header_row_count": header_count,
        "header_rows": header_rows,
        "headers": headers,
        "text": table_text[:5000],
        "domain_tags": domain_tags,
        "kb_matches": kb_matches,
        "requirement_like": is_requirement_like(table_text),
        "noise": False,
    }

    table_items: list[dict[str, Any]] = []
    current_cosem_object: dict[str, Any] | None = None
    for row_offset, row in enumerate(data_rows, start=1):
        row_index = header_count + row_offset
        if not any(row):
            continue
        fields = {
            headers[col_index]: row[col_index] if col_index < len(row) else ""
            for col_index in range(width)
        }
        compact_fields = {key: value for key, value in fields.items() if value}
        item_id = f"{table_id}-R{row_index:06d}"
        if is_cosem_object_header(compact_fields):
            current_cosem_object = build_cosem_object_context(item_id, row_index, compact_fields)
        matrix_facts = extract_matrix_facts(headers, row)
        fact_text = " | ".join(f"{fact['subject']} -> {fact['predicate_header']}" for fact in matrix_facts)
        context_text = " | ".join(str(value) for value in (current_cosem_object or {}).values() if value)
        item_text = " | ".join([*compact_fields.values(), fact_text, context_text])
        item_matches = match_knowledge(knowledge_bases, table_title, item_text, " > ".join(section_path))
        item_tags = merge_tags(tag_domains(table_title, item_text, " > ".join(section_path)), kb_domain_tags(item_matches))
        table_item = {
            "item_id": item_id,
            "type": "table_row",
            "table_id": table_id,
            "table_block_id": block_id,
            "table_title": table_title,
            "section_path": section_path,
            "row_index": row_index,
            "fields": compact_fields,
            "matrix_facts": matrix_facts,
            "domain_tags": item_tags,
            "kb_matches": item_matches,
            "requirement_like": is_requirement_like(item_text),
            "noise": False,
        }
        if current_cosem_object and (is_cosem_object_header(compact_fields) or is_cosem_attribute_row(compact_fields)):
            table_item["cosem_object_context"] = current_cosem_object
        table_items.append(table_item)

    return block, table_items


def interpret_table_matrix(matrix: list[list[str]]) -> dict[str, Any]:
    width = max((len(row) for row in matrix), default=0)
    header_count = infer_header_row_count(matrix)
    header_rows = [pad_row(row, width) for row in matrix[:header_count]]
    data_rows = [pad_row(row, width) for row in matrix[header_count:]]
    headers = effective_table_headers(header_rows, width)
    return {
        "width": width,
        "height": len(matrix),
        "header_row_count": header_count,
        "header_rows": header_rows,
        "headers": headers,
        "data_rows": data_rows,
    }


def pad_row(row: list[str], width: int) -> list[str]:
    return [row[index] if index < len(row) else "" for index in range(width)]


def infer_header_row_count(matrix: list[list[str]]) -> int:
    if not matrix:
        return 0
    width = max((len(row) for row in matrix), default=0)
    if width == 0:
        return 0

    header_count = 1
    while header_count < min(3, len(matrix)):
        first_header = pad_row(matrix[0], width)
        candidate = pad_row(matrix[header_count], width)
        if not is_continuation_header_row(first_header, candidate):
            break
        header_count += 1
    return header_count


def is_continuation_header_row(first_header: list[str], candidate: list[str]) -> bool:
    if not first_header or not candidate:
        return False
    if row_has_data_markers(candidate):
        return False
    top_values = [normalize_header_part(value) for value in first_header if normalize_header_part(value)]
    has_repeated_top_header = len(top_values) != len(set(top_values))
    if not has_repeated_top_header:
        return False

    first_top = normalize_header_part(first_header[0])
    first_candidate = normalize_header_part(candidate[0])
    if first_top and first_candidate == first_top:
        return True
    if not first_candidate and any(clean_text(value) for value in candidate[1:]):
        return True
    return False


def row_has_data_markers(row: list[str]) -> bool:
    return any(is_positive_marker(value) for value in row)


def effective_table_headers(header_rows: list[list[str]], width: int) -> list[str]:
    if not header_rows:
        return unique_headers([], width)

    headers: list[str] = []
    for column_index in range(width):
        parts: list[str] = []
        seen: set[str] = set()
        for row in header_rows:
            value = clean_text(row[column_index] if column_index < len(row) else "")
            key = normalize_header_part(value)
            if not value or key in seen:
                continue
            parts.append(value)
            seen.add(key)
        headers.append(" / ".join(parts) if parts else f"column_{column_index + 1}")
    return unique_headers(headers, width)


def normalize_header_part(value: str | None) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[_/\\-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_positive_marker(value: str | None) -> bool:
    normalized = normalize_header_part(value)
    return normalized in {"x", "yes", "true", "required", "mandatory", "applicable"}


def extract_matrix_facts(headers: list[str], row: list[str]) -> list[dict[str, Any]]:
    subject_header, subject, subject_index = primary_row_subject(headers, row)
    if not subject:
        return []

    facts: list[dict[str, Any]] = []
    for column_index, value in enumerate(row):
        marker = clean_text(value)
        if column_index == subject_index or not is_positive_marker(marker):
            continue
        facts.append(
            {
                "subject_header": subject_header,
                "subject": subject,
                "predicate_header": headers[column_index] if column_index < len(headers) else f"column_{column_index + 1}",
                "marker": marker,
                "value": True,
                "relation": "allowed",
            }
        )
    return facts


def primary_row_subject(headers: list[str], row: list[str]) -> tuple[str, str, int]:
    for index, value in enumerate(row):
        cleaned = clean_text(value)
        if cleaned and not is_positive_marker(cleaned):
            header = headers[index] if index < len(headers) else f"column_{index + 1}"
            return header, cleaned, index
    return "", "", -1


def is_cosem_object_header(fields: dict[str, Any]) -> bool:
    return bool(first_field_value(fields, "Object/attribute name") and first_field_value(fields, "CL"))


def is_cosem_attribute_row(fields: dict[str, Any]) -> bool:
    return bool(first_field_value(fields, "#") and first_field_value(fields, "Object/attribute name"))


def build_cosem_object_context(item_id: str, row_index: int, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_item_id": item_id,
        "row_index": row_index,
        "object_name": first_field_value(fields, "Object/attribute name"),
        "class_id": parse_intish(first_field_value(fields, "CL")),
        "obis": first_field_value(fields, "Value"),
        "meaning": first_field_value(fields, "Meaning"),
        "comment": first_field_value(fields, "Comment"),
    }


def parse_intish(value: Any) -> int | str | None:
    if value is None:
        return None
    text = clean_text(str(value)).lower()
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    if text in words:
        return words[text]
    if text.isdigit():
        return int(text)
    return clean_text(str(value))


def tag_domains(*texts: str) -> list[str]:
    haystack = normalize_match_term(" ".join(t for t in texts if t))
    tags: list[str] = []
    for tag, pattern in DOMAIN_RULE_PATTERNS:
        if find_matched_terms(pattern, haystack, normalized=True):
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
            match_pattern = compile_term_pattern(keywords)
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
                    match_pattern=match_pattern,
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


def stable_requirement_id(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("source_id") or ""),
        str(row.get("requirement_type") or ""),
        normalize_match_term(row.get("requirement", "")),
    ]
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16].upper()
    return f"SREQ-{digest}"


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
            matched_terms = find_matched_terms(entry.match_pattern, haystack, normalized=True)
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


def is_atomic_requirement_like(text: str) -> bool:
    low = text.lower()
    strong_signals = (
        "shall",
        "must",
        "not used, must",
        "is required",
        "are required",
        "access is required",
        "mandatory",
        "required by",
        "required for",
        "set to",
    )
    return any(signal in low for signal in strong_signals)


def extract_docx(
    input_path: Path,
    knowledge_bases: list[KnowledgeBase] | None = None,
    document_profile: DocumentProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    knowledge_bases = knowledge_bases or []
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
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
            heading = detect_heading(text, style_name, is_list_item=has_numbering(item), document_profile=profile)
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
                "noise": is_noise(text, document_profile=profile),
            }
            if heading:
                block["heading_level"] = heading[0]
            blocks.append(block)

            if looks_like_caption(text, document_profile=profile):
                last_caption = text
            elif block_type != "heading" and not is_noise(text, document_profile=profile):
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

            order += 1
            block_id = f"BLK-{order:06d}"
            table_block, new_table_items = build_table_artifacts(
                matrix,
                table_id=table_id,
                block_id=block_id,
                order=order,
                table_title=table_title,
                section_path=section_path,
                knowledge_bases=knowledge_bases,
            )
            blocks.append(table_block)
            table_items.extend(new_table_items)
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


def mark_doc_regions(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    document_profile: DocumentProfile | None = None,
) -> None:
    """Mark blocks as body/front matter so model tasks ignore cover and TOC pages."""
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    body_start_indexes: list[int] = []
    preface_index: int | None = None
    introduction_index: int | None = None

    for index, block in enumerate(blocks):
        text = normalize_title(block.get("text", ""))
        if block.get("type") == "heading" and text == profile.body_start_heading:
            body_start_indexes.append(index)
        if block.get("type") == "heading" and text == "preface" and preface_index is None:
            preface_index = index
        if block.get("type") == "heading" and text == "introduction" and introduction_index is None:
            introduction_index = index

    # Standards often include "The Scope in English..." in the preface before the
    # real normative body. If multiple Scope headings exist, the last one is the
    # safer body start.
    body_start = body_start_indexes[-1] if body_start_indexes else 0

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


def apply_table_pattern_shadow(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    domain_pack_dir: Path,
) -> dict[str, Any]:
    patterns_path = domain_pack_dir.expanduser().resolve() / "table_patterns.yaml"
    if not patterns_path.exists():
        raise AtomizerInputError(f"Missing table_patterns.yaml: {patterns_path}")
    patterns = load_table_patterns(patterns_path)
    table_items_by_block: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in table_items:
        table_items_by_block[str(item.get("table_block_id") or "")].append(item)

    by_pattern_id: Counter[str] = Counter()
    tables_total = 0
    tables_with_pattern = 0
    for block in blocks:
        if block.get("type") != "table":
            continue
        tables_total += 1
        matches = match_table_pattern(block, patterns)[:3]
        if not matches:
            continue
        block["pattern_matches"] = matches
        tables_with_pattern += 1
        by_pattern_id.update(match["pattern_id"] for match in matches)
        for item in table_items_by_block.get(str(block.get("block_id") or ""), []):
            item["pattern_matches"] = matches

    return {
        "tables_total": tables_total,
        "tables_with_pattern": tables_with_pattern,
        "by_pattern_id": dict(by_pattern_id.most_common()),
    }


def load_document_profile_from_domain_pack(domain_pack_dir: Path | None) -> DocumentProfile:
    if domain_pack_dir is None:
        return DEFAULT_DOCUMENT_PROFILE
    pack_path = domain_pack_dir.expanduser().resolve() / "pack.yaml"
    if not pack_path.exists():
        return DEFAULT_DOCUMENT_PROFILE
    pack = load_domain_pack(pack_path)
    return DocumentProfile.from_payload(pack.payload.get("document_profile"))


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
        if block.get("noise"):
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
                    "matrix_facts": item.get("matrix_facts", []),
                },
                "expected_output_schema": atomic_requirement_schema(),
            }
        )

    return tasks


def build_atomic_candidates(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    include_regions: set[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        key = (
            row.get("source_id", ""),
            row.get("requirement_type", ""),
            normalize_match_term(row.get("requirement", "")),
        )
        if key in seen:
            return
        seen.add(key)
        row["req_id"] = f"AREQ-{len(candidates) + 1:06d}"
        row["stable_req_id"] = stable_requirement_id(row)
        candidates.append(row)

    for block in blocks:
        if include_regions is not None and block.get("doc_region") not in include_regions:
            continue
        if block.get("type") != "paragraph" or block.get("noise"):
            continue
        paragraph_text = clean_text(block.get("text", ""))
        for context in paragraph_requirement_contexts(paragraph_text):
            sentence = context["sentence"]
            if not is_atomic_requirement_like(sentence):
                continue
            add(
                atomic_row(
                    source_id=block["block_id"],
                    source_type="paragraph",
                    source_refs=[block["block_id"]],
                    section_path=block.get("section_path", []),
                    domain_tags=block.get("domain_tags", []),
                    kb_matches=block.get("kb_matches", []),
                    requirement_type=classify_requirement_type(sentence, block.get("domain_tags", [])),
                    requirement=sentence,
                    object_name=infer_object_name(block.get("kb_matches", []), sentence),
                    parameters=extract_parameters(sentence),
                    verification_method=verification_method_for(block.get("domain_tags", []), sentence),
                    confidence=0.68,
                    ambiguity=is_ambiguous_text(sentence),
                    condition=condition_from_previous_sentence(context.get("prev_sentence")),
                    source_context={
                        "paragraph_text": truncate_text(paragraph_text, 600),
                        "prev_sentence": context.get("prev_sentence"),
                    },
                )
            )

    for item in table_items:
        if include_regions is not None and item.get("doc_region") not in include_regions:
            continue
        for fact in item.get("matrix_facts", []):
            predicate = clean_table_header(fact.get("predicate_header", ""))
            subject = clean_text(fact.get("subject"))
            if not subject or not predicate:
                continue
            add(
                atomic_row(
                    source_id=item["item_id"],
                    source_type="table_matrix_fact",
                    source_refs=[item["table_block_id"], item["item_id"]],
                    section_path=item.get("section_path", []),
                    domain_tags=item.get("domain_tags", []),
                    kb_matches=item.get("kb_matches", []),
                    requirement_type="capability_matrix",
                    requirement=f"{subject} shall support {predicate}.",
                    object_name=subject,
                    parameters={
                        "table_title": item.get("table_title"),
                        "row_index": item.get("row_index"),
                        "subject_header": fact.get("subject_header"),
                        "predicate_header": fact.get("predicate_header"),
                        "marker": fact.get("marker"),
                    },
                    verification_method="configuration_check",
                    confidence=0.82,
                    ambiguity=False,
                )
            )

        fields = item.get("fields", {})
        for valued_fact in extract_valued_matrix_facts(fields):
            add(valued_matrix_candidate(item, valued_fact))

        object_candidate = cosem_object_candidate(item, fields)
        if object_candidate:
            add(object_candidate)

        cosem_candidate = cosem_attribute_candidate(item, fields)
        if cosem_candidate:
            add(cosem_candidate)

        event_candidate = event_definition_candidate(item, fields)
        if event_candidate:
            add(event_candidate)

        event_group_candidate = event_group_candidate_from_fields(item, fields)
        if event_group_candidate:
            add(event_group_candidate)

        for candidate in [
            security_suite_candidate(item, fields),
            security_policy_bit_candidate(item, fields),
            security_policy_state_candidate(item, fields),
            measurement_quantity_candidate(item, fields),
            flag_definition_candidate(item, fields),
        ]:
            if candidate:
                add(candidate)

        row_requirement = table_row_requirement_candidate(item, fields)
        if row_requirement:
            add(row_requirement)

    return candidates


def atomic_row(
    *,
    source_id: str,
    source_type: str,
    source_refs: list[str],
    section_path: list[str],
    domain_tags: list[str],
    kb_matches: list[dict[str, Any]],
    requirement_type: str,
    requirement: str,
    object_name: str,
    parameters: dict[str, Any],
    verification_method: str,
    confidence: float,
    ambiguity: bool,
    condition: str | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "source_id": source_id,
        "source_type": source_type,
        "source_refs": source_refs,
        "section_path": section_path,
        "domain": primary_domain(domain_tags),
        "domain_tags": domain_tags,
        "object": object_name,
        "requirement_type": requirement_type,
        "requirement": clean_text(requirement),
        "condition": condition,
        "parameters": parameters,
        "verification_method": verification_method,
        "ambiguity": ambiguity,
        "review_questions": review_questions_for(requirement, ambiguity),
        "confidence": confidence,
        "kb_matches": compact_kb_matches(kb_matches),
        "generated_by": "rule_based_atomizer_v1",
    }
    if source_context is not None:
        row["source_context"] = source_context
    return row


def paragraph_requirement_contexts(text: str) -> list[dict[str, str | None]]:
    sentences = split_paragraph_sentences(text)
    contexts: list[dict[str, str | None]] = []
    for index, sentence in enumerate(sentences):
        contexts.append(
            {
                "sentence": sentence,
                "prev_sentence": sentences[index - 1] if index > 0 else None,
            }
        )
    return contexts


def split_paragraph_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    return [clean_text(part) for part in re.split(r"(?<=[.;!?])\s+", text) if clean_text(part)]


def condition_from_previous_sentence(prev_sentence: str | None) -> str | None:
    if not prev_sentence:
        return None
    if is_atomic_requirement_like(prev_sentence):
        return None
    return prev_sentence if re.match(r"^(if|when|where|in case|unless)\b", prev_sentence, flags=re.I) else None


def truncate_text(text: str, max_chars: int) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def classify_requirement_type(text: str, domain_tags: list[str]) -> str:
    low = text.lower()
    if "security" in domain_tags or any(term in low for term in ("hls", "lls", "password", "encrypt", "authenticat")):
        return "security"
    if "access_control" in domain_tags or any(term in low for term in ("read", "write", "access", "association")):
        return "access_control"
    if "communication_profile" in domain_tags or any(term in low for term in ("dlms", "xdlms", "communication", "push")):
        return "communication"
    if "cosem_object" in domain_tags or any(term in low for term in ("cosem", "obis", "logical_name", "attribute")):
        return "cosem_object"
    if "event" in domain_tags:
        return "event"
    return "functional"


def verification_method_for(domain_tags: list[str], text: str) -> str:
    low = text.lower()
    if "configuration_check" in domain_tags or any(term in low for term in ("set to", "access rights", "configured", "password", "hls", "lls")):
        return "configuration_check"
    if any(term in low for term in ("shall support", "must support", "service", "push", "notification")):
        return "test"
    if "security_policy" in domain_tags:
        return "test"
    return "inspection"


def infer_object_name(kb_matches: list[dict[str, Any]], text: str) -> str:
    preferred_types = {
        "cosem_interface_class",
        "cosem_object_instance",
        "object",
        "client_role",
        "logical_device",
        "service_set",
        "security_level",
    }
    for match in kb_matches:
        if match.get("type") in preferred_types and match.get("name"):
            return str(match["name"])
    text = clean_text(text)
    match = re.search(r"\b([A-Z][A-Za-z0-9_/-]*(?:\s+[A-Z][A-Za-z0-9_/-]*){0,4})\b", text)
    if not match:
        return ""
    candidate = match.group(1).strip()
    first_word = candidate.split()[0]
    return "" if first_word in OBJECT_NAME_STOPWORDS else candidate


def extract_parameters(text: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    obis_codes = re.findall(r"\b\d+-\d+:\d+(?:\.\d+|\.x){3}\b", text)
    if obis_codes:
        params["obis_codes"] = list(dict.fromkeys(obis_codes))
    sap_values = re.findall(r"\bSAP\s*=\s*0x[0-9A-Fa-f]+\b", text)
    if sap_values:
        params["sap_values"] = list(dict.fromkeys(sap_values))
    class_ids = re.findall(r"\b(?:class|CL)\s*=?\s*(\d{1,3})\b", text, flags=re.I)
    if class_ids:
        params["class_ids"] = list(dict.fromkeys(class_ids))
    return params


def is_ambiguous_text(text: str) -> bool:
    low = text.lower()
    return any(signal in low for signal in ("if necessary", "can be", "may be", "where applicable", "reserved"))


def review_questions_for(requirement: str, ambiguity: bool) -> list[str]:
    if not ambiguity:
        return []
    return [f"Confirm whether this source text is normative: {requirement[:140]}"]


def primary_domain(domain_tags: list[str]) -> str:
    return domain_tags[0] if domain_tags else "general"


def compact_kb_matches(kb_matches: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for match in kb_matches[:limit]:
        compact.append(
            {
                "kb_id": match.get("kb_id"),
                "entry_id": match.get("entry_id"),
                "type": match.get("type"),
                "name": match.get("name"),
                "matched_terms": match.get("matched_terms", [])[:5],
            }
        )
    return compact


def clean_table_header(value: str | None) -> str:
    value = clean_text(value)
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        if len(parts) >= 2:
            top = parts[0]
            leaf = parts[-1]
            if normalize_header_part(top) in normalize_header_part(leaf):
                return leaf
            return f"{top}: {leaf}"
    return value


def extract_valued_matrix_facts(fields: dict[str, Any]) -> list[dict[str, Any]]:
    if len(fields) < 3:
        return []
    if looks_like_non_matrix_row(fields):
        return []
    first_key = next(iter(fields), "")
    subject = clean_text(fields.get(first_key))
    if not subject:
        return []

    facts: list[dict[str, Any]] = []
    for key, value in list(fields.items())[1:]:
        cleaned_value = clean_text(str(value))
        if not cleaned_value or is_positive_marker(cleaned_value):
            continue
        facts.append(
            {
                "subject_header": first_key,
                "subject": subject,
                "predicate_header": key,
                "value": cleaned_value,
                "relation": "has_value",
            }
        )
    return facts


def looks_like_non_matrix_row(fields: dict[str, Any]) -> bool:
    normalized_keys = {normalize_header_part(key) for key in fields}
    non_matrix_markers = {
        "id",
        "name",
        "#",
        "object attribute name",
        "cl",
        "type",
        "value",
        "meaning",
        "comment",
        "unit",
        "flag",
        "description",
        "state",
        "security policy",
        "bit",
        "security policy security states",
        "access rights rc pc sc lc",
        "description of the event",
        "event number",
        "number of event",
        "group number",
        "subgroup number",
    }
    return bool(normalized_keys & non_matrix_markers)


def valued_matrix_candidate(item: dict[str, Any], fact: dict[str, Any]) -> dict[str, Any]:
    subject = clean_text(fact.get("subject"))
    predicate = clean_table_header(fact.get("predicate_header"))
    value = clean_text(fact.get("value"))
    requirement = f"{subject} shall have {predicate} set to {value}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="table_valued_matrix_fact",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type=classify_valued_matrix_type(item, fact),
        requirement=requirement,
        object_name=subject,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "subject_header": fact.get("subject_header"),
            "predicate_header": fact.get("predicate_header"),
            "value": value,
        },
        verification_method="configuration_check",
        confidence=0.8,
        ambiguity=is_ambiguous_text(value),
    )


def classify_valued_matrix_type(item: dict[str, Any], fact: dict[str, Any]) -> str:
    text = normalize_match_term(" ".join([item.get("table_title", ""), fact.get("predicate_header", ""), fact.get("value", "")]))
    if any(term in text for term in ("hls", "lls", "without security", "security")):
        return "association_security_matrix"
    return "table_value_matrix"


def cosem_attribute_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    attr_no = first_field_value(fields, "#")
    attr_name = first_field_value(fields, "Object/attribute name")
    access_rights = first_field_value(fields, "Access rights RC/PC/SC/LC")
    if not attr_no or not attr_name or not access_rights:
        return None

    object_context = item.get("cosem_object_context") or {}
    object_name = clean_text(object_context.get("object_name")) or infer_object_name(item.get("kb_matches", []), attr_name)
    qualified_attr_name = f"{object_name}.{attr_name}" if object_name else attr_name
    parsed_access_rights = parse_access_rights(access_rights)
    class_id = object_context.get("class_id")
    obis = clean_text(object_context.get("obis"))
    object_bits = []
    if object_name:
        object_bits.append(object_name)
    if class_id not in {None, ""}:
        object_bits.append(f"CL {class_id}")
    if obis:
        object_bits.append(f"OBIS {obis}")
    object_phrase = f" for {' / '.join(object_bits)}" if object_bits else ""
    requirement = f"COSEM attribute {qualified_attr_name}{object_phrase} shall use access rights {access_rights}."
    params = {
        "table_title": item.get("table_title"),
        "row_index": item.get("row_index"),
        "cosem_object": object_context,
        "attribute_id": attr_no,
        "attribute_name": attr_name,
        "type": first_field_value(fields, "Type"),
        "value": first_field_value(fields, "Value"),
        "meaning": first_field_value(fields, "Meaning"),
        "comment": first_field_value(fields, "Comment"),
        "access_rights": access_rights,
        "access_rights_by_client": parsed_access_rights,
    }
    return atomic_row(
        source_id=item["item_id"],
        source_type="cosem_attribute_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type="cosem_attribute_access",
        requirement=requirement,
        object_name=qualified_attr_name,
        parameters={key: value for key, value in params.items() if value},
        verification_method="configuration_check",
        confidence=0.9 if object_name else 0.82,
        ambiguity=False,
    )


def table_row_requirement_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    field_text = " | ".join(str(value) for value in fields.values() if value)
    if not is_atomic_requirement_like(field_text):
        return None
    return atomic_row(
        source_id=item["item_id"],
        source_type="table_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type=classify_requirement_type(field_text, item.get("domain_tags", [])),
        requirement=field_text,
        object_name=infer_object_name(item.get("kb_matches", []), field_text),
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "fields": fields,
        },
        verification_method=verification_method_for(item.get("domain_tags", []), field_text),
        confidence=0.74,
        ambiguity=is_ambiguous_text(field_text),
    )


def cosem_object_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    if not is_cosem_object_header(fields):
        return None

    context = item.get("cosem_object_context") or build_cosem_object_context(item["item_id"], item.get("row_index", 0), fields)
    object_name = clean_text(context.get("object_name"))
    class_id = context.get("class_id")
    obis = clean_text(context.get("obis"))
    if not object_name or not obis:
        return None

    object_bits = [object_name]
    if class_id not in {None, ""}:
        object_bits.append(f"CL {class_id}")
    object_bits.append(f"OBIS {obis}")
    requirement = f"COSEM object {' / '.join(object_bits)} shall be defined by the profile."
    return atomic_row(
        source_id=item["item_id"],
        source_type="cosem_object_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type="cosem_object_instance",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "cosem_object": context,
        },
        verification_method="configuration_check",
        confidence=0.88,
        ambiguity=False,
    )


def event_definition_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    group = first_field_value(fields, "Group number")
    subgroup = first_field_value(fields, "Subgroup number")
    event_number = first_field_value(fields, "Event number") or first_field_value(fields, "Number of event")
    description = (
        first_field_value(fields, "Description of the event")
        or first_field_value(fields, "Event description")
        or first_field_value(fields, "Event subgroup description")
    )
    if not event_number or not description:
        return None
    if not group and not subgroup and "event" not in item.get("table_title", "").lower():
        return None

    subgroup_description = (
        first_field_value(fields, "Event subgroup description")
        or first_field_value(fields, "Description of the subgroup of events")
    )
    object_name = "Event"
    if group or subgroup or event_number:
        object_name = f"Event G{group or '?'}-SG{subgroup or '?'}-E{event_number}"
    requirement = f"{object_name} shall be defined as: {description}."
    parameters = {
        "table_title": item.get("table_title"),
        "row_index": item.get("row_index"),
        "group_number": group,
        "subgroup_number": subgroup,
        "subgroup_description": subgroup_description,
        "event_number": parse_intish(event_number),
        "event_description": description,
    }
    return atomic_row(
        source_id=item["item_id"],
        source_type="event_table_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["event", "log"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="event_definition",
        requirement=requirement,
        object_name=object_name,
        parameters={key: value for key, value in parameters.items() if value not in {"", None}},
        verification_method="document_review",
        confidence=0.84,
        ambiguity=is_ambiguous_text(description),
    )


def event_group_candidate_from_fields(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    group = first_field_value(fields, "Group number")
    subgroup = first_field_value(fields, "Subgroup number")
    minimum_records = first_field_value(fields, "Minimum records")
    description = first_field_value(fields, "Description of the event") or first_field_value(fields, "Event subgroup description")
    subgroup_description = first_field_value(fields, "Event subgroup description")
    if not group or not subgroup or not minimum_records:
        return None
    object_name = f"Event subgroup G{group}-SG{subgroup}"
    requirement = f"{object_name} shall keep at least {minimum_records} records for {description}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="event_group_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["event", "log"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="event_group_retention",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "group_number": group,
            "subgroup_number": subgroup,
            "subgroup_description": subgroup_description,
            "minimum_records": parse_intish(minimum_records),
            "description": description,
        },
        verification_method="configuration_check",
        confidence=0.86,
        ambiguity=is_ambiguous_text(description),
    )


def security_suite_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    suite_id = first_field_value(fields, "ID")
    name = first_field_value(fields, "Name")
    if not suite_id or not name or "security" not in item.get("table_title", "").lower():
        return None
    params = {
        "table_title": item.get("table_title"),
        "row_index": item.get("row_index"),
        "id": parse_intish(suite_id),
        "name": name,
        "authenticated_encryption": first_field_value(fields, "Authenticated encryption"),
        "digital_signature": first_field_value(fields, "Digital signature"),
        "key_agreement": first_field_value(fields, "Key Agreement"),
        "hash": first_field_value(fields, '"Hash"') or first_field_value(fields, "Hash"),
        "transport_key": first_field_value(fields, "Transport key"),
        "compression": first_field_value(fields, "Compression"),
    }
    requirement = f"Security suite {suite_id} shall be defined as {name}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="security_suite_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["security_policy"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="security_suite_definition",
        requirement=requirement,
        object_name=f"Security suite {suite_id}",
        parameters={key: value for key, value in params.items() if value not in {"", None}},
        verification_method="document_review",
        confidence=0.86,
        ambiguity=False,
    )


def security_policy_bit_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    bit = first_field_value(fields, "bit")
    policy = first_field_value(fields, "Security Policy - Security States")
    if not bit or not policy:
        return None
    object_name = f"Security policy bit {bit}"
    requirement = f"{object_name} shall be defined as: {policy}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="security_policy_bit_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["security_policy"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="security_policy_bit",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "bit": parse_intish(bit),
            "definition": policy,
        },
        verification_method="configuration_check",
        confidence=0.86,
        ambiguity=is_ambiguous_text(policy),
    )


def security_policy_state_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    state = first_field_value(fields, "State")
    policy = first_field_value(fields, "Security policy")
    if not state or not policy:
        return None
    object_name = f"Security policy state {state}"
    requirement = f"{object_name} shall be defined as: {policy}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="security_policy_state_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["security_policy"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="security_policy_state",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "state": parse_intish(state),
            "policy": policy,
        },
        verification_method="configuration_check",
        confidence=0.84,
        ambiguity=is_ambiguous_text(policy),
    )


def measurement_quantity_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    quantity_group = first_field_value(fields, "Greatness")
    quantity = first_field_value(fields, "Greatness_2")
    unit = first_field_value(fields, "Unit")
    if not quantity_group or not quantity or not unit:
        return None
    object_name = quantity
    requirement = f"Measurement quantity {quantity} shall use unit {unit}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="measurement_quantity_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["measurement_quantity"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="measurement_quantity_unit",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "quantity_group": quantity_group,
            "quantity": quantity,
            "unit": unit,
        },
        verification_method="document_review",
        confidence=0.82,
        ambiguity=False,
    )


def flag_definition_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    flag = first_field_value(fields, "Flag")
    description = first_field_value(fields, "Description")
    if not flag or not description:
        return None
    title = item.get("table_title", "")
    object_name = f"{title}: {flag}" if title else flag
    requirement = f"{object_name} shall be defined as: {description}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="flag_definition_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type="flag_definition",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": title,
            "row_index": item.get("row_index"),
            "flag": flag,
            "description": description,
        },
        verification_method="document_review",
        confidence=0.8,
        ambiguity=is_ambiguous_text(description),
    )


def parse_access_rights(value: str | None, client_map: dict[str, str] | None = None) -> dict[str, Any]:
    text = clean_text(value)
    if not text:
        return {}
    clients = list((client_map or DEFAULT_ACCESS_RIGHT_CLIENTS).items())
    parts = [part.strip().upper() for part in text.split("/")]
    parsed_clients: list[dict[str, Any]] = []
    for index, (client_code, client_name) in enumerate(clients):
        code = parts[index] if index < len(parts) else ""
        parsed_clients.append(
            {
                "client": client_code,
                "client_name": client_name,
                "code": code,
                "read": "R" in code,
                "write": "W" in code,
                "allowed": code not in {"", "--"},
            }
        )
    return {
        "raw": text,
        "clients": parsed_clients,
    }


def first_field_value(fields: dict[str, Any], expected_header: str) -> str:
    expected = normalize_header_part(expected_header)
    for key, value in fields.items():
        if normalize_header_part(key) == expected:
            return clean_text(str(value))
    squashed = expected.replace(" ", "")
    for key, value in fields.items():
        if normalize_header_part(key).replace(" ", "") == squashed:
            return clean_text(str(value))
    return ""


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
                "stable_req_id": "string",
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


def assert_valid_atomic_requirements(rows: list[dict[str, Any]]) -> None:
    issues = validate_atomic_requirements(rows)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        preview = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise ValueError(f"invalid atomic requirements: {preview}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atomize a technical standard document for LLM requirement analysis.")
    parser.add_argument("input", type=Path, help="Input .docx or .xlsx file")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    parser.add_argument("--chunk-chars", type=int, default=3500, help="Target character size per retrieval chunk")
    parser.add_argument(
        "--kb",
        type=Path,
        action="append",
        default=[],
        help="External knowledge base JSON file. Can be provided multiple times.",
    )
    parser.add_argument("--domain-pack", type=Path, default=None, help="Optional domain pack directory for shadow table matching.")
    return parser.parse_args()


def run_atomizer_pipeline(
    input_path: Path,
    out_dir: Path,
    *,
    chunk_chars: int = 3500,
    kb_paths: list[Path] | None = None,
    domain_pack_dir: Path | None = None,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    if not input_path.exists():
        raise AtomizerInputError(f"Input file does not exist: {input_path}")
    input_format = input_path.suffix.lower()
    if input_format == ".xls":
        raise AtomizerInputError("Legacy .xls input is not supported; save it as .xlsx. Supported formats: .docx, .xlsx, .pdf.")
    if input_format not in SUPPORTED_INPUT_FORMATS:
        raise AtomizerInputError(f"Unsupported input format: {input_format or '<none>'}. Supported formats: .docx, .xlsx, .pdf.")

    out_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("loading knowledge bases (%s files)", len(kb_paths or []))
    knowledge_bases = load_knowledge_bases(kb_paths or [])
    document_profile = load_document_profile_from_domain_pack(domain_pack_dir)

    LOGGER.info("extracting %s", input_format.lstrip("."))
    if input_format == ".docx":
        blocks, table_items = extract_docx(input_path, knowledge_bases=knowledge_bases, document_profile=document_profile)
    elif input_format == ".xlsx":
        from parsers.xlsx_parser import extract_xlsx

        blocks, table_items = extract_xlsx(input_path, knowledge_bases=knowledge_bases, document_profile=document_profile)
    else:
        from parsers.pdf_parser import extract_pdf

        blocks, table_items = extract_pdf(input_path, knowledge_bases=knowledge_bases, document_profile=document_profile)
    LOGGER.info("extracted %s blocks, %s table rows", len(blocks), len(table_items))
    pattern_shadow = None
    if domain_pack_dir is not None:
        pattern_shadow = apply_table_pattern_shadow(blocks, table_items, domain_pack_dir)
    mark_doc_regions(blocks, table_items, document_profile=document_profile)
    LOGGER.info("building chunks")
    chunks = build_chunks(blocks, target_chars=chunk_chars, include_regions={"body"})
    body_table_items = [item for item in table_items if item.get("doc_region") == "body"]
    LOGGER.info("building candidates")
    atomic_candidates = build_atomic_candidates(blocks, body_table_items, include_regions={"body"})
    try:
        assert_valid_atomic_requirements(atomic_candidates)
    except ValueError as exc:
        raise AtomizerPipelineError(str(exc)) from exc
    llm_tasks = build_llm_tasks(chunks, body_table_items)
    quality_report = build_quality_report(blocks, table_items, atomic_candidates, llm_tasks, pattern_shadow=pattern_shadow)

    LOGGER.info("writing outputs")
    block_count = write_jsonl(out_dir / "blocks.jsonl", blocks)
    chunk_count = write_jsonl(out_dir / "chunks.jsonl", chunks)
    table_count = write_jsonl(out_dir / "table_items.jsonl", table_items)
    atomic_count = write_jsonl(out_dir / "atomic_requirements.jsonl", atomic_candidates)
    task_count = write_jsonl(out_dir / "llm_tasks.jsonl", llm_tasks)
    write_json(out_dir / "quality_report.json", quality_report)

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
        "version": __version__,
        "input": str(input_path),
        "input_format": input_format.lstrip("."),
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
        "domain_pack": str(domain_pack_dir.expanduser().resolve()) if domain_pack_dir else None,
        "counts": {
            "blocks": block_count,
            "chunks": chunk_count,
            "table_items": table_count,
            "body_table_items": len(body_table_items),
            "atomic_requirements": atomic_count,
            "llm_tasks": task_count,
        },
        "files": {
            "blocks": "blocks.jsonl",
            "chunks": "chunks.jsonl",
            "table_items": "table_items.jsonl",
            "atomic_requirements": "atomic_requirements.jsonl",
            "llm_tasks": "llm_tasks.jsonl",
            "quality_report": "quality_report.json",
            "summary": "summary.md",
        },
    }
    write_json(out_dir / "manifest.json", manifest)
    write_summary(out_dir / "summary.md", manifest, domain_counts, kb_counts, quality_report=quality_report)

    return manifest


def main() -> int:
    args = parse_args()
    try:
        manifest = run_atomizer_pipeline(
            args.input,
            args.out,
            chunk_chars=args.chunk_chars,
            kb_paths=args.kb,
            domain_pack_dir=args.domain_pack,
        )
    except AtomizerInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
