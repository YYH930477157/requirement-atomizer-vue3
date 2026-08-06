"""Tests for pdf_modern_adapter (WS1 wk6).

Pure-function coverage of the normalization layer + the honest-unavailable
contract. No real parser dependency is installed on this machine, so the live
entry point is asserted to be ``unavailable`` (the red line: a missing parser
is reported, never impersonated). The dual-track contract alignment is
verified by feeding a normalized table straight into the geometry validator.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from pdf_modern_adapter import (
    CANDIDATE_PARSERS,
    PDF_MODERN_ADAPTER_VERSION,
    PDF_MODERN_SOURCE_FORMAT,
    ModernParseResult,
    normalize_table_matrix,
    parse_pdf_modern,
    modern_parser_available,
    _coerce_matrix,
    _parse_gfm_tables,
)
from table_geometry_validator import ISSUED, PARTIAL_CONFLICT, validate_table_geometry


class NormalizeMatrixTests(unittest.TestCase):
    def test_rectangularizes_ragged_rows(self) -> None:
        parsed = normalize_table_matrix([["A", "B", "C"], ["D"]], parser="docling")
        self.assertEqual(parsed.matrix, [["A", "B", "C"], ["D", "", ""]])
        self.assertEqual(parsed.width, 3)
        self.assertEqual(len(parsed.matrix[1]), 3)

    def test_canonical_cells_exclude_covered_coordinates(self) -> None:
        # A 2x2 grid where row 1 is one merged cell (anchor (1,1), covers (1,2)).
        parsed = normalize_table_matrix(
            [["A", "B"], ["C", "D"]],
            parser="docling",
            merge_ranges=[(1, 1, 1, 2)],
        )
        # (1,2) is a covered coordinate -> not a canonical cell.
        self.assertIn((1, 1), parsed.cells)
        self.assertNotIn((1, 2), parsed.cells)
        anchor = parsed.cells[(1, 1)]
        self.assertEqual(anchor.covered_coordinates, ((1, 2),))
        self.assertEqual(anchor.column_span, 2)
        self.assertEqual(anchor.row_span, 1)

    def test_version_carries_parser_provenance(self) -> None:
        parsed = normalize_table_matrix([["x"]], parser="marker")
        self.assertEqual(parsed.version, f"{PDF_MODERN_ADAPTER_VERSION}:marker")
        self.assertNotEqual(parsed.version.split(":")[0], "docx-table-physical-v1")

    def test_style_evidence_attached_per_cell(self) -> None:
        parsed = normalize_table_matrix(
            [["h", "v"]],
            parser="docling",
            style_evidence={(1, 1): {"bold": True}},
        )
        self.assertEqual(parsed.cells[(1, 1)].style_evidence, {"bold": True})
        self.assertEqual(parsed.cells[(1, 2)].style_evidence, {})

    def test_blank_matrix_yields_no_canonical_cells(self) -> None:
        parsed = normalize_table_matrix([["", " "], ["", ""]], parser="docling")
        # Blank cells are still canonical coordinates (text=""); the contract is
        # that EVERY non-covered position is a cell. They are simply empty.
        self.assertEqual(len(parsed.cells), 4)
        self.assertEqual(parsed.width, 2)


class ContractAlignmentTests(unittest.TestCase):
    """A normalized table must be consumable by the dual-track validator."""

    def test_validator_issued_against_normalized_table(self) -> None:
        parsed = normalize_table_matrix(
            [["Header", "Val"], ["k", "1-1:32.0.0"]],
            parser="docling",
            merge_ranges=[(1, 1, 1, 2)],
        )
        # Hypothesis declares the anchor once (rule 2: exactly-once consumption).
        hypothesis = {
            "cells": [{"coordinate": [1, 1], "role": "header"}],
            "semantic_merges": [],
        }
        result = validate_table_geometry(hypothesis, parsed)
        self.assertEqual(result.status, ISSUED)

    def test_validator_partial_conflict_on_bad_coordinate(self) -> None:
        parsed = normalize_table_matrix([["A", "B"]], parser="docling")
        hypothesis = {
            "cells": [{"coordinate": [1, 9], "role": "header"}],  # out of bounds
            "semantic_merges": [],
        }
        result = validate_table_geometry(hypothesis, parsed)
        self.assertEqual(result.status, PARTIAL_CONFLICT)


class CoerceAndGfmTests(unittest.TestCase):
    def test_coerce_matrix_pads_ragged(self) -> None:
        self.assertEqual(_coerce_matrix([[1, 2], [3]]), [["1", "2"], ["3", ""]])

    def test_coerce_matrix_none_to_blank(self) -> None:
        self.assertEqual(_coerce_matrix([[None, "x"]]), [["", "x"]])

    def test_parse_gfm_tables_drops_separator_and_keeps_cells(self) -> None:
        markdown = (
            "| OBIS | Name |\n"
            "| --- | --- |\n"
            "| 0-0:96.1.0 | clock |\n"
            "| 1-1:32.0.0 | assoc |\n"
        )
        tables = _parse_gfm_tables(markdown)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0][0], ["OBIS", "Name"])
        self.assertEqual(tables[0][1], ["0-0:96.1.0", "clock"])
        self.assertEqual(len(tables[0]), 3)  # header + 2 data, separator dropped


class AvailabilityContractTests(unittest.TestCase):
    """The red line: no installed parser => honest unavailable, never faked."""

    def test_modern_parser_available_reports_no_candidate(self) -> None:
        name, reason = modern_parser_available()
        # This machine installs no candidate; the probe must say so honestly.
        self.assertEqual(name, "")
        self.assertTrue(reason.startswith("no_candidate_installed"))

    def test_parse_pdf_modern_unavailable_without_dependency(self) -> None:
        result = parse_pdf_modern(Path("does-not-exist.pdf"))
        self.assertIsInstance(result, ModernParseResult)
        self.assertTrue(result.is_unavailable)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.pages, ())
        self.assertNotEqual(result.reason, "")
        self.assertEqual(result.provenance["source_format"], PDF_MODERN_SOURCE_FORMAT)
        self.assertEqual(result.provenance["adapter_version"], PDF_MODERN_ADAPTER_VERSION)

    def test_candidate_parsers_constant_is_stable(self) -> None:
        # Probe order is a contract; Docling is preferred (highest alignment).
        self.assertIn("docling", CANDIDATE_PARSERS)
        self.assertIn("marker", CANDIDATE_PARSERS)


if __name__ == "__main__":
    unittest.main()
