from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import assemble_spec


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> Path:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"stable_req_id": "O-CLOCK", "requirement_type": "cosem_object_instance",
         "object": "Clock", "domain": "time", "source_refs": ["TBL-1"]},
        {"stable_req_id": "A-CLOCK", "requirement_type": "cosem_attribute_access",
         "object": "Clock.time", "source_refs": ["TBL-2"], "verification_method": "configuration_check"},
        {"stable_req_id": "ASM-1", "requirement_type": "association_security_matrix",
         "object": "ClientA", "source_refs": ["TBL-3"]},
        {"stable_req_id": "F-1", "requirement_type": "functional", "object": "Counter",
         "requirement": "The meter must reset to 0.", "source_refs": ["BLK-1"]},
        # 父类 Register 不在对象实例表 → 孤立 → 类级属性模板
        {"stable_req_id": "A-REGV", "requirement_type": "cosem_attribute_access",
         "object": "Register.value", "source_refs": ["TBL-4"]},
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {"item_id": "TBL-1", "fields": {"Object/attribute name": "Clock", "CL": "8", "Value": "0-0:1.0.0.255"}},
        {"item_id": "TBL-2", "fields": {"#": "1", "Object/attribute name": "time", "Type": "octet-string",
                                         "Value": "00", "Access rights RC/PC/SC/LC": "R-/RW/--/R-"}},
        {"item_id": "TBL-3", "fields": {"Customer application process": "ClientA",
                                         "Server application process / Management Logical Device": "HLS"}},
        {"item_id": "TBL-4", "fields": {"#": "1", "Object/attribute name": "value",
                                         "Type": "double-long-unsigned", "Access rights RC/PC/SC/LC": "R-/R-/R-/R-"}},
    ])
    reviews = out_dir / "reviews.jsonl"
    write_jsonl(reviews, [
        {"stable_req_id": "F-1", "decision": "accept", "revised_requirement": "The meter shall reset the counter to 0."},
    ])
    return reviews


class AssembleSpecTests(unittest.TestCase):
    def test_three_layers_assembled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            doc, breakdown = assemble_spec.assemble(out, reviews, source="t", extracted_at="2026-06-14T10:00:00")
            self.assertGreaterEqual(breakdown["p1_object_requirements"], 1)
            self.assertGreaterEqual(breakdown["p2_matrix_requirements"], 1)
            self.assertGreaterEqual(breakdown["p3_behavior_requirements"], 1)
            self.assertEqual(breakdown["total"], len(doc["requirements"]))
            self.assertEqual(doc["analysis"]["total_count"], breakdown["total"])

    def test_class_template_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            doc, breakdown = assemble_spec.assemble(out, reviews, source="t", extracted_at="2026-06-14T10:00:00")
            self.assertGreaterEqual(breakdown["p1_class_template_requirements"], 1)
            tpl = next(r for r in doc["requirements"] if "类级属性模板：Register" in r["title"])
            self.assertIsNotNone(tpl["threshold_table"])
            self.assertTrue(any("value" in row for row in tpl["threshold_table"]["rows"]))

    def test_ids_sequential_and_fields_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            doc, _ = assemble_spec.assemble(out, reviews, source="t", extracted_at="2026-06-14T10:00:00")
            ids = [r["id"] for r in doc["requirements"]]
            self.assertEqual(ids, [f"REQ-{i:03d}" for i in range(1, len(ids) + 1)])  # 全局重编号连续
            for req in doc["requirements"]:
                self.assertTrue(req["source_quote"])         # 必填非空
                self.assertTrue(req["labels"])                # 至少一个
                self.assertIn(req["type"], ("functional", "non_functional", "constraint", "business_rule"))
                self.assertIn(req["priority"], ("P0", "P1", "P2"))
                self.assertIn(req["status"], ("draft", "confirmed", "conflict", "gap"))

    def test_object_requirement_has_attribute_threshold_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            doc, _ = assemble_spec.assemble(out, reviews, source="t", extracted_at="2026-06-14T10:00:00")
            clock = next(r for r in doc["requirements"] if "Clock" in r["title"])
            tt = clock["threshold_table"]
            self.assertIsNotNone(tt)
            self.assertEqual(tt["columns"][:3], ["#", "属性", "类型"])
            self.assertTrue(any("time" in row for row in tt["rows"]))

    def test_security_matrix_requirement_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            doc, _ = assemble_spec.assemble(out, reviews, source="t", extracted_at="2026-06-14T10:00:00")
            assoc = next(r for r in doc["requirements"] if r["title"] == "关联安全矩阵")
            self.assertIn("安全", assoc["labels"])
            self.assertIsNotNone(assoc["threshold_table"])

    def test_p4_external_references_attached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            # fixture 没有 blocks.jsonl 与外部引用，补一条带 IEC 引用的正文块
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "BLK-1", "type": "paragraph", "section_path": ["Architecture"],
                            "text": "Application layer per IEC 62056-5-3."}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            doc, breakdown = assemble_spec.assemble(out, reviews, source="t", extracted_at="2026-06-14T10:00:00")
            self.assertIn("external_references", doc)
            self.assertGreaterEqual(breakdown["p4_external_references"], 1)
            ids = {e["spec_id"] for e in doc["external_references"]["references"]}
            self.assertIn("IEC 62056-5-3", ids)
            self.assertIn("external_references", doc["analysis"]["coverage_report"])


if __name__ == "__main__":
    unittest.main()
