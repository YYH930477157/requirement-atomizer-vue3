"""PDF 排版保真回归（2026-07-07 UNI 12007 机翻文档真实案例）。"""
from __future__ import annotations

import unittest

from parsers.pdf_parser import (
    DEFRAG_RATIO_THRESHOLD,
    _COPYRIGHT_FOOTER_RE,
    _normalize_repeated_line,
    defragment_text,
)


class DefragTests(unittest.TestCase):
    def test_real_fragment_patterns_joined(self) -> None:
        cases = {
            "Water M eters - V alue-Added F unctions": "Water Meters - Value-Added Functions",
            "UNI/TS 1 2007:2026": "UNI/TS 12007:2026",
            "UNI EN I SO 4 064-5:2023": "UNI EN ISO 4064-5:2023",
            "February 2 026": "February 2026",
            "© O NE Page 5": "© ONE Page 5",
        }
        for raw, expect in cases.items():
            self.assertEqual(defragment_text(raw), expect)

    def test_reference_letters_protected(self) -> None:
        """Annex/Class/Table 等后的单个大写字母是合法引用，不拼合（自审实锤的误伤）。"""
        cases = [
            "Annex A B gives the procedure",
            "meters of class A and class B",
            "see Annex B before testing",
        ]
        for text in cases:
            self.assertEqual(defragment_text(text), text)

    def test_normal_text_untouched(self) -> None:
        text = "The AFD shall withstand a drop from 0,5 m as given in Table 6."
        self.assertEqual(defragment_text(text), text)

    def test_threshold_documented(self) -> None:
        self.assertGreater(DEFRAG_RATIO_THRESHOLD, 0)   # 门控存在（ABNT 实测 0.001，UNI 0.19）


class FooterNoiseTests(unittest.TestCase):
    def test_copyright_footer_pattern(self) -> None:
        self.assertTrue(_COPYRIGHT_FOOTER_RE.search("UNI/TS 12007:2026 © UNI Page 23"))
        self.assertFalse(_COPYRIGHT_FOOTER_RE.search("The © symbol shall be displayed"))

    def test_roman_page_normalized(self) -> None:
        a = _normalize_repeated_line("UNI/TS 12007:2026 © UNI Page III")
        b = _normalize_repeated_line("UNI/TS 12007:2026 © UNI Page V")
        self.assertEqual(a, b)   # 罗马页码归一 → 重复行检测可命中
