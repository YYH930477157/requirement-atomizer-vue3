"""Shared workbook column authority used by writer and A/B gate."""
from __future__ import annotations

import unittest

import template_columns as tc
import template_writer as tw
from tools import ab_runner as ab


class TemplateColumnsTests(unittest.TestCase):
    def test_writer_and_gate_share_contract(self) -> None:
        self.assertIs(tw.WRITER_COLUMN_CONTRACT, tc.WRITER_COLUMN_CONTRACT)
        self.assertIs(ab.XLSX_COLUMN_ALIASES, tc.XLSX_COLUMN_ALIASES)
        header = ("关闭", "序号", "子模块", "描述", "需求模版", "需求",
                  "说明、示例、注意事项", "是否客户需求", "客户需求章节")
        self.assertEqual(
            tw.resolve_writer_sheet_columns(header),
            {"seq": 2, "submodule": 3, "question": 4, "template": 5,
             "answer": 6, "notes": 7, "is_customer": 8, "section": 9},
        )
        self.assertEqual(ab._writer_contract_columns(header), tc.WRITER_COLUMN_CONTRACT)

    def test_signed_split_body_uses_fixed_contract(self) -> None:
        # 电表类型拆分列没有「需求」表头；正文仍在写入器契约的第 6 列。
        header = ("关闭", "序号", "子模块", "描述", "需求模版", "1P2W_SP",
                  "说明、示例、注意事项", "是否客户需求", "客户需求章节")
        self.assertIsNone(tc.resolve_writer_sheet_columns(header))
        self.assertEqual(ab._writer_contract_columns(header), tc.WRITER_COLUMN_CONTRACT)

    def test_normalization_matches_gate_semantics(self) -> None:
        self.assertEqual(tc.normalize_header("  Requirement Text "), "requirementtext")
        self.assertEqual(ab._locate_columns((" Module ", "Requirement Text")),
                         {"module": 1, "body": 2})


if __name__ == "__main__":
    unittest.main()
