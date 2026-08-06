"""Excel semantic region detection — WS1 wk7 (plan §3.2.3).

Two deterministic services for the XLSX parser, both pure and side-effect free:

1. **Region boundary validation** — given the table regions a sheet was split
   into plus the sheet's native merge ranges, verify (a) no two regions
   overlap and (b) no region boundary cuts through a native merged cell. A
   cut merge would silently split one physical cell across two "tables",
   breaking the cell-conservation invariant the rest of the pipeline relies
   on. Failures are reported as a structured conflict set the caller routes
   to the human review panel via the existing ``record_table_geometry_conflicts``
   channel (WS1 wk3-5) OR marks honestly via ``parse_incomplete_reason`` — no
   new artifact format is invented.

2. **Multi-sheet OBIS linkage** — given per-sheet OBIS-key fingerprints,
   verify cross-sheet consistency BEFORE any merge is committed. The brief
   mandates: OBIS keys missing / conflicting ⇒ report honestly, never merge
   silently. This module returns a ``mergeable`` flag plus an explicit
   conflict list; ``xlsx_parser`` records the outcome through the existing
   ``parse_incomplete_reason`` channel. The merge itself stays the caller's
   decision — this is the deterministic gate, not the merge executor.

A region-hypothesis LLM hook (``propose_regions_llm``) is provided stub-first:
it returns ``unavailable`` unless a real ``chat`` callable is supplied, and
tests inject fakes. The deterministic ``_sheet_table_regions`` path remains
the default; the LLM hook is a future opt-in and is NOT invoked by
``xlsx_parser`` in this slice.

Hard contract: no LLM is called by default; no new artifact format; no
behaviour-version bump (the gate is read-only auditing over the existing
region/merge model).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from cosem_behavior_spec import extract_codes

XLSX_REGION_DETECT_VERSION = "xlsx-region-detect-v1"
XLSX_REGION_LLM_PROPOSER_VERSION = "xlsx-region-llm-proposer-v1"

# Boundary-conflict reason codes. These travel inside the existing
# ``parse_incomplete_reason`` dict (code + sample), so they reuse the
# established audit channel rather than introducing a new format.
CODE_REGION_OVERLAP = "xlsx_region_overlap"
CODE_REGION_SPLITS_MERGE = "xlsx_region_splits_merge"

# Multi-sheet linkage outcomes.
LINK_LINKED = "linked"                # ≥2 tables share OBIS keys, no conflict → mergeable
LINK_SINGLE_SHEET = "single_sheet"    # fewer than 2 tables carry OBIS keys
LINK_KEY_MISSING = "key_missing"      # ≥2 keyed tables but zero shared keys across sheets
LINK_KEY_CONFLICT = "key_conflict"    # same OBIS key repeats inside one sheet's tables

# A region is (min_row, min_col, max_row, max_col), 1-based, sheet-absolute —
# the same shape ``xlsx_parser._sheet_table_regions`` already returns.
Region = tuple[int, int, int, int]


@dataclass(frozen=True)
class RegionBoundaryConflict:
    """One deterministic boundary finding.

    ``code`` is ``xlsx_region_overlap`` or ``xlsx_region_splits_merge``;
    ``regions`` are the sheet-absolute region boxes involved;
    ``merge_range`` is the native merge that got split (only for
    ``splits_merge``); ``detail`` is a short stable audit string.
    """

    code: str
    regions: tuple[Region, ...]
    merge_range: Region | None = None
    detail: str = ""


@dataclass(frozen=True)
class RegionBoundaryCheck:
    status: str  # "ok" | "conflict"
    conflicts: tuple[RegionBoundaryConflict, ...] = ()
    version: str = XLSX_REGION_DETECT_VERSION

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


# --- geometry helpers --------------------------------------------------------


def _rectangles_overlap(a: Region, b: Region) -> bool:
    """Two sheet-absolute region boxes share at least one cell."""
    a_min_row, a_min_col, a_max_row, a_max_col = a
    b_min_row, b_min_col, b_max_row, b_max_col = b
    if a_max_row < b_min_row or b_max_row < a_min_row:
        return False
    if a_max_col < b_min_col or b_max_col < a_min_col:
        return False
    return True


def _region_contains(region: Region, box: Region) -> bool:
    """``region`` fully contains ``box`` (both sheet-absolute)."""
    r_min_row, r_min_col, r_max_row, r_max_col = region
    b_min_row, b_min_col, b_max_row, b_max_col = box
    return (
        r_min_row <= b_min_row
        and r_min_col <= b_min_col
        and r_max_row >= b_max_row
        and r_max_col >= b_max_col
    )


def _region_intersects(region: Region, box: Region) -> bool:
    return _rectangles_overlap(region, box)


# --- rule 1: regions do not overlap -----------------------------------------


def _check_overlap(regions: list[Region]) -> list[RegionBoundaryConflict]:
    conflicts: list[RegionBoundaryConflict] = []
    indexed = sorted(set(regions))
    for i in range(len(indexed)):
        for j in range(i + 1, len(indexed)):
            if _rectangles_overlap(indexed[i], indexed[j]):
                conflicts.append(
                    RegionBoundaryConflict(
                        code=CODE_REGION_OVERLAP,
                        regions=(indexed[i], indexed[j]),
                        detail=(
                            f"regions overlap: {indexed[i]} ∩ {indexed[j]}"
                        ),
                    )
                )
    return conflicts


# --- rule 2: no region boundary cuts a native merge -------------------------


def _check_split_merge(
    regions: list[Region], merge_ranges: list[Region]
) -> list[RegionBoundaryConflict]:
    """Each native merge must live entirely inside ONE region.

    A merge ``box`` is "cut" if it intersects more than one region (its anchor
    and at least one covered coordinate land in different regions), or if it
    intersects a region without being fully contained by it (the boundary
    slices through the merged cell). Either case splits one physical cell
    across tables and breaks cell conservation.
    """
    conflicts: list[RegionBoundaryConflict] = []
    for merge in sorted(set(merge_ranges)):
        touching = [region for region in regions if _region_intersects(region, merge)]
        if not touching:
            # Merge outside every region is not a region-detection problem
            # (e.g. a merge in a blank area the caller chose not to table).
            continue
        if len(touching) > 1 or not any(_region_contains(r, merge) for r in touching):
            conflicts.append(
                RegionBoundaryConflict(
                    code=CODE_REGION_SPLITS_MERGE,
                    regions=tuple(touching),
                    merge_range=merge,
                    detail=(
                        f"merge {merge} split across regions: "
                        f"{[r for r in touching]}"
                    ),
                )
            )
    return conflicts


def validate_region_boundaries(
    regions: Iterable[Region],
    merge_ranges: Iterable[Region],
) -> RegionBoundaryCheck:
    """Deterministic boundary gate: regions don't overlap / don't cut merges.

    Pure. Read-only over the caller's region + merge model — it neither
    re-derives regions nor mutates them. The caller routes ``conflicts`` to
    the human panel (``record_table_geometry_conflicts``) or marks
    ``parse_incomplete_reason`` honestly.
    """
    region_list = [tuple(r) for r in regions]  # type: ignore[misc]
    merge_list = [tuple(m) for m in merge_ranges]  # type: ignore[misc]
    conflicts = _check_overlap(region_list) + _check_split_merge(region_list, merge_list)
    if conflicts:
        return RegionBoundaryCheck(status="conflict", conflicts=tuple(conflicts))
    return RegionBoundaryCheck(status="ok", conflicts=())


def boundary_conflicts_to_audit(
    check: RegionBoundaryCheck,
    *,
    sheet_name: str,
) -> dict[str, Any] | None:
    """Render a ``check`` as a ``parse_incomplete_reason`` payload (existing format).

    Returns ``None`` when the check passed — the caller then leaves the audit
    untouched (no spurious ``parse_incomplete``). Reuses the established
    ``code`` + ``sample`` shape so no new artifact format is introduced.
    """
    if check.is_ok:
        return None
    overlap = [c for c in check.conflicts if c.code == CODE_REGION_OVERLAP]
    splits = [c for c in check.conflicts if c.code == CODE_REGION_SPLITS_MERGE]
    reasons: list[dict[str, Any]] = []
    if overlap:
        reasons.append({
            "code": CODE_REGION_OVERLAP,
            "count": len(overlap),
            "sample": [
                {"regions": [list(r) for r in c.regions]} for c in overlap[:5]
            ],
        })
    if splits:
        reasons.append({
            "code": CODE_REGION_SPLITS_MERGE,
            "count": len(splits),
            "sample": [
                {"merge_range": list(c.merge_range) if c.merge_range else []}
                for c in splits[:5]
            ],
        })
    return {
        "code": "xlsx_region_boundary_conflict",
        "sheet_name": str(sheet_name),
        "overlap_count": len(overlap),
        "split_merge_count": len(splits),
        "reasons": reasons,
    }


# --- OBIS key extraction -----------------------------------------------------


def extract_obis_keys_from_matrix(matrix: Iterable[Iterable[str]]) -> frozenset[str]:
    """Deterministic OBIS-key fingerprint of a table region.

    Sweeps every cell with the extract-stage ``extract_codes`` guard (OBIS
    ``\\d+-\\d+:\\d+(?:\\.\\d+)+``, the ``G..-SG..-E..`` form, and hex). The
    returned frozenset is the table's identity for cross-sheet linkage. Empty
    for tables that carry no protected encoding (the common case — most sheets
    are not OBIS tables).
    """
    keys: set[str] = set()
    for row in matrix or []:
        for value in row or []:
            if value is None:
                continue
            keys |= extract_codes(str(value))
    return frozenset(keys)


@dataclass(frozen=True)
class SheetTableFingerprint:
    """One table's OBIS fingerprint within a sheet."""

    sheet_name: str
    table_id: str
    obis_keys: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_keys(self) -> bool:
        return bool(self.obis_keys)


