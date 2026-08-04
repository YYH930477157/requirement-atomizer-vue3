from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atomize import build_table_artifacts
from io_utils import read_jsonl
from output_writer import write_jsonl
from requirement_kb import KnowledgeRepository
from table_dispositions import build_table_cell_dispositions
from table_recompute import recompute_confirmed_table_requirements


KB = KnowledgeRepository.from_paths([])


def _artifacts(matrix, *, title):
    return build_table_artifacts(
        matrix,
        table_id="TBL-ACCEPT",
        block_id="BLK-ACCEPT",
        order=1,
        table_title=title,
        section_path=["5 Requirements"],
        knowledge_bases=KB,
        merge_ranges=[],
    )


def _recompute(cells, dispositions, changed_ids):
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    write_jsonl(root / "blocks.jsonl", [])
    write_jsonl(root / "table_items.jsonl", [])
    write_jsonl(root / "table_cell_items.jsonl", cells)
    write_jsonl(root / "table_cell_dispositions.jsonl", dispositions)
    write_jsonl(root / "ai_requirements.jsonl", [])
    recompute_confirmed_table_requirements(
        root,
        table_id="TBL-ACCEPT",
        changed_cell_ids=set(changed_ids),
        cells=cells,
        dispositions=dispositions,
    )
    return temporary, read_jsonl(root / "ai_requirements.jsonl")


class DocxTableAcceptanceTests(unittest.TestCase):
    def test_multi_model_parameter_matrix_merges_only_exact_equivalents(self) -> None:
        block, _items, cells = _artifacts([
            ["Parameter", "Model A", "Model B", "Model C", "Unit"],
            ["Rated voltage", "230", "230", "230", "V"],
            ["Frequency", "50", "50", "50", "Hz"],
            ["Ingress rating", "54", "54", "54", "IP"],
            ["Accuracy class", "1", "1", "1", "class"],
            ["Maximum current", "60", "80", "100", "A"],
            ["Storage days", "30", "60", "90", "day"],
        ], title="Multi-model parameters")
        dispositions = build_table_cell_dispositions([block], cells)
        value_cells = [
            cell for cell in cells
            if int(cell.get("row_index") or 0) > 1
            and 2 <= int(cell.get("column_index") or 0) <= 4
        ]

        temporary, requirements = _recompute(
            cells, dispositions, [cell["cell_id"] for cell in value_cells]
        )
        self.addCleanup(temporary.cleanup)

        self.assertEqual(len(value_cells), 18)
        self.assertFalse(any(row["disposition"] == "review" for row in dispositions))
        self.assertEqual(len(requirements), 10)
        voltage = next(row for row in requirements if "Rated voltage" in row["description"])
        self.assertEqual(voltage["applicable_models"], ["Model A", "Model B", "Model C"])
        self.assertIn("V", [fact["text"] for fact in voltage["structured_facts"]])

    def test_multi_duty_cells_split_then_merge_across_models(self) -> None:
        duties = (
            "The meter shall log events. The meter shall report alarms. "
            "The meter shall store records. The meter shall protect data. "
            "The communication range shall support outdoor operation."
        )
        block, _items, cells = _artifacts([
            ["Capability", "Model A", "Model B", "Model C"],
            ["Remote operations", duties, duties, duties],
        ], title="Multi-duty capabilities")
        dispositions = build_table_cell_dispositions([block], cells)
        target_cells = [
            cell for cell in cells
            if next(row for row in dispositions if row["cell_id"] == cell["cell_id"])["disposition"]
            == "target"
        ]

        temporary, requirements = _recompute(
            cells, dispositions, [cell["cell_id"] for cell in target_cells]
        )
        self.addCleanup(temporary.cleanup)

        self.assertEqual(len(target_cells), 3)
        self.assertEqual(len(requirements), 5)
        self.assertTrue(all(len(row["source_cell_ids"]) == 3 for row in requirements))
        clarifications = {
            clarification
            for row in requirements
            for clarification in row.get("clarification_ids") or []
        }
        self.assertEqual(len(clarifications), 1)

    def test_not_applicable_is_scope_exclusion_not_a_negative_requirement(self) -> None:
        block, _items, cells = _artifacts([
            ["Capability", "Single A", "Single B", "Three phase"],
            [
                "Event functions",
                "Not Applicable",
                "Not Applicable",
                (
                    "The meter shall record events. "
                    "The meter shall support threshold configuration."
                ),
            ],
        ], title="Model applicability")
        dispositions = build_table_cell_dispositions([block], cells)
        target_cells = [
            cell for cell in cells
            if next(row for row in dispositions if row["cell_id"] == cell["cell_id"])["disposition"]
            == "target"
        ]

        temporary, requirements = _recompute(
            cells, dispositions, [cell["cell_id"] for cell in target_cells]
        )
        self.addCleanup(temporary.cleanup)

        exclusions = [row for row in dispositions if row.get("exclusion_reason") == "not_applicable"]
        self.assertEqual(len(exclusions), 2)
        self.assertEqual(len(requirements), 2)
        self.assertTrue(all(row["applicable_models"] == ["Three phase"] for row in requirements))
        self.assertFalse(any("not applicable" in row["description"].lower() for row in requirements))
        clarifications = {
            clarification
            for row in requirements
            for clarification in row.get("clarification_ids") or []
        }
        self.assertEqual(len(clarifications), 1)
        self.assertFalse(any(row["disposition"] == "review" for row in dispositions))


if __name__ == "__main__":
    unittest.main()
