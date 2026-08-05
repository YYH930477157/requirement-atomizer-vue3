"""LLM table-structure proposer (WS1 dual-track "proposal track", plan §3.1.1).

This module is the PROPOSER half of the dual-track table parser. It takes the
physical geometry produced by ``docx_table_parser.ParsedDocxTable`` plus per-cell
style evidence plus a matched table-family template, and asks an OpenAI-compatible
LLM to propose a structure hypothesis conforming to ``table-structure-hypothesis/v1``.

Hard contract (mandated by the handoff brief and plan §3.1.1):

* **Propose, never sign.** The proposer only emits a hypothesis; it has zero
  downstream effect until ``table_geometry_validator.validate_table_geometry`` signs
  it. The validator is the sole authority (see its module docstring).
* **Stub-first, honest unavailability.** The LLM call goes through the repo's existing
  ``llm_client`` channel and stub-first routing. Offline / no API key / stub route /
  exhausted budget / any LLM or parse error → return an honest ``unavailable`` status
  so the caller falls back to the deterministic geometry single-track. The proposer
  NEVER fabricates a hypothesis (provenance discipline: a missing model is reported,
  not impersonated).
* **No free-text fields.** The output is restricted to structured coordinates, the
  role enum (identical to ``STRUCTURAL_ROLES`` / the review panel), header-level
  count, and confidence grades. The schema itself closes the hallucination injection
  channel; the proposer additionally strips any extra keys before returning.
* **No real LLM calls in tests.** Tests inject a fake ``chat`` callable to exercise
  routing, prompt assembly, structural validation, and degradation logic. This
  machine has no API key, so a default-config call would be ``unavailable`` anyway.

This module performs no file I/O and writes nothing. It depends only on the parsed
table data model and the table-family template library.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from docx_table_parser import ParsedDocxTable
from table_family_templates import (
    TableFamilyLibrary,
    TableFamilyTemplate,
    load_table_family_templates,
    match_table_family,
)

LLM_TABLE_UNDERSTANDING_VERSION = "llm-table-understanding-v1"
LLM_TABLE_UNDERSTANDING_PROMPT_VERSION = "llm-table-understanding-prompt-v1"
# Single source of truth for the hypothesis schema constant — re-exported from the
# validator so proposer, validator, and schema file never drift.
from table_geometry_validator import TABLE_STRUCTURE_HYPOTHESIS_VERSION as _HYPOTHESIS_SCHEMA  # noqa: E402

PROPOSED = "proposed"
UNAVAILABLE = "unavailable"

# Role enum is identical to STRUCTURAL_ROLES in table_structure.py and to the review
# panel (table_cell_item.schema.json structural_role, table_cell_dispositions_v2
# role). Re-declared here to keep the proposer self-contained and to fail loud if the
# two ever drift (the structural check below rejects anything outside this set).
_HYPOTHESIS_ROLES = ("title", "header", "row_header", "data", "group_header")
_CONFIDENCE_GRADES = ("high", "medium", "low")


class TableUnderstandingUnavailable(RuntimeError):
    """Raised by eager entry points when the proposer is unavailable.

    The dataclass result already carries an honest ``unavailable`` status; this
    exception is for call sites that prefer raise-style control flow (mirrors
    ``spot_extract.SpotExtractUnavailableError``).
    """


@dataclass(frozen=True)
class TableUnderstandingResult:
    """Result of one proposer call.

    ``status`` is ``proposed`` (a hypothesis was produced — NOT yet signed by the
    validator) or ``unavailable`` (no hypothesis; caller falls back to geometry
    single-track). ``reason`` records the honest unavailability cause; it is empty
    when proposed. ``family_id`` is the matched table-family id used for few-shot
    context (empty when no family matched).
    """

    status: str
    hypothesis: dict[str, Any] | None
    route: str
    module_version: str = LLM_TABLE_UNDERSTANDING_VERSION
    prompt_version: str = LLM_TABLE_UNDERSTANDING_PROMPT_VERSION
    family_id: str = ""
    reason: str = ""

    @property
    def is_proposed(self) -> bool:
        return self.status == PROPOSED

    @property
    def is_unavailable(self) -> bool:
        return self.status == UNAVAILABLE


# --- prompt assembly ---------------------------------------------------------


def _matrix_preview(parsed: ParsedDocxTable, *, cell_text_cap: int = 120) -> list[dict[str, Any]]:
    """Render the physical matrix as a coordinate-keyed preview for the prompt.

    Only canonical cells (anchors / standalone cells) are shown — covered coordinates
    are omitted because they are not independent cells (the proposer may only
    reference coordinates that exist in ``parsed.cells``; the validator enforces
    canonical membership). Style evidence is attached per cell so the model can use
    bold/shading/borders as role hints. Cell text is capped to keep the prompt bounded.
    """
    preview: list[dict[str, Any]] = []
    for (row, col), cell in sorted(parsed.cells.items()):
        text = str(cell.text or "")
        if len(text) > cell_text_cap:
            text = text[:cell_text_cap] + "…"
        preview.append({
            "coordinate": [row, col],
            "text": text,
            "row_span": int(cell.row_span or 1),
            "column_span": int(cell.column_span or 1),
            "covered_coordinates": [
                [r, c] for r, c in (cell.covered_coordinates or ())
            ],
            "style": dict(cell.style_evidence or {}),
        })
    return preview


def _family_context(family: TableFamilyTemplate | None) -> dict[str, Any]:
    """Render the matched family template as structured priors (data, not prose).

    Protected-code columns and semantic-merge priors are passed as structured anchors
    so the model knows where verbatim comparison will be enforced and which merges are
    expected. No prompt-prose is generated from the family — only its declared fields.
    """
    if family is None:
        return {"matched": False}
    return {
        "matched": True,
        "family_id": family.family_id,
        "header_level_range": [family.header_level_range.min, family.header_level_range.max],
        "protected_code_columns": [
            {
                "column_kind": column.column_kind,
                "header_indicators": list(column.header_indicators),
                "verbatim": column.verbatim,
            }
            for column in family.protected_code_columns
        ],
        "semantic_merge_priors": [prior.prior_id for prior in family.semantic_merge_priors],
    }


def build_proposal_prompt(
    parsed: ParsedDocxTable,
    family: TableFamilyTemplate | None,
) -> tuple[str, str]:
    """Build the (system, user) prompt pair for the proposer call.

    The system prompt fixes the task, the output schema, and the no-free-text
    constraint. The user prompt carries the matrix preview + style evidence + family
    context as JSON, plus the version stamps the caller should pin into any cache
    fingerprint. Both prompts are deterministic functions of their inputs.
    """
    system = (
        "You are a table-structure proposer for technical-standard documents. "
        "Given a physical cell matrix (with coordinates, text, and style evidence) "
        "and an optional table-family template, propose a structure hypothesis.\n"
        "HARD RULES:\n"
        "1. Output ONLY a JSON object matching the schema. No markdown fences, no prose.\n"
        "2. Every coordinate is a [row, column] pair of 1-based ints and MUST reference a "
        "canonical cell present in the input matrix (never a covered coordinate).\n"
        "3. role MUST be one of: " + ", ".join(_HYPOTHESIS_ROLES) + ".\n"
        "4. confidence MUST be one of: " + ", ".join(_CONFIDENCE_GRADES) + ".\n"
        "5. You may ONLY emit the declared fields: schema, table_structure_version, "
        "header_level_count, cells[], semantic_merges[]. No free-text/prose fields. "
        "Any extra field will be rejected.\n"
        "6. You PROPOSE; you do not decide. Geometry validation happens downstream.\n"
        "7. If the matrix is too small or ambiguous to assign roles, return a hypothesis "
        "with header_level_count=0 and an empty cells list rather than guessing."
    )
    user_payload = {
        "schema": _HYPOTHESIS_SCHEMA,
        "table_structure_version": str(parsed.version or ""),
        "matrix_dimensions": {
            "rows": len(parsed.matrix),
            "width": int(parsed.width or 0),
        },
        "merge_ranges": [
            [int(value) for value in merge]
            for merge in (parsed.merge_ranges or [])
        ],
        "cells": _matrix_preview(parsed),
        "family_template": _family_context(family),
        "prompt_version": LLM_TABLE_UNDERSTANDING_PROMPT_VERSION,
    }
    user = "Propose a structure hypothesis for this table:\n" + json.dumps(
        user_payload, ensure_ascii=False
    )
    return system, user


# --- structural validation of the model output -------------------------------


def _is_coordinate(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(member, int) and not isinstance(member, bool) for member in value)
        and all(member >= 1 for member in value)
    )


def _validate_hypothesis_shape(payload: Any) -> tuple[dict[str, Any] | None, str]:
    """Lightweight structural check that the model output matches the hypothesis schema.

    Returns ``(cleaned_hypothesis_or_None, reason)``. This does NOT duplicate the
    geometry validator's checks (coordinate bounds, canonical membership, anchor
    conservation, encoding drift) — those stay owned by ``table_geometry_validator``.
    Here we only guarantee the payload is well-shaped enough for the validator to
    run on it, and that no free-text/extra fields leaked through.
    """
    if not isinstance(payload, dict):
        return None, "model output is not a JSON object"
    schema = str(payload.get("schema") or "")
    if schema != _HYPOTHESIS_SCHEMA:
        return None, f"schema mismatch: {schema!r}"
    raw_levels = payload.get("header_level_count")
    if not isinstance(raw_levels, int) or isinstance(raw_levels, bool) or raw_levels < 0:
        return None, "header_level_count must be a non-negative int"
    cells_field = payload.get("cells")
    if not isinstance(cells_field, list):
        return None, "cells must be a list"
    cleaned_cells: list[dict[str, Any]] = []
    known_cells: set[tuple[int, int]] = set()
    for entry in cells_field:
        if not isinstance(entry, dict):
            return None, "cells[] entries must be objects"
        coordinate = entry.get("coordinate")
        if not _is_coordinate(coordinate):
            return None, f"cells[].coordinate invalid: {coordinate!r}"
        role = str(entry.get("role") or "")
        if role not in _HYPOTHESIS_ROLES:
            return None, f"cells[].role not in enum: {role!r}"
        confidence = str(entry.get("confidence") or "")
        if confidence not in _CONFIDENCE_GRADES:
            return None, f"cells[].confidence not in enum: {confidence!r}"
        # additionalProperties:false — reject any extra key on a cell entry.
        if set(entry.keys()) != {"coordinate", "role", "confidence"}:
            return None, "cells[] entries must have exactly coordinate/role/confidence"
        key = (coordinate[0], coordinate[1])
        if key in known_cells:
            return None, f"duplicate cell coordinate: {coordinate!r}"
        known_cells.add(key)
        cleaned_cells.append({
            "coordinate": [coordinate[0], coordinate[1]],
            "role": role,
            "confidence": confidence,
        })
    merges_field = payload.get("semantic_merges")
    if not isinstance(merges_field, list):
        return None, "semantic_merges must be a list"
    cleaned_merges: list[dict[str, Any]] = []
    for entry in merges_field:
        if not isinstance(entry, dict):
            return None, "semantic_merges[] entries must be objects"
        coordinates = entry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return None, "semantic_merges[].coordinates must list >=2 members"
        cleaned_coords: list[list[int]] = []
        for member in coordinates:
            if not _is_coordinate(member):
                return None, f"semantic_merges member not a coordinate: {member!r}"
            cleaned_coords.append([member[0], member[1]])
        if set(entry.keys()) != {"coordinates"}:
            return None, "semantic_merges[] entries must have exactly coordinates"
        cleaned_merges.append({"coordinates": cleaned_coords})
    # additionalProperties:false at top level.
    if set(payload.keys()) != {"schema", "table_structure_version", "header_level_count", "cells", "semantic_merges"}:
        return None, "top-level must have exactly schema/table_structure_version/header_level_count/cells/semantic_merges"
    cleaned = {
        "schema": _HYPOTHESIS_SCHEMA,
        "table_structure_version": str(payload.get("table_structure_version") or ""),
        "header_level_count": int(raw_levels),
        "cells": cleaned_cells,
        "semantic_merges": cleaned_merges,
    }
    return cleaned, ""


# --- entry point -------------------------------------------------------------


def propose_table_structure(
    parsed_table: ParsedDocxTable,
    *,
    config: Any = None,
    chat: Callable[[str, str], dict[str, Any]] | None = None,
    family: TableFamilyTemplate | None = None,
    family_library: TableFamilyLibrary | None = None,
    request_budget: Any = None,
) -> TableUnderstandingResult:
    """Propose a table-structure hypothesis (stub-first, never fabricates).

    Inputs:
      * ``parsed_table`` — physical geometry from ``docx_table_parser``.
      * ``config`` — an ``LLMClientConfig`` for the openai_compatible route, or ``None``
        (stub route / offline). ``None`` → honest ``unavailable``.
      * ``chat`` — optional ``(system, user) -> dict`` callable. When ``None`` a default
        is built from ``config`` via ``llm_client.chat_json`` (the existing channel).
      * ``family`` — matched table-family template for few-shot context. When ``None``
        and ``family_library`` is given/loaded, the best match is derived from the
        parsed table's first non-empty row (advisory context only).
      * ``family_library`` — override the default template library.
      * ``request_budget`` — optional ``LLMRequestBudget`` for the default chat path.

    Output: a ``TableUnderstandingResult``. ``proposed`` means a hypothesis was
    produced (NOT yet signed); ``unavailable`` means the caller falls back to the
    deterministic geometry single-track. Any LLM/parse error, missing route, or
    structural mismatch is ``unavailable`` with an honest reason — never a stub
    hypothesis.
    """
    if config is None:
        return TableUnderstandingResult(
            status=UNAVAILABLE,
            hypothesis=None,
            route="stub",
            reason="no_openai_compatible_route",
        )

    # Resolve few-shot family context (advisory; never assigns roles).
    matched_family = family
    if matched_family is None:
        library = family_library if family_library is not None else load_table_family_templates()
        if library.families:
            header_row = next(
                (row for row in (parsed_table.matrix or []) if any(str(c or "").strip() for c in row)),
                [],
            )
            matched_family = match_table_family(header_row, library)
    family_id = str(matched_family.family_id) if matched_family is not None else ""

    # Build the chat callable through the existing llm_client channel when the caller
    # did not inject one (tests inject a fake; production wires config + budget).
    if chat is None:
        chat_callable = _default_chat(config, request_budget)
    else:
        chat_callable = chat

    system_prompt, user_prompt = build_proposal_prompt(parsed_table, matched_family)
    try:
        payload = chat_callable(system_prompt, user_prompt)
    except TableUnderstandingUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — any failure is honest unavailability.
        return TableUnderstandingResult(
            status=UNAVAILABLE,
            hypothesis=None,
            route="openai_compatible",
            family_id=family_id,
            reason=f"llm_call_failed:{type(exc).__name__}:{exc}",
        )
    if not isinstance(payload, dict):
        return TableUnderstandingResult(
            status=UNAVAILABLE,
            hypothesis=None,
            route="openai_compatible",
            family_id=family_id,
            reason="model_returned_non_object",
        )
    cleaned, reason = _validate_hypothesis_shape(payload)
    if cleaned is None:
        return TableUnderstandingResult(
            status=UNAVAILABLE,
            hypothesis=None,
            route="openai_compatible",
            family_id=family_id,
            reason=f"shape_invalid:{reason}",
        )
    return TableUnderstandingResult(
        status=PROPOSED,
        hypothesis=cleaned,
        route="openai_compatible",
        family_id=family_id,
        reason="",
    )


def _default_chat(config: Any, request_budget: Any) -> Callable[[str, str], dict[str, Any]]:
    """Build a ``chat(system, user) -> dict`` callable on the existing llm_client channel."""
    from llm_client import LLMError, chat_json  # lazy: avoids import cycles + keeps tests stub-free

    def chat(system_prompt: str, user_prompt: str) -> dict[str, Any]:
        try:
            return chat_json(
                config,
                system_prompt,
                user_prompt,
                _request_budget=request_budget,
            )
        except LLMError as exc:
            raise TableUnderstandingUnavailable(str(exc)) from exc

    return chat


__all__ = [
    "LLM_TABLE_UNDERSTANDING_VERSION",
    "LLM_TABLE_UNDERSTANDING_PROMPT_VERSION",
    "PROPOSED",
    "UNAVAILABLE",
    "TableUnderstandingUnavailable",
    "TableUnderstandingResult",
    "build_proposal_prompt",
    "propose_table_structure",
]
