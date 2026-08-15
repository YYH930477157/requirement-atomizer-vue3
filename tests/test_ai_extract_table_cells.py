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
from extract_units import (
    _fold_tiny_units,
    _pack_sections,
    assemble_sections,
    merge_sections,
)
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

        self.assertIn('"table_input_mode":"structured_leaves"', prompt)
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


class TableInputModeMergeRegressionTests(unittest.TestCase):
    """回归：merge_sections / _pack_sections / _fold_tiny_units 重建 dict 时丢失
    table_input_mode——结构化表段经合并后模式回落 plain_text，build_section_prompt 的
    「结构化表格硬约束」块生产上从不注入、且 prompt 谎报输入模式。

    既有 prompt 测试（test_prompt_declares_structured_fact_and_no_invention_contract）
    手搓一个带 table_input_mode 的 section 直喂 build_section_prompt，绕开 merge_sections，
    这正是该缺陷以「假绿」入库的根因。本组测试必须穿过 merge 网关。
    """

    @staticmethod
    def _structured_section(*, text=None, heading="Requirements"):
        return {
            "section_id": "sec-1",
            "heading": heading,
            "text": text or (
                "[TABLE_CONTEXT title=Parameters]\n"
                "[TABLE_LEAF kind=cell cell_id=TBL-000001-R000001-C000001] Model A | 230 V"
            ),
            "block_ids": ["BLK-000001"],
            "source_blocks": [],
            "table_input_mode": "structured_leaves",
        }

    def test_merge_sections_preserves_mode_and_injects_hard_constraint(self) -> None:
        merged = merge_sections([self._structured_section()], target_chars=5000)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["table_input_mode"], "structured_leaves")
        prompt = build_section_prompt(merged[0])
        self.assertIn('"table_input_mode":"structured_leaves"', prompt)
        self.assertIn("【结构化表格硬约束】", prompt)
        self.assertIn("不得新增或修改数值、单位、型号、代码", prompt)

    def test_pack_sections_preserves_mode_directly(self) -> None:
        merged = _pack_sections(
            [self._structured_section()], target_chars=5000, split_chars=5000
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["table_input_mode"], "structured_leaves")

    def test_structured_merged_with_plain_unit_stays_structured(self) -> None:
        # OR 语义：结构化表段与散文并单元后，硬约束宁可多覆盖不可漏。
        plain = {
            "section_id": "sec-2",
            "heading": "Notes",
            "text": (
                "These general notes describe surrounding context for the parameter "
                "table above and contain no table leaf markers whatsoever."
            ),
            "block_ids": ["BLK-000002"],
            "source_blocks": [],
            "table_input_mode": "plain_text",
        }
        merged = merge_sections(
            [self._structured_section(), plain], target_chars=5000
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["table_input_mode"], "structured_leaves")
        self.assertIn("【结构化表格硬约束】", build_section_prompt(merged[0]))

    def test_fold_tiny_units_propagates_mode_into_prev(self) -> None:
        # 微单元折叠：被折叠进前节的微小结构化段也必须把模式带上，不得回落 plain_text。
        prev = {
            "text": (
                "General prose paragraph that comfortably exceeds the one hundred twenty "
                "character fold threshold so it is treated as a normal sized unit here."
            ),
            "block_ids": ["BLK-000001"],
            "source_blocks": [],
            "table_input_mode": "plain_text",
        }
        tiny = {
            "text": "[TABLE_LEAF kind=cell cell_id=TBL-000009-R000001-C000001] X",
            "block_ids": ["BLK-000009"],
            "source_blocks": [],
            "table_input_mode": "structured_leaves",
        }
        out = _fold_tiny_units([prev, tiny], target_chars=5000)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["table_input_mode"], "structured_leaves")


class TableCellDispositionsGateTests(unittest.TestCase):
    """Kimi 高危 #5：旧迁移门指望 read_jsonl 抛异常触发 base_migration_required，
    但 io_utils.read_jsonl 对**缺失文件返回 []**——门对最常见的缺失场景静默失效，
    旧结果包（有 cells 无 dispositions）会静默按新逻辑继续抽取；且 JSON 真损坏时报文
    还错说 missing。现改显式 is_file 判定 + 如实报文。"""

    def test_absent_with_cell_items_raises_base_migration_required(self) -> None:
        from ai_extract import _load_table_cell_dispositions
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                _load_table_cell_dispositions(Path(tmp), [{"cell_id": "TBL-1-R1-C1"}])
            msg = str(ctx.exception)
            self.assertIn("base_migration_required", msg)
            self.assertIn("absent", msg)

    def test_absent_without_cell_items_returns_empty(self) -> None:
        from ai_extract import _load_table_cell_dispositions
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_load_table_cell_dispositions(Path(tmp), []), [])

    def test_present_valid_returns_rows(self) -> None:
        from ai_extract import _load_table_cell_dispositions
        from result_package import governed_artifact_path
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            path = governed_artifact_path(
                out_dir, "table_cell_dispositions.jsonl", for_write=False
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '{"cell_id":"TBL-000001-R000001-C000001","disposition":"target"}\n',
                encoding="utf-8",
            )
            rows = _load_table_cell_dispositions(
                out_dir, [{"cell_id": "TBL-000001-R000001-C000001"}]
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["disposition"], "target")

    def test_corrupt_file_reports_corrupt_not_missing(self) -> None:
        from ai_extract import _load_table_cell_dispositions
        from result_package import governed_artifact_path
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            path = governed_artifact_path(
                out_dir, "table_cell_dispositions.jsonl", for_write=False
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not valid json\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                _load_table_cell_dispositions(out_dir, [{"cell_id": "TBL-1-R1-C1"}])
            msg = str(ctx.exception)
            self.assertIn("corrupt", msg)
            self.assertNotIn("missing", msg)


if __name__ == "__main__":
    unittest.main()
