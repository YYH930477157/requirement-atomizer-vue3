"""Tests for parsers/html_parser.py (A5①)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parsers.html_parser import HtmlParser, extract_html


class ExtractHtmlTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_html(self, content: str) -> Path:
        path = Path(self.tmpdir.name) / "doc.html"
        path.write_text(content, encoding="utf-8")
        return path

    def test_headings_and_paragraphs(self):
        path = self._write_html("""
        <html><body>
          <h1>Scope</h1>
          <p>The meter shall support logging.</p>
          <h2>Terms</h2>
          <p>Definitions go here.</p>
        </body></html>
        """)
        blocks, items, cells = extract_html(path)
        self.assertEqual(len(blocks), 4)
        self.assertEqual(blocks[0]["type"], "heading")
        self.assertEqual(blocks[0]["text"], "Scope")
        self.assertEqual(blocks[0]["heading_level"], 1)
        self.assertEqual(blocks[1]["type"], "paragraph")
        self.assertEqual(blocks[1]["text"], "The meter shall support logging.")
        self.assertEqual(blocks[1]["section_path"], ["Scope"])
        self.assertEqual(blocks[3]["section_path"], ["Scope", "Terms"])
        self.assertEqual(len(items), 0)
        self.assertEqual(len(cells), 0)

    def test_table_extraction(self):
        path = self._write_html("""
        <html><body>
          <table>
            <tr><th>Parameter</th><th>Value</th></tr>
            <tr><td>Voltage</td><td>230 V</td></tr>
          </table>
        </body></html>
        """)
        blocks, items, cells = extract_html(path)
        table_blocks = [b for b in blocks if b["type"] == "table"]
        self.assertEqual(len(table_blocks), 1)
        self.assertEqual(table_blocks[0]["table_id"], "TBL-000001")
        self.assertEqual(len(items), 1)
        self.assertEqual(len(cells), 4)

    def test_script_and_style_ignored(self):
        path = self._write_html("""
        <html><body>
          <script>alert('x');</script>
          <style>body {}</style>
          <p>Visible text.</p>
        </body></html>
        """)
        blocks, _, _ = extract_html(path)
        texts = [b["text"] for b in blocks]
        self.assertIn("Visible text.", texts)
        self.assertNotIn("alert('x');", texts)
        self.assertNotIn("body {}", texts)


class HtmlParserInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_parser_interface(self):
        path = Path(self.tmpdir.name) / "doc.html"
        path.write_text("<html><body><p>Hello.</p></body></html>", encoding="utf-8")
        parser = HtmlParser()
        ir = parser.parse(path)
        self.assertEqual(ir.source_format, "html")
        self.assertEqual(ir.title, "doc")
        self.assertEqual(len(ir.blocks), 1)
        self.assertEqual(ir.blocks[0].text_original, "Hello.")


if __name__ == "__main__":
    unittest.main()
