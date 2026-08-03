"""参数表行确定性展开（guards-v16）：用户裁定"参数表每行都是需求"的确定性实现。"""
from __future__ import annotations

import unittest

from ai_extract import (
    _PARAM_REQ_CELL_RE,
    _is_parameter_table,
    _row_name_cell,
    _row_render_line,
    _supplement_parameter_table_rows,
    classify_table_kind,
)
from atomize import render_table_text


def _param_block() -> dict:
    headers = ["No.", "Parameter Name", "Technical requirements"]
    data_rows = [
        ["1.", "Rated voltage", "The meter shall operate at 230 V."],
        ["2.", "Rated frequency", "The meter shall operate at 50 Hz."],
        ["3.", "Backup power", "The meter shall include a reserve power supply."],
    ]
    return {
        "block_id": "BLK-000098",
        "type": "table",
        "headers": headers,
        "data_rows": data_rows,
        "text": render_table_text(headers, data_rows),
        "section_path": ["5. General Technical Requirements", "5.1. Single-phase IPUE"],
        "requirement_like": True,
        "noise": False,
    }


def _terms_block() -> dict:
    headers = ["No.", "Term", "Definition"]
    data_rows = [
        ["1.", "Overvoltage magnitude", "The maximum voltage value recorded."],
        ["2.", "Firmware", "Software that processes information."],
        ["3.", "Data", "Information from measuring instruments."],
    ]
    return {
        "block_id": "BLK-000061",
        "type": "table",
        "headers": headers,
        "data_rows": data_rows,
        "text": render_table_text(headers, data_rows),
        "section_path": ["3. Terms and Definitions"],
        "requirement_like": True,
        "noise": False,
    }


class ParameterTableQualificationTests(unittest.TestCase):
    def test_parameter_table_qualifies(self) -> None:
        self.assertTrue(_is_parameter_table(_param_block()))

    def test_terms_table_rejected_by_headers(self) -> None:
        self.assertFalse(_is_parameter_table(_terms_block()))

    def test_terms_section_rejected(self) -> None:
        block = _param_block()
        block["section_path"] = ["3. Terms and Definitions"]
        self.assertFalse(_is_parameter_table(block))

    def test_small_table_qualifies_row_count_is_only_evidence(self) -> None:
        # param-row-expand-v3：≥3 数据行硬门删除——行数只是分类置信证据，
        # 2 行参数表同样按行闭环（内容守恒优先于分类保守）
        block = _param_block()
        block["data_rows"] = block["data_rows"][:2]
        self.assertTrue(_is_parameter_table(block))
        result = _supplement_parameter_table_rows([], [block])
        self.assertEqual(len(result), 2)

    def test_non_table_block_rejected(self) -> None:
        block = _param_block()
        block["type"] = "paragraph"
        self.assertFalse(_is_parameter_table(block) if block.get("type") == "table" else False)


