"""TDD tests for table_geometry_validator.py (WS1 weeks 1-2).

The validator is the deterministic signing authority of the future LLM proposer
track. These tests pin the three rule classes mandated by the handoff brief and
the implementation plan (§3.1.2):

* coordinate consistency  — references stay in-matrix / canonical; a semantic
  merge group does not cross a vMerge physical boundary;
* merge-anchor conservation — each physical merge anchor is consumed exactly
  once; a non-empty difference set invalidates the WHOLE hypothesis;
* protected-encoding zero drift — OBIS / hex / event-code tokens are compared
  verbatim across a semantic merge (reusing extract-stage guards).

Output is three-state: issued / partial_conflict (with conflict-cell set) /
invalidated. Tests are written first and RED until the module exists.
"""
from __future__ import annotations

import unittest

from docx import Document  # type: ignore[import-not-found]

from docx_table_parser import (
    ParsedCell,
    ParsedCellContent,
    ParsedDocxTable,
    parse_docx_table,
)
from table_geometry_validator import (
    TABLE_GEOMETRY_VALIDATOR_VERSION,
    TABLE_STRUCTURE_HYPOTHESIS_VERSION,
    validate_table_geometry,
)


# --- fixture helpers ---------------------------------------------------------


def _cell(
    r: int,
    c: int,
    text: str,
    *,
    row_span: int = 1,
    column_span: int = 1,
    covered: tuple[tuple[int, int], ...] = (),
) -> ParsedCell:
    return ParsedCell(
        row_index=r,
        column_index=c,
        text=text,
        raw_text=text,
        row_span=row_span,
        column_span=column_span,
        covered_coordinates=covered,
        content=ParsedCellContent((), 0),
        style_evidence={},
    )


def _table(
    matrix: list[list[str]],
    cells: list[ParsedCell],
    merge_ranges: list[tuple[int, int, int, int]] | None = None,
) -> ParsedDocxTable:
    width = max((len(row) for row in matrix), default=0)
    return ParsedDocxTable(
        width=width,
        matrix=[list(row) for row in matrix],
        raw_matrix=[list(row) for row in matrix],
        cells={(cell.row_index, cell.column_index): cell for cell in cells},
        merge_ranges=list(merge_ranges or []),
        explicit_header_rows=[],
        nested_tables=[],
        parse_incomplete=False,
        parse_incomplete_reason={},
        raw_text="",
    )


def _hyp(
    cells: list[tuple[int, int, str]] | None = None,
    merges: list[list[tuple[int, int]]] | None = None,
    header_levels: int = 1,
) -> dict:
    """Build a minimal valid hypothesis. cells = [(r, c, role), ...]."""
    return {
        "schema": TABLE_STRUCTURE_HYPOTHESIS_VERSION,
        "table_structure_version": "table-structure-v7",
        "header_level_count": header_levels,
        "cells": [
            {"coordinate": [r, c], "role": role, "confidence": "high"}
            for (r, c, role) in (cells or [])
        ],
        "semantic_merges": [{"coordinates": [list(rc) for rc in group]} for group in (merges or [])],
    }


# --- issued (happy path) -----------------------------------------------------


class IssuedTests(unittest.TestCase):
    def test_plain_table_no_merges_signs(self) -> None:
        parsed = _table(
            [["H1", "H2"], ["v1", "v2"]],
            [_cell(1, 1, "H1"), _cell(1, 2, "H2"), _cell(2, 1, "v1"), _cell(2, 2, "v2")],
        )
        result = validate_table_geometry(
            _hyp(
                [(1, 1, "header"), (1, 2, "header"), (2, 1, "data"), (2, 2, "data")],
                header_levels=1,
            ),
            parsed,
        )
        self.assertEqual(result.status, "issued")
        self.assertEqual(result.conflict_cells, ())
        self.assertTrue(result.is_issued)
        self.assertEqual(result.version, TABLE_GEOMETRY_VALIDATOR_VERSION)

    def test_anchor_only_reference_to_vmerge_is_canonical_and_ok(self) -> None:
        # vMerge anchor (1,1) covers (2,1); referencing only the anchor is the
        # correct canonical way to refer to the whole merged cell.
        parsed = _table(
            [["A", "B"], ["", "v"]],
            [
                _cell(1, 1, "A", row_span=2, covered=((2, 1),)),
                _cell(1, 2, "B"),
                _cell(2, 2, "v"),
            ],
            merge_ranges=[(1, 1, 2, 1)],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "row_header"), (1, 2, "header"), (2, 2, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "issued")


