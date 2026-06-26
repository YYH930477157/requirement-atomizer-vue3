from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from requirement_kb.blue_book_report import build_blue_book_coverage_report, write_blue_book_coverage_report


ROOT = Path(__file__).resolve().parents[1]


class BlueBookCoverageReportTests(unittest.TestCase):
    def test_report_summarizes_current_kb_coverage(self) -> None:
        report = build_blue_book_coverage_report(ROOT / "knowledge_bases" / "compiled_from_obsidian.json")

        self.assertEqual(report["entries_total"], 283)
        self.assertEqual(report["part1_obis_tables"]["covered"], 73)
        self.assertEqual(report["part1_obis_tables"]["total"], 73)
        self.assertEqual(report["part2_interface_classes"]["covered"], 87)
        self.assertEqual(report["part2_interface_classes"]["total"], 87)
        self.assertEqual(report["part2_interface_classes"]["enriched"], 45)
        self.assertEqual(report["part2_interface_classes"]["catalogue_seed"], 42)
        self.assertEqual(report["object_instances"]["total"], 52)
        self.assertEqual(report["object_instances"]["by_medium"]["ac_electricity"], 33)
        self.assertIn("13", report["object_instances"]["by_table"])
        self.assertIn("3", report["object_instances"]["by_class_id"])

    def test_newly_enriched_communication_classes_have_actionable_semantics(self) -> None:
        report = build_blue_book_coverage_report(ROOT / "knowledge_bases" / "compiled_from_obsidian.json")
        seed_ids = {entry["class_id"] for entry in report["part2_interface_classes"]["seed_classes"]}

        for class_id in {12, 19, 24, 25, 27, 28, 29, 43, 44, 100}:
            self.assertNotIn(class_id, seed_ids)

    def test_next_priority_seed_classes_have_actionable_semantics(self) -> None:
        report = build_blue_book_coverage_report(ROOT / "knowledge_bases" / "compiled_from_obsidian.json")
        seed_ids = {entry["class_id"] for entry in report["part2_interface_classes"]["seed_classes"]}

        for class_id in {26, 30, 45, 46, 72, 74, 76, 77}:
            self.assertNotIn(class_id, seed_ids)

    def test_report_writes_machine_readable_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "coverage.json"

            report = write_blue_book_coverage_report(
                ROOT / "knowledge_bases" / "compiled_from_obsidian.json",
                target,
            )
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(payload["entries_total"], report["entries_total"])
        self.assertEqual(payload["object_instances"]["total"], 52)


if __name__ == "__main__":
    unittest.main()
