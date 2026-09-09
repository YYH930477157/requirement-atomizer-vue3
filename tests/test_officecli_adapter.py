from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from officecli_adapter import enrich_docx_blocks


class OfficeCliAdapterTests(unittest.TestCase):
    def test_xlsx_adds_stable_cell_paths_without_rewriting_values(self):
        cells = [{"sheet_name": "Requirements", "a1_address": "B2", "text": "original"}]
        rows = [{"sheet_name": "Requirements", "row_index": 2}]
        fake = '{"success":true,"data":{"sheets":[{"name":"Requirements","rows":[{"row":2,"cells":{"B2":"Office value"}}]}]}}'
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as source, tempfile.NamedTemporaryFile() as binary, \
             mock.patch.dict(os.environ, {"RATOMIZER_OFFICECLI_PATH": binary.name}, clear=False), \
             mock.patch("officecli_adapter.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=fake)
            result = __import__("officecli_adapter").enrich_xlsx_artifacts([], rows, cells, Path(source.name))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(cells[0]["text"], "original")
        self.assertEqual(cells[0]["officecli_path"], "/Requirements/B2")

    def test_unavailable_is_honest_and_does_not_mutate(self):
        blocks = [{"block_id": "B1", "type": "heading", "text": "9.1.1 The meter shall..."}]
        with mock.patch.dict(os.environ, {"RATOMIZER_OFFICECLI": "off"}, clear=False):
            result = enrich_docx_blocks(blocks, Path("/tmp/missing.docx"))
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("officecli_style", blocks[0])

    def test_style_hints_correct_numbered_body_and_lists(self):
        blocks = [
            {"block_id": "B1", "type": "heading", "text": "9 Communication", "section_path": ["9 Communication"]},
            {"block_id": "B2", "type": "heading", "text": "9.1.1 The meter shall provide a modular interface.", "section_path": ["9.1.1 The meter shall provide a modular interface."]},
            {"block_id": "B3", "type": "paragraph", "text": "Upon receipt of the request, the system shall:"},
            {"block_id": "B4", "type": "paragraph", "text": "Validate Meter B eligibility."},
        ]
        fake = '{"success":true,"data":{"content":"' \
               '[/body/p[1]] 「9 Communication」 ← Title | 26pt\\n' \
               '[/body/p[2]] 「9.1.1 The meter shall provide a modular interface.」 ← Normal | 11pt\\n' \
               '[/body/p[3]] 「Upon receipt of the request, the system shall:」 ← Normal | 11pt\\n' \
               '[/body/p[4]] • 「Validate Meter B eligibility.」 ← List Bullet | 11pt"}}'
        with tempfile.NamedTemporaryFile(suffix=".docx") as source, tempfile.NamedTemporaryFile() as binary, \
             mock.patch.dict(os.environ, {"RATOMIZER_OFFICECLI_PATH": binary.name}, clear=False), \
             mock.patch("officecli_adapter.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=fake)
            result = enrich_docx_blocks(blocks, Path(source.name))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(blocks[1]["type"], "paragraph")
        self.assertEqual(blocks[1]["section_path"], ["9 Communication"])
        self.assertTrue(blocks[3]["is_list_item"])
