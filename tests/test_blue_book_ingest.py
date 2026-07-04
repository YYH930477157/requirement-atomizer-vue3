from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BlueBookIngestTests(unittest.TestCase):
    def test_part2_splits_heading_sections_and_ignores_toc_rows(self) -> None:
        import blue_book_ingest

        toc = """
        COSEM Interface Classes
        4.3.1 Data (class_id = 1, version = 0) ........ 56
        4.3.2 Register (class_id = 3, version = 0) ........ 57
        """
        register = """
        DLMS UA 1000-2 Ed. 16
        COSEM Interface Classes
        4.3.2 Register (class_id = 3, version = 0)
        The register class stores a measured value.
        Attributes
        1 logical_name octet-string
        2 value choice
        3 scaler_unit structure
        Methods
        1 reset(data)
        DLMS UA 1000-2 Ed. 16
        """

        index = blue_book_ingest.build_index_from_text_sources([
            blue_book_ingest.TextSource(
                source_file="Blue-Book-Ed-16-part-2-V1.0.pdf",
                pages=[
                    blue_book_ingest.PageText(1, toc),
                    blue_book_ingest.PageText(57, register),
                ],
            )
        ])

        self.assertEqual(set(index["interface_classes"]), {"3"})
        entry = index["interface_classes"]["3"]
        self.assertEqual(entry["name"], "Register")
        self.assertEqual(entry["version"], 0)
        self.assertEqual(entry["section"], "4.3.2")
        self.assertEqual(entry["pages"], [57])
        self.assertIn("value", entry["text"])
        self.assertIn("scaler_unit", entry["text"])
        self.assertIn("2 value", entry["attributes"])
        self.assertIn("1 reset(data)", entry["methods"])
        self.assertNotIn("........", entry["text"])

    def test_part2_merges_versions_under_highest_version_entry(self) -> None:
        import blue_book_ingest

        v0 = """
        4.3.2 Register (class_id = 3, version = 0)
        Version zero behavior and compatibility text.
        """
        v1 = """
        4.3.3 Register (class_id = 3, version = 1)
        Version one behavior with extra capture metadata.
        """

        index = blue_book_ingest.build_index_from_text_sources([
            blue_book_ingest.TextSource(
                source_file="Blue-Book-Ed-16-part-2-V1.0.pdf",
                pages=[blue_book_ingest.PageText(10, v0), blue_book_ingest.PageText(11, v1)],
            )
        ])

        entry = index["interface_classes"]["3"]
        self.assertEqual(entry["version"], 1)
        self.assertEqual(entry["section"], "4.3.3")
        self.assertEqual(entry["pages"], [10, 11])
        self.assertIn("Version zero behavior", entry["text"])
        self.assertIn("Version one behavior", entry["text"])
        self.assertIn("version = 0", entry["text"])
        self.assertIn("version = 1", entry["text"])

    def test_repeated_page_headers_and_footers_are_cleaned(self) -> None:
        import blue_book_ingest

        page1 = """
        COSEM Interface Classes
        DLMS UA 1000-2 Ed. 16
        4.3.1 Data (class_id = 1, version = 0)
        Data text that is long enough to be treated as body content.
        DLMS UA 1000-2 Ed. 16
        """
        page2 = """
        COSEM Interface Classes
        DLMS UA 1000-2 Ed. 16
        4.3.2 Register (class_id = 3, version = 0)
        Register body content with value and scaler_unit fields.
        DLMS UA 1000-2 Ed. 16
        """

        index = blue_book_ingest.build_index_from_text_sources([
            blue_book_ingest.TextSource(
                source_file="Blue-Book-Ed-16-part-2-V1.0.pdf",
                pages=[blue_book_ingest.PageText(1, page1), blue_book_ingest.PageText(2, page2)],
            )
        ])

        text = index["interface_classes"]["3"]["text"]
        self.assertNotIn("COSEM Interface Classes", text)
        self.assertNotIn("DLMS UA 1000-2 Ed. 16", text)
        self.assertIn("Register body content", text)

    def test_part1_obis_value_group_sections_are_collected(self) -> None:
        import blue_book_ingest

        index = blue_book_ingest.build_index_from_text_sources([
            blue_book_ingest.TextSource(
                source_file="Blue-Book-Ed-16-part-1-V1.0.pdf",
                pages=[
                    blue_book_ingest.PageText(
                        30,
                        """
                        6.1 Value group C
                        Value group C identifies the measured quantity for electricity.
                        """,
                    )
                ],
            )
        ])

        self.assertEqual(len(index["obis_sections"]), 1)
        section = index["obis_sections"][0]
        self.assertEqual(section["key"], "value-group-c")
        self.assertEqual(section["section"], "6.1")
        self.assertEqual(section["pages"], [30])
        self.assertIn("measured quantity", section["text"])

    def test_main_writes_deterministic_index_and_stdout_envelope(self) -> None:
        import blue_book_ingest

        sources = {
            "part1.pdf": [
                blue_book_ingest.PageText(30, "6.1 Value group C\nValue group C electricity text."),
            ],
            "part2.pdf": [
                blue_book_ingest.PageText(
                    57,
                    """
                    4.3.2 Register (class_id = 3, version = 0)
                    Register text includes value and scaler_unit.
                    Attributes
                    1 logical_name
                    2 value
                    3 scaler_unit
                    """,
                )
            ],
        }

        def fake_read_pdf_pages(path: Path) -> list[blue_book_ingest.PageText]:
            return sources[path.name]

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            stdout = io.StringIO()
            with patch("blue_book_ingest.read_pdf_pages", side_effect=fake_read_pdf_pages), contextlib.redirect_stdout(stdout):
                exit_code = blue_book_ingest.main(["--pdf", "part1.pdf", "--pdf", "part2.pdf", "--out", str(out_dir)])
            first_payload = json.loads((out_dir / "blue_book_index.json").read_text(encoding="utf-8"))
            first_bytes = (out_dir / "blue_book_index.json").read_bytes()

            stdout_second = io.StringIO()
            with patch("blue_book_ingest.read_pdf_pages", side_effect=fake_read_pdf_pages), contextlib.redirect_stdout(stdout_second):
                second_exit_code = blue_book_ingest.main(["--pdf", "part1.pdf", "--pdf", "part2.pdf", "--out", str(out_dir)])
            second_bytes = (out_dir / "blue_book_index.json").read_bytes()

        envelope = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(second_exit_code, 0)
        self.assertEqual(first_bytes, second_bytes)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["command"], "blue_book_ingest")
        self.assertEqual(envelope["stats"]["interface_classes"], 1)
        self.assertEqual(envelope["stats"]["obis_sections"], 1)
        self.assertEqual(first_payload["meta"]["schema_version"], "blue-book-index/v1")
        self.assertEqual(first_payload["interface_classes"]["3"]["name"], "Register")

    def test_packaging_registration_and_ignore_rules_include_blue_book_ingest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        ratomizer_spec = (root / "packaging" / "ratomizer.spec").read_text(encoding="utf-8")
        desktop_spec = (root / "packaging" / "desktop_backend.spec").read_text(encoding="utf-8")
        gitignore = (root / ".gitignore").read_text(encoding="utf-8")

        self.assertIn('"blue_book_ingest"', pyproject)
        self.assertIn('"blue_book_ingest"', ratomizer_spec)
        self.assertIn('"blue_book_ingest"', desktop_spec)
        self.assertIn("blue_book_index.json", gitignore)


if __name__ == "__main__":
    unittest.main()