class RowExpansionTests(unittest.TestCase):
    def test_each_uncovered_row_becomes_one_requirement(self) -> None:
        block = _param_block()
        result = _supplement_parameter_table_rows([], [block])

        self.assertEqual(len(result), 3)
        by_id = {row["ai_req_id"]: row for row in result}
        first = by_id["PROW-DET-BLK-000098-R0001"]
        self.assertEqual(first["title"], "Rated voltage")
        self.assertEqual(first["source_quote"], "1. | Rated voltage | The meter shall operate at 230 V.")
        self.assertEqual(first["status"], "draft")
        self.assertEqual(first["source_mapping"], "deterministic_fallback")
        self.assertIn("参数表行确定性展开", first["suspicion_reasons"])
        self.assertEqual(first["source_block_ids"], ["BLK-000098"])

    def test_quote_is_verbatim_in_block_text(self) -> None:
        block = _param_block()
        result = _supplement_parameter_table_rows([], [block])
        for row in result:
            self.assertIn(row["source_quote"], block["text"])

    def test_llm_covered_rows_are_not_duplicated(self) -> None:
        block = _param_block()
        llm_req = {
            "ai_req_id": "AIR-1",
            "title": "电气参数",
            "description": "The meter shall operate at 230 V.",
            "source_quote": "The meter shall operate at 230 V.",
            "source_block_ids": ["BLK-000098"],
        }

        result = _supplement_parameter_table_rows([llm_req], [block])

        ids = [row["ai_req_id"] for row in result]
        self.assertNotIn("PROW-DET-BLK-000098-R0001", ids)   # 230 V 行已被覆盖
        self.assertIn("PROW-DET-BLK-000098-R0002", ids)
        self.assertIn("PROW-DET-BLK-000098-R0003", ids)
        self.assertEqual(len(result), 3)   # 1 LLM + 2 补行

    def test_terms_table_yields_no_rows(self) -> None:
        result = _supplement_parameter_table_rows([], [_terms_block()])
        self.assertEqual(result, [])

    def test_sparse_rows_skipped(self) -> None:
        block = _param_block()
        block["data_rows"].append(["4.", "", ""])
        block["text"] = render_table_text(block["headers"], block["data_rows"])
        result = _supplement_parameter_table_rows([], [block])
        self.assertEqual(len(result), 3)

    def test_group_header_rows_skipped(self) -> None:
        """合并单元格展开成全同值的分组标题行不是需求（STO 实证"3. TECHNICAL REQUIREMENTS"×N列）。"""
        block = _param_block()
        block["data_rows"].insert(0, ["2. PARAMETERS"] * 3)
        block["columns"] = 3
        block["merge_ranges"] = [[2, 1, 2, 3]]
        block["text"] = render_table_text(block["headers"], block["data_rows"])
        result = _supplement_parameter_table_rows([], [block])
        self.assertEqual(len(result), 3)
        self.assertNotIn("2. PARAMETERS", [row["title"] for row in result])

    def test_unmerged_repeated_values_are_not_silently_discarded(self) -> None:
        block = _param_block()
        block["data_rows"].insert(0, ["2. PARAMETERS"] * 3)
        block["columns"] = 3
        block["merge_ranges"] = []
        block["text"] = render_table_text(block["headers"], block["data_rows"])

        result = _supplement_parameter_table_rows([], [block])

        self.assertEqual(len(result), 4)
        self.assertIn("2. PARAMETERS", [row["title"] for row in result])

    def test_multi_level_index_not_used_as_title(self) -> None:
        """多级节号（3.1.1）是编号不是名称——标题取真实名称单元格。"""
        block = _param_block()
        block["data_rows"][0] = ["3.1.1", "Requirement for enclosure protection",
                                 "The IPUE must provide IP54 protection."]
        block["text"] = render_table_text(block["headers"], block["data_rows"])
        result = _supplement_parameter_table_rows([], [block])
        titles = [row["title"] for row in result]
        self.assertIn("Requirement for enclosure protection", titles)
        self.assertNotIn("3.1.1", titles)

    def test_row_render_matches_render_table_text(self) -> None:
        block = _param_block()
        line = _row_render_line(block["headers"], block["data_rows"][0])
        self.assertIn(line, block["text"])


class GroupHeaderEvidenceTests(unittest.TestCase):
    """S15（2026-08-03 清单）：merge_ranges=[] 是"已知无合并"的确切证据，
    不得触发历史同值启发式；只有 merge_ranges 缺失（None，旧产物无证据）
    才退回同值口径。"""

    def test_known_no_merge_does_not_use_legacy_heuristic(self) -> None:
        from extract_units import _is_group_header_evidence

        block = {"columns": 3, "merge_ranges": []}
        item = {"row_index": 2}
        self.assertFalse(_is_group_header_evidence(block, item, ["2. PARAMETERS"]))

    def test_missing_merge_evidence_uses_legacy_heuristic(self) -> None:
        from extract_units import _is_group_header_evidence

        block = {"columns": 3}
        item = {"row_index": 2}
        self.assertTrue(_is_group_header_evidence(block, item, ["2. PARAMETERS"]))

    def test_explicit_none_merge_evidence_uses_legacy_heuristic(self) -> None:
        from extract_units import _is_group_header_evidence

        block = {"columns": 3, "merge_ranges": None}
        item = {"row_index": 2}
        self.assertTrue(_is_group_header_evidence(block, item, ["2. PARAMETERS"]))

    def test_full_width_merge_anchor_is_group_header(self) -> None:
        from extract_units import _is_group_header_evidence

        block = {"columns": 3, "merge_ranges": [[2, 1, 2, 3]]}
        item = {"row_index": 2}
        self.assertTrue(_is_group_header_evidence(block, item, ["2. PARAMETERS"]))

    def test_partial_merge_anchor_is_not_group_header(self) -> None:
        from extract_units import _is_group_header_evidence

        block = {"columns": 3, "merge_ranges": [[2, 1, 2, 2]]}
        item = {"row_index": 2}
        self.assertFalse(_is_group_header_evidence(block, item, ["2. PARAMETERS"]))


