"""Tests for the WS1 dual-track additions (weeks 3-5).

Three areas:
  1. Table-family template library (table_family_templates.py) — load + match.
  2. table_structure.py dual-track entry (analyze_table_dual_track /
     structure_from_hypothesis / dual_track_enabled) — switch off → old path; switch
     on + signed hypothesis → hypothesis-derived structure; switch on + validation
     failure → deterministic fallback + conflict metadata for the panel.
  3. table_review_state.py degradation exit — geometry-conflict registry round-trip,
     read-path surfacing, and isomorphic writeback clearance.

The default-OFF switch is asserted throughout: the production path (analyze_table) is
byte-identical unless RATOMIZER_TABLE_DUAL_TRACK is set. No real LLM is called.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx_table_parser import (
    ParsedCell,
    ParsedCellContent,
    ParsedDocxTable,
)
from output_writer import write_jsonl
from requirement_kb import KnowledgeRepository
from result_package import governed_artifact_path, resolve_analysis_root
from table_dispositions import build_table_cell_dispositions
from table_geometry_validator import (
    ISSUED,
    PARTIAL_CONFLICT,
    INVALIDATED,
    validate_table_geometry,
)
from table_review_state import (
    apply_table_review_decision,
    build_table_review_payload,
    clear_table_geometry_conflicts,
    load_table_geometry_conflicts,
    record_table_geometry_conflicts,
    table_evidence_fingerprint,
)
from table_structure import (
    TABLE_DUAL_TRACK_SWITCH,
    TABLE_DUAL_TRACK_VERSION,
    analyze_table,
    analyze_table_dual_track,
    dual_track_enabled,
    structure_from_hypothesis,
)
from table_family_templates import (
    DEFAULT_FAMILY_TEMPLATES_PATH,
    load_table_family_templates,
    match_table_family,
)

from atomize import build_table_artifacts

KB = KnowledgeRepository.from_paths([])


# --- fixtures ----------------------------------------------------------------


def _cell(r: int, c: int, text: str, *, covered=()) -> ParsedCell:
    return ParsedCell(
        row_index=r,
        column_index=c,
        text=text,
        raw_text=text,
        covered_coordinates=covered,
        content=ParsedCellContent((), 0),
        style_evidence={"bold": False},
    )


def _plain_table() -> ParsedDocxTable:
    matrix = [["H1", "H2"], ["v1", "v2"]]
    cells = {
        (1, 1): _cell(1, 1, "H1"),
        (1, 2): _cell(1, 2, "H2"),
        (2, 1): _cell(2, 1, "v1"),
        (2, 2): _cell(2, 2, "v2"),
    }
    return ParsedDocxTable(
        width=2,
        matrix=[list(row) for row in matrix],
        raw_matrix=[list(row) for row in matrix],
        cells=cells,
        merge_ranges=[],
        explicit_header_rows=[],
        nested_tables=[],
        parse_incomplete=False,
        parse_incomplete_reason={},
        raw_text="",
    )


def _merged_anchor_table() -> ParsedDocxTable:
    # Row 1 col 1 is a vertical merge anchor covering (1,1) and (2,1).
    matrix = [["Group", "H2"], ["Group", "v2"], ["g2", "v3"]]
    cells = {
        (1, 1): _cell(1, 1, "Group", covered=((2, 1),)),
        (1, 2): _cell(1, 2, "H2"),
        (2, 2): _cell(2, 2, "v2"),
        (3, 1): _cell(3, 1, "g2"),
        (3, 2): _cell(3, 2, "v3"),
    }
    return ParsedDocxTable(
        width=2,
        matrix=[list(row) for row in matrix],
        raw_matrix=[list(row) for row in matrix],
        cells=cells,
        merge_ranges=[(1, 1, 2, 1)],
        explicit_header_rows=[],
        nested_tables=[],
        parse_incomplete=False,
        parse_incomplete_reason={},
        raw_text="",
    )


def _hyp(cells, *, header_levels=1, merges=None) -> dict:
    from table_geometry_validator import TABLE_STRUCTURE_HYPOTHESIS_VERSION

    return {
        "schema": TABLE_STRUCTURE_HYPOTHESIS_VERSION,
        "table_structure_version": "table-structure-v7",
        "header_level_count": header_levels,
        "cells": [
            {"coordinate": [r, c], "role": role, "confidence": "high"}
            for (r, c, role) in cells
        ],
        "semantic_merges": [
            {"coordinates": [list(rc) for rc in group]} for group in (merges or [])
        ],
    }


def _panel_seed(root: Path) -> tuple[Path, list[dict], list[dict]]:
    source = root / "source.docx"
    source.write_bytes(b"synthetic")
    from result_package import initialize_result_package

    initialize_result_package(root, input_path=source, requested_stages=["atomize"])
    analysis = resolve_analysis_root(root)
    block, items, cells = build_table_artifacts(
        [
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ],
        table_id="TBL-000001",
        block_id="BLK-000001",
        order=1,
        table_title="Auxiliary output",
        section_path=["5 Requirements"],
        knowledge_bases=KB,
        merge_ranges=[],
    )
    dispositions = build_table_cell_dispositions([block], cells)
    write_jsonl(governed_artifact_path(analysis, "blocks.jsonl"), [block])
    write_jsonl(governed_artifact_path(analysis, "table_items.jsonl"), items)
    write_jsonl(governed_artifact_path(analysis, "table_cell_items.jsonl"), cells)
    write_jsonl(
        governed_artifact_path(analysis, "table_cell_dispositions.jsonl"),
        dispositions,
    )
    return analysis, cells, dispositions


# --- 1. table family templates ----------------------------------------------


class TableFamilyTemplateTests(unittest.TestCase):
    def test_default_library_loads_three_families(self) -> None:
        library = load_table_family_templates()
        self.assertTrue(DEFAULT_FAMILY_TEMPLATES_PATH.is_file())
        ids = {family.family_id for family in library.families}
        self.assertEqual(ids, {"parameter_matrix", "obis_object", "event_code"})

    def test_obis_object_family_declares_protected_columns(self) -> None:
        library = load_table_family_templates()
        obis = library.by_id("obis_object")
        self.assertIsNotNone(obis)
        self.assertIn("obis", obis.protected_code_kinds)
        self.assertIn("class_id", obis.protected_code_kinds)
        self.assertTrue(obis.header_level_range.contains(2))

    def test_match_obis_object_by_headers(self) -> None:
        family = match_table_family(["Object/attribute name", "CL", "Value"])
        self.assertIsNotNone(family)
        self.assertEqual(family.family_id, "obis_object")

    def test_match_event_code_by_headers(self) -> None:
        family = match_table_family(
            ["Group number", "Subgroup number", "Event number", "Description of the event"]
        )
        self.assertEqual(family.family_id, "event_code")

    def test_match_parameter_matrix_by_headers(self) -> None:
        family = match_table_family(["Requirement", "Value", "Unit"])
        self.assertEqual(family.family_id, "parameter_matrix")

    def test_no_indicator_match_returns_none(self) -> None:
        self.assertIsNone(match_table_family(["unrelated", "columns"]))

    def test_missing_explicit_path_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_table_family_templates(Path("does/not/exist.yaml"))


# --- 2. dual-track entry -----------------------------------------------------


class DualTrackSwitchTests(unittest.TestCase):
    def test_switch_defaults_off(self) -> None:
        self.assertFalse(dual_track_enabled())

    def test_switch_name_and_default_are_documented(self) -> None:
        self.assertEqual(TABLE_DUAL_TRACK_SWITCH, "RATOMIZER_TABLE_DUAL_TRACK")

    def test_switch_off_returns_deterministic_path_unchanged(self) -> None:
        matrix = [["H1", "H2"], ["v1", "v2"]]
        deterministic = analyze_table(matrix)
        result = analyze_table_dual_track(matrix)
        # Every deterministic key is preserved verbatim; only the dual_track block is added.
        for key, value in deterministic.items():
            self.assertEqual(result[key], value)
        self.assertEqual(result["dual_track"]["mode"], "off")
        self.assertEqual(result["dual_track"]["version"], TABLE_DUAL_TRACK_VERSION)


class StructureFromHypothesisTests(unittest.TestCase):
    def test_title_then_header_then_data_rows(self) -> None:
        matrix = [["Title", ""], ["H1", "H2"], ["v1", "v2"]]
        hypothesis = _hyp(
            [
                (1, 1, "title"), (1, 2, "title"),
                (2, 1, "header"), (2, 2, "header"),
                (3, 1, "data"), (3, 2, "data"),
            ],
            header_levels=1,
        )
        structure = structure_from_hypothesis(matrix, hypothesis)
        self.assertEqual(structure["title_row_indexes"], [1])
        self.assertEqual(structure["header_row_indexes"], [2])
        self.assertEqual(structure["data_row_indexes"], [3])
        self.assertEqual(structure["header_detection_status"], "explicit")
        self.assertEqual(structure["ambiguous_structure_rows"], [])
        # Drop-in compatible: every analyze_table key is present.
        for key in (
            "width", "height", "title_row_indexes", "header_row_indexes",
            "header_row_count", "data_row_indexes", "header_detection_status",
            "header_detection_evidence", "ambiguous_structure_rows",
        ):
            self.assertIn(key, structure)

    def test_unlabelled_row_defaults_to_data(self) -> None:
        matrix = [["H1", "H2"], ["v1", "v2"]]
        # Hypothesis labels row 1 header but says nothing about row 2.
        hypothesis = _hyp([(1, 1, "header"), (1, 2, "header")])
        structure = structure_from_hypothesis(matrix, hypothesis)
        self.assertEqual(structure["header_row_indexes"], [1])
        self.assertEqual(structure["data_row_indexes"], [2])

    def test_mixed_row_with_more_data_than_header_is_data(self) -> None:
        matrix = [["h", "v1", "v2"]]
        hypothesis = _hyp([(1, 1, "header"), (1, 2, "data"), (1, 3, "data")])
        structure = structure_from_hypothesis(matrix, hypothesis)
        # header_count(1) < data_count(2) → conservative data row.
        self.assertEqual(structure["header_row_indexes"], [])
        self.assertEqual(structure["data_row_indexes"], [1])


class DualTrackEntryTests(unittest.TestCase):
    def test_switch_on_no_hypothesis_falls_back(self) -> None:
        matrix = [["H1", "H2"], ["v1", "v2"]]
        with patch.dict(os.environ, {TABLE_DUAL_TRACK_SWITCH: "1"}):
            self.assertTrue(dual_track_enabled())
            result = analyze_table_dual_track(matrix)
        self.assertEqual(result["dual_track"]["mode"], "fallback_no_hypothesis")
        # Deterministic structure preserved on fallback.
        self.assertEqual(result["header_row_indexes"], analyze_table(matrix)["header_row_indexes"])

    def test_switch_on_no_geometry_falls_back(self) -> None:
        matrix = [["H1", "H2"], ["v1", "v2"]]
        hypothesis = _hyp(
            [(1, 1, "header"), (1, 2, "header"), (2, 1, "data"), (2, 2, "data")]
        )
        with patch.dict(os.environ, {TABLE_DUAL_TRACK_SWITCH: "1"}):
            result = analyze_table_dual_track(matrix, hypothesis=hypothesis)
        self.assertEqual(result["dual_track"]["mode"], "fallback_no_geometry")

    def test_switch_on_signed_hypothesis_derives_structure(self) -> None:
        parsed = _plain_table()
        hypothesis = _hyp(
            [(1, 1, "header"), (1, 2, "header"), (2, 1, "data"), (2, 2, "data")]
        )
        # Pre-condition: the validator signs this hypothesis.
        signed = validate_table_geometry(hypothesis, parsed)
        self.assertEqual(signed.status, ISSUED)
        with patch.dict(os.environ, {TABLE_DUAL_TRACK_SWITCH: "1"}):
            result = analyze_table_dual_track(
                parsed.matrix, parsed_table=parsed, hypothesis=hypothesis
            )
        self.assertEqual(result["dual_track"]["mode"], "hypothesis_signed")
        self.assertEqual(result["dual_track"]["validator_status"], ISSUED)
        self.assertEqual(result["header_row_indexes"], [1])
        self.assertEqual(result["data_row_indexes"], [2])

    def test_partial_conflict_falls_back_with_conflict_cells(self) -> None:
        parsed = _plain_table()
        # Out-of-bounds coordinate ([5,5]) → partial_conflict.
        hypothesis = _hyp(
            [(1, 1, "header"), (1, 2, "header"), (2, 1, "data"), (5, 5, "data")]
        )
        signed = validate_table_geometry(hypothesis, parsed)
        self.assertEqual(signed.status, PARTIAL_CONFLICT)
        with patch.dict(os.environ, {TABLE_DUAL_TRACK_SWITCH: "1"}):
            result = analyze_table_dual_track(
                parsed.matrix, parsed_table=parsed, hypothesis=hypothesis
            )
        self.assertEqual(result["dual_track"]["mode"], "fallback_validation_failed")
        self.assertEqual(result["dual_track"]["validator_status"], PARTIAL_CONFLICT)
        self.assertIn([5, 5], result["dual_track"]["conflict_cells"])
        # Deterministic fallback structure preserved.
        self.assertEqual(result["header_row_indexes"], analyze_table(parsed.matrix)["header_row_indexes"])

    def test_invalidated_falls_back_with_conflict_cells(self) -> None:
        parsed = _merged_anchor_table()
        # Hypothesis references no anchor cell (1,1) → anchor_missing → invalidated.
        hypothesis = _hyp(
            [(1, 2, "header"), (2, 2, "data"), (3, 1, "data"), (3, 2, "data")]
        )
        signed = validate_table_geometry(hypothesis, parsed)
        self.assertEqual(signed.status, INVALIDATED)
        with patch.dict(os.environ, {TABLE_DUAL_TRACK_SWITCH: "1"}):
            result = analyze_table_dual_track(
                parsed.matrix, parsed_table=parsed, hypothesis=hypothesis
            )
        self.assertEqual(result["dual_track"]["mode"], "fallback_validation_failed")
        self.assertEqual(result["dual_track"]["validator_status"], INVALIDATED)

    def test_precomputed_validator_result_is_reused(self) -> None:
        parsed = _plain_table()
        hypothesis = _hyp(
            [(1, 1, "header"), (1, 2, "header"), (2, 1, "data"), (2, 2, "data")]
        )
        signed = validate_table_geometry(hypothesis, parsed)
        with patch.dict(os.environ, {TABLE_DUAL_TRACK_SWITCH: "1"}):
            result = analyze_table_dual_track(
                parsed.matrix, hypothesis=hypothesis, validator_result=signed
            )
        self.assertEqual(result["dual_track"]["mode"], "hypothesis_signed")


# --- 3. panel degradation exit ----------------------------------------------


class GeometryConflictRegistryTests(unittest.TestCase):
    def test_record_load_clear_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = record_table_geometry_conflicts(
                root,
                table_id="TBL-000001",
                table_block_id="BLK-000001",
                validator_status=PARTIAL_CONFLICT,
                conflict_cells=[(3, 1), [2, 2]],
                reasons=[{"code": "coordinate_out_of_bounds", "cells": [[5, 5]], "detail": ""}],
            )
            self.assertEqual(record["schema"], "table-geometry-conflict/v1")
            self.assertEqual(record["validator_status"], PARTIAL_CONFLICT)
            loaded = load_table_geometry_conflicts(root)
            self.assertIn("TBL-000001", loaded)
            self.assertEqual(len(loaded["TBL-000001"]["conflict_cells"]), 2)
            # Coordinate forms normalize to {row_index, column_index}.
            self.assertEqual(
                {(c["row_index"], c["column_index"]) for c in loaded["TBL-000001"]["conflict_cells"]},
                {(3, 1), (2, 2)},
            )
            self.assertTrue(clear_table_geometry_conflicts(root, "TBL-000001"))
            self.assertEqual(load_table_geometry_conflicts(root), {})

    def test_empty_conflict_cells_clears_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_table_geometry_conflicts(
                root, table_id="TBL-000001",
                validator_status=PARTIAL_CONFLICT, conflict_cells=[(3, 1)],
            )
            self.assertIn("TBL-000001", load_table_geometry_conflicts(root))
            record_table_geometry_conflicts(
                root, table_id="TBL-000001",
                validator_status=PARTIAL_CONFLICT, conflict_cells=[],
            )
            self.assertEqual(load_table_geometry_conflicts(root), {})

    def test_missing_registry_loads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_table_geometry_conflicts(Path(tmp)), {})


class PanelSurfacingTests(unittest.TestCase):
    def test_conflict_cells_surface_in_review_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, cells, dispositions = _panel_seed(Path(tmp))
            # Pick a real context cell that is NOT already terminal or review. The seed
            # assigns row 2 (Mode/Value) disposition=context; a geometry conflict on it
            # must escalate to review + highlight. Terminal cells (target/composite/
            # excluded) are intentionally left alone by the overlay.
            target = next(
                cell for cell in cells
                if int(cell.get("row_index") or 0) == 2
                and int(cell.get("column_index") or 0) == 1
            )
            coord = (int(target["row_index"]), int(target["column_index"]))
            # Confirm it is not pending review in the base projection.
            base = next(
                row for row in dispositions
                if str(row.get("cell_id") or "") == str(target["cell_id"])
            )
            self.assertNotEqual(str(base.get("disposition") or ""), "review")

            record_table_geometry_conflicts(
                analysis, table_id="TBL-000001", table_block_id="BLK-000001",
                validator_status=PARTIAL_CONFLICT, conflict_cells=[coord],
                reasons=[{"code": "coordinate_out_of_bounds", "detail": ""}],
            )
            payload = build_table_review_payload(analysis)
            table = payload["tables"][0]
            self.assertEqual(table["structure_review_status"], "pending")
            self.assertEqual(table["review_mode"], "geometry_conflict")
            self.assertEqual(table["geometry_conflict"]["validator_status"], PARTIAL_CONFLICT)
            overlaid = next(
                cell for cell in table["cells"]
                if str(cell["cell_id"]) == str(target["cell_id"])
            )
            self.assertEqual(overlaid["disposition"], "review")
            self.assertTrue(overlaid["geometry_conflict"])

    def test_non_conflicted_table_unchanged_by_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, _cells, _dispositions = _panel_seed(Path(tmp))
            # No conflict recorded → payload behaves exactly as before.
            payload = build_table_review_payload(analysis)
            table = payload["tables"][0]
            self.assertNotIn("geometry_conflict", table)
            for cell in table["cells"]:
                self.assertNotIn("geometry_conflict", cell)


class PanelWritebackTests(unittest.TestCase):
    def test_resolving_conflict_overlay_clears_registry_isomorphically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, cells, dispositions = _panel_seed(Path(tmp))
            target = next(
                cell for cell in cells
                if int(cell.get("row_index") or 0) == 2
                and int(cell.get("column_index") or 0) == 1
            )
            coord = (int(target["row_index"]), int(target["column_index"]))
            record_table_geometry_conflicts(
                analysis, table_id="TBL-000001", table_block_id="BLK-000001",
                validator_status=PARTIAL_CONFLICT, conflict_cells=[coord],
            )
            fingerprint = table_evidence_fingerprint("TBL-000001", dispositions)
            # The existing disposition writeback channel resolves the conflict cell.
            # Pure overlay cell → no claim delegation, just registry clearance; the
            # state/event format is unchanged.
            state = apply_table_review_decision(
                analysis,
                table_id="TBL-000001",
                expected_evidence_fingerprint=fingerprint,
                role_mapping={
                    str(target["cell_id"]): {"role": "data", "disposition": "context"},
                },
                actor="reviewer",
                reason="geometry conflict resolved",
            )
            results = {entry["cell_id"]: entry for entry in state["claim_results"]}
            self.assertIn(str(target["cell_id"]), results)
            self.assertEqual(
                results[str(target["cell_id"])]["result"]["status"],
                "geometry_conflict_cleared",
            )
            # Registry cleared for the resolved cell.
            registry = load_table_geometry_conflicts(analysis)
            self.assertNotIn("TBL-000001", registry)
            # Re-built payload no longer flags the cell as a geometry conflict.
            payload = build_table_review_payload(analysis)
            table = payload["tables"][0]
            self.assertNotIn("geometry_conflict", table)


if __name__ == "__main__":
    unittest.main()
