from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class BlueBookLookupTests(unittest.TestCase):
    def sample_index(self) -> dict:
        return {
            "meta": {"schema_version": "blue-book-index/v1"},
            "interface_classes": {
                "3": {
                    "name": "Register",
                    "version": 0,
                    "section": "4.3.2",
                    "pages": [66, 67],
                    "text": "4.3.2 Register (class_id = 3, version = 0)\n" + "A" * 5000,
                    "attributes": ["1 logical_name", "2 value", "3 scaler_unit"],
                    "methods": ["1 reset(data)"],
                },
                "15": {
                    "name": "Association LN",
                    "version": 3,
                    "section": "4.4.4",
                    "pages": [110],
                    "text": "4.4.4 Association LN text",
                    "attributes": ["2 object_list"],
                    "methods": ["1 reply_to_HLS_authentication(data)"],
                },
            },
            "obis_sections": [],
        }

    def test_load_index_returns_payload_or_none_for_missing_and_broken_json(self) -> None:
        import blue_book_lookup

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "blue_book_index.json"
            good.write_text(json.dumps(self.sample_index()), encoding="utf-8")
            broken = root / "broken.json"
            broken.write_text("{not json", encoding="utf-8")

            self.assertEqual(blue_book_lookup.load_index(good)["meta"]["schema_version"], "blue-book-index/v1")
            self.assertIsNone(blue_book_lookup.load_index(root / "missing.json"))
            self.assertIsNone(blue_book_lookup.load_index(broken))

    def test_lookup_class_matches_exact_class_id_only(self) -> None:
        import blue_book_lookup

        index = self.sample_index()

        self.assertEqual(blue_book_lookup.lookup_class(index, 3)["name"], "Register")
        self.assertEqual(blue_book_lookup.lookup_class(index, "15")["name"], "Association LN")
        self.assertIsNone(blue_book_lookup.lookup_class(index, "03"))
        self.assertIsNone(blue_book_lookup.lookup_class(index, 999))
        self.assertIsNone(blue_book_lookup.lookup_class(None, 3))

    def test_lookup_class_by_name_is_casefold_exact_not_fuzzy(self) -> None:
        import blue_book_lookup

        index = self.sample_index()

        self.assertEqual(blue_book_lookup.lookup_class_by_name(index, "register")["section"], "4.3.2")
        self.assertEqual(blue_book_lookup.lookup_class_by_name(index, "Association LN")["section"], "4.4.4")
        self.assertIsNone(blue_book_lookup.lookup_class_by_name(index, "Association"))
        self.assertIsNone(blue_book_lookup.lookup_class_by_name(index, "Register object"))
        self.assertIsNone(blue_book_lookup.lookup_class_by_name(None, "Register"))

    def test_condensed_text_keeps_section_head_and_adds_citation_note_when_truncated(self) -> None:
        import blue_book_lookup

        entry = self.sample_index()["interface_classes"]["3"]

        condensed = blue_book_lookup.condensed_text(entry, max_chars=240)

        self.assertLessEqual(len(condensed), 240)
        self.assertTrue(condensed.startswith("4.3.2 Register"))
        self.assertIn("完整定义见 Blue Book §4.3.2", condensed)

    def test_condensed_text_returns_full_text_when_short(self) -> None:
        import blue_book_lookup

        entry = self.sample_index()["interface_classes"]["15"]

        self.assertEqual(blue_book_lookup.condensed_text(entry, max_chars=4000), entry["text"])
        self.assertEqual(blue_book_lookup.condensed_text({}, max_chars=4000), "")


if __name__ == "__main__":
    unittest.main()
