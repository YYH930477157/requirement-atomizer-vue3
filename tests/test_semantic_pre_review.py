from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from semantic_pre_review import build_semantic_pre_review
from semantic_segmentation import build_semantic_report


class SemanticPreReviewTests(unittest.TestCase):
    def test_deterministic_pre_review_is_source_conserving_and_builds_map(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The audit log shall be:", "section_path": ["8"]},
            {"block_id": "B2", "type": "paragraph", "text": "- Tamper-evident entries", "section_path": ["8"]},
            {"block_id": "B3", "type": "paragraph", "text": "- Retained for 1 year", "section_path": ["8"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_pre_review(blocks, source)
        self.assertEqual(report["effective_mode"], "deterministic")
        self.assertEqual([row["element_id"] for row in report["elements"]], ["B1", "B2", "B3"])
        self.assertEqual(report["elements"][1]["relation_to_previous"], "continues")
        self.assertEqual(report["semantic_map"]["topics"][0]["element_ids"], ["B1", "B2", "B3"])

    def test_llm_payload_is_validated_and_invalid_payload_falls_back(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The meter shall report status.", "section_path": ["4"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_pre_review(
                blocks, source, mode="llm", chat=lambda _system, _user: {"elements": [{"element_id": "WRONG"}]},
            )
        self.assertEqual(report["effective_mode"], "deterministic")
        self.assertTrue(report["errors"])
        self.assertEqual(report["counts"]["annotations"], 1)

    def test_llm_payload_preserves_order_and_records_route(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The system shall support:", "section_path": ["4"]},
            {"block_id": "B2", "type": "paragraph", "text": "- local operation", "section_path": ["4"]},
        ]
        payload = {"elements": [
            {"element_id": "B1", "role": "body", "relation_to_previous": "independent", "boundary_after": False, "context_owner": "support", "uncertainty": "low", "reason": "lead-in"},
            {"element_id": "B2", "role": "list_item", "relation_to_previous": "continues", "boundary_after": True, "context_owner": "support", "uncertainty": "low", "reason": "list item"},
        ]}
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.docx"
            source.write_bytes(b"doc")
            report = build_semantic_pre_review(blocks, source, mode="llm", route="openai_compatible", chat=lambda _system, _user: payload)
        self.assertEqual(report["effective_mode"], "llm")
        self.assertEqual(report["route"], "injected")
        self.assertEqual([row["element_id"] for row in report["elements"]], ["B1", "B2"])

    def test_llm_pre_review_is_consumed_by_semantic_segmentation(self):
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The system shall support:", "section_path": ["4"]},
            {"block_id": "B2", "type": "paragraph", "text": "- local operation", "section_path": ["4"], "is_list_item": True},
        ]
        pre_review = {"effective_mode": "llm", "elements": [
            {"element_id": "B1", "relation_to_previous": "independent"},
            {"element_id": "B2", "relation_to_previous": "continues"},
        ]}
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "doc.pdf"
            source.write_bytes(b"doc")
            report = build_semantic_report(blocks, source, mode="llm", pre_review=pre_review)
        self.assertEqual(report["units"][0]["source_block_ids"], ["B1", "B2"])


if __name__ == "__main__":
    unittest.main()
