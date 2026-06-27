from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from requirement_kb.coverage import build_coverage_report, render_report


def _instance(table_no: int, *, medium: str = "ac_electricity", class_id: int = 3) -> dict:
    return {
        "id": f"KB-OBIS-T{table_no}",
        "type": "cosem_object_instance",
        "name": f"instance table {table_no}",
        "blue_book_table_ref": {"part": 1, "table_no": table_no, "title": f"Table {table_no}"},
        "medium": medium,
        "likely_interface_class_id": class_id,
    }


def _class(*, class_id: int, rich: bool, name: str = "X") -> dict:
    entry = {"id": f"KB-L3-IC-{class_id}", "type": "cosem_interface_class", "name": name, "class_id": class_id}
    if rich:
        entry["attributes"] = [{"name": "logical_name"}]
    return entry


class CoverageReportTests(unittest.TestCase):
    def _write_kb(self, entries: list[dict]) -> Path:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"kb_id": "test_kb", "entries": entries}, tmp, ensure_ascii=False)
        tmp.close()
        return Path(tmp.name)

    def test_report_counts_part1_instances_by_table_and_flags_empty_tables(self) -> None:
        kb = self._write_kb([
            {"id": "KB-T13", "type": "obis_table", "blue_book_table_ref": {"table_no": 13}},
            {"id": "KB-T14", "type": "obis_table", "blue_book_table_ref": {"table_no": 14}},
            _instance(13),
            _instance(13),
        ])
        report = build_coverage_report(kb)
        self.assertEqual(report["part1_obis"]["row_level_instances"], 2)
        self.assertEqual(report["part1_obis"]["instances_by_table_no"], {13: 2})
        # table 14 has a catalogue entry but no row-level instances
        self.assertEqual(report["part1_obis"]["tables_with_catalogue_but_no_rows"], [14])

    def test_report_flags_empty_top_level_table_no_catalogue_entries(self) -> None:
        kb = self._write_kb([
            {"id": "KB-T61", "type": "obis_table", "table_no": 61},
            _instance(13),
        ])
        report = build_coverage_report(kb)
        self.assertIn(61, report["part1_obis"]["tables_with_catalogue_but_no_rows"])

    def test_report_separates_catalogue_only_obis_tables_from_row_level_gaps(self) -> None:
        kb = self._write_kb([
            {"id": "KB-T52", "type": "obis_table", "table_no": 52, "object_family": "value_group_definition"},
            {"id": "KB-T14", "type": "obis_table", "table_no": 14, "object_family": "value_group_definition"},
            {"id": "KB-T50", "type": "obis_table", "table_no": 50, "object_family": "obis_code_family"},
            {"id": "KB-T41", "type": "obis_table", "table_no": 41, "object_family": "examples"},
            _instance(14),
            _instance(13),
        ])
        report = build_coverage_report(kb)
        part1 = report["part1_obis"]
        self.assertNotIn(52, part1["tables_with_catalogue_but_no_rows"])
        self.assertEqual(part1["tables_not_expected_to_have_row_instances"], [52])
        self.assertEqual(part1["tables_with_catalogue_but_no_rows"], [41, 50])

    def test_real_compiled_obsidian_row_level_gaps_only_include_object_tables(self) -> None:
        root = Path(__file__).resolve().parents[1]
        kb = root / "knowledge_bases" / "compiled_from_obsidian.json"
        if not kb.exists():
            self.skipTest("compiled_from_obsidian.json not present")
        report = build_coverage_report(kb)
        part1 = report["part1_obis"]
        self.assertEqual(part1["tables_with_catalogue_but_no_rows"], [])
        self.assertEqual(
            part1["tables_not_expected_to_have_row_instances"],
            [1, 2, 3, 4, 5, 6, 7, 34, 35, 36, 43, 44, 52, 53, 54, 55, 56, 57, 58, 59, 60, 66, 67, 73],
        )

    def test_report_splits_part2_classes_into_rich_and_seed(self) -> None:
        kb = self._write_kb([
            _class(class_id=1, rich=True, name="Data"),
            _class(class_id=3, rich=True, name="Register"),
            _class(class_id=40, rich=False, name="Push setup"),
        ])
        report = build_coverage_report(kb)
        self.assertEqual(report["part2_interface_classes"]["total"], 3)
        self.assertEqual(report["part2_interface_classes"]["with_attributes_or_methods"], 2)
        self.assertEqual(report["part2_interface_classes"]["catalogue_only_seed"], 1)
        self.assertIn(40, report["part2_interface_classes"]["seed_class_ids"])

    def test_report_distribution_groups_by_medium_and_class_id(self) -> None:
        kb = self._write_kb([
            _instance(13, medium="ac_electricity", class_id=3),
            _instance(26, medium="dc_electricity", class_id=3),
        ])
        report = build_coverage_report(kb)
        self.assertEqual(report["instance_distribution"]["by_medium"],
                         {"ac_electricity": 1, "dc_electricity": 1})
        self.assertEqual(report["instance_distribution"]["by_likely_interface_class_id"], {"3": 2})

    def test_render_report_contains_key_sections(self) -> None:
        kb = self._write_kb([_instance(13), _class(class_id=1, rich=True, name="Data")])
        report = build_coverage_report(kb)
        md = render_report(report)
        for marker in ("Part 1 — Blue Book OBIS", "Part 2 — COSEM Interface Classes",
                       "Object instance distribution", "Row-level instances"):
            self.assertIn(marker, md)

    def test_semantic_depth_counts_classes_with_access_rights_and_behavior_notes(self) -> None:
        kb = self._write_kb([
            {"id": "KB-IC-19", "type": "cosem_interface_class", "class_id": 19, "name": "IEC local port setup",
             "attributes": [
                 {"attribute_id": 1, "name": "logical_name", "access_rights": "R"},
                 {"attribute_id": 2, "name": "default_mode", "access_rights": "RW"},
             ],
             "behavior_notes": ["port configuration"], "access_semantics": ["all static"]},
            {"id": "KB-IC-23", "type": "cosem_interface_class", "class_id": 23, "name": "IEC HDLC Setup",
             "attributes": [
                 {"attribute_id": 1, "name": "logical_name", "access_rights": "R"},
             ],
             "behavior_notes": ["HDLC channel"]},
            {"id": "KB-IC-8", "type": "cosem_interface_class", "class_id": 8, "name": "Clock",
             "attributes": [{"attribute_id": 1, "name": "logical_name"}], "methods": []},
        ])
        report = build_coverage_report(kb)
        sd = report["part2_interface_classes"]["semantic_depth"]
        self.assertEqual(sd["classes_with_access_rights"], 2)   # IC 19 and 23
        self.assertEqual(sd["classes_with_behavior_notes"], 2)  # IC 19 and 23
        self.assertEqual(sd["classes_with_access_semantics"], 1)  # only IC 19
        self.assertEqual(sd["attributes_with_access_rights"], 3)  # 2 + 1

    def test_real_compiled_obsidian_kb_has_no_seed_classes_and_expected_instance_total(self) -> None:
        """回归保护：覆盖度报表必须与真实 compiled_from_obsidian.json 一致。

        交接 baseline 已更新为：87 class 全部 rich（0 seed）、136 row-level instance、367 total。
        AC electricity 表 14-20 全部 materialized (tariff/harmonics/phase angle/loss/dips/distortion)。
        表 9/14-20/27/28 于 2026-06-25 从蓝皮书原文 materialize。
        任何人补 KB 后跑此测试，若 class 退化成 seed 或总数骤变会立即暴露。
        """
        root = Path(__file__).resolve().parents[1]
        kb = root / "knowledge_bases" / "compiled_from_obsidian.json"
        if not kb.exists():
            self.skipTest("compiled_from_obsidian.json not present")
        report = build_coverage_report(kb)
        self.assertEqual(report["part2_interface_classes"]["catalogue_only_seed"], 0)
        self.assertEqual(report["part2_interface_classes"]["total"], 87)
        self.assertGreaterEqual(report["part1_obis"]["row_level_instances"], 140)
        self.assertGreaterEqual(report["total_entries"], 371)
        by_medium = report["instance_distribution"]["by_medium"]
        self.assertGreaterEqual(by_medium.get("gas", 0), 10)
        self.assertGreaterEqual(by_medium.get("water", 0), 8)
        self.assertGreaterEqual(by_medium.get("hot_water", 0), 4)
        self.assertGreaterEqual(by_medium.get("thermal_energy", 0), 7)
        self.assertGreaterEqual(by_medium.get("hca", 0), 4)
        # AC electricity 表 14-20 应全部有 row-level 覆盖
        for tn in (14, 15, 16, 17, 18, 19, 20):
            self.assertIn(tn, report["part1_obis"]["instances_by_table_no"],
                          f"AC electricity table {tn} should have row-level instances")
        # 目标全部 17 个点名 class enrichment: 通信 9 + 事件/监控 4 + 付费 4
        # 通信: 19/23/41/42/44/45/46/48/100  事件/监控: 63/65/66/67  付费: 111/112/113/115
        sd = report["part2_interface_classes"]["semantic_depth"]
        self.assertGreaterEqual(sd["classes_with_access_rights"], 17,
                                "all 17 named classes (9 comm + 4 monitoring + 4 payment) should carry attribute access_rights")
        self.assertGreaterEqual(sd["classes_with_behavior_notes"], 31,
                                "behavior_notes coverage should not regress")


if __name__ == "__main__":
    unittest.main()
