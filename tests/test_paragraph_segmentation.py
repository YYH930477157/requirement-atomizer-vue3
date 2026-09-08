from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from paragraph_segmentation import SegmentationOptions, build_segmentation_report, render_segmentation_review


class ParagraphSegmentationContractTests(unittest.TestCase):
    def test_options_require_explicit_visual_capability_for_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            SegmentationOptions(mode="vision_assisted", fallback="fail_closed") .initial_mode()
        self.assertEqual(
            SegmentationOptions(mode="vision_assisted", fallback="text_fallback").initial_mode(),
            "text_only",
        )

    def test_report_preserves_source_text_and_marks_uncertain_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "sample.docx"
            source.write_bytes(b"source")
            blocks = [{
                "block_id": "BLK-1", "order": 1, "type": "paragraph",
                "text": "Line one Line two", "raw_text": "Line one\nLine two",
                "section_path": ["4 Requirements"], "is_list_item": False,
            }, {
                "block_id": "BLK-2", "order": 2, "type": "heading",
                "text": "A" * 161, "raw_text": "A" * 161, "section_path": ["4 Requirements"],
            }]
            report = build_segmentation_report(blocks, source, SegmentationOptions())
            self.assertEqual(report["schema"], "paragraph-segmentation/v1")
            self.assertEqual(report["units"][0]["text_original"], "Line one\nLine two")
            self.assertIn("manual_line_breaks_preserved_in_source", report["units"][0]["review_flags"])
            self.assertIn("possible_heading_body_merge", report["units"][1]["review_flags"])
            page = render_segmentation_review(report)
            self.assertIn("Line one\nLine two", page)
            self.assertIn("规则提示不等于错误", page)

    def test_lineage_is_key_free_and_distinguishes_modes(self) -> None:
        text = SegmentationOptions(mode="text_only").lineage()
        layout = SegmentationOptions(mode="layout").lineage()
        self.assertEqual(text["version"], "paragraph-segmentation-v1")
        self.assertEqual(text["mode"], "text_only")
        self.assertEqual(layout["mode"], "layout")
        self.assertNotIn("api_key", json.dumps(layout))
