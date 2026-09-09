from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from semantic_segmentation import _semantic_prompt, build_semantic_report


def _blocks():
    return [
        {"block_id": "B1", "type": "paragraph", "text": "The meter shall read remotely.", "section_path": ["4"]},
        {"block_id": "B2", "type": "paragraph", "text": "This applies through the optical interface.", "section_path": ["4"]},
        {"block_id": "H1", "type": "heading", "text": "5 Events", "section_path": ["5"]},
        {"block_id": "B3", "type": "paragraph", "text": "The meter shall record events.", "section_path": ["5"]},
    ]


class SemanticSegmentationTests(unittest.TestCase):
    def test_prompt_states_contextual_goal_and_hard_constraints(self) -> None:
        prompt = _semantic_prompt()
        for phrase in (
            "lead-in sentence introduces its list",
            "numbered clause containing a full sentence",
            "preserve source order",
            "never rewrite, summarize, translate, or invent text",
            "mark the case uncertain",
        ):
            self.assertIn(phrase, prompt)

    def test_deterministic_grouping_keeps_independent_obligations_separate(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(_blocks(), source)
        self.assertEqual(report["effective_mode"], "deterministic")
        groups = [u["source_block_ids"] for u in report["units"]]
        self.assertIn(["B1", "B2"], groups)
        self.assertIn(["H1"], groups)
        self.assertIn(["B3"], groups)

    def test_colon_lead_in_owns_the_following_pdf_list(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The system shall support:", "section_path": ["4"]},
            {"block_id": "B2", "type": "paragraph", "text": "• local operation", "section_path": ["4"]},
            {"block_id": "B3", "type": "paragraph", "text": "• remote operation", "section_path": ["4"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["B1", "B2"], ["B3"]])

    def test_prose_after_a_pdf_list_starts_a_new_unit(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The system shall support:", "section_path": ["4"]},
            {"block_id": "B2", "type": "paragraph", "text": "• local operation", "section_path": ["4"]},
            {"block_id": "B3", "type": "paragraph", "text": "The system shall report the selected mode.", "section_path": ["4"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["B1", "B2"], ["B3"]])

    def test_reused_section_path_after_heading_cannot_merge_across_heading(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The meter shall read remotely.", "section_path": ["4"]},
            {"block_id": "H1", "type": "heading", "text": "5 Events", "section_path": ["5"]},
            {"block_id": "B2", "type": "paragraph", "text": "This applies through the optical interface.", "section_path": ["4"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["B1"], ["H1"], ["B2"]])

    def test_numbered_normative_heading_is_joined_to_wrapped_body(self):
        blocks = [
            {"block_id": "H1", "type": "heading", "text": "9.1.1 The meter shall provide a modular interface", "section_path": ["9", "9.1", "9.1.1 The meter shall provide a modular interface"]},
            {"block_id": "B1", "type": "paragraph", "text": "for hot-swappable communication modems.", "section_path": ["9", "9.1", "9.1.1 The meter shall provide a modular interface"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["H1", "B1"]])
        self.assertEqual(report["units"][0]["section_path"], ["9", "9.1"])

    def test_numbered_normative_heading_with_terminal_dot_is_joined(self):
        blocks = [
            {"block_id": "H1", "type": "heading", "text": "9.2.2.1. The modem shall support both paths", "section_path": ["9", "9.2", "9.2.2", "9.2.2.1. The modem shall support both paths"]},
            {"block_id": "B1", "type": "paragraph", "text": "within a single modem.", "section_path": ["9", "9.2", "9.2.2", "9.2.2.1. The modem shall support both paths"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["H1", "B1"]])
        self.assertEqual(report["units"][0]["section_path"], ["9", "9.2", "9.2.2"])

    def test_roman_subtopic_marker_starts_a_new_unit(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "Retained for a minimum of 1 year", "section_path": ["8.12"]},
            {"block_id": "B2", "type": "paragraph", "text": "v. Common Criteria Requirements", "section_path": ["8.12"]},
            {"block_id": "B3", "type": "paragraph", "text": "The bidder shall provide certification evidence.", "section_path": ["8.12"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["B1"], ["B2"], ["B3"]])

    def test_noise_blocks_never_share_a_semantic_unit_with_prose(self):
        blocks = [
            {"block_id": "N1", "type": "paragraph", "text": "Page 1 of 2", "noise": True, "section_path": ["4"]},
            {"block_id": "B1", "type": "paragraph", "text": "The meter shall report status.", "noise": False, "section_path": ["4"]},
            {"block_id": "N2", "type": "paragraph", "text": "Page 2 of 2", "noise": True, "section_path": ["4"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["N1"], ["B1"], ["N2"]])

    def test_cross_page_table_continuation_is_a_review_link_not_a_merge(self):
        blocks = [
            {
                "block_id": "T1", "type": "table", "table_id": "TBL-1",
                "page_number": 10, "columns": 4, "section_path": ["6"],
                "data_rows": [["6.25", "Sleep", "The device shall sleep", "The device shall sleep"]],
                "text": "clause | name | value",
            },
            {"block_id": "N1", "type": "paragraph", "noise": True,
             "page_number": 10, "section_path": ["6"], "text": "Page 10"},
            {
                "block_id": "T2", "type": "table", "table_id": "TBL-2",
                "page_number": 11, "columns": 4, "section_path": ["6"],
                "data_rows": [["", "", "and wake on demand", "and wake on demand"]],
                "text": "column_1 | column_2 | column_3",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual(report["counts"]["table_continuations"], 1)
        self.assertEqual(report["table_continuations"][0]["to_block_id"], "T2")
        self.assertEqual([u["source_block_ids"] for u in report["units"]], [["T1"], ["N1"], ["T2"]])
        t2 = next(u for u in report["units"] if u["source_block_ids"] == ["T2"])
        self.assertIn("possible_table_continuation", t2["review_flags"])
        self.assertEqual(t2["review_status"], "needs_review")

    def test_unrelated_next_page_table_is_not_flagged_without_clause_and_lowercase_evidence(self):
        blocks = [
            {
                "block_id": "T1", "type": "table", "table_id": "TBL-1",
                "page_number": 10, "columns": 3, "section_path": ["6"],
                "data_rows": [["6.25", "Sleep", "The device shall sleep"]],
                "text": "clause | name | value",
            },
            {
                "block_id": "T2", "type": "table", "table_id": "TBL-2",
                "page_number": 11, "columns": 3, "section_path": ["6"],
                "data_rows": [["6.26", "Network", "The device shall connect"]],
                "text": "clause | name | value",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source)
        self.assertEqual(report["table_continuations"], [])

    def test_llm_grouping_is_validated_and_cannot_cross_heading(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            def valid_groups(blocks, **_):
                ids = [b["block_id"] for b in blocks]
                return [["B1", "B2"]] if ids == ["B1", "B2"] else [["H1"], ["B3"]]
            with mock.patch("semantic_segmentation._llm_groups", side_effect=valid_groups):
                report = build_semantic_report(_blocks(), source, mode="llm")
            self.assertEqual(report["effective_mode"], "llm")
            self.assertEqual(report["errors"], [])
            # 成功节的单元如实标 llm。
            for unit in report["units"]:
                self.assertEqual(unit["boundary_basis"], "llm")
            with mock.patch("semantic_segmentation._llm_groups", return_value=[["B1", "H1"], ["B2"], ["B3"]]):
                fallback = build_semantic_report(_blocks(), source, mode="llm")
        self.assertEqual(fallback["effective_mode"], "deterministic_fallback")
        self.assertEqual(fallback["counts"]["errors"], 2)
        # 回退后单元不得再标 llm——血统按节如实（2026-09-09 review 修复）。
        for unit in fallback["units"]:
            self.assertEqual(unit["boundary_basis"], "deterministic_fallback")
