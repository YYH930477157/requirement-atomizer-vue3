"""Deterministic, table-scoped B-track regeneration after human structure review."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ai_review_actions import ensure_requirement_identity
from io_utils import read_jsonl
from table_structure import cell_context_text, is_normative_text, sentence_spans


TABLE_RECOMPUTE_VERSION = "table-local-recompute-v1"
_MISSING_PARAMETER_RE = re.compile(
    r"\b(?:threshold|distance|range|calculation method|calculation|step|default)\b",
    re.IGNORECASE,
)
_NUMERIC_VALUE_RE = re.compile(r"\d")
_UNIT_HEADER_RE = re.compile(r"^(?:unit|uom|units?)$", re.IGNORECASE)


def _fragments(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    fragments = [
        part.strip()
        for part in re.split(r"(?<=[.!?;。！？；])\s+|[\r\n]+", normalized)
        if part.strip()
    ]
    if len(fragments) <= 1:
        spans = sentence_spans(normalized)
        fragments = [normalized[start:end].strip() for start, end in spans]
    return [fragment for fragment in fragments if fragment] or [normalized]


def _merge_equivalent_requirements(
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for requirement in requirements:
        key = (
            str(requirement.get("functional_key") or ""),
            str(requirement.get("description") or ""),
            str(requirement.get("constraint_strength") or ""),
        )
        current = grouped.get(key)
        if current is None:
            grouped[key] = dict(requirement)
            order.append(key)
            continue
        for field in ("source_block_ids", "source_cell_ids"):
            current[field] = list(dict.fromkeys([
                *(current.get(field) or []),
                *(requirement.get(field) or []),
            ]))
        current["source_cell_id"] = current["source_cell_ids"][0]
    return [grouped[key] for key in order]


def _requirement_for_fragment(
    cell: dict[str, Any],
    fragment: str,
    *,
    fragment_index: int,
    supporting_cell_ids: list[str] | None = None,
    unit_text: str = "",
) -> dict[str, Any]:
    from ai_extract import _constraint_strength

    cell_id = str(cell.get("cell_id") or "")
    context = cell_context_text(cell).strip() or fragment
    normative = is_normative_text(fragment)
    row_headers = [str(value) for value in (cell.get("row_header_context") or []) if str(value)]
    parameter_context = row_headers[0] if row_headers else ""
    description = (
        fragment
        if normative
        else (
            "The implementation shall satisfy the table constraint: "
            f"{parameter_context or context} | {fragment}"
            f"{' ' + unit_text if unit_text else ''}."
        )
    )
    headers = [str(value) for value in (cell.get("header_path") or []) if str(value)]
    title_basis = row_headers[0] if row_headers else headers[-1] if headers else fragment
    stable_basis = f"{TABLE_RECOMPUTE_VERSION}|{cell_id}|{fragment_index}|{fragment}"
    stable_id = "AIR-TBL-" + hashlib.sha1(stable_basis.encode("utf-8")).hexdigest()[:12]
    section_path = [str(value) for value in (cell.get("section_path") or []) if str(value)]
    clarification_ids: list[str] = []
    if _MISSING_PARAMETER_RE.search(fragment) and not _NUMERIC_VALUE_RE.search(fragment):
        clarification_ids.append(
            "CLR-TBL-" + hashlib.sha1(
                f"{cell.get('table_id')}|{title_basis}|missing-parameter".encode("utf-8")
            ).hexdigest()[:12]
        )
    source_cell_ids = list(dict.fromkeys([
        cell_id,
        *(supporting_cell_ids or []),
    ]))
    requirement = {
        "ai_req_id": stable_id,
        "title": title_basis[:120],
        "functional_key": "table." + hashlib.sha1(
            f"{cell.get('table_id')}|{title_basis}".encode("utf-8")
        ).hexdigest()[:12],
        "description": description,
        "type": "constraint",
        "priority": "must",
        "module": "other",
        "ownership": "软件",
        "source_section": " / ".join(section_path) or str(cell.get("table_id") or ""),
        "source_quote": fragment,
        "source_block_ids": [str(cell.get("table_block_id") or "")],
        "source_cell_ids": source_cell_ids,
        "source_cell_id": cell_id,
        "source_mapping": "table_review_deterministic",
        "constraint_strength": _constraint_strength(fragment),
        "acceptance_criteria": [
            f"Verify the implementation against source table cell {cell_id}."
        ],
        "dev_guidance": [],
        "design_options": [],
        "dependencies": [],
        "labels": ["other"],
        "notes": (
            "Deterministic local regeneration after human table-structure confirmation; "
            "source wording and cell identity remain authoritative."
        ),
        "suspicion_reasons": [],
        "clarification_ids": clarification_ids,
        "table_recompute_version": TABLE_RECOMPUTE_VERSION,
    }
    return ensure_requirement_identity(requirement)


def recompute_confirmed_table_requirements(
    out_dir: Path,
    *,
    table_id: str,
    changed_cell_ids: set[str],
    cells: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
) -> list[str]:
    """Replace only requirements owned by changed cells; never rerun the document."""
    root = Path(out_dir).expanduser().resolve()
    requirements_path = root / "ai_requirements.jsonl"
    if not requirements_path.is_file():
        return []

    from ai_extract import (
        _apply_table_requirement_metadata,
        atomic_write_jsonl,
        extraction_input_fingerprint,
        write_ai_requirements_metadata,
    )

    relevant_cells = {
        str(cell.get("cell_id") or ""): cell
        for cell in cells
        if str(cell.get("table_id") or "") == table_id
        and str(cell.get("cell_id") or "") in changed_cell_ids
    }
    disposition_by_cell = {
        str(row.get("cell_id") or ""): row for row in dispositions
    }
    existing = read_jsonl(requirements_path)
    kept = [
        row for row in existing
        if not changed_cell_ids.intersection(
            str(value) for value in (row.get("source_cell_ids") or [])
        )
    ]
    generated: list[dict[str, Any]] = []
    table_cells = [
        cell for cell in cells if str(cell.get("table_id") or "") == table_id
    ]
    cells_by_row: dict[int, list[dict[str, Any]]] = {}
    for cell in table_cells:
        cells_by_row.setdefault(int(cell.get("row_index") or 0), []).append(cell)
    for cell_id in sorted(relevant_cells):
        disposition = str(
            (disposition_by_cell.get(cell_id) or {}).get("disposition") or ""
        )
        if disposition not in {"target", "composite"}:
            continue
        cell = relevant_cells[cell_id]
        unit_cell = next((
            sibling for sibling in cells_by_row.get(int(cell.get("row_index") or 0), [])
            if _UNIT_HEADER_RE.fullmatch(
                str(((sibling.get("header_path") or [""])[-1]) or "")
            )
            and str(sibling.get("text") or "").strip()
        ), None)
        support_ids = [str(unit_cell.get("cell_id") or "")] if unit_cell else []
        unit_text = str(unit_cell.get("text") or "").strip() if unit_cell else ""
        for index, fragment in enumerate(_fragments(str(cell.get("text") or "")), start=1):
            generated.append(_requirement_for_fragment(
                cell,
                fragment,
                fragment_index=index,
                supporting_cell_ids=support_ids,
                unit_text=unit_text,
            ))
    generated = _merge_equivalent_requirements(generated)
    _apply_table_requirement_metadata(generated, cells, dispositions)
    rows = [*kept, *generated]
    atomic_write_jsonl(requirements_path, rows)

    old_meta: dict[str, Any] = {}
    meta_path = root / "ai_requirements.meta.json"
    try:
        old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    write_ai_requirements_metadata(
        root,
        input_fingerprint=extraction_input_fingerprint(root),
        run_id=f"table-review:{table_id}",
        failed_sections=int(old_meta.get("failed_sections") or 0),
        failed_section_ids=list(old_meta.get("failed_section_ids") or []),
        failed_section_block_ids=list(old_meta.get("failed_section_block_ids") or []),
        no_ledger_baseline_cost=dict(old_meta.get("no_ledger_baseline_cost") or {}),
    )
    return ["ai_requirements.jsonl", "ai_requirements.meta.json"]
