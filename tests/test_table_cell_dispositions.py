from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atomize import build_table_artifacts
from requirement_kb import KnowledgeRepository
from result_package import initialize_result_package, package_artifact_path
from table_dispositions import (
    TABLE_CELL_DISPOSITION_SCHEMA,
    build_table_cell_dispositions,
    summarize_table_dispositions,
    validate_disposition_conservation,
)


KB = KnowledgeRepository.from_paths([])


def _artifacts(matrix, *, merges=None):
    return build_table_artifacts(
        matrix,
        table_id="TBL-000001",
        block_id="BLK-000001",
        order=1,
        table_title="Synthetic table",
        section_path=["5 Requirements"],
        knowledge_bases=KB,
        merge_ranges=merges,
    )


class TableCellDispositionTests(unittest.TestCase):
    def test_every_canonical_cell_has_exactly_one_disposition(self) -> None:
        block, _items, cells = _artifacts([
            ["No.", "Parameter", "Value", "Unit"],
            ["1", "Rated voltage", "230", "V"],
            ["2", "Frequency", "50", "Hz"],
        ])

        rows = build_table_cell_dispositions([block], cells)
        validate_disposition_conservation([block], cells, rows)

        self.assertEqual(len(rows), len(cells))
        self.assertEqual(len({row["cell_id"] for row in rows}), len(cells))
        self.assertTrue(all(row["schema"] == TABLE_CELL_DISPOSITION_SCHEMA for row in rows))
        by_text = {row["text"]: row for row in rows}
        self.assertEqual(by_text["No."]["disposition"], "context")
        self.assertEqual(by_text["1"]["disposition"], "excluded")
        self.assertEqual(by_text["230"]["disposition"], "composite")
        self.assertEqual(by_text["V"]["disposition"], "composite")

    def test_normative_content_is_never_silently_excluded(self) -> None:
        block, _items, cells = _artifacts([
            ["The device shall retain audit records.", ""],
            ["Parameter", "Value"],
            ["Voltage", "230 V"],
        ])

        rows = build_table_cell_dispositions([block], cells)
        normative = next(row for row in rows if "shall retain" in row["text"])

        self.assertIn(normative["disposition"], {"target", "review"})
        self.assertNotEqual(normative["disposition"], "excluded")
        self.assertTrue(normative["evidence"])

    def test_not_applicable_is_an_exclusion_fact_not_a_negative_requirement(self) -> None:
        block, _items, cells = _artifacts([
            ["Capability", "Single phase", "Three phase"],
            ["Event recording", "Not Applicable", "Required"],
        ])

        rows = build_table_cell_dispositions([block], cells)
        excluded = next(row for row in rows if row["text"] == "Not Applicable")

        self.assertEqual(excluded["disposition"], "excluded")
        self.assertEqual(excluded["exclusion_reason"], "not_applicable")
        self.assertEqual(excluded["applicability"], "excluded")
        self.assertNotIn("prohibited", str(excluded).lower())

    def test_ambiguous_structure_routes_the_whole_table_to_review(self) -> None:
        block, _items, cells = _artifacts([
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ])

        rows = build_table_cell_dispositions([block], cells)
        summary = summarize_table_dispositions(rows)[0]

        self.assertEqual(summary["structure_review_status"], "pending")
        self.assertGreaterEqual(summary["review_count"], 1)
        self.assertTrue(any(row["disposition"] == "review" for row in rows))

    def test_parse_incomplete_cannot_auto_exclude_any_cell(self) -> None:
        block, _items, cells = _artifacts([
            ["Parameter", "Value"],
            ["Voltage", "230 V"],
        ])
        block["parse_incomplete"] = True
        block["parse_incomplete_reason"] = {"code": "row_width_conflict"}

        rows = build_table_cell_dispositions([block], cells)

        self.assertTrue(all(row["disposition"] == "review" for row in rows))
        self.assertTrue(all(row["confidence"] == "low" for row in rows))

    def test_result_package_registers_disposition_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.docx"
            source.write_bytes(b"synthetic")
            initialize_result_package(
                root,
                input_path=source,
                requested_stages=["atomize"],
            )

            path = package_artifact_path(
                root, "table_cell_dispositions", for_write=True
            )

            self.assertEqual(
                path,
                root / ".ratomizer" / "pipeline" / "table_cell_dispositions.jsonl",
            )


if __name__ == "__main__":
    unittest.main()
