"""PDF 排版保真回归（2026-07-07 UNI 12007 机翻文档真实案例）。"""
from __future__ import annotations

import unittest

from parsers.pdf_parser import (
    DEFRAG_RATIO_THRESHOLD,
    _COPYRIGHT_FOOTER_RE,
    _fragmentation_signal_count,
    _merge_words,
    _merge_lines,
    _normalize_repeated_line,
    defragment_text,
    defragment_text_with_audit,
    text_repair_vocabulary_fingerprint,
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
        text = "The XDEV shall withstand a drop from 0,5 m as given in Table 6."
        self.assertEqual(defragment_text(text), text)

    def test_wordlist_repair_handles_single_letter_fragments_without_merging_words(self) -> None:
        cases = {
            "i sobliged to deliver": "is obliged to deliver",
            "a nd communication": "and communication",
            "must beable to communicate": "must be able to communicate",
            "i nthe standards": "in the standards",
            "b e able": "be able",
        }
        for raw, expect in cases.items():
            self.assertEqual(defragment_text(raw), expect)

    def test_wordlist_repair_protects_valid_short_words_and_references(self) -> None:
        cases = [
            "I am sure",
            "a nice day",
            "in such a way",
            "Annex B gives",
            "class A meters",
        ]
        for text in cases:
            self.assertEqual(defragment_text(text), text)

    def test_repair_events_are_auditable(self) -> None:
        repaired, events = defragment_text_with_audit("i sobliged to deliver")

        self.assertEqual(repaired, "is obliged to deliver")
        self.assertTrue(events)
        event = events[0]
        self.assertEqual(event["before"], "i sobliged")
        self.assertEqual(event["after"], "is obliged")
        self.assertIn("rule", event)
        self.assertIn("start", event)
        self.assertIn("end", event)
        self.assertIn("vocab_version", event)

    def test_multiline_repair_replays_each_line_independently(self) -> None:
        raw = "H ighest threshold\nL owest threshold\nH umidity 9 5%"

        repaired, events = defragment_text_with_audit(raw)

        self.assertEqual(
            repaired,
            "Highest threshold\nLowest threshold\nHumidity 95%",
        )
        self.assertEqual({event["line_index"] for event in events}, {0, 1, 2})

    def test_residual_metric_is_independent_from_repairability(self) -> None:
        repaired, events = defragment_text_with_audit("a nice day")

        self.assertEqual(repaired, "a nice day")
        self.assertEqual(events, [])
        self.assertEqual(_fragmentation_signal_count(repaired), 1)

    def test_word_line_preserves_raw_text_and_repair_metadata(self) -> None:
        line = _merge_words([
            {"text": "i", "x0": 0, "x1": 4, "top": 0, "bottom": 10},
            {"text": "sobliged", "x0": 6, "x1": 50, "top": 0, "bottom": 10},
        ], defrag=True)

        self.assertEqual(line["raw_text"], "i sobliged")
        self.assertEqual(line["text"], "is obliged")
        self.assertTrue(line["text_repair_checked"])
        self.assertTrue(line["text_repairs"])

    def test_repair_vocabulary_has_a_stable_fingerprint(self) -> None:
        fingerprint = text_repair_vocabulary_fingerprint()
        self.assertRegex(fingerprint, r"^[0-9a-f]{16}$")

    def test_threshold_documented(self) -> None:
        self.assertGreater(DEFRAG_RATIO_THRESHOLD, 0)   # 门控存在（ABNT 实测 0.001，UNI 0.19）


class DedoubleTests(unittest.TestCase):
    """PDF 假粗体双写（粗体=同字形画两遍,抽出来每字符×2——真实案例 UNI 前言）。"""

    def test_doubled_bold_paragraph_collapsed(self) -> None:
        raw = "TThhiiss tteecchhnniiccaall ssppeecciiffiiccaattiioonn ww aass dd eevveellooppeedd"
        self.assertEqual(defragment_text(raw), "This technical specification was developed")

    def test_mixed_bold_and_normal_line(self) -> None:
        raw = "TThhiiss ww aass aapppprroovveedd The normal sentence stays."
        self.assertEqual(defragment_text(raw), "This was approved The normal sentence stays.")

    def test_normal_text_never_collapsed(self) -> None:
        text = "The meter shall support classes A and B look book proof"
        self.assertEqual(defragment_text(text), text)

    def test_legit_double_letter_words_safe(self) -> None:
        text = "The book keeper took a good look at the wood floor"
        self.assertEqual(defragment_text(text), text)

    def test_numeric_and_time_tokens_are_never_dedoubled(self) -> None:
        text = "TThhiiss interval is 11:00 and code 2200"
        self.assertEqual(
            defragment_text(text),
            "This interval is 11:00 and code 2200",
        )


class ParagraphRepairTests(unittest.TestCase):
    def test_final_paragraph_repair_is_replayable_at_paragraph_scope(self) -> None:
        lines = [
            {
                "text": "The m eter shall",
                "raw_text": "The m eter shall",
                "top": 0,
                "bottom": 10,
                "x0": 0,
                "x1": 80,
                "text_repair_checked": True,
                "text_repairs": [],
            },
            {
                "text": "record the out put.",
                "raw_text": "record the out put.",
                "top": 12,
                "bottom": 22,
                "x0": 0,
                "x1": 90,
                "text_repair_checked": True,
                "text_repairs": [],
            },
        ]

        paragraph = _merge_lines(lines)
        replayed, _events = defragment_text_with_audit(paragraph["raw_text"])

        self.assertEqual(paragraph["text"], replayed)
        self.assertEqual(paragraph["text_repairs"], _events)


class FooterNoiseTests(unittest.TestCase):
    def test_copyright_footer_pattern(self) -> None:
        self.assertTrue(_COPYRIGHT_FOOTER_RE.search("UNI/TS 12007:2026 © UNI Page 23"))
        self.assertFalse(_COPYRIGHT_FOOTER_RE.search("The © symbol shall be displayed"))

    def test_roman_page_normalized(self) -> None:
        a = _normalize_repeated_line("UNI/TS 12007:2026 © UNI Page III")
        b = _normalize_repeated_line("UNI/TS 12007:2026 © UNI Page V")
        self.assertEqual(a, b)   # 罗马页码归一 → 重复行检测可命中
