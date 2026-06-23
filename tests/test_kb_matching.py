from __future__ import annotations

import unittest

from requirement_kb.matching import compile_term_pattern, find_matched_terms, normalize_match_term


class KBMatchingTests(unittest.TestCase):
    def test_short_terms_require_word_boundaries(self) -> None:
        pattern = compile_term_pattern(["rf"])

        self.assertEqual(find_matched_terms(pattern, "interface performance"), [])
        self.assertEqual(find_matched_terms(pattern, "RF communication profile"), ["rf"])

    def test_long_terms_require_word_boundaries(self) -> None:
        pattern = compile_term_pattern(["prime", "event"])

        self.assertEqual(find_matched_terms(pattern, "primary association shall be used"), [])
        self.assertEqual(find_matched_terms(pattern, "The meter shall prevent reset"), [])
        self.assertEqual(find_matched_terms(pattern, "Event log shall be readable"), ["event"])
        self.assertEqual(find_matched_terms(pattern, "Events shall be logged"), ["event"])

    def test_plural_suffix_matches_singular_terms(self) -> None:
        pattern = compile_term_pattern(["register"])

        self.assertEqual(find_matched_terms(pattern, "The registers shall be readable"), ["register"])
        self.assertEqual(find_matched_terms(pattern, "registered values are historical"), [])

    def test_symbol_ended_terms_do_not_require_alnum_boundary_on_that_side(self) -> None:
        pattern = compile_term_pattern(["0-0:"])

        self.assertEqual(find_matched_terms(pattern, "logical name 0-0:1.0.0.255 shall be used"), ["0-0:"])

    def test_multi_word_phrases_require_boundaries(self) -> None:
        pattern = compile_term_pattern(["load profile"])

        self.assertEqual(find_matched_terms(pattern, "the load profile shall be available"), ["load profile"])
        self.assertEqual(find_matched_terms(pattern, "the overload profile shall be ignored"), [])

    def test_normalization_handles_case_and_full_width_space(self) -> None:
        pattern = compile_term_pattern(["load profile"])
        haystack = normalize_match_term("The LOAD\u3000PROFILE shall be retained")

        self.assertEqual(find_matched_terms(pattern, haystack), ["load profile"])


if __name__ == "__main__":
    unittest.main()
