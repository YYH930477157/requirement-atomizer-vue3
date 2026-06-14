from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cosem_object_model as com


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> None:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"stable_req_id": "O-CLOCK", "requirement_type": "cosem_object_instance",
         "object": "Clock", "domain": "time", "source_refs": ["BLK-1", "TBL-1-R1"], "confidence": 0.9},
        {"stable_req_id": "O-REG", "requirement_type": "cosem_object_instance",
         "object": "Register", "domain": "metering", "source_refs": ["TBL-1-R2"], "confidence": 0.9},
        # 同名对象、不同 OBIS → 冲突（被丢弃，不覆盖首条）
        {"stable_req_id": "O-CLOCK2", "requirement_type": "cosem_object_instance",
         "object": "Clock", "domain": "time", "source_refs": ["TBL-1-R3"], "confidence": 0.7},
        {"stable_req_id": "A-CLOCK-TIME", "requirement_type": "cosem_attribute_access",
         "object": "Clock.time", "verification_method": "configuration_check",
         "source_refs": ["BLK-1", "TBL-2-R1"], "confidence": 0.9, "ambiguity": False},
        {"stable_req_id": "A-REG-VALUE", "requirement_type": "cosem_attribute_access",
         "object": "Register.value", "source_refs": ["TBL-2-R2"], "confidence": 0.9},
        # 父对象 Ghost 不存在 → 孤立
        {"stable_req_id": "A-GHOST", "requirement_type": "cosem_attribute_access",
         "object": "Ghost.x", "source_refs": ["TBL-2-R3"], "confidence": 0.5},
        {"stable_req_id": "U-1", "requirement_type": "measurement_quantity_unit",
         "object": "Active energy", "source_refs": ["TBL-3-R1"]},
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {"item_id": "TBL-1-R1", "fields": {"Object/attribute name": "Clock", "CL": "8", "Value": "0-0:1.0.0.255"}},
        {"item_id": "TBL-1-R2", "fields": {"Object/attribute name": "Register", "CL": "3", "Value": "1-0:1.8.0.255"}},
        {"item_id": "TBL-1-R3", "fields": {"Object/attribute name": "Clock", "CL": "8", "Value": "0-0:1.0.0.111"}},
        {"item_id": "TBL-2-R1", "fields": {"#": "2", "Object/attribute name": "time", "Type": "octet-string",
                                            "Value": "00", "Access rights RC/PC/SC/LC": "R-/RW/--/R-"}},
        {"item_id": "TBL-2-R2", "fields": {"#": "2", "Object/attribute name": "value", "Type": "double-long-unsigned",
                                            "Value": "0", "Access rights RC/PC/SC/LC": "R-/R-/R-/R-"}},
        {"item_id": "TBL-2-R3", "fields": {"#": "2", "Object/attribute name": "x", "Type": "integer",
                                            "Access rights RC/PC/SC/LC": "--/--/--/--"}},
        {"item_id": "TBL-3-R1", "fields": {"Greatness": "Energy", "Greatness_2": "Active energy", "Unit": "Wh"}},
    ])
    write_jsonl(out_dir / "review_states.jsonl", [
        {"requirement_id": "O-CLOCK", "status": "accepted"},
    ])


class CosemObjectModelTests(unittest.TestCase):
    def test_join_counts_and_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            counts = model["counts"]
            self.assertEqual(counts["objects"], 2)            # Clock, Register（重复 Clock 进冲突）
            self.assertEqual(counts["attributes"], 3)          # time + value + x(orphan)
            self.assertEqual(counts["attributes_attached"], 2)
            self.assertEqual(counts["orphan_attributes"], 1)
            self.assertEqual(counts["units"], 1)
            self.assertEqual(counts["conflicts"], 1)
            # 不变量：总属性 == 挂载 + 孤立
            attached = sum(len(o["attributes"]) for o in model["objects"])
            self.assertEqual(counts["attributes"], attached + counts["orphan_attributes"])

    def test_object_obis_class_and_access_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            clock = next(o for o in model["objects"] if o["object"] == "Clock")
            self.assertEqual(clock["obis"], "0-0:1.0.0.255")   # 首条，不被冲突项覆盖
            self.assertEqual(clock["class_id"], "8")
            self.assertEqual(clock["review_status"], "accepted")
            self.assertEqual(len(clock["attributes"]), 1)
            time_attr = clock["attributes"][0]
            self.assertEqual(time_attr["name"], "time")
            self.assertEqual(time_attr["access"], {"RC": "R-", "PC": "RW", "SC": "--", "LC": "R-"})
            self.assertEqual(time_attr["verification_method"], "configuration_check")

    def test_orphan_and_conflict_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            self.assertEqual([a["parent"] for a in model["orphan_attributes"]], ["Ghost"])
            self.assertEqual(model["conflicts"][0]["object"], "Clock")
            self.assertEqual(model["conflicts"][0]["incoming"], {"obis": "0-0:1.0.0.111", "class_id": "8"})

    def test_write_emits_three_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            written = com.write_object_model(out, model)
            self.assertEqual(set(written), {"cosem_object_model.json", "cosem_object_model.md", "cosem_attribute_matrix.csv"})
            for name in written:
                self.assertTrue((out / name).exists())
            md = (out / "cosem_object_model.md").read_text(encoding="utf-8")
            self.assertIn("OBIS `0-0:1.0.0.255`", md)
            self.assertIn("Ghost", md)  # 孤立分组出现


if __name__ == "__main__":
    unittest.main()
