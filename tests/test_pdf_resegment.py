"""Tests for parsers/pdf_resegment.py (A8②)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from parsers.pdf_resegment import (
    PDF_RESEG_SWITCH,
    PDF_RESEG_WORDLIST,
    load_resegment_wordlist,
    maybe_resegment,
    resegment_enabled,
    resegment_text,
)


class ResegmentTests(unittest.TestCase):
    def setUp(self):
        self._clean_env()

    def tearDown(self):
        self._clean_env()
        load_resegment_wordlist.cache_clear()

    def _clean_env(self):
        for key in (PDF_RESEG_SWITCH, PDF_RESEG_WORDLIST):
            os.environ.pop(key, None)

    def test_default_off_returns_original(self):
        text = "Water M eters shall log"
        result, events = maybe_resegment(text)
        self.assertEqual(result, text)
        self.assertEqual(events, [])

    def test_switch_on_merges_known_word(self):
        os.environ[PDF_RESEG_SWITCH] = "1"
        text = "The meter shall M easure ment data"
        result, events = resegment_text(text)
        self.assertEqual(result, "The meter shall measurement data")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["before"], "M easure ment")
        self.assertEqual(events[0]["after"], "measurement")

    def test_unknown_fragment_left_untouched(self):
        os.environ[PDF_RESEG_SWITCH] = "1"
        text = "Xy Zy shall log"
        result, events = resegment_text(text)
        self.assertEqual(result, text)
        self.assertEqual(events, [])

    def test_yaml_wordlist_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "words.yaml"
            path.write_text("words:\n  - customword\n  - anotherterm\n", encoding="utf-8")
            os.environ[PDF_RESEG_SWITCH] = "1"
            os.environ[PDF_RESEG_WORDLIST] = str(path)
            load_resegment_wordlist.cache_clear()
            result, events = resegment_text("Cus Tomword test")
            self.assertEqual(result, "customword test")
            self.assertEqual(len(events), 1)

    def test_plain_wordlist_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "words.txt"
            path.write_text("# comment\nplainword\n", encoding="utf-8")
            os.environ[PDF_RESEG_SWITCH] = "1"
            os.environ[PDF_RESEG_WORDLIST] = str(path)
            load_resegment_wordlist.cache_clear()
            result, events = resegment_text("Pla Inword test")
            self.assertEqual(result, "plainword test")

    def test_enabled_helper(self):
        self.assertFalse(resegment_enabled())
        os.environ[PDF_RESEG_SWITCH] = "1"
        self.assertTrue(resegment_enabled())
        os.environ[PDF_RESEG_SWITCH] = "0"
        self.assertFalse(resegment_enabled())


if __name__ == "__main__":
    unittest.main()
