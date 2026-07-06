"""行契约 + 产物血统（F2）回归。"""
from __future__ import annotations

import unittest

from requirement_record import (
    check_provenance,
    provenance,
    validate_requirement_row,
    validate_rows,
)


def good_row() -> dict:
    return {"title": "t", "description": "d", "type": "functional", "priority": "P1",
            "module": "计量", "labels": ["计量"], "source_quote": "q", "source_section": "4",
            "source_block_ids": ["B1"], "acceptance_criteria": [], "dev_guidance": [],
            "notes": "", "status": "draft", "threshold_table": None,
            "sub_items": [{"label": "a", "text": "x"}]}


class ContractTests(unittest.TestCase):
    def test_good_row_passes(self) -> None:
        self.assertEqual(validate_requirement_row(good_row()), [])

    def test_missing_key_and_wrong_types_reported(self) -> None:
        row = good_row()
        del row["source_block_ids"]
        row["labels"] = "计量"
        row["threshold_table"] = []
        row["sub_items"] = ["not-a-dict"]
        problems = validate_requirement_row(row)
        joined = "；".join(problems)
        self.assertIn("缺键 source_block_ids", joined)
        self.assertIn("labels 应为 list", joined)
        self.assertIn("threshold_table 应为 dict|None", joined)
        self.assertIn("sub_items 应为 dict 列表", joined)

    def test_validate_rows_counts_bad(self) -> None:
        rows = [good_row(), {"title": 1}]
        self.assertEqual(validate_rows(rows, where="t"), 1)


class ProvenanceTests(unittest.TestCase):
    def test_stamp_shape(self) -> None:
        stamp = provenance("ai_extract", "ai-extract-v11")
        self.assertEqual(stamp["producer"], "ai_extract")
        self.assertEqual(stamp["producer_version"], "ai-extract-v11")
        self.assertIn("generated_at", stamp)

    def test_check_warns_on_stale_version_only(self) -> None:
        payload = {"provenance": provenance("requirements_analysis", "analyze-llm-v2")}
        warn = check_provenance(payload, expect_producer="requirements_analysis",
                                current_version="analyze-llm-v3")
        self.assertIn("analyze-llm-v2", warn)
        self.assertEqual(check_provenance(payload, expect_producer="requirements_analysis",
                                          current_version="analyze-llm-v2"), "")
        self.assertEqual(check_provenance({}, expect_producer="x", current_version="1"), "")
