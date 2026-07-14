"""P1 全局一致性 critic 回归（确定性，零 LLM）。"""
from __future__ import annotations

import unittest

import merged_consistency as mc


class CrossSectionDuplicateTests(unittest.TestCase):
    def test_same_quote_across_sections_flagged(self) -> None:
        reqs = [
            {"id": "REQ-001", "source_quote": "The meter shall record total active energy import.",
             "source_section": "4.1"},
            {"id": "REQ-050", "source_quote": "The meter shall record total active energy import.",
             "source_section": "7.3"},
        ]
        groups = mc.find_cross_section_duplicates(reqs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(sorted(groups[0]["members"]), ["REQ-001", "REQ-050"])
        self.assertEqual(groups[0]["sections"], ["4.1", "7.3"])

    def test_short_quotes_not_grouped(self) -> None:
        reqs = [{"id": "A", "source_quote": "see 4.2"}, {"id": "B", "source_quote": "see 4.2"}]
        self.assertEqual(mc.find_cross_section_duplicates(reqs), [])

    def test_distinct_quotes_not_grouped(self) -> None:
        reqs = [
            {"id": "A", "source_quote": "The meter shall record total active energy."},
            {"id": "B", "source_quote": "The meter shall log power failure events."},
        ]
        self.assertEqual(mc.find_cross_section_duplicates(reqs), [])


class ObisCoreferenceTests(unittest.TestCase):
    def test_same_obis_multiple_reqs_grouped(self) -> None:
        reqs = [
            {"id": "R1", "source_quote": "energy register at 1-0:1.8.0.255, class_id 3", "source_section": "4"},
            {"id": "R2", "source_quote": "read 1-0:1.8.0.255 attribute", "source_section": "5"},
        ]
        groups = mc.find_obis_coreference(reqs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["obis"], "1-0:1.8.0.255")
        self.assertEqual(sorted(groups[0]["members"]), ["R1", "R2"])

    def test_values_differ_flag_when_numeric_context_diverges(self) -> None:
        # 同一 OBIS，一条带 100（entries），一条不带 → 数值上下文发散，标待核
        reqs = [
            {"id": "R1", "source_quote": "log to 0-0:99.98.0.255 keep 100 entries"},
            {"id": "R2", "source_quote": "events at 0-0:99.98.0.255 with severity high"},
        ]
        groups = mc.find_obis_coreference(reqs)
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["values_differ"])

    def test_singleton_obis_not_grouped(self) -> None:
        reqs = [{"id": "R1", "source_quote": "only ref 1-0:1.8.0.255"}]
        self.assertEqual(mc.find_obis_coreference(reqs), [])

    def test_values_differ_groups_sort_first(self) -> None:
        reqs = [
            {"id": "A1", "source_quote": "1-0:1.8.0.255 attribute"},
            {"id": "A2", "source_quote": "1-0:1.8.0.255 attribute"},   # same ints → no divergence
            {"id": "B1", "source_quote": "0-0:99.98.0.255 keep 100"},
            {"id": "B2", "source_quote": "0-0:99.98.0.255 severity"},  # divergent ints
        ]
        groups = mc.find_obis_coreference(reqs)
        self.assertTrue(groups[0]["values_differ"])   # 待核组排最前


class CoverageGapTests(unittest.TestCase):
    def test_uncovered_requirement_like_reported(self) -> None:
        reqs = [{"id": "R1", "source_quote": "The meter shall do A."}]
        blocks = [
            {"block_id": "B1", "text": "The meter shall do A.", "requirement_like": True, "noise": False},
            {"block_id": "B2", "text": "The meter shall do B.", "requirement_like": True, "noise": False},
        ]
        cov = mc.coverage_gaps(reqs, blocks)
        self.assertTrue(cov["measured"])
        self.assertEqual(cov["requirement_like"], 2)
        self.assertEqual(cov["covered"], 1)
        self.assertEqual(cov["uncovered_count"], 1)
        # 0714 批次一：样本带溯源（block_id/section），供澄清清单与批注视图回链
        self.assertEqual(cov["uncovered_samples"][0]["text"], "The meter shall do B.")
        self.assertEqual(cov["uncovered_samples"][0]["block_id"], "B2")

    def test_no_block_info_marks_unmeasured(self) -> None:
        cov = mc.coverage_gaps([], None)
        self.assertFalse(cov["measured"])


class AnalyzeConsistencyTests(unittest.TestCase):
    def test_summary_counts(self) -> None:
        reqs = [
            {"id": "R1", "source_quote": "The meter shall record total active energy import.",
             "source_section": "4"},
            {"id": "R2", "source_quote": "The meter shall record total active energy import.",
             "source_section": "7"},
            {"id": "R3", "source_quote": "read 1-0:1.8.0.255 keep 100"},
            {"id": "R4", "source_quote": "read 1-0:1.8.0.255 severity high"},
        ]
        blocks = [{"block_id": "B1", "text": "uncovered requirement statement here",
                   "requirement_like": True, "noise": False}]
        report = mc.analyze_consistency(reqs, blocks)
        self.assertEqual(report["summary"]["duplicate_groups"], 1)
        self.assertGreaterEqual(report["summary"]["obis_coreference_groups"], 1)
        self.assertEqual(report["summary"]["obis_values_differ"], 1)
        self.assertEqual(report["summary"]["uncovered_requirement_like"], 1)

    def test_non_destructive_reports_only(self) -> None:
        # critic 只读只报，不改输入需求（结构字段一位不动）
        reqs = [{"id": "R1", "source_quote": "The meter shall record total active energy import.",
                 "labels": ["计量"]}]
        before = [dict(r) for r in reqs]
        mc.analyze_consistency(reqs, None)
        self.assertEqual(reqs, before)


if __name__ == "__main__":
    unittest.main()
