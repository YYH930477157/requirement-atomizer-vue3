"""Deterministic geometry validator for LLM table-structure hypotheses (WS1).

This module is the *signing authority* of the future dual-track table parser
(``llm_table_understanding`` proposes a hypothesis, this validator signs or
rejects it). It is deliberately pure and deterministic: the LLM never signs a
structure decision, and the validator depends only on the physical geometry
produced by ``docx_table_parser.ParsedDocxTable`` — never on any LLM
intermediate representation. That asymmetry is the structural guarantee that an
LLM cannot bypass geometry checks (see implementation plan §3.1.2).

Three rule classes are implemented exactly as mandated by the handoff brief and
the implementation plan §3.1.2; no fourth rule is added and none is omitted:

1. **Coordinate consistency** — every coordinate referenced by the hypothesis
   is in-bounds and canonical (an anchor or standalone cell, never a covered
   coordinate); a semantic-merge group does not cross a vertical-merge physical
   boundary.
2. **Merge-anchor conservation** — each physical merge anchor is consumed
   exactly once across the hypothesis; a non-empty difference set invalidates
   the WHOLE hypothesis (not a local conflict).
3. **Protected-encoding zero drift** — OBIS / G-SG-E / hex tokens (reusing the
   extract-stage ``extract_codes`` guard) are compared verbatim before/after a
   semantic-merge concatenation; any token created or destroyed by the
   concatenation is drift.

Output is three-state: ``issued`` / ``partial_conflict`` (with a conflict-cell
set) / ``invalidated``. Signing only proves geometric legality — never semantic
correctness; a hypothesis whose role labels are all wrong but whose geometry is
legal will still be signed (the quality gate is the §3.2.4 A/B panel audit, not
this validator).

Scope (per brief): the validator is a pure function over ``hypothesis`` +
``parsed_table``. It performs no I/O, holds no state, and is safe to call from
any read path. It does NOT touch ``table_structure.py``, ``docx_table_parser.py``
or any parsing mainline file.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from cosem_behavior_spec import extract_codes
from docx_table_parser import ParsedDocxTable

TABLE_GEOMETRY_VALIDATOR_VERSION = "table-geometry-validator-v1"
TABLE_STRUCTURE_HYPOTHESIS_VERSION = "table-structure-hypothesis/v1"

# Reason codes -----------------------------------------------------------------
CODE_COORD_OUT_OF_BOUNDS = "coordinate_out_of_bounds"
CODE_COORD_NOT_CANONICAL = "coordinate_not_canonical"
CODE_MERGE_CROSSES_VMERGE = "semantic_merge_crosses_vmerge"
CODE_ANCHOR_MISSING = "anchor_missing"
CODE_ANCHOR_DOUBLE_ATTRIBUTION = "anchor_double_attribution"
CODE_PROTECTED_ENCODING_DRIFT = "protected_encoding_drift"

# Reason codes that invalidate the whole hypothesis (rule 2 is authoritative).
_INVALIDATING_CODES = frozenset({CODE_ANCHOR_MISSING, CODE_ANCHOR_DOUBLE_ATTRIBUTION})

ISSUED = "issued"
PARTIAL_CONFLICT = "partial_conflict"
INVALIDATED = "invalidated"


@dataclass(frozen=True)
class GeometryValidationReason:
    """A single deterministic finding.

    ``code`` is a machine-readable reason code; ``cells`` are the referenced
    coordinates the finding is about (for panel highlight / write-back);
    ``detail`` is a short stable string for audit logs.
    """

    code: str
    cells: tuple[tuple[int, int], ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class GeometryValidationResult:
    status: str
    conflict_cells: tuple[tuple[int, int], ...] = ()
    reasons: tuple[GeometryValidationReason, ...] = ()
    version: str = TABLE_GEOMETRY_VALIDATOR_VERSION

    @property
    def is_issued(self) -> bool:
        return self.status == ISSUED

    @property
    def is_partial_conflict(self) -> bool:
        return self.status == PARTIAL_CONFLICT

    @property
    def is_invalidated(self) -> bool:
        return self.status == INVALIDATED


# --- geometry helpers --------------------------------------------------------


@dataclass(frozen=True)
class _Geometry:
    """Pre-computed physical-geometry facts derived once from ParsedDocxTable."""

    nrows: int
    width: int
    canonical: frozenset[tuple[int, int]]
    merge_anchors: frozenset[tuple[int, int]]
    # per-column list of (start_row, end_row) vertical-merge intervals.
    vmerge_intervals_by_col: dict[int, list[tuple[int, int]]]
    text_by_coord: dict[tuple[int, int], str]


def _coord(value: Any) -> tuple[int, int] | None:
    """Coerce a hypothesis coordinate into a 1-based (row, col) int pair.

    Returns ``None`` for anything that is not exactly a 2-element sequence of
    ints >= 1 — the caller treats that as an out-of-bounds reference.
    """
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        r, c = value  # type: ignore[misc]
        if r >= 1 and c >= 1:
            return (r, c)
    return None


def _vertical_intervals(
    parsed: ParsedDocxTable,
) -> dict[int, list[tuple[int, int]]]:
    """Per-column vertical-merge row-intervals from ``merge_ranges``.

    A ``merge_ranges`` tuple ``(r1, c1, r2, c2)`` with ``r2 > r1`` has vertical
    extent; it contributes one row-interval ``[r1, r2]`` to every column in
    ``[c1, c2]`` (rectangular merges are decomposed per column).
    """
    by_col: dict[int, list[tuple[int, int]]] = {}
    for r1, c1, r2, c2 in parsed.merge_ranges:
        if r2 <= r1:
            continue
        for column in range(c1, c2 + 1):
            by_col.setdefault(column, []).append((r1, r2))
    for column, intervals in by_col.items():
        by_col[column] = sorted(intervals)
    return by_col


def _geometry(parsed: ParsedDocxTable) -> _Geometry:
    canonical: set[tuple[int, int]] = set()
    merge_anchors: set[tuple[int, int]] = set()
    text_by_coord: dict[tuple[int, int], str] = {}
    for (r, c), cell in parsed.cells.items():
        canonical.add((r, c))
        text_by_coord[(r, c)] = str(cell.text)
        if cell.covered_coordinates:
            merge_anchors.add((r, c))
    return _Geometry(
        nrows=len(parsed.matrix),
        width=max(parsed.width, 0),
        canonical=frozenset(canonical),
        merge_anchors=frozenset(merge_anchors),
        vmerge_intervals_by_col=_vertical_intervals(parsed),
        text_by_coord=text_by_coord,
    )


def _in_bounds(geo: _Geometry, r: int, c: int) -> bool:
    return 1 <= r <= geo.nrows and 1 <= c <= geo.width


# --- rule 1: coordinate consistency -----------------------------------------


def _check_coordinate(
    geo: _Geometry, raw: Any
) -> tuple[GeometryValidationReason | None, tuple[int, int] | None]:
    """Validate a single referenced coordinate.

    Returns ``(reason_or_None, canonical_coord_or_None)``. A non-None canonical
    coordinate is one that exists in ``parsed.cells``; covered coordinates and
    out-of-bounds slots yield a reason and no canonical coordinate.
    """
    coord = _coord(raw)
    if coord is None:
        # Malformed (non-int / wrong arity / < 1) is reported as out-of-bounds:
        # the reference does not land on a real matrix cell.
        return (
            GeometryValidationReason(
                CODE_COORD_OUT_OF_BOUNDS,
                (),
                detail=f"malformed_coordinate={raw!r}",
            ),
            None,
        )
    r, c = coord
    if not _in_bounds(geo, r, c):
        return (
            GeometryValidationReason(CODE_COORD_OUT_OF_BOUNDS, (coord,)),
            None,
        )
    if coord not in geo.canonical:
        # In-bounds but not a cell: a covered coordinate of some merge anchor,
        # or an absent slot. Either way the hypothesis treats a non-canonical
        # position as if it were an independent cell.
        return (
            GeometryValidationReason(CODE_COORD_NOT_CANONICAL, (coord,)),
            None,
        )
    return None, coord


def _group_crosses_vmerge(
    geo: _Geometry, group: list[tuple[int, int]]
) -> bool:
    """Rule 1c: a semantic-merge group must not cross a vMerge physical boundary.

    For each column the group touches, the set of member rows must not straddle
    any vertical-merge region: if the group has any row inside a vMerge region
    of that column AND any row outside it, the boundary is crossed (this covers
    both splitting a single vMerge and bridging two distinct ones). Members in
    columns without a vMerge, or fully inside / fully outside a region, are
    fine. Covered coordinates never reach here (rule 1b rejects them first), so
    every member is a canonical anchor or standalone cell.
    """
    rows_by_col: dict[int, set[int]] = {}
    for r, c in group:
        rows_by_col.setdefault(c, set()).add(r)
    for column, rows in rows_by_col.items():
        for (start, end) in geo.vmerge_intervals_by_col.get(column, ()):
            inside = any(start <= r <= end for r in rows)
            outside = any(not (start <= r <= end) for r in rows)
            if inside and outside:
                return True
    return False


def _check_semantic_merge(
    geo: _Geometry, group_raw: list[Any]
) -> list[GeometryValidationReason]:
    """Rules 1c + 3 for one semantic-merge group.

    Coordinate shape/bounds are checked per-member here too so the conflict
    cell set names the offending group's members; the per-cell declarations in
    ``cells[]`` are checked separately by the coordinate sweep.
    """
    members: list[tuple[int, int]] = []
    reasons: list[GeometryValidationReason] = []
    for raw in group_raw:
        reason, coord = _check_coordinate(geo, raw)
        if reason is not None:
            reasons.append(reason)
        if coord is not None:
            members.append(coord)
    if members and _group_crosses_vmerge(geo, members):
        reasons.append(
            GeometryValidationReason(
                CODE_MERGE_CROSSES_VMERGE,
                tuple(members),
                detail="group spans inside and outside a vertical-merge region",
            )
        )
    if members:
        drift = _encoding_drift(geo, members)
        if drift is not None:
            reasons.append(drift)
    return reasons


# --- rule 3: protected-encoding zero drift ----------------------------------


def _encoding_drift(
    geo: _Geometry, group: list[tuple[int, int]]
) -> GeometryValidationReason | None:
    """Detect protected-encoding drift caused by concatenating member cell text.

    ``extract_codes`` is the extract-stage anti-drift guard (OBIS
    ``\\d+-\\d+:\\d+(?:\\.\\d+)+``, the ``G..-SG..-E..`` form, and hex
    ``0x..``). The set of codes found in each member cell individually is
    compared with the set found in the member-text concatenation (coordinate
    order): any code present only after concatenation was *fabricated* at a cell
    boundary; any code present only before was *destroyed*. Both are drift and
    hard-flag the group as a local conflict.
    """
    member_codes: set[str] = set()
    parts: list[str] = []
    for coord in group:
        text = geo.text_by_coord.get(coord, "")
        member_codes |= extract_codes(text)
        parts.append(text)
    concat_codes = extract_codes("".join(parts))
    created = concat_codes - member_codes
    destroyed = member_codes - concat_codes
    if not created and not destroyed:
        return None
    detail = "; ".join(
        [f"created={sorted(created)}" if created else "", f"destroyed={sorted(destroyed)}" if destroyed else ""]
    ).strip("; ")
    return GeometryValidationReason(
        CODE_PROTECTED_ENCODING_DRIFT,
        tuple(group),
        detail=detail or "encoding set changed",
    )


# --- rule 2: merge-anchor conservation --------------------------------------


def _check_anchor_conservation(
    geo: _Geometry,
    cells_counts: Counter[tuple[int, int]],
    merge_counts: Counter[tuple[int, int]],
) -> list[GeometryValidationReason]:
    """Each physical merge anchor must be consumed exactly once.

    Consumption is measured across two independent attribution dimensions:
    ``cells_counts`` (role declarations in ``cells[]``) and ``merge_counts``
    (membership in semantic-merge groups). Both must be ``<= 1`` for every
    anchor and their sum must be ``>= 1``: an anchor may legitimately carry one
    role AND belong to one merge group, but it may not be declared twice nor
    claimed by two groups, and an anchor referenced nowhere is lost. The
    difference set is ``{missing anchors} ∪ {duplicated anchors}``; the brief
    mandates that a non-empty difference set invalidates the whole hypothesis
    (status takes precedence over local conflicts).
    """
    reasons: list[GeometryValidationReason] = []
    missing = sorted(
        anchor
        for anchor in geo.merge_anchors
        if cells_counts[anchor] + merge_counts[anchor] == 0
    )
    duplicated = sorted(
        anchor
        for anchor in geo.merge_anchors
        if cells_counts[anchor] > 1 or merge_counts[anchor] > 1
    )
    if missing:
        reasons.append(
            GeometryValidationReason(
                CODE_ANCHOR_MISSING,
                tuple(missing),
                detail=f"{len(missing)} anchor(s) never referenced",
            )
        )
    if duplicated:
        reasons.append(
            GeometryValidationReason(
                CODE_ANCHOR_DOUBLE_ATTRIBUTION,
                tuple(duplicated),
                detail=f"{len(duplicated)} anchor(s) referenced more than once",
            )
        )
    return reasons


# --- entrypoint --------------------------------------------------------------


def validate_table_geometry(
    hypothesis: dict[str, Any], parsed_table: ParsedDocxTable
) -> GeometryValidationResult:
    """Validate a table-structure hypothesis against physical geometry.

    Pure and deterministic. The result's ``status`` is the worst outcome across
    the three rules: rule-2 findings (anchor conservation) promote to
    ``invalidated``; rule-1/rule-3 findings yield ``partial_conflict`` with the
    offending cells in ``conflict_cells``; an absence of findings is ``issued``.
    All findings are always reported in ``reasons`` for auditability regardless
    of the final status.
    """
    geo = _geometry(parsed_table)
    reasons: list[GeometryValidationReason] = []
    cells_counts: Counter[tuple[int, int]] = Counter()
    merge_counts: Counter[tuple[int, int]] = Counter()

    # Rule 1a/1b: per-cell coordinate sweep. Every canonical reference also
    # feeds the role-declaration counter (rule 2, dimension A).
    for entry in hypothesis.get("cells", []) or []:
        if not isinstance(entry, dict):
            reasons.append(
                GeometryValidationReason(CODE_COORD_OUT_OF_BOUNDS, (), detail=f"malformed_cell_entry={entry!r}")
            )
            continue
        reason, coord = _check_coordinate(geo, entry.get("coordinate"))
        if reason is not None:
            reasons.append(reason)
        if coord is not None:
            cells_counts[coord] += 1

    # Rules 1c + 3: semantic-merge groups. Every canonical member reference
    # feeds the merge-membership counter (rule 2, dimension B): an anchor may
    # belong to at most one group.
    for merge in hypothesis.get("semantic_merges", []) or []:
        if not isinstance(merge, dict):
            continue
        group_raw = merge.get("coordinates", []) or []
        for reason in _check_semantic_merge(geo, list(group_raw)):
            reasons.append(reason)
        for raw in group_raw:
            coord = _coord(raw)
            if coord is not None and coord in geo.canonical:
                merge_counts[coord] += 1

    # Rule 2: anchor conservation (evaluated last; its findings override status).
    reasons.extend(_check_anchor_conservation(geo, cells_counts, merge_counts))

    if any(reason.code in _INVALIDATING_CODES for reason in reasons):
        status = INVALIDATED
    elif reasons:
        status = PARTIAL_CONFLICT
    else:
        status = ISSUED

    # De-duplicate conflict cells (rule 1c/3 name whole groups; rule 1a/1b name
    # individual coords) preserving deterministic row-major order.
    seen: set[tuple[int, int]] = set()
    conflict_cells: list[tuple[int, int]] = []
    for reason in reasons:
        for cell in reason.cells:
            if cell not in seen:
                seen.add(cell)
                conflict_cells.append(cell)
    conflict_cells.sort()

    return GeometryValidationResult(
        status=status,
        conflict_cells=tuple(conflict_cells),
        reasons=tuple(reasons),
    )


__all__ = [
    "TABLE_GEOMETRY_VALIDATOR_VERSION",
    "TABLE_STRUCTURE_HYPOTHESIS_VERSION",
    "GeometryValidationReason",
    "GeometryValidationResult",
    "validate_table_geometry",
]
