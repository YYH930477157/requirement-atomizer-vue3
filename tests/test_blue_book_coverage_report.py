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

        self.assertEqual(report["entries_total"], 744)
        self.assertEqual(report["part1_obis_tables"]["covered"], 73)
        self.assertEqual(report["part1_obis_tables"]["total"], 73)
        # 2026-06-27: 补漏 18 个 Blue Book Part 2 Ed.16 current 通信类（87→105）。
        self.assertEqual(report["part2_interface_classes"]["covered"], 105)
        self.assertEqual(report["part2_interface_classes"]["total"], 105)
        # 2026-06-28: 剩余 35 个 catalogue-seed 通信类从 IC 属性/方法表富化（catalogue_seed 35→0，enriched 53→88）。
        self.assertEqual(report["part2_interface_classes"]["enriched"], 88)
        self.assertEqual(report["part2_interface_classes"]["catalogue_seed"], 0)
        self.assertEqual(report["object_instances"]["total"], 495)
        self.assertEqual(report["object_instances"]["by_medium"]["ac_electricity"], 328)
        self.assertEqual(report["object_instances"]["by_medium"]["general"], 102)
        self.assertEqual(report["object_instances"]["by_medium"]["hot_water"], 4)
        self.assertEqual(report["object_instances"]["by_medium"]["gas"], 13)
        self.assertEqual(report["object_instances"]["by_medium"]["hca"], 7)
        self.assertEqual(report["object_instances"]["by_medium"]["thermal_energy"], 10)
        self.assertEqual(report["object_instances"]["by_medium"]["water"], 11)
        self.assertEqual(report["object_instances"]["by_table"]["13"], 72)
        self.assertEqual(report["object_instances"]["by_table"]["8"], 44)
        self.assertEqual(report["object_instances"]["by_table"]["9"], 49)
        self.assertEqual(report["object_instances"]["by_table"]["12"], 12)
        self.assertEqual(report["object_instances"]["by_table"]["14"], 103)
        self.assertEqual(report["object_instances"]["by_table"]["17"], 13)
        self.assertEqual(report["object_instances"]["by_table"]["19"], 32)
        self.assertEqual(report["object_instances"]["by_table"]["21"], 13)
        self.assertEqual(report["object_instances"]["by_table"]["24"], 9)
        for table_no in ("41", "49", "50", "72"):
            self.assertIn(table_no, report["object_instances"]["by_table"])
            self.assertEqual(report["object_instances"]["by_table"][table_no], 3)
        self.assertEqual(report["object_instances"]["by_class_id"]["1"], 78)
        self.assertEqual(report["object_instances"]["by_class_id"]["11"], 1)
        self.assertEqual(report["object_instances"]["by_class_id"]["122"], 1)
        self.assertEqual(report["object_instances"]["by_class_id"]["128"], 1)
        self.assertEqual(report["object_instances"]["by_class_id"]["15"], 5)
        self.assertEqual(report["object_instances"]["by_class_id"]["18"], 1)
        self.assertEqual(report["object_instances"]["by_class_id"]["22"], 5)
        self.assertEqual(report["object_instances"]["by_class_id"]["23"], 2)
        self.assertEqual(report["object_instances"]["by_class_id"]["64"], 2)
        self.assertEqual(report["object_instances"]["by_class_id"]["70"], 3)
        self.assertEqual(report["object_instances"]["by_class_id"]["7"], 26)
        self.assertEqual(report["object_instances"]["by_class_id"]["4"], 20)
        self.assertEqual(report["object_instances"]["by_class_id"]["5"], 8)
        self.assertEqual(report["object_instances"]["by_class_id"]["9"], 6)
        self.assertEqual(report["object_instances"]["by_class_id"]["3"], 329)

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
        self.assertEqual(payload["object_instances"]["total"], 495)


if __name__ == "__main__":
    unittest.main()
