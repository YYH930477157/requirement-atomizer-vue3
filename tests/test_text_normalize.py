from __future__ import annotations

import unittest

from text_normalize import formula_safe, normalize_event_id, normalize_numeric


class NormalizeNumericTests(unittest.TestCase):
    def test_word_to_digit(self) -> None:
        self.assertEqual(normalize_numeric("two"), "2")
        self.assertEqual(normalize_numeric("TWO"), "2")
        self.assertEqual(normalize_numeric("  three "), "3")
        self.assertEqual(normalize_numeric("fifteen"), "15")

    def test_passthrough(self) -> None:
        self.assertEqual(normalize_numeric("10"), "10")
        self.assertEqual(normalize_numeric("All"), "All")
        self.assertEqual(normalize_numeric(""), "")
        self.assertEqual(normalize_numeric(None), "")
        self.assertEqual(normalize_numeric("0-0:1.0.0.255"), "0-0:1.0.0.255")


class NormalizeEventIdTests(unittest.TestCase):
    def test_fixes_glued_word_inside_event_id(self) -> None:
        self.assertEqual(
            normalize_event_id("Event G1-SG10-Etwo shall be defined."),
            "Event G1-SG10-E2 shall be defined.",
        )

    def test_leaves_digit_event_id_unchanged(self) -> None:
        self.assertEqual(normalize_event_id("Event G1-SG10-E1 ok"), "Event G1-SG10-E1 ok")

    def test_preserves_non_number_words(self) -> None:
        # SGAll 的 "All" 不是数词 → 不动；组号里的逗号结构保留
        self.assertEqual(
            normalize_event_id("Event G1, 2, 3-SGAll-E255 def"),
            "Event G1, 2, 3-SGAll-E255 def",
        )

    def test_does_not_touch_plain_prose(self) -> None:
        # 没有事件号结构时，正文里的 'someone'/'two' 一概不动
        self.assertEqual(normalize_event_id("someone may send two messages"),
                         "someone may send two messages")


class FormulaSafeTests(unittest.TestCase):
    def test_neutralizes_formula_prefixes(self) -> None:
        # = + @ 及 - 开头的可疑文本被前置单引号转为纯文本，防 Excel/CSV 公式注入
        self.assertEqual(formula_safe("=cmd|' /C calc'!A0"), "'=cmd|' /C calc'!A0")
        self.assertEqual(formula_safe("+1+1"), "'+1+1")
        self.assertEqual(formula_safe("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(formula_safe("-2+3+cmd"), "'-2+3+cmd")
        self.assertEqual(formula_safe("\t=evil"), "'\t=evil")

    def test_exempts_legitimate_dlms_values(self) -> None:
        # DLMS 访问码、纯数字、OBIS、普通文本不被误伤
        for safe in ("R-", "--", "-A--", "-/-/-A--", "0-0:96.1.0", "1-0:1.8.0.255",
                     "double-long-unsigned", "octet-string", "-5", "-1.5", "100%"):
            self.assertEqual(formula_safe(safe), safe)

    def test_non_strings_pass_through(self) -> None:
        self.assertEqual(formula_safe(17), 17)
        self.assertEqual(formula_safe(0.9), 0.9)
        self.assertIsNone(formula_safe(None))
        self.assertEqual(formula_safe(""), "")


if __name__ == "__main__":
    unittest.main()
