from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from ai_extract import (
    _apply_table_requirement_metadata,
    _claim_projected_table_dispositions,
    _map_requirement_source,
    _merge_llm_into_deterministic_rows,
    _supplement_parameter_table_rows,
    build_section_prompt,
    extract_section,
)
from atomize import build_table_artifacts
from extract_units import assemble_sections
from requirement_kb import KnowledgeRepository
from table_dispositions import build_table_cell_dispositions


KB = KnowledgeRepository.from_paths([])


def _artifacts(matrix, *, title="Product capabilities"):
    return build_table_artifacts(
        matrix,
        table_id="TBL-000001",
        block_id="BLK-000001",
        order=1,
        table_title=title,
        section_path=["5 Requirements"],
        knowledge_bases=KB,
        merge_ranges=[],
    )


class StructuredTableExtractionUnitTests(unittest.TestCase):
    def test_projection_is_empty_when_catalog_exists_without_claim_generation(self) -> None:
        block, _items, cells = _artifacts([
            ["Parameter", "Value"],
            ["Rated voltage", "230 V"],
        ])
        dispositions = build_table_cell_dispositions([block], cells)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "claim_catalog.jsonl").write_text("{}\n", encoding="utf-8")

            projected = _claim_projected_table_dispositions(root, cells, dispositions)

        self.assertEqual(projected, dispositions)

    def test_extraction_projects_claim_authority_before_building_table_leaves(self) -> None:
        block, _items, cells = _artifacts([
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ])
        dispositions = build_table_cell_dispositions([block], cells)
        review_cell = next(row for row in dispositions if row["disposition"] == "review")
        authority = {
            review_cell["cell_id"]: {
                "status": "promoted",
                "claim_id": "CLM-0000000000000001",
                "override_id": "CSO-0000000000000001",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "claim_catalog.jsonl"
            marker.write_text("{}\n", encoding="utf-8")
            with patch(
                "claim_artifacts.claim_artifact_path", return_value=marker
            ), patch(
                "table_claim_authority.load_table_claim_authority_projection",
                return_value=authority,
            ):
                projected = _claim_projected_table_dispositions(
                    Path(tmp), cells, dispositions
                )

        updated = next(row for row in projected if row["cell_id"] == review_cell["cell_id"])
        self.assertEqual(updated["disposition"], "target")
        self.assertEqual(updated["decision_source"], "claim_authority")

    def test_table_blob_is_replaced_by_addressable_row_leaves(self) -> None:
        block, items, cells = _artifacts([
            ["Parameter", "Model A", "Model B", "Unit"],
            ["Rated voltage", "230", "230", "V"],
            ["Frequency", "50", "60", "Hz"],
        ])
        dispositions = build_table_cell_dispositions([block], cells)

        section = assemble_sections(
            [block],
            table_items=items,
            table_cell_items=cells,
            table_cell_dispositions=dispositions,
        )[0]

        self.assertNotEqual(section["text"], block["text"])
        self.assertIn("[TABLE_LEAF", section["text"])
        self.assertIn("item_id=TBL-000001-R000002", section["text"])
        self.assertIn("cell_ids=", section["text"])
        self.assertNotIn(block["text"], section["text"])
        self.assertEqual(section["table_input_mode"], "structured_leaves")
        self.assertEqual(section["source_blocks"][0]["text"], section["text"])

    def test_cell_leaf_always_contains_table_row_and_column_context(self) -> None:
        block, items, cells = _artifacts([
            ["Aspect", "Requirement A", "Requirement B"],
            [
                "Storage",
                "The meter shall store daily profiles for at least sixty days.",
                "The meter must protect stored profiles against unauthorized access.",
            ],
            [
                "Display",
                "The display shall remain readable under direct sunlight conditions.",
                "The display must show all segments during the diagnostic test.",
            ],
        ])
        dispositions = build_table_cell_dispositions([block], cells)

        section = assemble_sections(
            [block],
            table_items=items,
            table_cell_items=cells,
            table_cell_dispositions=dispositions,
        )[0]

        target = next(
            cell for cell in cells if "store daily profiles" in cell["text"]
        )
        line = next(line for line in section["text"].splitlines() if target["cell_id"] in line)
        self.assertIn("Product capabilities", line)
        self.assertIn("Aspect=Storage", line)
        self.assertIn("Requirement A", line)
        self.assertIn("The meter shall store daily profiles for at least sixty days.", line)
        self.assertNotIn("prohibit", line.lower())

    def test_prompt_declares_structured_fact_and_no_invention_contract(self) -> None:
        section = {
            "heading": "5 Requirements",
            "text": "[TABLE_LEAF kind=cell cell_id=TBL-1] Model A | 230 V",
            "table_input_mode": "structured_leaves",
        }

        prompt = build_section_prompt(section)

        self.assertIn('"table_input_mode": "structured_leaves"', prompt)
        self.assertIn("不得新增或修改数值、单位、型号、代码", prompt)
        self.assertNotIn("把整张表合成一条需求", prompt)

    def test_source_mapping_collects_all_matching_cell_ids(self) -> None:
        block, items, cells = _artifacts([
            ["Aspect", "Requirement A", "Requirement B"],
            [
                "Logging",
                "The meter shall store daily records for diagnostic analysis.",
                "The meter shall store daily records for diagnostic analysis.",
            ],
            [
                "Display",
                "The display shall remain readable under direct sunlight conditions.",
                "The display must show all segments during the diagnostic test.",
            ],
        ])
        dispositions = build_table_cell_dispositions([block], cells)
        section = assemble_sections(
            [block],
            table_items=items,
            table_cell_items=cells,
            table_cell_dispositions=dispositions,
        )[0]
        cell_lines = [
            cell["extraction_text"]
            for cell in section["source_blocks"][0]["cells"]
            if "store daily records for diagnostic" in cell["extraction_text"]
        ]
        req = {
            "source_quote": "\n".join(cell_lines),
            "source_section": "5 Requirements",
        }

        _map_requirement_source(req, section)

        self.assertEqual(len(req["source_cell_ids"]), 2)
        self.assertEqual(req["source_cell_id"], req["source_cell_ids"][0])

    def test_requirement_metadata_keeps_models_strength_and_structured_facts(self) -> None:
        block, _items, cells = _artifacts([
            ["Capability", "Model A", "Model B"],
            [
                "Logging",
                "The meter shall store daily records.",
                "The meter shall store daily records.",
            ],
        ])
        dispositions = build_table_cell_dispositions([block], cells)
        source_cells = [cell for cell in cells if "store daily records" in cell["text"]]
        req = {
            "ai_req_id": "AIR-1",
            "description": "The meter shall store daily records.",
            "source_quote": "The meter shall store daily records.",
            "source_cell_ids": [cell["cell_id"] for cell in source_cells],
        }

        _apply_table_requirement_metadata([req], cells, dispositions)

        self.assertEqual(req["applicable_models"], ["Model A", "Model B"])
        self.assertEqual(req["constraint_strength"], "shall")
        self.assertEqual(len(req["structured_facts"]), 2)
        self.assertEqual(req["clarification_ids"], [])

    def test_fake_chat_parameter_row_merge_publishes_one_requirement_with_all_sources(self) -> None:
        block, items, cells = _artifacts([
            ["Parameter", "Requirement", "Unit"],
            ["Retention period", "30 days", "days"],
        ], title="Storage parameters")
        dispositions = build_table_cell_dispositions([block], cells)
        section = assemble_sections(
            [block],
            table_items=items,
            table_cell_items=cells,
            table_cell_dispositions=dispositions,
        )[0]

        def fake_chat(_system: str, user: str) -> dict:
            self.assertIn("[TABLE_LEAF kind=row", user)
            return {"requirements": [{
                "title": "Retention period",
                "description": (
                    "The product shall support the configured retention period."
                ),
                "type": "functional",
                "priority": "P1",
                "labels": ["other"],
                "source_quote": "Retention period",
            }]}

        llm_rows = extract_section(section, fake_chat)
        supplemented = _supplement_parameter_table_rows(llm_rows, [block])
        merged = _merge_llm_into_deterministic_rows(supplemented)

        self.assertEqual(len(llm_rows), 1)
        self.assertEqual(len(supplemented), 2)
        self.assertEqual(len(merged), 1)
        row = merged[0]
        expected_cell_ids = [
            cell["cell_id"] for cell in cells if cell["row_index"] == 2
        ]
        self.assertEqual(row["source_item_id"], "TBL-000001-R000002")
        self.assertEqual(row["source_cell_ids"], expected_cell_ids)
        self.assertEqual(row["source_cell_id"], expected_cell_ids[0])
        self.assertEqual(
            row["llm_narrative"],
            "The product shall support the configured retention period.",
        )
        self.assertEqual(len(row["merge_trace"]), 1)


if __name__ == "__main__":
    unittest.main()
