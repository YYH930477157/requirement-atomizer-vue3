from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atomize import build_atomic_candidates, build_chunks, extract_docx, mark_doc_regions
from tests.docx_fixtures import write_synthetic_docx


class ExtractDocxE2ETests(unittest.TestCase):
    def test_extract_docx_preserves_sections_and_generates_key_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "synthetic_standard.docx"
            write_synthetic_docx(input_path)

            blocks, table_items = extract_docx(input_path)
            mark_doc_regions(blocks, table_items)
            chunks = build_chunks(blocks, target_chars=800, include_regions={"body"})
            candidates = build_atomic_candidates(blocks, table_items, include_regions={"body"})

        blocks_by_text = {block["text"]: block for block in blocks}
        list_block = blocks_by_text["Display all segments"]

        self.assertEqual(blocks_by_text["Scope"]["type"], "heading")
        self.assertEqual(blocks_by_text["5.1 Security requirements"]["type"], "heading")
        self.assertEqual(list_block["type"], "paragraph")
        self.assertEqual(list_block["section_path"], ["Scope", "5.1 Security requirements"])
        self.assertTrue(all(block.get("doc_region") == "body" for block in blocks if block["text"] != "ABNT 2022 all rights reserved"))
        self.assertTrue(chunks)

        candidate_types = {candidate["requirement_type"] for candidate in candidates}
        self.assertIn("capability_matrix", candidate_types)
        self.assertIn("cosem_attribute_access", candidate_types)
        self.assertIn("event_definition", candidate_types)

        matrix_item = next(item for item in table_items if item.get("matrix_facts"))
        self.assertTrue(matrix_item["matrix_facts"])

        cosem_candidate = next(candidate for candidate in candidates if candidate["requirement_type"] == "cosem_attribute_access")
        self.assertIn("Clock.logical_name", cosem_candidate["object"])
        self.assertEqual(cosem_candidate["parameters"]["cosem_object"]["object_name"], "Clock")

        event_candidate = next(candidate for candidate in candidates if candidate["requirement_type"] == "event_definition")
        self.assertEqual(event_candidate["object"], "Event G1-SG10-E1")


if __name__ == "__main__":
    unittest.main()
