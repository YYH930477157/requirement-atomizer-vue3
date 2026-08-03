"""Deterministic source-claim inventory used by the shadow claim ledger.

The catalog deliberately starts at parsed artifacts rather than requirement-like
heuristics.  Every canonical source leaf is represented before any LLM call and
every eligible leaf is assigned to exactly one virtual extraction unit.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from claim_structural_overrides import (
    CLAIM_STRUCTURAL_OVERRIDE_VERSION,
    StructuralOverrideSnapshot,
    apply_structural_overrides,
    empty_structural_override_snapshot,
    read_structural_overrides,
    structural_override_identity,
)
from source_spans import (
    SOURCE_ALIGNMENT_VERSION,
    SOURCE_TEXT_NORMALIZATION_VERSION,
    SOURCE_TRANSFORMATION_POLICY_VERSION,
    SOURCE_TRANSFORMATION_RULESET_VERSION,
    source_alignment_fields,
)
from table_structure import (
    TABLE_STRUCTURE_VERSION,
    is_normative_text,
    is_positive_marker,
    row_bears_normative_sentence,
)

CLAIM_CATALOG_VERSION = "claim-catalog-v11"
CLAIM_UNIT_PACKING_VERSION = "claim-unit-packing-v1"
CLAIM_CATALOG_SCHEMA = "claim-catalog/v2"
CLAIM_CATALOG_META_SCHEMA = "claim-catalog-meta/v1"

TABLE_FALLBACK_MAX_ROWS = 20
TABLE_FALLBACK_MAX_CHARS = 2000
DEFAULT_CLAIM_UNIT_CHARS = 2800
PAGE_FURNITURE_MIN_PAGES = 3

_LIST_MARKER_RE = re.compile(
    r"^\s*(?:[-*\u2022\u25aa\u25e6]|(?:[A-Za-z]|\d{1,3})[.)\u3001\uff09])\s+"
)
_LIST_INTRO_RE = re.compile(r"[^\n]{1,160}[:\uff1a]\s*$")
_WS_RE = re.compile(r"\s+")

# \u5207\u53e5\u5668\u5355\u6e90\u5728 table_structure\uff08\u7ed3\u6784\u5c42\u591a\u4e49\u52a1\u683c\u5224\u5b9a\u4e0e claim \u5c42\u6309\u53e5\u51fa claim \u540c\u53e3\u5f84\uff09
from table_structure import sentence_spans as _sentence_spans


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(*parts: bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return "sha256:" + digest.hexdigest()


def _normalized_text(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    return _WS_RE.sub(" ", value).strip().casefold()


def _artifact_bytes(rows: list[dict[str, Any]], supplied: bytes | None) -> bytes:
    if supplied is not None:
        return supplied
    return b"".join(_canonical_bytes(row) + b"\n" for row in rows)


def build_document_generation(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    blocks_bytes: bytes | None = None,
    table_items_bytes: bytes | None = None,
    table_cell_items: list[dict[str, Any]] | None = None,
    table_cell_items_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Return the deterministic generation anchored to the parser artifacts.

    世代哈希向后兼容：只有当输入携带 table-structure-v2 证据（结构化表格块或
    canonical cells）时才把 cell payload / 结构版本钉进 generation——旧产物
    （无 cell 时代）哈希与 v5 逐字节一致，历史绑定不失效，禁止伪造迁移。"""
    cell_rows = table_cell_items or []
    structure_v2 = bool(cell_rows) or any(
        str(block.get("table_structure_version") or "") == TABLE_STRUCTURE_VERSION
        for block in blocks
    )
    block_payload = _artifact_bytes(blocks, blocks_bytes)
    table_payload = _artifact_bytes(table_items, table_items_bytes)
    cell_payload = _artifact_bytes(cell_rows, table_cell_items_bytes)
    repair_versions = sorted({
        str(row.get("text_repair_version") or "")
        for row in [*blocks, *table_items]
        if str(row.get("text_repair_version") or "")
    })
    parser_provenance = {
        "text_repair_versions": repair_versions,
        "source_alignment_version": SOURCE_ALIGNMENT_VERSION,
        "source_transformation_policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
        "source_transformation_ruleset_version": SOURCE_TRANSFORMATION_RULESET_VERSION,
        "blocks_with_raw_mapping": sum(bool(row.get("raw_to_repaired_spans")) for row in blocks),
        "table_items_with_raw_mapping": sum(bool(row.get("raw_to_repaired_spans")) for row in table_items),
    }
    hash_parts = [block_payload, table_payload]
    if structure_v2:
        parser_provenance["table_structure_version"] = TABLE_STRUCTURE_VERSION
        hash_parts.append(cell_payload)
    hash_parts.append(_canonical_bytes(parser_provenance))
    generation_id = _sha256_bytes(*hash_parts)
    result = {
        "document_generation_id": generation_id,
        "blocks_sha256": _sha256_bytes(block_payload),
        "table_items_sha256": _sha256_bytes(table_payload),
        "parser_provenance": parser_provenance,
    }
    if structure_v2:
        result["table_cell_items_sha256"] = _sha256_bytes(cell_payload)
    return result


def _line_spans(text: str) -> list[tuple[int, int]]:
    if not text:
        return []
    starts: list[int] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            starts.append(offset)
        offset += len(line)
    if offset < len(text) and text[offset:].strip():
        starts.append(offset)
    if not starts:
        return [(0, len(text))]
    starts[0] = 0
    return [(start, starts[index + 1] if index + 1 < len(starts) else len(text))
            for index, start in enumerate(starts)]


def _looks_like_list(text: str, block: dict[str, Any]) -> bool:
    if block.get("is_list_item") or block.get("list_coalesced") or block.get("list_items"):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return bool(
        any(_LIST_MARKER_RE.match(line) for line in lines)
        or (_LIST_INTRO_RE.fullmatch(lines[0]) and len(lines) > 1)
    )


def _mapping_partition_is_complete(
    spans: object,
    *,
    raw_text: str,
    repaired_text: str,
) -> bool:
    raw_length = len(raw_text)
    repaired_length = len(repaired_text)
    if not isinstance(spans, list) or not spans:
        return raw_length == repaired_length == 0
    raw_cursor = 0
    repaired_cursor = 0
    for row in spans:
        if not isinstance(row, dict):
            return False
        operation_keys = {key for key in ("operation", "tag") if key in row}
        if len(operation_keys) != 1:
            return False
        if set(row) != {
            *operation_keys,
            "raw_start", "raw_end", "repaired_start", "repaired_end",
        }:
            return False
        try:
            coordinates = (
                row["raw_start"], row["raw_end"],
                row["repaired_start"], row["repaired_end"],
            )
        except KeyError:
            return False
        if any(type(value) is not int for value in coordinates):
            return False
        raw_start, raw_end, repaired_start, repaired_end = coordinates
        if not (0 <= raw_start <= raw_end <= raw_length
                and 0 <= repaired_start <= repaired_end <= repaired_length):
            return False
        if raw_start != raw_cursor or repaired_start != repaired_cursor:
            return False
        operation_key = next(iter(operation_keys))
        operation = str(row.get(operation_key) or "")
        raw_size = raw_end - raw_start
        repaired_size = repaired_end - repaired_start
        if operation != "equal":
            return False
        if (raw_size <= 0 or raw_size != repaired_size
                or raw_text[raw_start:raw_end] != repaired_text[repaired_start:repaired_end]):
            return False
        raw_cursor = raw_end
        repaired_cursor = repaired_end
    return raw_cursor == raw_length and repaired_cursor == repaired_length


def _flat_projection_matches_alignment(
    spans: object,
    alignment: dict[str, Any],
) -> bool:
    if not isinstance(spans, list):
        return False
    expected = [
        {
            "operation": opcode["tag"],
            "raw_start": opcode["raw_start"],
            "raw_end": opcode["raw_end"],
            "repaired_start": opcode["repaired_start"],
            "repaired_end": opcode["repaired_end"],
        }
        for opcode in alignment.get("opcodes") or []
    ]
    if len(spans) != len(expected):
        return False
    for actual, wanted in zip(spans, expected):
        if not isinstance(actual, dict) or set(actual) != set(wanted):
            return False
        for key, wanted_value in wanted.items():
            actual_value = actual.get(key)
            if type(actual_value) is not type(wanted_value) or actual_value != wanted_value:
                return False
    return True


def _raw_mapping_complete(row: dict[str, Any], repaired_text: str) -> bool:
    raw_text = str(row.get("raw_text") if row.get("raw_text") is not None else repaired_text)
    alignment = row.get("source_alignment")
    if alignment is not None:
        try:
            from source_spans import source_alignment_is_approved

            if not source_alignment_is_approved(raw_text, repaired_text, alignment):
                return False
        except (TypeError, ValueError):
            return False
        return _flat_projection_matches_alignment(
            row.get("raw_to_repaired_spans"), alignment)
    if raw_text != repaired_text:
        return False
    spans = row.get("raw_to_repaired_spans")
    if spans is None or spans == []:
        return True
    return _mapping_partition_is_complete(
        spans,
        raw_text=raw_text,
        repaired_text=repaired_text,
    )