# --- Rule 1: coordinate consistency ------------------------------------------


class CoordinateConsistencyTests(unittest.TestCase):
    def test_coordinate_out_of_bounds(self) -> None:
        parsed = _table(
            [["H1", "H2"], ["v1", "v2"]],
            [_cell(1, 1, "H1"), _cell(1, 2, "H2"), _cell(2, 1, "v1"), _cell(2, 2, "v2")],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "header"), (5, 1, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertIn((5, 1), result.conflict_cells)
        self.assertTrue(any(r.code == "coordinate_out_of_bounds" for r in result.reasons))

    def test_coordinate_references_covered_cell_is_not_canonical(self) -> None:
        # Horizontal merge anchor (1,1) covers (1,2). (1,2) is not a canonical
        # cell and must not be referenced as if it were independent. The anchor
        # (1,1) itself is referenced once so rule 2 stays quiet and rule 1b is
        # the only finding.
        parsed = _table(
            [["A", ""], ["v1", "v2"]],
            [
                _cell(1, 1, "A", column_span=2, covered=((1, 2),)),
                _cell(2, 1, "v1"),
                _cell(2, 2, "v2"),
            ],
            merge_ranges=[(1, 1, 1, 2)],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "header"), (1, 2, "header"), (2, 1, "data"), (2, 2, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertIn((1, 2), result.conflict_cells)
        self.assertTrue(any(r.code == "coordinate_not_canonical" for r in result.reasons))

    def test_coordinate_in_width_but_absent_is_not_canonical(self) -> None:
        # (2, 3) is within declared width 3 but is not a real cell here.
        parsed = _table(
            [["H1", "H2", ""], ["v1", "v2", ""]],
            [_cell(1, 1, "H1"), _cell(1, 2, "H2"), _cell(2, 1, "v1"), _cell(2, 2, "v2")],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "header"), (2, 3, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertIn((2, 3), result.conflict_cells)

    def test_semantic_merge_crosses_vmerge_boundary(self) -> None:
        # Column 1: vMerge A anchor (1,1) row_span 2 covers (2,1); then a
        # separate standalone cell at (3,1). A semantic merge that joins the
        # vMerge anchor with the out-of-region cell crosses the boundary.
        parsed = _table(
            [["A", "h1"], ["", "h2"], ["B", "h3"]],
            [
                _cell(1, 1, "A", row_span=2, covered=((2, 1),)),
                _cell(1, 2, "h1"),
                _cell(2, 2, "h2"),
                _cell(3, 1, "B"),
                _cell(3, 2, "h3"),
            ],
            merge_ranges=[(1, 1, 2, 1)],
        )
        result = validate_table_geometry(
            _hyp(
                [(1, 1, "row_header"), (3, 1, "row_header"), (1, 2, "header")],
                merges=[[(1, 1), (3, 1)]],
            ),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        codes = {r.code for r in result.reasons}
        self.assertIn("semantic_merge_crosses_vmerge", codes)
        # both group members are surfaced as the suspect merge
        self.assertIn((1, 1), result.conflict_cells)
        self.assertIn((3, 1), result.conflict_cells)

    def test_semantic_merge_within_same_column_no_vmerge_is_ok(self) -> None:
        # Same column, two standalone (non-merged) cells: no vMerge boundary
        # exists, so grouping them does not cross anything.
        parsed = _table(
            [["A", "x"], ["B", "y"]],
            [_cell(1, 1, "A"), _cell(1, 2, "x"), _cell(2, 1, "B"), _cell(2, 2, "y")],
        )
        result = validate_table_geometry(
            _hyp(
                [(1, 1, "data"), (2, 1, "data"), (1, 2, "header"), (2, 2, "header")],
                merges=[[(1, 1), (2, 1)]],
            ),
            parsed,
        )
        self.assertEqual(result.status, "issued")

    def test_semantic_merge_crosses_between_two_distinct_vmerges(self) -> None:
        # Column 1: vMerge A [1,2] anchor (1,1); vMerge B [3,4] anchor (3,1).
        # Both anchors are canonical; joining them in one semantic merge bridges
        # across the two physically-separate vertical merges.
        parsed = _table(
            [["A", "x"], ["", "x"], ["B", "x"], ["", "x"]],
            [
                _cell(1, 1, "A", row_span=2, covered=((2, 1),)),
                _cell(1, 2, "x"),
                _cell(2, 2, "x"),
                _cell(3, 1, "B", row_span=2, covered=((4, 1),)),
                _cell(3, 2, "x"),
                _cell(4, 2, "x"),
            ],
            merge_ranges=[(1, 1, 2, 1), (3, 1, 4, 1)],
        )
        result = validate_table_geometry(
            _hyp(
                [(1, 1, "row_header"), (3, 1, "row_header")],
                merges=[[(1, 1), (3, 1)]],
            ),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertTrue(any(r.code == "semantic_merge_crosses_vmerge" for r in result.reasons))


# --- Rule 2: merge-anchor conservation ---------------------------------------


class AnchorConservationTests(unittest.TestCase):
    def test_missing_anchor_invalidates_whole(self) -> None:
        # Physical horizontal merge anchor at (1,1) covering (1,2). Hypothesis
        # never references the anchor -> difference set non-empty -> invalidated.
        parsed = _table(
            [["A", ""], ["v1", "v2"]],
            [
                _cell(1, 1, "A", column_span=2, covered=((1, 2),)),
                _cell(2, 1, "v1"),
                _cell(2, 2, "v2"),
            ],
            merge_ranges=[(1, 1, 1, 2)],
        )
        result = validate_table_geometry(
            _hyp([(2, 1, "data"), (2, 2, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "invalidated")
        self.assertTrue(result.is_invalidated)
        self.assertTrue(any(r.code == "anchor_missing" for r in result.reasons))
        self.assertIn((1, 1), r_cells(r := result, "anchor_missing"))

    def test_double_anchor_attribution_invalidates_whole(self) -> None:
        parsed = _table(
            [["A", ""], ["v1", "v2"]],
            [
                _cell(1, 1, "A", column_span=2, covered=((1, 2),)),
                _cell(2, 1, "v1"),
                _cell(2, 2, "v2"),
            ],
            merge_ranges=[(1, 1, 1, 2)],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "header"), (1, 1, "data"), (2, 1, "data"), (2, 2, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "invalidated")
        self.assertTrue(any(r.code == "anchor_double_attribution" for r in result.reasons))

    def test_anchor_referenced_once_via_semantic_merge_is_ok(self) -> None:
        parsed = _table(
            [["A", ""], ["v1", "v2"]],
            [
                _cell(1, 1, "A", column_span=2, covered=((1, 2),)),
                _cell(2, 1, "v1"),
                _cell(2, 2, "v2"),
            ],
            merge_ranges=[(1, 1, 1, 2)],
        )
        result = validate_table_geometry(
            _hyp(
                [(2, 1, "data"), (2, 2, "data")],
                merges=[[(1, 1)]],  # not really a merge (single member) but counts as one reference
            ),
            parsed,
        )
        self.assertNotEqual(result.status, "invalidated")


# --- Rule 3: protected-encoding zero drift -----------------------------------


class ProtectedEncodingDriftTests(unittest.TestCase):
    def test_semantic_merge_fabricates_obis_at_boundary(self) -> None:
        # Two half-codes that combine at the concatenation boundary into a
        # fabricated OBIS not present in either member cell.
        parsed = _table(
            [["0-0:96.", "1.0"]],
            [_cell(1, 1, "0-0:96."), _cell(1, 2, "1.0")],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "data"), (1, 2, "data")], merges=[[(1, 1), (1, 2)]]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertTrue(any(r.code == "protected_encoding_drift" for r in result.reasons))
        self.assertIn((1, 1), result.conflict_cells)
        self.assertIn((1, 2), result.conflict_cells)

    def test_semantic_merge_alters_obis_value(self) -> None:
        # Merging "0-0:96.1.0" with ".255" turns the code into "0-0:96.1.0.255":
        # the original is destroyed and a different code is created.
        parsed = _table(
            [["0-0:96.1.0", ".255"]],
            [_cell(1, 1, "0-0:96.1.0"), _cell(1, 2, ".255")],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "data"), (1, 2, "data")], merges=[[(1, 1), (1, 2)]]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertTrue(any(r.code == "protected_encoding_drift" for r in result.reasons))

    def test_semantic_merge_preserves_obis_is_ok(self) -> None:
        # A label cell + an OBIS cell merged: the OBIS survives verbatim.
        parsed = _table(
            [["OBIS", "0-0:96.1.0"]],
            [_cell(1, 1, "OBIS"), _cell(1, 2, "0-0:96.1.0")],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "row_header"), (1, 2, "data")], merges=[[(1, 1), (1, 2)]]),
            parsed,
        )
        self.assertNotIn(
            "protected_encoding_drift",
            {r.code for r in result.reasons},
        )

    def test_hex_drift_detected(self) -> None:
        # "0x1" + "F" fabricates "0x1F" at the boundary.
        parsed = _table(
            [["0x1", "F"]],
            [_cell(1, 1, "0x1"), _cell(1, 2, "F")],
        )
        result = validate_table_geometry(
            _hyp([(1, 1, "data"), (1, 2, "data")], merges=[[(1, 1), (1, 2)]]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertTrue(any(r.code == "protected_encoding_drift" for r in result.reasons))


# --- precedence / aggregation ------------------------------------------------


class PrecedenceTests(unittest.TestCase):
    def test_invalidated_overrides_local_conflicts(self) -> None:
        # Both a coordinate-out-of-bounds AND a missing anchor: rule 2 promotes
        # the result to invalidated, but the local conflict is still reported.
        parsed = _table(
            [["A", ""], ["v1", "v2"]],
            [
                _cell(1, 1, "A", column_span=2, covered=((1, 2),)),
                _cell(2, 1, "v1"),
                _cell(2, 2, "v2"),
            ],
            merge_ranges=[(1, 1, 1, 2)],
        )
        result = validate_table_geometry(
            _hyp([(9, 9, "data"), (2, 1, "data"), (2, 2, "data")]),
            parsed,
        )
        self.assertEqual(result.status, "invalidated")
        codes = {r.code for r in result.reasons}
        self.assertIn("anchor_missing", codes)
        self.assertIn("coordinate_out_of_bounds", codes)

    def test_multiple_local_conflicts_aggregate(self) -> None:
        parsed = _table(
            [["H1", "H2"], ["v1", "v2"]],
            [_cell(1, 1, "H1"), _cell(1, 2, "H2"), _cell(2, 1, "v1"), _cell(2, 2, "v2")],
        )
        result = validate_table_geometry(
            _hyp([(5, 1, "data"), (1, 9, "header")]),
            parsed,
        )
        self.assertEqual(result.status, "partial_conflict")
        self.assertIn((5, 1), result.conflict_cells)
        self.assertIn((1, 9), result.conflict_cells)


# --- real-parser end-to-end (input contract binding) ------------------------


class RealParserContractTests(unittest.TestCase):
    def test_real_docx_horizontal_merge_signs(self) -> None:
        document = Document()
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Header"
        table.cell(0, 1).text = "Value"
        table.cell(1, 0).text = "The meter shall retain records."
        table.cell(1, 1).text = "230 V"
        parsed = parse_docx_table(table)

        # Annotate each canonical anchor exactly once; no semantic merges.
        cells = [(c.row_index, c.column_index, "data") for c in parsed.cells.values()]
        result = validate_table_geometry(_hyp(cells, header_levels=1), parsed)
        self.assertEqual(result.status, "issued")


# --- small helper used inside the test module --------------------------------


def r_cells(result, code: str) -> tuple[tuple[int, int], ...]:
    for reason in result.reasons:
        if reason.code == code:
            return reason.cells
    return ()


if __name__ == "__main__":
    unittest.main()
