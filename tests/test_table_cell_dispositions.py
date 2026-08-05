from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from atomize import build_table_artifacts
from requirement_kb import KnowledgeRepository
from result_package import initialize_result_package, package_artifact_path
from table_claim_authority import project_table_dispositions
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

    def test_claim_projected_disposition_validates_current_schema(self) -> None:
        block, _items, cells = _artifacts([
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ])
        rows = build_table_cell_dispositions([block], cells)
        review = next(row for row in rows if row["disposition"] == "review")
        projected = project_table_dispositions(
            rows,
            cells,
            {
                review["cell_id"]: {
                    "version": "table-claim-authority-v1",
                    "status": "confirmed_excluded",
                    "claim_id": "CLM-0000000000000001",
                    "claim_hash": "sha256:" + "1" * 64,
                    "document_generation_id": "sha256:" + "2" * 64,
                    "catalog_generation_id": "sha256:" + "3" * 64,
                    "decision_id": "CSCD-0000000000000001",
                    "decision_hash": "sha256:" + "4" * 64,
                    "prior_structural_reason": "ambiguous_table_structure",
                }
            },
        )
        schema = json.loads(
            (Path(__file__).resolve().parents[1]
             / "schemas" / "table_cell_dispositions_v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)

        for row in projected:
            validator.validate(row)

    def test_table_cell_item_v1_has_a_formal_schema(self) -> None:
        _block, _items, cells = _artifacts(
            [["Parameter", "Value"], ["Voltage", "230 V"]],
            merges=[(1, 1, 1, 2)],
        )
        schema = json.loads(
            (Path(__file__).resolve().parents[1]
             / "schemas" / "table_cell_item.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)

        for cell in cells:
            validator.validate(cell)


if __name__ == "__main__":
    unittest.main()
