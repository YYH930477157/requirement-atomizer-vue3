from __future__ import annotations

import unittest

from atomize import (
    DocumentProfile,
    detect_heading,
    is_noise,
    looks_like_caption,
    mark_doc_regions,
)


class DocumentProfileTests(unittest.TestCase):
    def test_profile_noise_patterns_and_exact_values_extend_default_noise_rules(self) -> None:
        profile = DocumentProfile(
            noise_patterns=("vendor confidential",),
            noise_exact=("draft watermark",),
        )

        self.assertTrue(is_noise("Vendor Confidential - internal", document_profile=profile))
        self.assertTrue(is_noise("Draft Watermark", document_profile=profile))
        self.assertFalse(is_noise("Vendor Confidential - internal"))

    def test_profile_major_headings_extend_heading_detection(self) -> None:
        profile = DocumentProfile(major_headings=("conformance",))

        self.assertEqual(detect_heading("Conformance", "Normal", document_profile=profile), (1, "Conformance"))
        self.assertIsNone(detect_heading("Conformance", "Normal"))

    def test_profile_caption_pattern_replaces_caption_detection(self) -> None:
        profile = DocumentProfile(caption_pattern=r"^appendix\s+table\s+\d+\b")

        self.assertTrue(looks_like_caption("Appendix Table 7 - Object map", document_profile=profile))
        self.assertFalse(looks_like_caption("Appendix Table 7 - Object map"))

    def test_profile_body_start_heading_controls_region_marking(self) -> None:
        blocks = [
            {"block_id": "B1", "type": "heading", "text": "Preface", "section_path": ["Preface"]},
            {"block_id": "B2", "type": "heading", "text": "Overview", "section_path": ["Overview"]},
            {"block_id": "B3", "type": "paragraph", "text": "Normative body starts here.", "section_path": ["Overview"]},
            {"block_id": "B4", "type": "heading", "text": "Scope", "section_path": ["Scope"]},
        ]
        table_items = [{"item_id": "T1-R1", "table_block_id": "B3"}]

        mark_doc_regions(blocks, table_items, document_profile=DocumentProfile(body_start_heading="overview"))

        self.assertEqual([block["doc_region"] for block in blocks], ["preface", "body", "body", "body"])
        self.assertEqual(table_items[0]["doc_region"], "body")


if __name__ == "__main__":
    unittest.main()
