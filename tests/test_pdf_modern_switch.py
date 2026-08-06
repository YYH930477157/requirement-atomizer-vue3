"""Tests for the PDF modern-parser degradation switch in parsers/pdf_parser.py.

The switch (RATOMIZER_PDF_MODERN_PARSER) defaults OFF — the handwritten
pdfplumber path then runs unchanged and emits NO ``parser_provenance`` field
(byte-identical to the pre-switch behaviour). Switching ON routes to the
modern adapter; on ``unavailable`` (the default on this machine — no parser
dependency is installed) it falls back HONESTLY to the handwritten path and
stamps ``parser_provenance``. A successful modern route stamps a modern
provenance. The handwritten body is stubbed so no real PDF is needed; no
real LLM or parser is called.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import parsers.pdf_parser as pdf_parser
import pdf_modern_adapter


def _fake_handwritten(blocks: int = 1):
    """Return a fake returning ``blocks`` bare blocks (no provenance field)."""
    def _impl(input_path, knowledge_bases, document_profile):
        return (
            [{"block_id": f"BLK-{i:06d}", "source_format": "pdf"} for i in range(1, blocks + 1)],
            [],
            [],
        )
    return _impl


class _FakeModernOk:
    status = "ok"
    is_ok = True
    provenance = {"parser": "docling", "adapter_version": pdf_modern_adapter.PDF_MODERN_ADAPTER_VERSION}

    def __init__(self) -> None:
        class _PT:
            matrix = [["A", "B"]]
            raw_matrix = [["A", "B"]]
            parse_incomplete = False
            parse_incomplete_reason = {}
            merge_ranges: list = []
            explicit_header_rows: list = []
        class _Pg:
            page_number = 1
            parsed_table = _PT()
            provenance = {"parser": "docling"}
        self.pages = (_Pg(),)


class PdfSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        # Always start from the default-OFF state.
        os.environ.pop(pdf_parser.PDF_MODERN_PARSER_SWITCH, None)
        self.addCleanup(os.environ.pop, pdf_parser.PDF_MODERN_PARSER_SWITCH, None)

    def test_switch_constant_registered(self) -> None:
        self.assertEqual(pdf_parser.PDF_MODERN_PARSER_SWITCH, "RATOMIZER_PDF_MODERN_PARSER")

    def test_default_off_runs_handwritten_without_provenance(self) -> None:
        with patch.object(pdf_parser, "_extract_pdf_handwritten", _fake_handwritten()):
            blocks, _tables, _cells = pdf_parser.extract_pdf(Path("x.pdf"))
        self.assertEqual(len(blocks), 1)
        # Default path is byte-identical to pre-switch: no provenance field added.
        self.assertNotIn("parser_provenance", blocks[0])

    def test_switch_on_unavailable_falls_back_and_stamps_provenance(self) -> None:
        os.environ[pdf_parser.PDF_MODERN_PARSER_SWITCH] = "1"
        with patch.object(pdf_parser, "_extract_pdf_handwritten", _fake_handwritten()):
            blocks, _tables, _cells = pdf_parser.extract_pdf(Path("x.pdf"))
        provenance = blocks[0]["parser_provenance"]
        self.assertTrue(provenance.startswith("pdfplumber-handwritten-fallback:"))
        # The fallback reason is the honest unavailability cause.
        self.assertIn("no_candidate_installed", provenance)

    def test_switch_on_modern_ok_stamps_modern_provenance(self) -> None:
        os.environ[pdf_parser.PDF_MODERN_PARSER_SWITCH] = "1"
        # Modern route must NOT call the handwritten body, so we patch it with
        # a plain Mock that would fail the test loudly if it were called.
        with patch.object(pdf_modern_adapter, "parse_pdf_modern", lambda path: _FakeModernOk()), \
             patch.object(pdf_parser, "_extract_pdf_handwritten") as hw:
            blocks, _tables, _cells = pdf_parser.extract_pdf(Path("x.pdf"))
        self.assertEqual(blocks[0]["parser_provenance"], "modern:docling")
        hw.assert_not_called()

    def test_switch_truthy_values_accepted(self) -> None:
        for value in ("1", "true", "YES", "on"):
            os.environ[pdf_parser.PDF_MODERN_PARSER_SWITCH] = value
            self.assertTrue(pdf_parser._pdf_modern_switch_on(), value)
        for value in ("0", "false", "", "no"):
            os.environ[pdf_parser.PDF_MODERN_PARSER_SWITCH] = value
            self.assertFalse(pdf_parser._pdf_modern_switch_on(), value)


if __name__ == "__main__":
    unittest.main()