def _value_spec_block() -> dict:
    """英文表头参数表（Value/Unit）——扩展前 _PARAM_REQ_CELL_RE 漏判,扩展后命中。"""
    headers = ["No.", "Parameter", "Value", "Unit"]
    data_rows = [
        ["1.", "Rated voltage", "230", "V"],
        ["2.", "Rated frequency", "50", "Hz"],
        ["3.", "Maximum current", "60", "A"],
    ]
    return {
        "block_id": "BLK-VALUE",
        "type": "table",
        "headers": headers,
        "data_rows": data_rows,
        "text": render_table_text(headers, data_rows),
        "section_path": ["5. General Technical Requirements", "5.1. Parameters"],
        "requirement_like": True,
        "noise": False,
    }


class EnglishHeaderExpansionTests(unittest.TestCase):
    """Phase 1:英文表头扩展(value/spec/min/max/...)+classify_table_kind。"""

    def test_param_req_regex_covers_english_headers(self) -> None:
        for header in ("Value", "Specification", "Spec", "Minimum", "Min", "Maximum",
                       "Max", "Limit", "Rating", "Nominal", "Tolerance", "Range", "Unit",
                       "值", "规格", "额定", "限值", "最小", "最大", "公差", "单位", "范围"):
            self.assertTrue(_PARAM_REQ_CELL_RE.search(header), f"应命中表头: {header}")
        # 原有词不回归
        for header in ("requirement", "Technical", "要求", "参数值"):
            self.assertTrue(_PARAM_REQ_CELL_RE.search(header))

    def test_is_parameter_table_accepts_value_spec_headers(self) -> None:
        # 扩展前(只 requirement/technical/...)此表会被漏判为非参数表 → 整表当一个块
        self.assertTrue(_is_parameter_table(_value_spec_block()))

    def test_classify_table_kind_parameter_and_other(self) -> None:
        # mapping_matrix 判据 Phase 3 落地;Phase 1 只区分 parameter/other
        self.assertEqual(classify_table_kind(_param_block()), "parameter")
        self.assertEqual(classify_table_kind(_value_spec_block()), "parameter")
        self.assertEqual(classify_table_kind(_terms_block()), "other")
        paragraph = {"type": "paragraph", "text": "x", "headers": [], "data_rows": []}
        self.assertEqual(classify_table_kind(paragraph), "other")

    def test_supplement_covers_newly_qualified_value_table_rows(self) -> None:
        block = _value_spec_block()
        result = _supplement_parameter_table_rows([], [block])
        self.assertEqual(len(result), 3)
        for index, row in enumerate(result, start=1):
            self.assertEqual(row["ai_req_id"], f"PROW-DET-BLK-VALUE-R{index:04d}")
            self.assertEqual(row["status"], "draft")
            self.assertEqual(row["source_mapping"], "deterministic_fallback")
            # 引句逐字 = 渲染行（行级锚定的前提）
            self.assertEqual(
                row["source_quote"],
                _row_render_line(block["headers"], block["data_rows"][index - 1]),
            )

    def test_row_name_cell_skips_extended_req_columns(self) -> None:
        # Value/Unit 列(扩展后属要求类)不当名字;名字取 Parameter 列
        headers = ["No.", "Parameter", "Value", "Unit"]
        row = ["1.", "Rated voltage", "230", "V"]
        self.assertEqual(_row_name_cell(headers, row), "Rated voltage")


if __name__ == "__main__":
    unittest.main()
