"""A9 招标文件适配测试（默认关时字节不变；开启时按验收判据执行）。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

import table_structure
import unextracted_registry
from claim_catalog import build_claim_catalog
from table_dispositions import build_table_cell_dispositions
from tender_regions import apply_tender_regions, classify_tender_region
from tender_table_filter import (
    TENDER_TABLE_FILTER_VERSION,
    classify_tender_table_kind,
    is_tender_commercial_table,
)


class TenderTableFilterTests(unittest.TestCase):
    """A9-1：商务/表单表识别排除。"""

    def _price_table(self) -> tuple[list[str], list[list[str]]]:
        headers = ["Item No", "Description", "Quantity", "Unit Price", "Total"]
        rows = [
            ["1", "Smart meter", "100", "USD 120.00", "USD 12,000.00"],
            ["2", "DCU", "20", "USD 450.00", "USD 9,000.00"],
        ]
        return headers, rows

    def _technical_table(self) -> tuple[list[str], list[list[str]]]:
        headers = ["Parameter", "Value", "Unit", "Requirement"]
        rows = [
            ["Voltage", "230", "V", "shall be 230 V"],
            ["Current", "5", "A", "shall be 5 A"],
        ]
        return headers, rows

    def test_default_off_returns_none(self):
        os.environ.pop("RATOMIZER_TENDER_TABLE_FILTER", None)
        headers, rows = self._price_table()
        self.assertIsNone(classify_tender_table_kind(
            headers=headers, data_rows=rows, section_path=[], table_title=""
        ))

    def test_price_table_detected_as_commercial(self):
        os.environ["RATOMIZER_TENDER_TABLE_FILTER"] = "1"
        try:
            headers, rows = self._price_table()
            self.assertEqual(
                classify_tender_table_kind(
                    headers=headers, data_rows=rows, section_path=[], table_title=""
                ),
                "commercial",
            )
        finally:
            os.environ.pop("RATOMIZER_TENDER_TABLE_FILTER", None)

    def test_technical_parameter_table_not_commercial(self):
        os.environ["RATOMIZER_TENDER_TABLE_FILTER"] = "1"
        try:
            headers, rows = self._technical_table()
            self.assertIsNone(classify_tender_table_kind(
                headers=headers, data_rows=rows, section_path=[], table_title=""
            ))
        finally:
            os.environ.pop("RATOMIZER_TENDER_TABLE_FILTER", None)

    def test_modal_blocks_commercial_classification(self):
        os.environ["RATOMIZER_TENDER_TABLE_FILTER"] = "1"
        try:
            # 含 shall 的价格表 → 不判商务（保守，避免误伤带义务的混合表）
            headers = ["Item", "Qty", "Price"]
            rows = [["1", "2", "USD 100"], ["2", "3", "shall supply"]]
            self.assertIsNone(classify_tender_table_kind(
                headers=headers, data_rows=rows, section_path=[], table_title=""
            ))
        finally:
            os.environ.pop("RATOMIZER_TENDER_TABLE_FILTER", None)


class TenderTableDispositionTests(unittest.TestCase):
    """A9-1：商务表 disposition 与 claim catalog 投影。"""

    def _build_price_block(self) -> dict[str, Any]:
        matrix = [
            ["Item", "Qty", "Unit Price", "Total"],
            ["1", "10", "USD 100", "USD 1,000"],
            ["2", "20", "USD 50", "USD 1,000"],
        ]
        structure = table_structure.analyze_table(matrix, explicit_header_rows=[1])
        plan = table_structure.plan_table_leaves(
            structure, matrix, table_kind="other",
            tender_table_kind="commercial",
        )
        cells = table_structure.build_cell_items(
            matrix, None, structure, plan,
            table_id="TBL-001", block_id="BLK-001",
            table_title="Price Schedule", section_path=["Annex A"],
            headers=["Item", "Qty", "Unit Price", "Total"],
            table_kind="other",
            source_format="docx",
        )
        block = {
            "block_id": "BLK-001",
            "type": "table",
            "table_id": "TBL-001",
            "table_title": "Price Schedule",
            "section_path": ["Annex A"],
            "table_structure_version": table_structure.TABLE_STRUCTURE_VERSION,
            "table_kind": "other",
            "leaf_plan": {
                "mode": plan["mode"],
                "row_leaves": [],
                "cell_leaves": [],
                "context_cells": [],
                "tender_commercial_cells": [
                    f"TBL-001-R{row:06d}-C{col:06d}"
                    for row, col in plan["tender_commercial_cells"]
                ],
            },
            "tender_table_kind": "commercial",
            "header_row_indexes": structure["header_row_indexes"],
            "title_row_indexes": structure["title_row_indexes"],
            "data_row_indexes": structure["data_row_indexes"],
            "header_detection_status": structure["header_detection_status"],
            "header_detection_evidence": structure["header_detection_evidence"],
            "merge_ranges": [],
            "matrix_fact_columns": [],
            "matrix_dimension_evidence": {},
            "matrix_rejected_marker_columns": [],
            "parse_incomplete": False,
        }
        return block, cells

    def test_tender_commercial_dispositions_excluded(self):
        block, cells = self._build_price_block()
        dispositions = build_table_cell_dispositions([block], cells)
        for row in dispositions:
            self.assertEqual(row["disposition"], "excluded")
            self.assertEqual(row["exclusion_reason"], "tender_commercial_table")
            self.assertIn("tender_commercial_table", row["evidence"])

    def test_tender_commercial_claims_excluded(self):
        block, cells = self._build_price_block()
        catalog_doc = build_claim_catalog(
            blocks=[block],
            table_items=[],
            table_cell_items=cells,
        )
        catalog = catalog_doc.get("catalog", [])
        # 商务表应生成 claim，但 eligibility=excluded
        commercial = [row for row in catalog if row.get("eligibility") == "excluded"]
        self.assertTrue(len(commercial) > 0, "应有 tender commercial 排除 claim")
        for row in commercial:
            exclusion = row.get("exclusion") or {}
            self.assertEqual(exclusion.get("reason"), "tender_commercial_table")
            self.assertEqual(exclusion.get("rule_id"), "catalog-tender-commercial-table")
        # 不应有 claim（需求候选）
        claim_rows = [row for row in catalog if row.get("eligibility") == "claim"]
        self.assertEqual(claim_rows, [])


class TenderRegionTests(unittest.TestCase):
    """A9-2：tender 区域识别。"""

    def test_technical_spec_heading_maps_to_body(self):
        block = {"type": "heading", "text": "Technical Specification"}
        region = classify_tender_region(block)
        self.assertEqual(region, "tender_technical")

    def test_instructions_heading_maps_to_instructions(self):
        block = {"type": "heading", "text": "Instructions to Bidders"}
        region = classify_tender_region(block)
        self.assertEqual(region, "tender_instructions")

    def test_non_heading_returns_none(self):
        block = {"type": "paragraph", "text": "Instructions to Bidders"}
        self.assertIsNone(classify_tender_region(block))

    def test_apply_sets_doc_region_non_product_reference(self):
        blocks = [
            {"block_id": "B1", "type": "heading", "text": "Instructions to Bidders", "doc_region": "body"},
            {"block_id": "B2", "type": "paragraph", "text": "Bid submission deadline is ...", "doc_region": "body"},
            {"block_id": "B3", "type": "heading", "text": "Technical Specification", "doc_region": "body"},
        ]
        apply_tender_regions(blocks)
        self.assertEqual(blocks[0]["doc_region"], "non_product_reference")
        self.assertEqual(blocks[0].get("tender_region"), "tender_instructions")
        self.assertEqual(blocks[1]["doc_region"], "body")  # paragraph 不被重新标记
        self.assertEqual(blocks[2]["doc_region"], "body")
        self.assertEqual(blocks[2].get("tender_region"), "tender_technical")

    # --- A-1：泛词误伤收窄（技术章节不得被整章踢出功能需求）---------------------

    def test_qualification_tests_stays_technical(self):
        """'Qualification Tests' 是设备验收技术章节，不得命中 procedural qualification。"""
        block = {"type": "heading", "text": "Qualification Tests"}
        self.assertEqual(classify_tender_region(block), "tender_technical")

    def test_type_routine_tests_stay_technical(self):
        block = {"type": "heading", "text": "Type Tests and Routine Tests"}
        self.assertEqual(classify_tender_region(block), "tender_technical")

    def test_acceptance_test_procedure_stays_technical(self):
        block = {"type": "heading", "text": "Acceptance Test Procedure"}
        self.assertEqual(classify_tender_region(block), "tender_technical")

    def test_evaluation_of_performance_not_kicked_to_reference(self):
        """'Evaluation of Harmonic Performance' 是技术评估，不得被 procedural evaluation 误伤。

        不得归为 tender_instructions（否则整章进 non_product_reference 静默漏抽）。
        """
        block = {"type": "heading", "text": "Evaluation of Harmonic Performance"}
        self.assertNotEqual(classify_tender_region(block), "tender_instructions")

    def test_assessment_of_compliance_not_kicked_to_reference(self):
        block = {"type": "heading", "text": "Assessment of Compliance Accuracy"}
        self.assertNotEqual(classify_tender_region(block), "tender_instructions")

    def test_qualification_tests_block_stays_body(self):
        """整章链路：含 'Qualification Tests' 的块保持 doc_region=body（进功能需求候选）。"""
        blocks = [
            {"block_id": "B1", "type": "heading", "text": "Qualification Tests", "doc_region": "body"},
        ]
        apply_tender_regions(blocks)
        self.assertEqual(blocks[0]["doc_region"], "body")
        self.assertEqual(blocks[0].get("tender_region"), "tender_technical")

    # --- A-1 回归守卫：收窄后真正的 procedural 短语仍命中 instructions ----------

    def test_qualification_requirements_still_instructions(self):
        block = {"type": "heading", "text": "Qualification Requirements"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")

    def test_bid_evaluation_still_instructions(self):
        block = {"type": "heading", "text": "Bid Evaluation"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")

    def test_evaluation_criteria_still_instructions(self):
        block = {"type": "heading", "text": "Evaluation Criteria"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")

    def test_prequalification_still_instructions(self):
        block = {"type": "heading", "text": "Pre-Qualification of Bidders"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")

    def test_scoring_sheet_still_instructions(self):
        block = {"type": "heading", "text": "Scoring Sheet"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")

    def test_bid_opening_still_instructions(self):
        block = {"type": "heading", "text": "1.10 Bid Opening"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")

    def test_tax_clearance_still_instructions(self):
        block = {"type": "heading", "text": "11 Valid Tax Clearance Certificate"}
        self.assertEqual(classify_tender_region(block), "tender_instructions")


class TenderFigurePageTests(unittest.TestCase):
    """A9-3：疑似流程图页强制高亮。"""

    def test_default_off_no_figure_entries(self):
        os.environ.pop("RATOMIZER_TENDER_FIGURE_PAGE_FILTER", None)
        blocks = [
            {"block_id": "B1", "type": "heading", "text": "Credit Transfer Process Flow Diagram", "page_number": 62, "section_path": []},
        ]
        registry = unextracted_registry.build_unextracted_registry(Path("x.pdf"), blocks)
        kinds = {entry["kind"] for entry in registry["entries"]}
        self.assertNotIn("figure_page", kinds)

    def test_figure_page_detected_when_enabled(self):
        os.environ["RATOMIZER_TENDER_FIGURE_PAGE_FILTER"] = "1"
        try:
            blocks = [
                {"block_id": "B1", "type": "heading", "text": "Credit Transfer Process Flow Diagram", "page_number": 62, "section_path": ["Annex"]},
            ]
            registry = unextracted_registry.build_unextracted_registry(Path("x.pdf"), blocks)
            figure_entries = [e for e in registry["entries"] if e["kind"] == "figure_page"]
            self.assertEqual(len(figure_entries), 1)
            self.assertEqual(figure_entries[0]["source_id"], "PAGE-62")
            self.assertIn("请专家人工核对", figure_entries[0]["reason"])
        finally:
            os.environ.pop("RATOMIZER_TENDER_FIGURE_PAGE_FILTER", None)

    def test_text_rich_page_not_figure(self):
        os.environ["RATOMIZER_TENDER_FIGURE_PAGE_FILTER"] = "1"
        try:
            long_text = " ".join(["word"] * 50)
            blocks = [
                {"block_id": "B1", "type": "paragraph", "text": long_text, "page_number": 5},
            ]
            registry = unextracted_registry.build_unextracted_registry(Path("x.pdf"), blocks)
            self.assertEqual([e for e in registry["entries"] if e["kind"] == "figure_page"], [])
        finally:
            os.environ.pop("RATOMIZER_TENDER_FIGURE_PAGE_FILTER", None)


class TenderClarificationReportIntegrationTests(unittest.TestCase):
    """A9：未抽取登记册进入澄清报告。"""

    def test_non_product_reference_and_figure_page_in_clarification(self):
        os.environ["RATOMIZER_TENDER_FIGURE_PAGE_FILTER"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = Path(tmp)
                blocks = [
                    {"block_id": "B1", "type": "heading", "text": "Instructions to Bidders", "page_number": 2, "section_path": [], "doc_region": "non_product_reference"},
                    {"block_id": "B2", "type": "heading", "text": "Credit Transfer Process Flow Diagram", "page_number": 3, "section_path": [], "doc_region": "body"},
                ]
                registry = unextracted_registry.build_unextracted_registry(Path("x.pdf"), blocks)
                unextracted_registry.write_unextracted_registry(out_dir, registry, use_governed_path=False)
                entries = unextracted_registry.collect_unextracted_clarification_entries(out_dir)
                kinds = {e["kind"] for e in entries}
                self.assertIn("non_product_reference_block", kinds)
                self.assertIn("figure_page", kinds)
        finally:
            os.environ.pop("RATOMIZER_TENDER_FIGURE_PAGE_FILTER", None)


if __name__ == "__main__":
    unittest.main()
