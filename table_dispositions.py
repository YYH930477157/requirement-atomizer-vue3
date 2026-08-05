"""Deterministic, versioned disposition ledger for canonical table cells."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from table_structure import TABLE_STRUCTURE_VERSION, is_normative_text


TABLE_CELL_DISPOSITION_SCHEMA = "table-cell-disposition/v2"
TABLE_DISPOSITION_RULE_VERSION = "table-disposition-rules-v2"
DISPOSITIONS = ("target", "context", "composite", "excluded", "review")

_NOT_APPLICABLE_RE = re.compile(
    r"^\s*(?:n\s*/?\s*a|not\s+applicable|non[- ]applicable|不适用|不适合)\s*[.!。]?$",
    re.IGNORECASE,
)
_INDEX_HEADER_RE = re.compile(
    r"^\s*(?:no\.?|number|index|item|序号|编号|项号)\s*$", re.IGNORECASE
)
_INDEX_VALUE_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s*$")


class TableDispositionError(ValueError):
    pass


def _iter_table_blocks(blocks: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") == "table":
            yield block
        yield from _iter_table_blocks(block.get("nested_tables") or [])


def _candidate_sets(block: dict[str, Any]) -> dict[str, set[str]]:
    plan = block.get("leaf_plan") or {}
    return {
        key: {str(value) for value in (plan.get(key) or [])}
        for key in (
            "ambiguous_structure_cells",
            "weak_signal_cells",
            "unsignaled_data_cells",
            "untyped_colon_spec_cells",
        )
    }


def _is_index_cell(cell: dict[str, Any]) -> bool:
    header = str((cell.get("header_path") or [""])[0] or "")
    return bool(_INDEX_HEADER_RE.fullmatch(header) and _INDEX_VALUE_RE.fullmatch(
        str(cell.get("text") or "")
    ))


def _base_disposition(
    block: dict[str, Any], cell: dict[str, Any]
) -> tuple[str, str, list[str], str | None, str | None]:
    """Return disposition, confidence, evidence, exclusion reason, applicability."""
    text = str(cell.get("text") or "").strip()
    cell_id = str(cell.get("cell_id") or "")
    role = str(cell.get("structural_role") or "")
    leaf_kind = str(cell.get("leaf_kind") or "context")
    candidates = _candidate_sets(block)
    normative = bool(cell.get("requirement_like")) or is_normative_text(text)

    if bool(block.get("parse_incomplete")):
        reason = str((block.get("parse_incomplete_reason") or {}).get("code") or "unknown")
        return "review", "low", [f"parse_incomplete:{reason}"], None, None
    if _NOT_APPLICABLE_RE.fullmatch(text):
        return (
            "excluded",
            "high",
            ["explicit_not_applicable", "scope_exclusion_only"],
            "not_applicable",
            "excluded",
        )
    if cell_id in candidates["ambiguous_structure_cells"]:
        return "review", "low", ["ambiguous_structure_cell"], None, None
    if cell_id in candidates["weak_signal_cells"]:
        return "review", "medium", ["weak_sentence_signal"], None, None
    if cell_id in candidates["unsignaled_data_cells"]:
        return "review", "medium", ["unsignaled_data_cell"], None, None
    if cell_id in candidates["untyped_colon_spec_cells"]:
        return "review", "medium", ["untyped_colon_spec"], None, None
    if _is_index_cell(cell):
        return "excluded", "high", ["index_column", "non_semantic_number"], "index", None
    if normative:
        if leaf_kind == "cell":
            return "target", "high", ["normative_text", "cell_leaf_owner"], None, None
        if leaf_kind == "row":
            return "composite", "high", ["normative_text", "row_leaf_owner"], None, None
        # A normative title/header/context is never silently downgraded.
        return "review", "medium", ["normative_context_conflict", f"role:{role}"], None, None
    if role in {"title", "header", "row_header", "group_header"}:
        return "context", "high", [f"structural_role:{role}"], None, None
    if leaf_kind == "cell":
        return "composite", "high", ["cell_leaf_owner", "context_required"], None, None
    if leaf_kind == "row":
        return "composite", "high", ["row_leaf_owner", "context_required"], None, None
    return "context", "high", [f"leaf_kind:{leaf_kind}", f"structural_role:{role}"], None, None


def build_table_cell_dispositions(
    blocks: list[dict[str, Any]],
    table_cell_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    block_by_table = {
        str(block.get("table_id") or ""): block
        for block in _iter_table_blocks(blocks)
        if str(block.get("table_id") or "")
    }
    rows: list[dict[str, Any]] = []
    for cell in table_cell_items:
        cell_version = str(cell.get("table_structure_version") or "")
        if cell_version != TABLE_STRUCTURE_VERSION:
            raise TableDispositionError(
                "base_migration_required: table cell structure version mismatch "
                f"({cell_version or 'missing'} != {TABLE_STRUCTURE_VERSION})"
            )
        table_id = str(cell.get("table_id") or "")
        block = block_by_table.get(table_id)
        if block is None:
            raise TableDispositionError(
                f"base_migration_required: missing table block for {table_id or '<empty>'}"
            )
        disposition, confidence, evidence, exclusion_reason, applicability = (
            _base_disposition(block, cell)
        )
        leaf_ids: list[str] = []
        if disposition == "target":
            leaf_ids.append(str(cell.get("cell_id") or ""))
        elif disposition == "composite":
            if str(cell.get("leaf_kind") or "") == "row":
                leaf_ids.append(
                    f"{table_id}-R{int(cell.get('row_index') or 0):06d}"
                )
            else:
                leaf_ids.append(str(cell.get("cell_id") or ""))
        row = {
            "schema": TABLE_CELL_DISPOSITION_SCHEMA,
            "cell_id": str(cell.get("cell_id") or ""),
            "table_id": table_id,
            "table_block_id": str(cell.get("table_block_id") or ""),
            "text": str(cell.get("text") or ""),
            "role": str(cell.get("structural_role") or ""),
            "disposition": disposition,
            "confidence": confidence,
            "evidence": evidence,
            "decision_source": "deterministic",
            "decision_version": TABLE_DISPOSITION_RULE_VERSION,
            "table_structure_version": TABLE_STRUCTURE_VERSION,
            "linked_leaf_ids": [value for value in leaf_ids if value],
            "linked_requirement_ids": [],
            "clarification_ids": [],
        }
        if exclusion_reason:
            row["exclusion_reason"] = exclusion_reason
        if applicability:
            row["applicability"] = applicability
        rows.append(row)

    table_has_review = Counter(
        row["table_id"] for row in rows if row["disposition"] == "review"
    )
    for row in rows:
        row["structure_review_status"] = (
            "pending" if table_has_review[row["table_id"]] else "ready"
        )
    validate_disposition_conservation(blocks, table_cell_items, rows)
    return rows


def validate_disposition_conservation(
    blocks: list[dict[str, Any]],
    table_cell_items: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
) -> None:
    del blocks  # Reserved for future table-level hard-constraint validation.
    expected = [str(cell.get("cell_id") or "") for cell in table_cell_items]
    actual = [str(row.get("cell_id") or "") for row in dispositions]
    counts = Counter(actual)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    duplicate = sorted(cell_id for cell_id, count in counts.items() if count != 1)
    invalid = sorted({
        str(row.get("disposition") or "")
        for row in dispositions
        if str(row.get("disposition") or "") not in DISPOSITIONS
    })
    if missing or extra or duplicate or invalid or len(expected) != len(actual):
        raise TableDispositionError(
            "table cell disposition conservation failed: "
            f"missing={missing[:5]} extra={extra[:5]} duplicate={duplicate[:5]} "
            f"invalid={invalid[:5]} expected={len(expected)} actual={len(actual)}"
        )


def summarize_table_dispositions(
    dispositions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dispositions:
        grouped[str(row.get("table_id") or "")].append(row)
    summaries: list[dict[str, Any]] = []
    for table_id in sorted(grouped):
        rows = grouped[table_id]
        counts = Counter(str(row.get("disposition") or "") for row in rows)
        summaries.append({
            "table_id": table_id,
            "table_block_id": str(rows[0].get("table_block_id") or ""),
            "cell_count": len(rows),
            "target_count": counts["target"],
            "context_count": counts["context"],
            "composite_count": counts["composite"],
            "excluded_count": counts["excluded"],
            "review_count": counts["review"],
            "structure_review_status": (
                "pending" if counts["review"] else "ready"
            ),
            "decision_version": TABLE_DISPOSITION_RULE_VERSION,
            "table_structure_version": TABLE_STRUCTURE_VERSION,
        })
    return summaries
