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
            with mock.patch("semantic_segmentation._llm_groups", return_value=[["B1", "H1"], ["B2"], ["B3"]]):
                fallback = build_semantic_report(_blocks(), source, mode="llm")
        self.assertEqual(fallback["effective_mode"], "deterministic_fallback")
        self.assertEqual(fallback["counts"]["errors"], 2)
