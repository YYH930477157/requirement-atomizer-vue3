from __future__ import annotations

import unittest

from ai_extract import (
    _apply_table_requirement_metadata,
    _map_requirement_source,
    build_section_prompt,
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


if __name__ == "__main__":
    unittest.main()
