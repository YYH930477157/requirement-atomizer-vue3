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
    def test_expert_non_requirement_is_audited_but_removed_from_core_denominator(self) -> None:
        blocks = [
            {"block_id": "B1", "order": 1, "type": "paragraph",
             "text": "The meter shall expose alarms.", "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2, "type": "paragraph",
             "text": "Product family background statement.", "requirement_like": True, "noise": False},
        ]

        coverage = mc.layered_coverage(
            [], mc.coverage_denominator_blocks(blocks), source_blocks=blocks,
            expert_excluded_block_ids={"B2"},
        )

        self.assertEqual(coverage["requirement_like"], 1)
        self.assertEqual(coverage["uncovered_block_ids"], ["B1"])
        self.assertEqual(coverage["excluded"]["block_ids"], ["B2"])
        self.assertEqual(coverage["excluded"]["samples"][0]["reason"], "expert_non_requirement")

    def test_coverage_is_split_into_core_compliance_and_excluded_layers(self) -> None:
        reqs = [
            {
                "id": "R-CORE",
                "type": "behavior",
                "source_quote": "The meter shall communicate bidirectionally.",
            },
            {
                "id": "R-COMP",
                "type": "compliance",
                "source_quote": "A valid type certificate shall be supplied.",
            },
        ]
        blocks = [
            {"block_id": "B1", "order": 1, "type": "paragraph",
             "text": "The meter shall communicate bidirectionally.",
             "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2, "type": "paragraph",
             "text": "A valid type certificate shall be supplied.",
             "requirement_like": True, "noise": False},
            {"block_id": "B3", "order": 3, "type": "paragraph",
             "text": "The verification period shall comply with Decree no. 161/2019.",
             "requirement_like": True, "noise": False},
            {"block_id": "B4", "order": 4, "type": "heading",
             "text": "2.1 Legal requirements", "requirement_like": True, "noise": False},
        ]

        report = mc.analyze_consistency(reqs, mc.coverage_denominator_blocks(blocks), source_blocks=blocks)
        coverage = report["coverage"]

        self.assertEqual(coverage["scope"], "core")
        self.assertEqual(coverage["requirement_like"], 1)
        self.assertEqual(coverage["covered"], 1)
        self.assertEqual(coverage["core"]["coverage_ratio"], 1.0)
        self.assertEqual(coverage["compliance"]["requirement_like"], 2)
        self.assertEqual(coverage["compliance"]["covered"], 1)
        self.assertEqual(coverage["compliance"]["uncovered_block_ids"], ["B3"])
        self.assertEqual(coverage["excluded"]["count"], 1)
        self.assertEqual(coverage["excluded"]["block_ids"], ["B4"])

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
        self.assertEqual(cov["uncovered_block_ids"], ["B2"])

    def test_no_block_info_marks_unmeasured(self) -> None:
        cov = mc.coverage_gaps([], None)
        self.assertFalse(cov["measured"])

    def test_fragmented_block_is_covered_by_normalized_quote(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": (
                "Electricity meters must be able to communicate bidirectionally with the data "
                "and communication center."
            ),
            "source_block_ids": ["B1", "B2"],
            "source_mapping": "section_fallback",
        }]
        blocks = [
            {
                "block_id": "B1",
                "order": 1,
                "text": (
                    "Electricity meters must beable to communicate bidirectionally with the data "
                    "a nd communication center. The meter shall remain operational."
                ),
                "requirement_like": True,
                "noise": False,
            },
            {
                "block_id": "B2",
                "order": 2,
                "text": "Unrelated requirement shall remain visible.",
                "requirement_like": True,
                "noise": False,
            },
        ]

        cov = mc.coverage_gaps(reqs, blocks)

        self.assertEqual(cov["covered"], 1)
        self.assertEqual(cov["uncovered_count"], 1)
        self.assertEqual(cov["uncovered_samples"][0]["block_id"], "B2")

    def test_quote_spanning_adjacent_blocks_covers_each_source_block(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": "The meter shall communicate by modem. Communication shall use DLMS over IP.",
        }]
        blocks = [
            {"block_id": "B1", "order": 1, "section_path": ["2"],
             "text": "The meter shall communicate by modem.", "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2, "section_path": ["2"],
             "text": "Communication shall use DLMS over IP.", "requirement_like": True, "noise": False},
        ]

        cov = mc.coverage_gaps(reqs, blocks)

        self.assertEqual(cov["covered"], 2)
        self.assertEqual(cov["uncovered_count"], 0)

    def test_cross_block_reverse_match_must_cover_most_of_quote(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": (
                "Alpha requirement shall be retained. "
                "Beta requirement shall be retained. "
                "Gamma requirement shall be retained."
            ),
        }]
        blocks = [
            {"block_id": "B1", "order": 1, "text": "Alpha requirement shall be retained.",
             "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2, "text": "Beta requirement shall be retained.",
             "requirement_like": True, "noise": False},
            {"block_id": "B3", "order": 3, "text": "Gamma requirement shall be retained.",
             "requirement_like": True, "noise": False},
        ]

        self.assertEqual(mc.covered_block_ids(reqs, blocks), {"B1", "B2", "B3"})

    def test_section_fallback_ids_do_not_mark_unrelated_blocks_covered(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": "The meter shall do A.",
            "source_block_ids": ["B1", "B2"],
            "source_mapping": "section_fallback",
        }]
        blocks = [
            {"block_id": "B1", "order": 1, "text": "The meter shall do A.",
             "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2, "text": "The meter shall do B.",
             "requirement_like": True, "noise": False},
        ]

        covered = mc.covered_block_ids(reqs, blocks)

        self.assertEqual(covered, {"B1"})

    def test_fuzzy_source_mapping_does_not_count_as_coverage(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": "The meter shall record voltage events.",
            "source_block_ids": ["B1"],
            "source_mapping": "fuzzy",
        }]
        blocks = [{
            "block_id": "B1", "order": 1,
            "text": "The meter shall record current events and retain diagnostics.",
            "requirement_like": True, "noise": False,
        }]

        self.assertEqual(mc.covered_block_ids(reqs, blocks), set())

    def test_unverified_echo_id_does_not_count_as_coverage(self) -> None:
        source = (
            "The meter shall record active energy values for every configured tariff "
            "and retain the values for billing review."
        )
        unrelated = (
            "The communication module shall reconnect to the cellular network after an outage "
            "and report its diagnostic state."
        )
        reqs = [{
            "id": "R1", "source_quote": source,
            "source_block_ids": ["B1"], "source_mapping": "exact",
            "echo_block_ids": ["B2"],
        }]
        blocks = [
            {"block_id": "B1", "order": 1, "text": source,
             "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2, "text": unrelated,
             "requirement_like": True, "noise": False},
        ]

        self.assertEqual(mc.covered_block_ids(reqs, blocks), {"B1"})

    def test_nonadjacent_quote_fragments_do_not_form_a_multi_block_source(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": (
                "The meter shall communicate by modem. "
                "Communication shall use DLMS over IP."
            ),
        }]
        denominator = [
            {"block_id": "B1", "order": 1, "text": "The meter shall communicate by modem.",
             "requirement_like": True, "noise": False},
            {"block_id": "B3", "order": 3, "text": "Communication shall use DLMS over IP.",
             "requirement_like": True, "noise": False},
        ]
        source_blocks = [
            denominator[0],
            {"block_id": "B2", "order": 2,
             "text": "The supplier shall provide an unrelated maintenance service."},
            denominator[1],
        ]

        cov = mc.coverage_gaps(reqs, denominator, source_blocks=source_blocks)

        self.assertEqual(cov["covered"], 0)
        self.assertEqual(cov["uncovered_block_ids"], ["B1", "B3"])

    def test_explicit_multiline_excerpts_can_cover_separate_source_blocks(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": (
                "Valid certificate according to IEC 62053-22.\n"
                "EU declaration of conformity. ... National metrology law shall apply."
            ),
        }]
        blocks = [
            {"block_id": "B1", "order": 1,
             "text": "Valid certificate according to IEC 62053-22.",
             "requirement_like": True, "noise": False},
            {"block_id": "B2", "order": 2,
             "text": "Unrelated production equipment requirement.",
             "requirement_like": True, "noise": False},
            {"block_id": "B3", "order": 3,
             "text": "EU declaration of conformity. National metrology law shall apply.",
             "requirement_like": True, "noise": False},
        ]

        covered = mc.covered_block_ids(reqs, blocks)

        self.assertEqual(covered, {"B1", "B3"})

    def test_explicit_multiline_excerpts_require_every_excerpt_to_anchor(self) -> None:
        reqs = [{
            "id": "R1",
            "source_quote": (
                "Valid certificate according to IEC 62053-22.\n"
                "A missing declaration shall also be supplied."
            ),
        }]
        blocks = [{
            "block_id": "B1", "order": 1,
            "text": "Valid certificate according to IEC 62053-22.",
            "requirement_like": True, "noise": False,
        }]

        self.assertEqual(mc.covered_block_ids(reqs, blocks), set())


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