def _alignment_operations(row: dict[str, Any], repaired_text: str) -> list[dict[str, Any]]:
    raw_text = str(row.get("raw_text") if row.get("raw_text") is not None else repaired_text)
    if raw_text == repaired_text and not row.get("raw_to_repaired_spans"):
        return ([{
            "operation": "equal",
            "raw_start": 0,
            "raw_end": len(raw_text),
            "repaired_start": 0,
            "repaired_end": len(repaired_text),
        }] if raw_text else [])
    return [dict(span) for span in (row.get("raw_to_repaired_spans") or [])]


def _raw_boundary_map(row: dict[str, Any], repaired_text: str) -> list[int] | None:
    """Map every repaired boundary to one monotonic raw boundary."""
    raw_text = str(row.get("raw_text") if row.get("raw_text") is not None else repaired_text)
    if not _raw_mapping_complete(row, repaired_text):
        return None
    if not repaired_text:
        return [0]
    boundaries: list[int | None] = [None] * (len(repaired_text) + 1)
    deletions: list[tuple[int, int, int]] = []
    for span in _alignment_operations(row, repaired_text):
        operation = str(span.get("operation") or span.get("tag") or "")
        raw_start, raw_end = int(span["raw_start"]), int(span["raw_end"])
        repaired_start = int(span["repaired_start"])
        repaired_end = int(span["repaired_end"])
        if operation == "delete":
            deletions.append((repaired_start, raw_start, raw_end))
            continue
        repaired_size = repaired_end - repaired_start
        raw_size = raw_end - raw_start
        for offset in range(repaired_size + 1):
            if operation == "insert":
                projected = raw_start
            elif operation == "equal":
                projected = raw_start + offset
            else:
                projected = raw_start + (offset * raw_size // repaired_size)
            boundaries[repaired_start + offset] = projected
    for repaired_position, raw_start, raw_end in deletions:
        if repaired_position == 0:
            boundaries[0] = min(int(boundaries[0] or raw_end), raw_start)
        else:
            boundaries[repaired_position] = max(
                int(boundaries[repaired_position] or raw_start), raw_end,
            )
    if any(value is None for value in boundaries):
        return None
    result = [int(value) for value in boundaries]
    if any(left > right for left, right in zip(result, result[1:])):
        return None
    return result


def _raw_leaf_projection(
    row: dict[str, Any],
    repaired_text: str,
    start: int,
    end: int,
) -> tuple[str, dict[str, Any] | None]:
    raw_text = str(row.get("raw_text") if row.get("raw_text") is not None else repaired_text)
    if not repaired_text and start == end == 0 and _raw_mapping_complete(row, repaired_text):
        raw_start, raw_end = 0, len(raw_text)
    else:
        boundaries = _raw_boundary_map(row, repaired_text)
        if boundaries is None or not (0 <= start <= end < len(boundaries)):
            return "", None
        raw_start, raw_end = boundaries[start], boundaries[end]
    return raw_text[raw_start:raw_end], {
        "block_id": str(row.get("block_id") or row.get("table_block_id") or ""),
        "start": raw_start,
        "end": raw_end,
        "position_basis": "raw_text",
    }


def _region_evidence(
    row: dict[str, Any],
    *,
    locator: dict[str, Any],
    raw_locator: dict[str, Any] | None,
) -> dict[str, Any]:
    pdf_regions = [dict(value) for value in (row.get("pdf_regions") or [])
                   if isinstance(value, dict)]
    declared_format = str(row.get("source_format") or "")
    source_format = (
        declared_format
        if declared_format in {"pdf", "docx", "xlsx"}
        else ("pdf" if pdf_regions or row.get("page_number") is not None else "docx")
    )
    return {
        "source_format": source_format,
        "block_id": str(locator.get("block_id") or row.get("block_id") or ""),
        "block_order": int(row.get("order") or 0),
        "block_type": str(row.get("type") or ""),
        "style": str(row.get("style") or ""),
        "page_number": row.get("page_number"),
        "repaired_start": locator.get("start"),
        "repaired_end": locator.get("end"),
        "raw_start": raw_locator.get("start") if raw_locator else None,
        "raw_end": raw_locator.get("end") if raw_locator else None,
        "pdf_regions": pdf_regions,
    }


def _region_source_for_span(block: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    source = dict(block)
    member_regions: list[dict[str, Any]] = []
    for member in block.get("list_items") or []:
        if not isinstance(member, dict):
            continue
        locator = member.get("locator") if isinstance(member.get("locator"), dict) else {}
        member_start = locator.get("start")
        member_end = locator.get("end")
        if not isinstance(member_start, int) or not isinstance(member_end, int):
            continue
        if member_start < end and start < member_end:
            member_regions.extend(
                dict(value) for value in (member.get("pdf_regions") or [])
                if isinstance(value, dict)
            )
    if member_regions:
        source["pdf_regions"] = member_regions
    return source


def _list_members(block: dict[str, Any]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for member in block.get("list_items") or []:
        if not isinstance(member, dict) or not str(member.get("block_id") or ""):
            continue
        locator = member.get("locator") if isinstance(member.get("locator"), dict) else None
        raw_locator = (
            member.get("raw_locator")
            if isinstance(member.get("raw_locator"), dict)
            else None
        )
        members.append({
            "block_id": str(member["block_id"]),
            "role": "intro" if member.get("role") == "intro" else "item",
            "locator": dict(locator) if locator is not None else None,
            "raw_locator": dict(raw_locator) if raw_locator is not None else None,
        })
    return members


def _member_role_for_span(
    members: list[dict[str, Any]],
    start: int,
    end: int,
) -> str | None:
    for member in members:
        locator = member.get("locator")
        if not isinstance(locator, dict):
            continue
        member_start = locator.get("start")
        member_end = locator.get("end")
        if (type(member_start) is int and type(member_end) is int
                and member_start == start and member_end <= end):
            return str(member["role"])
    return None


def _page_band(block: dict[str, Any]) -> str | None:
    regions = block.get("pdf_regions") or []
    if not regions or not isinstance(regions[0], dict):
        return None
    region = regions[0]
    bbox = region.get("bbox") or []
    try:
        top, bottom = float(bbox[1]), float(bbox[3])
        height = float(region.get("page_height") or 0)
    except (IndexError, TypeError, ValueError):
        return None
    if height <= 0:
        return None
    center = ((top + bottom) / 2) / height
    if center <= 0.18:
        return "top"
    if center >= 0.82:
        return "bottom"
    return f"fixed:{center:.2f}"


def _proven_page_furniture_ids(blocks: list[dict[str, Any]]) -> set[str]:
    occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        text = str(block.get("text") or "")
        band = _page_band(block)
        if not block.get("noise") or not band or not text.strip() or len(text) > 120:
            continue
        occurrences[(_normalized_text(text), band)].append(block)
    proven: set[str] = set()
    for rows in occurrences.values():
        pages = {str(row.get("page_number") or "") for row in rows if row.get("page_number") is not None}
        if len(pages) < PAGE_FURNITURE_MIN_PAGES:
            continue
        proven.update(str(row.get("block_id") or "") for row in rows)
    return proven


def _ordered_fields(item: dict[str, Any], headers: Iterable[object]) -> list[tuple[str, str]]:
    fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for header in headers:
        key = str(header)
        if key in fields:
            ordered.append((key, str(fields[key] or "")))
            seen.add(key)
    for key, value in fields.items():
        key_text = str(key)
        if key_text not in seen:
            ordered.append((key_text, str(value or "")))
    return ordered


def _table_row_text(fields: list[tuple[str, str]]) -> str:
    return " | ".join(f"{key}={value}" for key, value in fields)


def _table_is_incomplete(block: dict[str, Any]) -> bool:
    if any(block.get(key) for key in (
        "parse_incomplete", "parser_incomplete", "is_truncated", "rows_truncated",
    )):
        return True
    declared_rows = int(block.get("rows") or 0)
    header_rows = int(
        block.get("header_row_count")
        if block.get("header_row_count") is not None
        else 1 if block.get("headers") else 0
    )
    # table-structure-v2 起 block.rows 含标题行；期望数据行数须扣除标题区
    title_rows = len(block.get("title_row_indexes") or [])
    data_rows = block.get("data_rows")
    if isinstance(data_rows, list):
        expected_data_rows = max(0, declared_rows - header_rows - title_rows)
        if declared_rows and len(data_rows) < expected_data_rows:
            return True
        if data_rows:
            return False

        # An empty structured row list is trustworthy only when the rendered
        # table contains no text beyond its declared header cells.
        rendered_text = _normalized_text(block.get("text"))
        rendered_headers = _normalized_text(
            " | ".join(str(value or "") for value in (block.get("headers") or []))
        )
        return bool(rendered_text and rendered_text != rendered_headers)
    return bool(
        block.get("text_truncated")
        or len(str(block.get("text") or "")) >= 5000
        or declared_rows > header_rows
    )


def _fallback_fragments(block: dict[str, Any]) -> list[dict[str, Any]]:
    rows = block.get("data_rows")
    if not isinstance(rows, list):
        return []
    fragments: list[dict[str, Any]] = []
    base_row = int(block.get("header_row_count") or 0)
    for offset, raw_row in enumerate(rows):
        values = raw_row if isinstance(raw_row, list) else [raw_row]
        rendered = " | ".join(str(value or "") for value in values)
        if not rendered.strip():
            continue
        row_index = base_row + offset
        if len(rendered) <= TABLE_FALLBACK_MAX_CHARS:
            fragments.append({
                "row_index": row_index,
                "column_index": None,
                "fragment_index": 0,
                "split_method": "row",
                "text": rendered,
            })
            continue

        fragment_index = 0
        for column_index, raw_value in enumerate(values):
            value = str(raw_value or "")
            if not value:
                continue
            if len(value) <= TABLE_FALLBACK_MAX_CHARS:
                pieces = [(value, "cell")]
            else:
                pieces: list[tuple[str, str]] = []
                for start, end in _sentence_spans(value):
                    sentence = value[start:end]
                    if len(sentence) <= TABLE_FALLBACK_MAX_CHARS:
                        pieces.append((sentence, "sentence"))
                    else:
                        pieces.extend(
                            (sentence[index:index + TABLE_FALLBACK_MAX_CHARS], "window")
                            for index in range(0, len(sentence), TABLE_FALLBACK_MAX_CHARS)
                        )
            for piece, split_method in pieces:
                fragments.append({
                    "row_index": row_index,
                    "column_index": column_index,
                    "fragment_index": fragment_index,
                    "split_method": split_method,
                    "text": piece,
                })
                fragment_index += 1
    return fragments


def _group_fallback_fragments(block: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if not current:
            return
        row_indexes = [int(item["row_index"]) for item in current]
        groups.append({
            "text": "\n".join(str(item["text"]) for item in current),
            "row_start": min(row_indexes),
            "row_end": max(row_indexes) + 1,
            "fragments": [{
                "row_index": item["row_index"],
                "column_index": item.get("column_index"),
                "fragment_index": item["fragment_index"],
                "split_method": item.get("split_method", "row"),
            } for item in current],
        })
        current, current_length = [], 0

    for fragment in _fallback_fragments(block):
        candidate_length = current_length + (1 if current else 0) + len(fragment["text"])
        row_count = len({int(item["row_index"]) for item in [*current, fragment]})
        if current and (candidate_length > TABLE_FALLBACK_MAX_CHARS
                        or row_count > TABLE_FALLBACK_MAX_ROWS):
            flush()
            candidate_length = len(fragment["text"])
        current.append(fragment)
        current_length = candidate_length
    flush()
    return groups


def _source_alignment_lineage(
    block: dict[str, Any],
    locator: dict[str, Any],
    raw_locator: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if raw_locator is None:
        return None
    block_id = str(block.get("block_id") or block.get("table_block_id") or "")
    raw_text = str(block.get("raw_text") if block.get("raw_text") is not None
                   else block.get("text") or "")
    repaired_text = str(block.get("text") or "")
    raw_start, raw_end = raw_locator.get("start"), raw_locator.get("end")
    repaired_start, repaired_end = locator.get("start"), locator.get("end")
    alignment = block.get("source_alignment")
    if (isinstance(alignment, dict)
            and all(type(value) is int for value in (
                raw_start, raw_end, repaired_start, repaired_end,
            ))):
        try:
            from source_spans import validate_source_alignment

            validate_source_alignment(raw_text, repaired_text, alignment)
        except (TypeError, ValueError):
            return None
        opcode_refs: list[dict[str, Any]] = []
        for index, opcode in enumerate(alignment.get("opcodes") or []):
            parent_raw_start = int(opcode["raw_start"])
            parent_raw_end = int(opcode["raw_end"])
            parent_repaired_start = int(opcode["repaired_start"])
            parent_repaired_end = int(opcode["repaired_end"])
            raw_overlap = (
                raw_start <= parent_raw_start <= raw_end
                if parent_raw_start == parent_raw_end
                else max(raw_start, parent_raw_start) < min(raw_end, parent_raw_end)
            )
            repaired_overlap = (
                repaired_start <= parent_repaired_start <= repaired_end
                if parent_repaired_start == parent_repaired_end
                else max(repaired_start, parent_repaired_start)
                < min(repaired_end, parent_repaired_end)
            )
            if raw_overlap or repaired_overlap:
                opcode_refs.append({"opcode_index": index, **dict(opcode)})
        return {
            "schema": "claim-source-alignment-lineage/v1",
            "kind": "parent_alignment",
            "parent_block_id": block_id,
            "parent_alignment_version": str(alignment.get("version") or ""),
            "parent_alignment_fingerprint": _sha256_bytes(_canonical_bytes(alignment)),
            "parent_raw_sha256": str(alignment.get("raw_sha256") or ""),
            "parent_repaired_sha256": str(alignment.get("repaired_sha256") or ""),
            "parent_raw_start": raw_start,
            "parent_raw_end": raw_end,
            "parent_repaired_start": repaired_start,
            "parent_repaired_end": repaired_end,
            "parent_opcode_refs": opcode_refs,
        }

    kind = (
        "canonical_projection"
        if raw_locator.get("position_basis") == "canonical_table_cells"
        else "legacy_identity"
    )
    payload = {
        "kind": kind,
        "block_id": block_id,
        "raw_sha256": _sha256_bytes(raw_text.encode("utf-8")),
        "repaired_sha256": _sha256_bytes(repaired_text.encode("utf-8")),
    }
    return {
        "schema": "claim-source-alignment-lineage/v1",
        "kind": kind,
        "parent_block_id": block_id,
        "parent_alignment_version": "legacy-identity-v1" if kind == "legacy_identity"
        else "canonical-table-cells-v1",
        "parent_alignment_fingerprint": _sha256_bytes(_canonical_bytes(payload)),
        "parent_raw_sha256": payload["raw_sha256"],
        "parent_repaired_sha256": payload["repaired_sha256"],
        "parent_raw_start": raw_start if type(raw_start) is int else None,
        "parent_raw_end": raw_end if type(raw_end) is int else None,
        "parent_repaired_start": repaired_start if type(repaired_start) is int else None,
        "parent_repaired_end": repaired_end if type(repaired_end) is int else None,
        "parent_opcode_refs": [],
    }


def _base_leaf(
    block: dict[str, Any],
    *,
    source_kind: str,
    text: str,
    locator: dict[str, Any],
    eligibility: str = "claim",
    exclusion: dict[str, Any] | None = None,
    raw_text: str | None = None,
    raw_locator: dict[str, Any] | None = None,
    region_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_value = str(raw_text if raw_text is not None else text)
    parent_alignment = block.get("source_alignment")
    repair_provenance = (
        dict(parent_alignment.get("repair_provenance"))
        if isinstance(parent_alignment, dict)
        and isinstance(parent_alignment.get("repair_provenance"), dict)
        else None
    )
    alignment_fields = (
        source_alignment_fields(
            raw_value,
            text,
            repair_provenance=repair_provenance,
        )
        if raw_locator is not None else None
    )
    declared_repair_version = str(block.get("text_repair_version") or "")
    if raw_value == text:
        text_repair_version = declared_repair_version or "identity-v1"
    elif declared_repair_version and declared_repair_version != "identity-v1":
        text_repair_version = declared_repair_version
    elif repair_provenance is not None:
        text_repair_version = str(
            repair_provenance.get("producer_version") or "unproven-repair-v1"
        )
    elif alignment_fields is not None and all(
        opcode.get("tag") == "equal"
        or opcode.get("transformation", {}).get("allowed") is True
        for opcode in alignment_fields["source_alignment"]["opcodes"]
    ):
        text_repair_version = SOURCE_TEXT_NORMALIZATION_VERSION
    else:
        text_repair_version = "unproven-repair-v1"
    leaf: dict[str, Any] = {
        "source_kind": source_kind,
        "locator": locator,
        "text": text,
        "raw_text": raw_value,
        "raw_locator": raw_locator,
        "raw_mapping_status": "mapped" if raw_locator is not None else "unavailable",
        "text_repair_version": text_repair_version,
        "section_path": [str(value) for value in (block.get("section_path") or [])],
        "source_order": int(block.get("order") or 0),
        "eligibility": eligibility,
        "exclusion": exclusion,
        "region_evidence": _region_evidence(
            region_source or block,
            locator=locator,
            raw_locator=raw_locator,
        ),
    }
    if raw_locator is not None:
        leaf.update(alignment_fields or {})
        leaf["source_alignment_lineage"] = _source_alignment_lineage(
            block, locator, raw_locator,
        )
    else:
        leaf["source_alignment"] = None
        leaf["raw_to_repaired_spans"] = []
        leaf["source_alignment_lineage"] = None
    return leaf


def _block_locator(block: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    return {
        "block_id": str(block.get("block_id") or ""),
        "line": None,
        "start": start,
        "end": end,
        "position_basis": "repaired_text",
        "table_item_id": None,
        "row_index": None,
    }


def _leaf_locator_key(row: dict[str, Any]) -> str:
    return json.dumps(row.get("locator") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _enumerate_leaves(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    table_cell_items: list[dict[str, Any]] | None = None,
    catalog_version: str = CLAIM_CATALOG_VERSION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int], str]:
    leaves: list[dict[str, Any]] = []
    container_mappings: list[dict[str, Any]] = []
    audit = {
        "unmapped_source_span_count": 0,
        "unmapped_raw_span_count": 0,
        "overlapping_raw_span_count": 0,
        "overlapping_leaf_span_count": 0,
        "parse_incomplete_count": 0,
        "parent_child_duplicate_count": 0,
        "orphan_table_item_count": 0,
        "multi_consumed_table_item_count": 0,
        "non_table_parent_item_count": 0,
        # table-structure-v2 单元格闭环审计（全部 hard-fail）
        "unconsumed_table_cell_count": 0,
        "multi_consumed_table_cell_count": 0,
        "dangling_table_item_reference_count": 0,
        "dangling_table_cell_reference_count": 0,
        "normative_context_only_count": 0,
        "orphan_table_cell_count": 0,
        "duplicate_table_cell_id_count": 0,
        # table-structure-v3 内容保全审计（informational，非 hard-fail）：
        # 弱信号说明句/无信号数据格落入 context = 内容从 claim 面消失——
        # 计数如实暴露并联动 needs_review，绝不呈现"零计数=ok"假象
        "weak_signal_context_cell_count": 0,
        "unsignaled_data_cell_count": 0,
        # table-structure-v4（P0-5 复审）：无结构证据的单格"标题/表头"格——
        # 可定位的歧义资格候选，计数如实暴露并联动 needs_review
        "ambiguous_structure_cell_count": 0,
        "untyped_colon_spec_cell_count": 0,
    }
    structure_status = "ok"
    items_by_block: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in table_items:
        items_by_block[str(item.get("table_block_id") or "")].append(item)
    for items in items_by_block.values():
        items.sort(key=lambda item: (int(item.get("row_index") or 0), str(item.get("item_id") or "")))
    cells_by_block: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    seen_cell_ids: set[str] = set()
    duplicate_cell_ids = 0
    for cell in table_cell_items or []:
        cell_id = str(cell.get("cell_id") or "")
        if cell_id and cell_id in seen_cell_ids:
            duplicate_cell_ids += 1
            continue  # 重复 cell_id 不覆盖先到的 canonical cell，但必须入账
        if cell_id:
            seen_cell_ids.add(cell_id)
        cells_by_block[str(cell.get("table_block_id") or "")][cell_id] = cell
    audit["duplicate_table_cell_id_count"] = duplicate_cell_ids
    table_item_consumers: dict[str, int] = defaultdict(int)
    block_types: dict[str, set[str]] = defaultdict(set)
    for block in blocks:
        block_types[str(block.get("block_id") or "")].add(str(block.get("type") or "other"))

    furniture_ids = _proven_page_furniture_ids(blocks)
    for block in sorted(blocks, key=lambda row: (int(row.get("order") or 0), str(row.get("block_id") or ""))):
        block_id = str(block.get("block_id") or "")
        block_type = str(block.get("type") or "other")
        text = str(block.get("text") or "")

        if block_type == "table" and str(block.get("table_structure_version") or "") == TABLE_STRUCTURE_VERSION:
            # ---- table-structure-v2：leaf plan 唯一 owner 闭环 --------------------
            if str(block.get("header_detection_status") or "") == "ambiguous":
                structure_status = "needs_review"
            if str(block.get("merge_evidence_status") or "") in {
                "dropped_conflict",
                "dropped_text_conflict",
            }:
                # 合并证据自相矛盾/覆盖异文被降级（保留全部文本与全部格）——结构进审核
                structure_status = "needs_review"
            leaf_plan = block.get("leaf_plan") if isinstance(block.get("leaf_plan"), dict) else {}
            weak_signal_count = len(leaf_plan.get("weak_signal_cells") or [])
            unsignaled_count = len(leaf_plan.get("unsignaled_data_cells") or [])
            if weak_signal_count or unsignaled_count:
                # B5 第三维如实暴露：弱信号说明句/无信号数据格未进 claim 面——
                # 不计 hard-fail（内容原文仍在 context/行文本中保留），但必须
                # 计数并联动 needs_review，"零计数 ok"不得掩盖未知内容
                audit["weak_signal_context_cell_count"] += weak_signal_count
                audit["unsignaled_data_cell_count"] += unsignaled_count
                structure_status = "needs_review"
            ambiguous_structure_count = len(leaf_plan.get("ambiguous_structure_cells") or [])
            if ambiguous_structure_count:
                # P0-5：无结构证据的单格"标题/表头"内容格——可定位的歧义资格
                # 候选；计数 + needs_review，"0 claim + 审计全零 + ok"不得再现
                audit["ambiguous_structure_cell_count"] += ambiguous_structure_count
                structure_status = "needs_review"
            untyped_colon_spec_count = len(
                leaf_plan.get("untyped_colon_spec_cells") or []
            )
            if untyped_colon_spec_count:
                audit["untyped_colon_spec_cell_count"] += untyped_colon_spec_count
                structure_status = "needs_review"
            if block.get("matrix_rejected_marker_columns"):
                # B3/B4：marker 占多数但表头不是能力维度的列——X 以原文保留、
                # 不合成义务、不成 cell leaf；"3 个裸 X claim 且审计全绿"的反例
                # 不得再现：拒收列存在即结构待审
                structure_status = "needs_review"
            row_leaf_indexes = {int(value) for value in (leaf_plan.get("row_leaves") or [])}
            cell_leaf_ids = [str(value) for value in (leaf_plan.get("cell_leaves") or [])]
            context_cell_ids = [str(value) for value in (leaf_plan.get("context_cells") or [])]
            cell_leaf_id_set = set(cell_leaf_ids)
            context_cell_id_set = set(context_cell_ids)
            ambiguous_candidate_ids = {
                str(value)
                for value in (leaf_plan.get("ambiguous_structure_cells") or [])
            }
            weak_signal_candidate_ids = {
                str(value)
                for value in (leaf_plan.get("weak_signal_cells") or [])
            }
            unsignaled_candidate_ids = {
                str(value)
                for value in (leaf_plan.get("unsignaled_data_cells") or [])
            }
            untyped_colon_candidate_ids = {
                str(value)
                for value in (leaf_plan.get("untyped_colon_spec_cells") or [])
            }
            rejected_marker_columns = {
                int(value)
                for value in (block.get("matrix_rejected_marker_columns") or [])
            }
            rejected_marker_candidate_ids = {
                str(cell_id)
                for cell_id, cell in cells_by_block.get(block_id, {}).items()
                if (
                    str(cell.get("structural_role") or "") == "data"
                    and int(cell.get("column_index") or 0) - 1
                    in rejected_marker_columns
                    and is_positive_marker(str(cell.get("text") or ""))
                )
            }
            # A cell already admitted as a claim is directly reviewable and must
            # not gain a second, excluded catalog identity. The remaining weak
            # cells are materialized as default-excluded review candidates.
            review_candidate_ids = (
                ambiguous_candidate_ids
                | weak_signal_candidate_ids
                | unsignaled_candidate_ids
                | untyped_colon_candidate_ids
                | rejected_marker_candidate_ids
            ) - cell_leaf_id_set
            block_cells = cells_by_block.get(block_id, {})
            table_rows = items_by_block.get(block_id, [])
            mapping = {"container_block_id": block_id, "kind": "table", "leaf_locator_keys": []}
            if _table_is_incomplete(block):
                audit["parse_incomplete_count"] += 1
                mapping.update({
                    "parse_incomplete": True,
                    "reason": str(
                        (block.get("parse_incomplete_reason") or {}).get("code")
                        if isinstance(block.get("parse_incomplete_reason"), dict)
                        else "complete_table_rows_unavailable"
                    ),
                    "parse_incomplete_reason": block.get("parse_incomplete_reason"),
                })
            if table_rows:
                table_item_consumers[block_id] += 1
            headers = [str(value) for value in (block.get("headers") or [])]
            # 组合表（mixed）：只有真正成为 cell leaf 的事实格才按 (row, column)
            # 坐标从行文本剔除——marker 格由 cell claim 闭环，同一物理内容只有一个
            # owner。事实列中的非 marker 文本格（"optional"/"see note"）不是 cell
            # leaf，必须保留在 row claim；按整列剔除会让该格零 owner 消失，而旧
            # 消费审计只查"行在 row_leaf_indexes"坐标即计消费（2026-08-03 清单 I4：
            # `Voltage|230 V|required|optional` 的 optional 无 owner 且审计全零
            # 假通过）。stored matrix_fact_columns 缺失时不再重推导事实列——
            # 坐标剔除只消费 leaf plan 的真实 cell leaf，重推导只会重新引入整列口径。
            fact_leaf_fields: dict[int, set[str]] = {}
            if row_leaf_indexes and cell_leaf_id_set:
                for cell_id in cell_leaf_id_set:
                    fact_cell = block_cells.get(cell_id)
                    if fact_cell is None:
                        continue
                    fact_row = int(fact_cell.get("row_index") or 0)
                    fact_column = int(fact_cell.get("column_index") or 0)
                    if fact_row in row_leaf_indexes and 1 <= fact_column <= len(headers):
                        fact_leaf_fields.setdefault(fact_row, set()).add(
                            headers[fact_column - 1]
                        )
            # 多义务格（同格 ≥2 条独立规范性句）按 (行, 列) 逐格排除出行文本——
            # 该格由按句 cell claim 闭环，行仍 own 其余字段（不株连整列）
            multi_duty_fields: dict[int, set[str]] = {}
            for cell_id in (leaf_plan.get("multi_duty_cells") or []):
                duty_cell = block_cells.get(str(cell_id))
                if duty_cell is None:
                    continue
                duty_row = int(duty_cell.get("row_index") or 0)
                duty_column = int(duty_cell.get("column_index") or 0)
                if duty_row and 1 <= duty_column <= len(headers):
                    multi_duty_fields.setdefault(duty_row, set()).add(headers[duty_column - 1])
            review_candidate_fields: dict[int, set[str]] = {}
            for cell_id in review_candidate_ids:
                candidate_cell = block_cells.get(cell_id)
                if candidate_cell is None:
                    continue
                candidate_row = int(candidate_cell.get("row_index") or 0)
                candidate_column = int(candidate_cell.get("column_index") or 0)
                if candidate_row and 1 <= candidate_column <= len(headers):
                    review_candidate_fields.setdefault(candidate_row, set()).add(
                        headers[candidate_column - 1]
                    )
            item_rows = {int(item.get("row_index") or 0) for item in table_rows}
            for row_index in sorted(row_leaf_indexes):
                if row_index not in item_rows:
                    audit["dangling_table_item_reference_count"] += 1
            for item in table_rows:
                item_row_index = int(item.get("row_index") or 0)
                if item_row_index not in row_leaf_indexes:
                    continue  # cell/mixed 模式中的行仅作容器，不生成重复父 claim
                excluded_names = (
                    fact_leaf_fields.get(item_row_index, set())
                    | multi_duty_fields.get(item_row_index, set())
                    | review_candidate_fields.get(item_row_index, set())
                )
                ordered = [
                    (key, value) for key, value in _ordered_fields(item, headers)
                    if key not in excluded_names
                ]
                row_text = _table_row_text(ordered)
                locator = {
                    "block_id": block_id,
                    "line": None,
                    "start": None,
                    "end": None,
                    "position_basis": "table_item_fields",
                    "table_item_id": str(item.get("item_id") or ""),
                    "row_index": int(item.get("row_index") or 0),
                }
                item_text = str(item.get("text") or row_text)
                if excluded_names:
                    # trimmed claim 文本需要同口径 raw 投影（剔除事实列/多义务格后的 raw 行）
                    raw_fields = item.get("raw_fields") if isinstance(item.get("raw_fields"), dict) else {}
                    raw_trimmed = " | ".join(
                        f"{key}={str(raw_fields.get(key) or '')}" for key, _value in ordered
                    )
                    alignment = source_alignment_fields(raw_trimmed, row_text)
                    shim = {
                        "raw_text": raw_trimmed,
                        "source_alignment": alignment.get("source_alignment"),
                        "raw_to_repaired_spans": alignment.get("raw_to_repaired_spans") or [],
                        "table_block_id": block_id,
                    }
                    raw_value, raw_locator = _raw_leaf_projection(shim, row_text, 0, len(row_text))
                else:
                    raw_value, raw_locator = _raw_leaf_projection(
                        item,
                        item_text,
                        0,
                        len(item_text),
                    )
                if raw_locator is None:
                    audit["unmapped_raw_span_count"] += 1
                region_source = {**block, **{
                    key: value for key, value in item.items()
                    if key in {"page_number", "pdf_regions"}
                }}
                leaf = _base_leaf(
                    item,
                    source_kind="table_row",
                    text=row_text,
                    locator=locator,
                    raw_text=raw_value,
                    raw_locator=raw_locator,
                    region_source=region_source,
                )
                leaf["table_context"] = {
                    "headers": headers,
                    "fields": [{"name": key, "value": value} for key, value in ordered],
                    "table_title": str(block.get("table_title") or ""),
                }
                leaf["source_order"] = int(block.get("order") or 0)
                leaves.append(leaf)
                mapping["leaf_locator_keys"].append(_leaf_locator_key(leaf))
            for cell_id in cell_leaf_ids:
                cell = block_cells.get(cell_id)
                if cell is None:
                    audit["dangling_table_cell_reference_count"] += 1
                    continue
                for leaf in _table_cell_leaves(block, cell, headers, catalog_version=catalog_version):
                    leaves.append(leaf)
                    mapping["leaf_locator_keys"].append(_leaf_locator_key(leaf))
            for cell_id in sorted(review_candidate_ids):
                cell = block_cells.get(cell_id)
                if cell is None:
                    audit["dangling_table_cell_reference_count"] += 1
                    continue
                if cell_id in untyped_colon_candidate_ids:
                    candidate_reason = "untyped_colon_spec_cell"
                elif cell_id in ambiguous_candidate_ids:
                    candidate_reason = "ambiguous_table_structure"
                elif cell_id in weak_signal_candidate_ids:
                    candidate_reason = "weak_signal_table_cell"
                elif cell_id in rejected_marker_candidate_ids:
                    candidate_reason = "rejected_matrix_marker_cell"
                else:
                    candidate_reason = "unsignaled_table_cell"
                leaf = _table_cell_review_candidate_leaf(
                    block,
                    cell,
                    headers,
                    reason=candidate_reason,
                    catalog_version=catalog_version,
                )
                if leaf is None:
                    audit["dangling_table_cell_reference_count"] += 1
                    continue
                leaves.append(leaf)
                mapping["leaf_locator_keys"].append(_leaf_locator_key(leaf))
            for cell_id in context_cell_ids:
                cell = block_cells.get(cell_id)
                if cell is None:
                    continue
                if cell_id in review_candidate_ids:
                    continue
                cell_text = str(cell.get("text") or "")
                # 裸 marker 词（"Required"/"X"）是矩阵记号不是义务——粒度规划
                # 刻意路由为 context（同 normative_context_only 不互斥的同口径）；
                # 其余规范性内容被路由成纯 context = 静默丢失，hard-fail。
                # 标题/表头位的冒号规格/短标签（"xDLMS Service: GET" 服务名）是
                # 维度名，刻意作 context——只有句子型规范性内容才算静默丢失
                if is_positive_marker(cell_text):
                    continue
                role = str(cell.get("structural_role") or "data")
                if role in {"title", "header"}:
                    if row_bears_normative_sentence([cell_text]):
                        audit["normative_context_only_count"] += 1
                elif is_normative_text(cell_text):
                    audit["normative_context_only_count"] += 1
            # 每个非空 canonical cell 恰好被消费一次（cell leaf 优先于行 ownership：
            # mixed 组合表的 marker 格由 cell claim 闭环，不再计入行消费）
            for cell_id, cell in block_cells.items():
                consumed = 0
                if cell_id in review_candidate_ids:
                    consumed += 1
                elif cell_id in cell_leaf_id_set:
                    consumed += 1
                elif cell_id in context_cell_id_set:
                    consumed += 1
                elif int(cell.get("row_index") or 0) in row_leaf_indexes:
                    # 坐标落在 row leaf 内 ≠ 文本确实进入 row claim：被逐格剔除
                    # （cell leaf/多义务格/审查候选）的格必须另有 owner，否则是零
                    # owner 静默丢失——审计不得靠坐标假通过（I4 封堵）
                    cell_row = int(cell.get("row_index") or 0)
                    cell_column = int(cell.get("column_index") or 0)
                    header_name = (
                        headers[cell_column - 1]
                        if 1 <= cell_column <= len(headers)
                        else None
                    )
                    row_excluded_names = (
                        fact_leaf_fields.get(cell_row, set())
                        | multi_duty_fields.get(cell_row, set())
                        | review_candidate_fields.get(cell_row, set())
                    )
                    if header_name is not None and header_name not in row_excluded_names:
                        consumed += 1
                if consumed == 0:
                    audit["unconsumed_table_cell_count"] += 1
                elif consumed > 1:
                    audit["multi_consumed_table_cell_count"] += 1
            container_mappings.append(mapping)
            continue

        if block_type == "table":
            # 旧产物（无 table-structure-v2 证据）：行级遗留路径，禁止伪造迁移
            structure_status = "base_migration_required"
            table_rows = items_by_block.get(block_id, [])
            mapping = {"container_block_id": block_id, "kind": "table", "leaf_locator_keys": []}
            if _table_is_incomplete(block):
                audit["parse_incomplete_count"] += 1
                mapping.update({
                    "parse_incomplete": True,
                    "reason": str(
                        (block.get("parse_incomplete_reason") or {}).get("code")
                        if isinstance(block.get("parse_incomplete_reason"), dict)
                        else "complete_table_rows_unavailable"
                    ),
                    "parse_incomplete_reason": block.get("parse_incomplete_reason"),
                })
            if table_rows:
                table_item_consumers[block_id] += 1
                headers = [str(value) for value in (block.get("headers") or [])]
                for item in table_rows:
                    ordered = _ordered_fields(item, headers)
                    row_text = _table_row_text(ordered)
                    locator = {
                        "block_id": block_id,
                        "line": None,
                        "start": None,
                        "end": None,
                        "position_basis": "table_item_fields",
                        "table_item_id": str(item.get("item_id") or ""),
                        "row_index": int(item.get("row_index") or 0),
                    }
                    item_text = str(item.get("text") or row_text)
                    raw_value, raw_locator = _raw_leaf_projection(
                        item,
                        item_text,
                        0,
                        len(item_text),
                    )
                    if raw_locator is None:
                        audit["unmapped_raw_span_count"] += 1
                    region_source = {**block, **{
                        key: value for key, value in item.items()
                        if key in {"page_number", "pdf_regions"}
                    }}
                    leaf = _base_leaf(
                        item,
                        source_kind="table_row",
                        text=row_text,
                        locator=locator,
                        raw_text=raw_value,
                        raw_locator=raw_locator,
                        region_source=region_source,
                    )
                    leaf["table_context"] = {
                        "headers": headers,
                        "fields": [{"name": key, "value": value} for key, value in ordered],
                        "table_title": str(block.get("table_title") or ""),
                    }
                    leaf["source_order"] = int(block.get("order") or 0)
                    leaves.append(leaf)
                    mapping["leaf_locator_keys"].append(_leaf_locator_key(leaf))
                container_mappings.append(mapping)
                continue

            if mapping.get("parse_incomplete"):
                container_mappings.append({
                    **mapping,
                })
                continue
            fallback_groups = _group_fallback_fragments(block)
            if not table_rows and not fallback_groups:
                # 遗留空表格（无结构化行、无截断）但有超表头正文：整块作为一个 table_fallback
                # 叶子——此前既不产叶子也不记 parse_incomplete，块文本游离出保全账本；
                # 仅表头文本不产叶子（与 _table_is_incomplete 的 header-only 判定同口径）
                rendered = str(block.get("text") or "").strip()
                rendered_headers = _normalized_text(
                    " | ".join(str(value or "") for value in (block.get("headers") or []))
                )
                has_body = bool(rendered) and _normalized_text(rendered) != rendered_headers
                if has_body and len(rendered) < TABLE_FALLBACK_MAX_CHARS:
                    fallback_groups = [{
                        "text": rendered,
                        "fragments": [rendered],
                        "row_start": None,
                        "row_end": None,
                    }]
                elif has_body:
                    audit["parse_incomplete_count"] += 1
                    mapping.update({
                        "parse_incomplete": True,
                        "reason": "legacy_table_without_rows",
                        "parse_incomplete_reason": {"code": "legacy_table_without_rows"},
                    })
            for index, group in enumerate(fallback_groups):
                locator = {
                    "block_id": block_id,
                    "line": None,
                    "start": None,
                    "end": None,
                    "position_basis": "table_data_rows",
                    "table_item_id": None,
                    "row_index": None,
                    "row_start": group["row_start"],
                    "row_end": group["row_end"],
                    "fallback_group_id": f"{block_id}-FB-{index + 1:04d}",
                }
                leaf = _base_leaf(
                    block,
                    source_kind="table_fallback",
                    text=str(group["text"]),
                    locator=locator,
                    raw_text=str(group["text"]),
                    raw_locator={
                        "block_id": block_id,
                        "start": None,
                        "end": None,
                        "position_basis": "canonical_table_cells",
                        "row_start": group["row_start"],
                        "row_end": group["row_end"],
                    },
                )
                leaf["table_context"] = {
                    "headers": [str(value) for value in (block.get("headers") or [])],
                    "fragments": group["fragments"],
                }
                leaves.append(leaf)
                mapping["leaf_locator_keys"].append(_leaf_locator_key(leaf))
            container_mappings.append(mapping)
            continue

        raw_mapping_complete = _raw_mapping_complete(block, text)
        if not raw_mapping_complete:
            audit["unmapped_raw_span_count"] += 1

        if not text.strip():
            raw_value, raw_locator = _raw_leaf_projection(block, text, 0, len(text))
            leaves.append(_base_leaf(
                block,
                source_kind="other",
                text=text,
                locator=_block_locator(block, 0, len(text)),
                eligibility="excluded",
                exclusion={
                    "reason": "empty",
                    "rule_id": "catalog-empty",
                    "rule_version": catalog_version,
                    "evidence": {"text_length": len(text)},
                },
                raw_text=raw_value,
                raw_locator=raw_locator,
            ))
            continue

        structural_exclusion = block_id in furniture_ids
        if block_type in {"heading", "caption"}:
            spans = [(0, len(text))]
        elif _looks_like_list(text, block):
            spans = _line_spans(text)
        else:
            spans = _sentence_spans(text)

        list_members = _list_members(block)
        list_mapping: dict[str, Any] | None = None
        if _looks_like_list(text, block) and (
            len(spans) > 1
            or block.get("is_list_container")
            or block.get("list_coalesced")
            or list_members
        ):
            list_mapping = {
                "container_block_id": block_id,
                "kind": "list",
                "leaf_locator_keys": [],
                "members": list_members,
            }

        cursor = 0
        raw_cursor = 0
        for span_index, (start, end) in enumerate(spans):
            if start < cursor:
                audit["overlapping_leaf_span_count"] += 1
            elif start > cursor:
                audit["unmapped_source_span_count"] += 1
            cursor = max(cursor, end)
            if block_type == "heading":
                source_kind = "heading"
            elif block_type == "caption":
                source_kind = "caption"
            elif _looks_like_list(text, block):
                source_kind = "list_item"
            elif block.get("noise"):
                source_kind = "noise"
            elif block_type == "paragraph":
                source_kind = "paragraph_sentence"
            else:
                source_kind = "other"
            exclusion = None
            eligibility = "claim"
            if structural_exclusion:
                eligibility = "excluded"
                exclusion = {
                    "reason": "repeated_page_furniture",
                    "rule_id": "catalog-repeated-page-furniture",
                    "rule_version": catalog_version,
                    "evidence": {
                        "page_number": block.get("page_number"),
                        "position_band": _page_band(block),
                        "normalized_text_hash": _sha256_bytes(_normalized_text(text).encode("utf-8")),
                    },
                }
            raw_value, raw_locator = _raw_leaf_projection(block, text, start, end)
            if raw_mapping_complete and raw_locator is None:
                audit["unmapped_raw_span_count"] += 1
            if raw_locator is not None:
                raw_start = int(raw_locator["start"])
                if raw_start < raw_cursor:
                    audit["overlapping_raw_span_count"] += 1
                elif raw_start > raw_cursor:
                    audit["unmapped_raw_span_count"] += 1
                raw_cursor = max(raw_cursor, int(raw_locator["end"]))
            leaf = _base_leaf(
                block,
                source_kind=source_kind,
                text=text[start:end],
                locator=_block_locator(block, start, end),
                eligibility=eligibility,
                exclusion=exclusion,
                raw_text=raw_value,
                raw_locator=raw_locator,
                region_source=_region_source_for_span(block, start, end),
            )
            if source_kind == "list_item":
                stripped = text[start:end].strip()
                member_role = _member_role_for_span(list_members, start, end)
                leaf["list_role"] = member_role or (
                    "intro" if span_index == 0 and _LIST_INTRO_RE.fullmatch(stripped) else "item"
                )
            leaves.append(leaf)
            if list_mapping is not None:
                list_mapping["leaf_locator_keys"].append(_leaf_locator_key(leaf))
        if cursor < len(text):
            audit["unmapped_source_span_count"] += 1
        raw_length = len(str(block.get("raw_text") if block.get("raw_text") is not None else text))
        if raw_mapping_complete and raw_cursor < raw_length:
            audit["unmapped_raw_span_count"] += 1
        if list_mapping is not None:
            container_mappings.append(list_mapping)

    for leaf in leaves:
        leaf_text = str(leaf.get("text") or "")
        if (
            leaf.get("eligibility") == "claim"
            and leaf_text.strip()
            and not any(char.isalnum() for char in leaf_text)
        ):
            leaf["eligibility"] = "excluded"
            leaf["exclusion"] = {
                "reason": "separator_only",
                "rule_id": "catalog-separator-only",
                "rule_version": catalog_version,
                "evidence": {
                    "text_length": len(leaf_text),
                    "normalized_text_hash": _sha256_bytes(
                        _normalized_text(leaf_text).encode("utf-8")
                    ),
                },
            }
    for item_block_id, items in items_by_block.items():
        if not items:
            continue
        consumers = table_item_consumers.get(item_block_id, 0)
        if consumers > 1:
            audit["multi_consumed_table_item_count"] += len(items) * (consumers - 1)
        elif consumers == 0:
            if item_block_id in block_types:
                audit["non_table_parent_item_count"] += len(items)
            else:
                audit["orphan_table_item_count"] += len(items)
    # 孤立 cell：父块不存在或不是表格块——不得被 cells_by_block 静默吞掉
    for cell_block_id, cells in cells_by_block.items():
        if not cells:
            continue
        if cell_block_id not in block_types or "table" not in block_types[cell_block_id]:
            audit["orphan_table_cell_count"] += len(cells)
    return leaves, container_mappings, audit, structure_status


def _table_cell_leaves(
    block: dict[str, Any],
    cell: dict[str, Any],
    headers: list[str],
    *,
    catalog_version: str = CLAIM_CATALOG_VERSION,
    split_sentences: bool = True,
) -> list[dict[str, Any]]:
    """一个 cell leaf 的按句切分：同格两条独立义务生成两个 claim。

    locator.position_basis=table_cell_text，cell_start/end 是 cell 正文（修复后文本）
    内的半开区间；raw 投影经 cell 自身的 raw_text 对齐计算。每个 leaf 携带
    semantic_context（表标题+行头+列头+正文，确定性拼装）——裸格（如 "X"）
    对 verifier 没有语义，上下文是验证证据的一部分。"""
    block_id = str(block.get("block_id") or "")
    cell_id = str(cell.get("cell_id") or "")
    cell_text = str(cell.get("text") or "")
    raw_cell_text = str(cell.get("raw_text") if cell.get("raw_text") is not None else cell_text)
    alignment = source_alignment_fields(raw_cell_text, cell_text)
    shim = {
        "raw_text": raw_cell_text,
        "source_alignment": alignment.get("source_alignment"),
        "raw_to_repaired_spans": alignment.get("raw_to_repaired_spans") or [],
        "table_block_id": block_id,
    }
    from table_structure import cell_context_text

    full_context = cell_context_text(cell)
    context_prefix = full_context[: len(full_context) - len(cell_text)] if cell_text and full_context.endswith(cell_text) else ""
    spans = (
        (_sentence_spans(cell_text) or [(0, len(cell_text))])
        if split_sentences
        else [(0, len(cell_text))]
    )
    region_source = {**block}
    if cell.get("page_number") is not None:
        region_source["page_number"] = cell.get("page_number")
    leaves: list[dict[str, Any]] = []
    leaves_by_sentence: dict[str, dict[str, Any]] = {}
    for start, end in spans:
        sentence = cell_text[start:end]
        if not sentence.strip():
            continue
        # 同格内逐字节重复（含空白差）的句子只出一个 claim：DOCX 合并把两格
        # 文本拼进同一 tc，同句重复是拼接伪影，重复 claim 会制造孪生 open 行。
        # M4：被合并出现的全部别名 locator 必须保留在 span_aliases——合并 ≠
        # 抹除位置证据，审计/热区仍可定位每一次出现
        sentence_key = " ".join(sentence.split())
        if sentence_key in leaves_by_sentence:
            alias: dict[str, Any] = {"cell_start": start, "cell_end": end}
            _alias_raw, alias_raw_locator = _raw_leaf_projection(shim, cell_text, start, end)
            if alias_raw_locator is not None:
                alias_raw_locator["table_cell_id"] = cell_id
                alias_raw_locator["row_index"] = int(cell.get("row_index") or 0)
                alias_raw_locator["column_index"] = int(cell.get("column_index") or 0)
            alias["raw_locator"] = alias_raw_locator
            leaves_by_sentence[sentence_key]["span_aliases"].append(alias)
            continue
        locator = {
            "block_id": block_id,
            "line": None,
            "start": None,
            "end": None,
            "position_basis": "table_cell_text",
            "table_item_id": None,
            "row_index": int(cell.get("row_index") or 0),
            "table_cell_id": cell_id,
            "column_index": int(cell.get("column_index") or 0),
            "cell_start": start,
            "cell_end": end,
        }
        raw_value, raw_locator = _raw_leaf_projection(shim, cell_text, start, end)
        if raw_locator is not None:
            raw_locator["table_cell_id"] = cell_id
            raw_locator["row_index"] = int(cell.get("row_index") or 0)
            raw_locator["column_index"] = int(cell.get("column_index") or 0)
        leaf = _base_leaf(
            {**block, **cell},
            source_kind="table_cell",
            text=sentence,
            locator=locator,
            raw_text=raw_value,
            raw_locator=raw_locator,
            region_source=region_source,
        )
        leaf["table_context"] = {
            "headers": headers,
            "header_path": [str(value) for value in (cell.get("header_path") or [])],
            "row_header_context": [str(value) for value in (cell.get("row_header_context") or [])],
            "table_title": str(block.get("table_title") or cell.get("table_title") or ""),
            "structural_role": str(cell.get("structural_role") or "data"),
        }
        leaf["semantic_context"] = f"{context_prefix}{sentence}"
        leaf["source_order"] = int(block.get("order") or 0)
        leaf["span_aliases"] = []
        leaves_by_sentence[sentence_key] = leaf
        leaves.append(leaf)
    return leaves


_TABLE_CELL_REVIEW_RULES = {
    "ambiguous_table_structure": "catalog-ambiguous-table-structure",
    "weak_signal_table_cell": "catalog-weak-signal-table-cell",
    "unsignaled_table_cell": "catalog-unsignaled-table-cell",
    "rejected_matrix_marker_cell": "catalog-rejected-matrix-marker-cell",
    "untyped_colon_spec_cell": "catalog-untyped-colon-spec-cell",
}


def _table_cell_review_candidate_leaf(
    block: dict[str, Any],
    cell: dict[str, Any],
    headers: list[str],
    *,
    reason: str,
    catalog_version: str,
) -> dict[str, Any] | None:
    """Materialize one reviewable, default-excluded candidate per physical cell."""
    if reason not in _TABLE_CELL_REVIEW_RULES:
        raise ValueError(f"unsupported table-cell review reason: {reason}")
    leaves = _table_cell_leaves(
        block,
        cell,
        headers,
        catalog_version=catalog_version,
        split_sentences=False,
    )
    if not leaves:
        return None
    leaf = leaves[0]
    cell_text = str(cell.get("text") or "")
    block_id = str(block.get("block_id") or "")
    cell_id = str(cell.get("cell_id") or "")
    leaf["eligibility"] = "excluded"
    leaf["exclusion"] = {
        "reason": reason,
        "rule_id": _TABLE_CELL_REVIEW_RULES[reason],
        "rule_version": catalog_version,
        "evidence": {
            "table_structure_version": TABLE_STRUCTURE_VERSION,
            "table_block_id": block_id,
            "table_cell_id": cell_id,
            "row_index": int(cell.get("row_index") or 0),
            "column_index": int(cell.get("column_index") or 0),
            "cell_text_sha256": _sha256_bytes(cell_text.encode("utf-8")),
        },
    }
    return leaf


def _materialize_claim_identity(
    leaves: list[dict[str, Any]],
    *,
    document_generation_id: str,
    catalog_version: str = CLAIM_CATALOG_VERSION,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    seen_locators: set[str] = set()
    seen_hashes: set[str] = set()
    duplicate_locators = 0
    duplicate_hashes = 0
    for leaf in leaves:
        locator_key = _leaf_locator_key(leaf)
        if locator_key in seen_locators:
            duplicate_locators += 1
        seen_locators.add(locator_key)
        normalized = _normalized_text(leaf.get("text"))
        claim_hash = _sha256_bytes(_canonical_bytes({
            "document_generation_id": document_generation_id,
            "catalog_version": catalog_version,
            "source_kind": leaf.get("source_kind"),
            "locator": leaf.get("locator"),
            "normalized_text": normalized,
        }))
        if claim_hash in seen_hashes:
            duplicate_hashes += 1
        seen_hashes.add(claim_hash)
        row = {
            "schema": CLAIM_CATALOG_SCHEMA,
            "catalog_version": catalog_version,
            "document_generation_id": document_generation_id,
            "catalog_generation_id": "",
            "claim_id": "CLM-" + claim_hash.removeprefix("sha256:")[:16],
            "claim_hash": claim_hash,
            "normalized_text_hash": _sha256_bytes(normalized.encode("utf-8")),
            "owner_unit_id": None,
            **leaf,
        }
        rows.append(row)
    return rows, duplicate_locators, duplicate_hashes


def _render_unit_prompt(rows: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for row in rows:
        context = row.get("table_context") if isinstance(row.get("table_context"), dict) else None
        header = ""
        if row.get("source_kind") == "table_cell":
            # cell claim 必须带确定性 semantic_context（表标题+行头+列头）——
            # 裸格（"X"）对验证者没有语义
            semantic = str(row.get("semantic_context") or "")
            if semantic:
                header = f"SEMANTIC CONTEXT: {semantic}\n"
            elif context and context.get("headers"):
                header = "TABLE HEADERS: " + " | ".join(str(value) for value in context["headers"]) + "\n"
        elif context and context.get("headers"):
            header = "TABLE HEADERS: " + " | ".join(str(value) for value in context["headers"]) + "\n"
        chunks.append(f"[CLAIM {row['claim_id']}]\n{header}{row['text']}")
    return "\n\n".join(chunks)


def pack_claim_units(
    rows: list[dict[str, Any]],
    *,
    catalog_generation_id: str,
    target_chars: int = DEFAULT_CLAIM_UNIT_CHARS,
    unit_mode: str = "clause",
) -> list[dict[str, Any]]:
    """Pack each eligible claim once; a single long claim is never duplicated."""
    target_chars = max(1, int(target_chars))
    eligible = [row for row in rows if row.get("eligibility") == "claim"]
    units_rows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_len = 0
    current_section: tuple[str, ...] | None = None
    for row in eligible:
        section = tuple(str(value) for value in (row.get("section_path") or []))
        estimated = len(str(row.get("text") or "")) + len(str(row.get("claim_id") or "")) + 16
        section_changed = current_section is not None and section != current_section
        if current and (current_len + estimated > target_chars or section_changed):
            units_rows.append(current)
            current, current_len = [], 0
        current.append(row)
        current_len += estimated
        current_section = section
    if current:
        units_rows.append(current)

    units: list[dict[str, Any]] = []
    for index, members in enumerate(units_rows):
        prompt = _render_unit_prompt(members)
        unit_digest = _sha256_bytes(_canonical_bytes({
            "catalog_generation_id": catalog_generation_id,
            "packing_version": CLAIM_UNIT_PACKING_VERSION,
            "target_chars": target_chars,
            "unit_mode": unit_mode,
            "claim_hashes": [row["claim_hash"] for row in members],
        }))
        unit_id = "UNIT-" + unit_digest.removeprefix("sha256:")[:16]
        unit = {
            "unit_id": unit_id,
            "unit_index": index,
            "claim_ids": [row["claim_id"] for row in members],
            "claim_hashes": [row["claim_hash"] for row in members],
            "section_path": list(members[0].get("section_path") or []),
            "block_ids": list(dict.fromkeys(
                str(row.get("locator", {}).get("block_id") or "") for row in members
            )),
            "prompt": prompt,
            "prompt_hash": _sha256_bytes(prompt.encode("utf-8")),
        }
        for row in members:
            row["owner_unit_id"] = unit_id
        units.append(unit)
    return units


def _owner_audit(rows: list[dict[str, Any]], units: list[dict[str, Any]]) -> dict[str, int]:
    memberships: dict[str, list[str]] = defaultdict(list)
    prompts = {str(unit["unit_id"]): str(unit.get("prompt") or "") for unit in units}
    for unit in units:
        for claim_id in unit.get("claim_ids") or []:
            memberships[str(claim_id)].append(str(unit["unit_id"]))
    orphan = 0
    multi = 0
    prompt_missing = 0
    for row in rows:
        if row.get("eligibility") != "claim":
            if row.get("owner_unit_id") is not None:
                multi += 1
            continue
        owners = memberships.get(str(row.get("claim_id") or ""), [])
        if len(owners) == 0 or not row.get("owner_unit_id"):
            orphan += 1
        if len(owners) > 1 or (owners and row.get("owner_unit_id") not in owners):
            multi += 1
        if owners and str(row.get("text") or "") not in prompts.get(owners[0], ""):
            prompt_missing += 1
    return {
        "orphan_claim_count": orphan,
        "multi_owner_count": multi,
        "owner_prompt_missing_count": prompt_missing,
    }


def build_claim_catalog(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    blocks_bytes: bytes | None = None,
    table_items_bytes: bytes | None = None,
    table_cell_items: list[dict[str, Any]] | None = None,
    table_cell_items_bytes: bytes | None = None,
    scope: str = "full",
    target_chars: int = DEFAULT_CLAIM_UNIT_CHARS,
    unit_mode: str = "clause",
    replay_catalog_version: str | None = None,
    structural_override_snapshot: StructuralOverrideSnapshot | None = None,
) -> dict[str, Any]:
    """Build the immutable Phase 0A catalog and its virtual owner units."""
    if scope not in {"full", "sample"}:
        raise ValueError("scope must be 'full' or 'sample'")
    catalog_version = str(replay_catalog_version or CLAIM_CATALOG_VERSION)
    if replay_catalog_version is not None and catalog_version not in {
        "claim-catalog-v2",
        "claim-catalog-v3",
        "claim-catalog-v4",
        "claim-catalog-v5",
        CLAIM_CATALOG_VERSION,
    }:
        raise ValueError("unsupported replay catalog version")
    document = build_document_generation(
        blocks,
        table_items,
        blocks_bytes=blocks_bytes,
        table_items_bytes=table_items_bytes,
        table_cell_items=table_cell_items,
        table_cell_items_bytes=table_cell_items_bytes,
    )
    leaves, container_mappings, audit, structure_status = _enumerate_leaves(
        blocks,
        table_items,
        table_cell_items=table_cell_items,
        catalog_version=catalog_version,
    )
    rows, duplicate_locators, duplicate_hashes = _materialize_claim_identity(
        leaves,
        document_generation_id=document["document_generation_id"],
        catalog_version=catalog_version,
    )
    override_snapshot = (
        structural_override_snapshot
        if structural_override_snapshot is not None
        else empty_structural_override_snapshot()
    )
    override_identity = structural_override_identity(override_snapshot)
    applied_override_count = apply_structural_overrides(rows, override_snapshot)
    packing_config = {"target_chars": int(target_chars), "unit_mode": str(unit_mode)}
    catalog_generation_id = _sha256_bytes(_canonical_bytes({
        "document_generation_id": document["document_generation_id"],
        "catalog_version": catalog_version,
        "packing_version": CLAIM_UNIT_PACKING_VERSION,
        "packing_config": packing_config,
        "structural_override_version": override_identity["version"],
        "structural_override_prefix_sha256": override_identity["prefix_sha256"],
        "structural_override_prefix_count": override_identity["prefix_count"],
    }))
    for row in rows:
        row["catalog_generation_id"] = catalog_generation_id
    units = pack_claim_units(
        rows,
        catalog_generation_id=catalog_generation_id,
        target_chars=target_chars,
        unit_mode=unit_mode,
    )
    owner_audit = _owner_audit(rows, units)
    locator_to_id = {_leaf_locator_key(row): row["claim_id"] for row in rows}
    for mapping in container_mappings:
        mapping["leaf_ids"] = [
            locator_to_id[key] for key in mapping.pop("leaf_locator_keys", []) if key in locator_to_id
        ]
    audit.update(owner_audit)
    audit["duplicate_leaf_locator_count"] = duplicate_locators
    audit["duplicate_leaf_hash_count"] = duplicate_hashes
    audit["parent_child_duplicate_count"] = _parent_child_duplicate_count(rows)
    hard_fail_keys = (
        "unmapped_source_span_count",
        "unmapped_raw_span_count",
        "overlapping_raw_span_count",
        "overlapping_leaf_span_count",
        "parse_incomplete_count",
        "parent_child_duplicate_count",
        "orphan_claim_count",
        "multi_owner_count",
        "owner_prompt_missing_count",
        "duplicate_leaf_locator_count",
        "duplicate_leaf_hash_count",
        "orphan_table_item_count",
        "multi_consumed_table_item_count",
        "non_table_parent_item_count",
        "unconsumed_table_cell_count",
        "multi_consumed_table_cell_count",
        "dangling_table_item_reference_count",
        "dangling_table_cell_reference_count",
        "normative_context_only_count",
        "orphan_table_cell_count",
        "duplicate_table_cell_id_count",
    )
    accounting_status = "complete" if all(int(audit[key]) == 0 for key in hard_fail_keys) else "incomplete"
    meta = {
        "schema": CLAIM_CATALOG_META_SCHEMA,
        "catalog_version": catalog_version,
        "packing_version": CLAIM_UNIT_PACKING_VERSION,
        **document,
        "catalog_generation_id": catalog_generation_id,
        "structural_override_version": CLAIM_STRUCTURAL_OVERRIDE_VERSION,
        "structural_override_prefix_sha256": override_identity["prefix_sha256"],
        "structural_override_prefix_count": override_identity["prefix_count"],
        "structural_override_applied_count": applied_override_count,
        "scope": scope,
        "document_closure_claimed": False,
        "packing_config": packing_config,
        "accounting_status": accounting_status,
        # 结构歧义/旧产物迁移是结构状态，不与内容守恒（accounting_status）混为一谈
        "table_structure_status": structure_status,
        "table_structure_version": TABLE_STRUCTURE_VERSION,
        "counts": {
            "catalog_total_count": len(rows),
            "eligible_claim_count": sum(row.get("eligibility") == "claim" for row in rows),
            "structural_excluded_count": sum(row.get("eligibility") == "excluded" for row in rows),
            "table_cell_claim_count": sum(
                row.get("source_kind") == "table_cell"
                and row.get("eligibility") == "claim"
                for row in rows
            ),
            "structural_review_candidate_count": sum(
                row.get("eligibility") == "excluded"
                and isinstance(row.get("exclusion"), dict)
                and row["exclusion"].get("reason") in _TABLE_CELL_REVIEW_RULES
                for row in rows
            ),
            "owner_unit_count": len(units),
        },
        "audit": audit,
        "container_mappings": container_mappings,
        "unit_prompt_hashes": {unit["unit_id"]: unit["prompt_hash"] for unit in units},
    }
    return {"catalog": rows, "units": units, "meta": meta}


def _parent_child_duplicate_count(rows: list[dict[str, Any]]) -> int:
    """父子重复计数：同一块内一个叶子的 span 严格包含另一个叶子的 span。

    父容器按设计不生成叶子行，本检查是结构性不变量的运行时证明（此前为恒零死计数器）。
    """
    by_block: dict[str, list[tuple[int, int]]] = {}
    for row in rows:
        locator = row.get("locator") or {}
        block_id = str(locator.get("block_id") or "")
        start = locator.get("start")
        end = locator.get("end")
        if not block_id or not isinstance(start, int) or not isinstance(end, int):
            continue
        by_block.setdefault(block_id, []).append((start, end))
    count = 0
    for spans in by_block.values():
        for index, (a_start, a_end) in enumerate(spans):
            for b_start, b_end in spans[index + 1:]:
                a_contains_b = a_start <= b_start and a_end >= b_end
                b_contains_a = b_start <= a_start and b_end >= a_end
                if (a_contains_b or b_contains_a) and (a_start, a_end) != (b_start, b_end):
                    count += 1
    return count


def build_catalog_from_directory(
    out_dir: Path,
    *,
    scope: str = "full",
    target_chars: int = DEFAULT_CLAIM_UNIT_CHARS,
    unit_mode: str = "clause",
) -> dict[str, Any]:
    """Read exact artifact bytes so the generation matches what was persisted."""
    from io_utils import read_jsonl

    root = Path(out_dir).expanduser().resolve()
    blocks_path = root / "blocks.jsonl"
    table_path = root / "table_items.jsonl"
    cell_path = root / "table_cell_items.jsonl"
    block_bytes = blocks_path.read_bytes()
    table_bytes = table_path.read_bytes() if table_path.exists() else b""
    cell_bytes = cell_path.read_bytes() if cell_path.exists() else b""
    override_snapshot = read_structural_overrides(root)
    return build_claim_catalog(
        read_jsonl(blocks_path),
        read_jsonl(table_path),
        blocks_bytes=block_bytes,
        table_items_bytes=table_bytes,
        table_cell_items=read_jsonl(cell_path) if cell_path.exists() else [],
        table_cell_items_bytes=cell_bytes,
        scope=scope,
        target_chars=target_chars,
        unit_mode=unit_mode,
        structural_override_snapshot=override_snapshot,
    )
