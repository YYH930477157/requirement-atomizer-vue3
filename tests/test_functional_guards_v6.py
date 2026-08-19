"""guards-v6：表格标题前缀伪影修复（phase2 第 1 项探针实证，2026-08-17c）。

背景：chunk 渲染给表格块加 `[TBL-NNNNNN] 标题` 前缀。flash 直抽的引句常原样带回
该前缀 → `quote_matches_no_block` 假失败；前缀里的 6 位数字进入保真基线 →
preservation 假 blocking（token "000008" 实为表格 ID）。守恒检查侧统一剥离。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import functional_extract as fe


def _section(section_id: str, text: str, block_ids: list[str]) -> dict:
    return {"section_id": section_id, "section_path": [section_id],
            "heading": section_id, "text": text, "block_ids": block_ids}


class TableMarkerStripTests(unittest.TestCase):
    def test_strip_removes_marker_line_only(self) -> None:
        raw = "[TBL-000008] Table 7 (continuation)\nGroup number | Subgroup\n3 | 31"
        self.assertEqual(fe._strip_table_markers(raw),
                         "\nGroup number | Subgroup\n3 | 31")

    def test_text_without_markers_unchanged(self) -> None:
        raw = "The meter shall log events at 230 V."
        self.assertEqual(fe._strip_table_markers(raw), raw)


class QuoteEvidenceTests(unittest.TestCase):
    def test_quote_with_table_marker_prefix_now_matches(self) -> None:
        block = {"block_id": "B1", "type": "table", "section_path": ["2 20"],
                 "text": "Group number | Subgroup number | Event subgroup description\n"
                         "3 | 31 | Quality event not finished"}
        quote = ("[TBL-000008] Table 7 (continuation)\n"
                 "Group number | Subgroup number | Event subgroup description\n"
                 "3 | 31 | Quality event not finished")
        section = _section("2 20", block["text"], ["B1"])
        item = {"functional_requirement_id": "FRE-1",
                "source_block_ids": ["B1"], "source_quote": quote,
                "objective": "Quality event not finished"}
        report = fe.conservation_report([section], [item], blocks=[block])
        evidence = report["checks"]["evidence_presence"]
        self.assertTrue(evidence["ok"], evidence)


class PreservationBaselineTests(unittest.TestCase):
    def test_table_id_digits_not_counted_as_content_numbers(self) -> None:
        # 节文本只含表格标记 + 一行无数字义务句：000008 不得成为 blocking number
        section = _section(
            "2 20", "[TBL-000008] Table 7 (continuation)\nThe meter shall log events.",
            ["B1"])
        block = {"block_id": "B1", "type": "table", "section_path": ["2 20"],
                 "text": "[TBL-000008] Table 7 (continuation)\nThe meter shall log events."}
        item = {"functional_requirement_id": "FRE-1",
                "source_block_ids": ["B1"],
                "source_quote": "The meter shall log events.",
                "objective": "电表应记录事件。", "description": "电表应记录事件。"}
        report = fe.conservation_report([section], [item], blocks=[block])
        preservation = report["checks"]["preservation"]
        number_tokens = [f["token"] for f in preservation.get("blocking_losses", [])
                         if f.get("kind") == "number"]
        self.assertNotIn("000008", number_tokens)
        self.assertNotIn("8", number_tokens)


class GuardsVersionTests(unittest.TestCase):
    def test_version_bumped(self) -> None:
        self.assertEqual(fe.FUNCTIONAL_EXTRACT_GUARDS_VERSION,
                         "functional-extract-guards-v6")


if __name__ == "__main__":
    unittest.main()