@dataclass(frozen=True)
class MultiSheetLinkResult:
    status: str  # LINK_*
    join_key: str  # "obis"
    sheet_count: int
    table_count: int
    keyed_table_count: int
    conflicts: tuple[dict[str, Any], ...] = ()
    mergeable: bool = False
    version: str = XLSX_REGION_DETECT_VERSION

    @property
    def is_linked(self) -> bool:
        return self.status == LINK_LINKED


def link_multi_sheet_tables(
    fingerprints: list[SheetTableFingerprint],
    *,
    join_key: str = "obis",
) -> MultiSheetLinkResult:
    """Cross-sheet OBIS consistency gate.

    Deterministic. The merge is allowed (``mergeable=True``) ONLY when at
    least two tables across at least two sheets share OBIS keys and no key
    repeats inside one sheet. Otherwise the outcome is reported honestly:

    * fewer than two keyed tables, or all keyed tables on one sheet →
      ``single_sheet`` (nothing to link; not an error);
    * ≥2 keyed tables on ≥2 sheets but zero shared keys across sheets →
      ``key_missing`` (claimed multi-sheet but no joinable key);
    * the same OBIS key appears in two tables on the SAME sheet →
      ``key_conflict`` (a sheet-internal duplicate is ambiguous data; the
      merge is blocked and the duplicate is reported).

    The caller commits a cross-sheet merge only when ``mergeable`` is True;
    otherwise it records ``conflicts`` via the existing audit channel. This
    function never performs the merge itself.
    """
    table_count = len(fingerprints)
    sheet_names = {fp.sheet_name for fp in fingerprints}
    keyed = [fp for fp in fingerprints if fp.has_keys]

    if len(keyed) < 2 or len({fp.sheet_name for fp in keyed}) < 2:
        return MultiSheetLinkResult(
            status=LINK_SINGLE_SHEET,
            join_key=join_key,
            sheet_count=len(sheet_names),
            table_count=table_count,
            keyed_table_count=len(keyed),
        )

    # Sheet-internal duplicate keys = ambiguous data, blocks the merge.
    conflicts: list[dict[str, Any]] = []
    by_sheet: dict[str, list[SheetTableFingerprint]] = {}
    for fp in keyed:
        by_sheet.setdefault(fp.sheet_name, []).append(fp)
    for sheet_name, fps in by_sheet.items():
        if len(fps) < 2:
            continue
        seen: dict[str, list[str]] = {}
        for fp in fps:
            for key in fp.obis_keys:
                seen.setdefault(key, []).append(fp.table_id)
        for key, owners in seen.items():
            if len(set(owners)) > 1:
                conflicts.append({
                    "code": "obis_key_intra_sheet_duplicate",
                    "sheet_name": sheet_name,
                    "obis_key": key,
                    "table_ids": sorted(set(owners)),
                })

    if conflicts:
        return MultiSheetLinkResult(
            status=LINK_KEY_CONFLICT,
            join_key=join_key,
            sheet_count=len(sheet_names),
            table_count=table_count,
            keyed_table_count=len(keyed),
            conflicts=tuple(conflicts),
            mergeable=False,
        )

    # Cross-sheet shared keys = linkage candidates.
    shared: set[str] = set()
    sheet_keys = {
        sheet_name: frozenset().union(*(fp.obis_keys for fp in fps))
        for sheet_name, fps in by_sheet.items()
    }
    sheet_list = sorted(sheet_keys)
    for i in range(len(sheet_list)):
        for j in range(i + 1, len(sheet_list)):
            shared |= sheet_keys[sheet_list[i]] & sheet_keys[sheet_list[j]]

    if not shared:
        missing_conflicts = [
            {
                "code": "obis_no_shared_key",
                "sheets": sheet_list,
                "key_counts": {s: len(sheet_keys[s]) for s in sheet_list},
            }
        ]
        return MultiSheetLinkResult(
            status=LINK_KEY_MISSING,
            join_key=join_key,
            sheet_count=len(sheet_names),
            table_count=table_count,
            keyed_table_count=len(keyed),
            conflicts=tuple(missing_conflicts),
            mergeable=False,
        )

    return MultiSheetLinkResult(
        status=LINK_LINKED,
        join_key=join_key,
        sheet_count=len(sheet_names),
        table_count=table_count,
        keyed_table_count=len(keyed),
        conflicts=(),
        mergeable=True,
    )


def link_result_to_audit(result: MultiSheetLinkResult) -> dict[str, Any] | None:
    """Render a non-linked result as a ``parse_incomplete_reason`` payload.

    Returns ``None`` for ``single_sheet`` and ``linked`` (no audit signal —
    single-sheet is normal and a clean link is success). Only
    ``key_missing`` / ``key_conflict`` produce an honest audit payload, so a
    cross-sheet merge is never committed silently.
    """
    if result.is_linked or result.status == LINK_SINGLE_SHEET:
        return None
    return {
        "code": "xlsx_multi_sheet_link_blocked",
        "status": result.status,
        "join_key": result.join_key,
        "sheet_count": result.sheet_count,
        "table_count": result.table_count,
        "keyed_table_count": result.keyed_table_count,
        "conflicts": [dict(c) for c in result.conflicts],
    }


# --- LLM region-hypothesis hook (stub-first) ---------------------------------


@dataclass(frozen=True)
class RegionLLMResult:
    """Outcome of the (opt-in) LLM region hypothesis.

    ``status`` is ``proposed`` (a region hypothesis was produced — still
    subject to ``validate_region_boundaries`` before use) or ``unavailable``
    (no chat supplied / stub route / any error). The proposer never signs a
    region decision; the deterministic boundary gate does.
    """

    status: str
    regions: tuple[Region, ...] = ()
    reason: str = ""
    proposer_version: str = XLSX_REGION_LLM_PROPOSER_VERSION

    @property
    def is_proposed(self) -> bool:
        return self.status == "proposed"

    @property
    def is_unavailable(self) -> bool:
        return self.status == "unavailable"


def propose_regions_llm(
    sheet_matrix: list[list[str]],
    *,
    chat: Callable[..., Any] | None = None,
) -> RegionLLMResult:
    """Opt-in LLM region hypothesis. STUB-FIRST; never called by default.

    Without an explicit ``chat`` callable this returns ``unavailable`` — the
    deterministic ``xlsx_parser._sheet_table_regions`` path is the production
    default and this hook is a future opt-in. Even with a ``chat`` callable,
    any error / empty response returns ``unavailable`` honestly; a proposal
    is ALWAYS re-validated by ``validate_region_boundaries`` before it can
    affect parsing (the LLM never signs a region decision).

    Tests inject a fake ``chat``; no real LLM is called.
    """
    if chat is None:
        return RegionLLMResult(status="unavailable", reason="no_chat_supplied")
    try:
        payload = chat(sheet_matrix)
    except Exception as exc:  # pragma: no cover - defensive; tests inject fakes
        return RegionLLMResult(
            status="unavailable", reason=f"chat_error:{type(exc).__name__}"
        )
    if not payload:
        return RegionLLMResult(status="unavailable", reason="empty_response")
    raw_regions = payload.get("regions") if isinstance(payload, dict) else None
    if not raw_regions or not isinstance(raw_regions, list):
        return RegionLLMResult(status="unavailable", reason="malformed_response")
    regions: list[Region] = []
    for entry in raw_regions:
        try:
            r1, c1, r2, c2 = (int(v) for v in entry)
        except (TypeError, ValueError):
            return RegionLLMResult(status="unavailable", reason="malformed_region")
        if r1 >= 1 and c1 >= 1 and r2 >= r1 and c2 >= c1:
            regions.append((r1, c1, r2, c2))
    if not regions:
        return RegionLLMResult(status="unavailable", reason="no_valid_regions")
    return RegionLLMResult(status="proposed", regions=tuple(regions))


__all__ = [
    "XLSX_REGION_DETECT_VERSION",
    "XLSX_REGION_LLM_PROPOSER_VERSION",
    "CODE_REGION_OVERLAP",
    "CODE_REGION_SPLITS_MERGE",
    "LINK_LINKED",
    "LINK_SINGLE_SHEET",
    "LINK_KEY_MISSING",
    "LINK_KEY_CONFLICT",
    "RegionBoundaryConflict",
    "RegionBoundaryCheck",
    "SheetTableFingerprint",
    "MultiSheetLinkResult",
    "RegionLLMResult",
    "validate_region_boundaries",
    "boundary_conflicts_to_audit",
    "extract_obis_keys_from_matrix",
    "link_multi_sheet_tables",
    "link_result_to_audit",
    "propose_regions_llm",
]
