from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cosem_behavior_spec as cbs


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> Path:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"stable_req_id": "B1", "requirement_type": "functional", "object": "Counter",
         "requirement": "The meter must reset to 0.", "verification_method": "test"},
        {"stable_req_id": "B2", "requirement_type": "event_definition", "object": "Ev",
         "requirement": "Event G1-SG10-E1 shall be defined.", "ambiguity": True},
        {"stable_req_id": "B3", "requirement_type": "communication", "object": "Push",
         "requirement": "Push must be available."},
        # 非行为类 → 必须被排除
        {"stable_req_id": "D1", "requirement_type": "cosem_object_instance", "object": "Clock",
         "requirement": "COSEM object Clock / OBIS 0-0:1.0.0.255."},
    ])
    reviews = out_dir / "reviews.jsonl"
    write_jsonl(reviews, [
        {"stable_req_id": "B1", "decision": "accept",
         "revised_requirement": "The meter shall reset the counter to 0.", "acceptance": ["..."]},
        # B2：改写里凭空引入一个原文没有的 OBIS → 必须被护栏拦截
        {"stable_req_id": "B2", "decision": "accept",
         "revised_requirement": "The meter shall log G1-SG10-E1 and also write OBIS 1-0:99.98.0.255."},
        # B3 无 review → pending
    ])
    return reviews


class BehaviorSpecTests(unittest.TestCase):
    def test_extract_codes(self) -> None:
        codes = cbs.extract_codes("see 0-0:41.0.0.255 and G1-SG10-E1 and 0xAB plus 15")
        self.assertIn("0-0:41.0.0.255", codes)
        self.assertIn("G1-SG10-E1", codes)
        self.assertIn("0xAB", codes)

    def test_counts_and_type_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            model = cbs.build_behavior_spec(out, reviews)
            c = model["counts"]
            self.assertEqual(c["behavioral_atoms"], 3)   # D1 (cosem_object_instance) 排除
            self.assertEqual(c["llm_derived"], 2)        # B1, B2
            self.assertEqual(c["pending_review"], 1)     # B3
            self.assertEqual(c["number_drift"], 1)       # B2

    def test_clean_derivation_not_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            items = {i["stable_req_id"]: i for i in cbs.build_behavior_spec(out, reviews)["items"]}
            b1 = items["B1"]
            self.assertTrue(b1["derived"])
            self.assertEqual(b1["decision"], "accept")
            self.assertEqual(b1["drift_codes"], [])
            self.assertFalse(b1["in_expert_queue"])

    def test_number_drift_forces_expert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            items = {i["stable_req_id"]: i for i in cbs.build_behavior_spec(out, reviews)["items"]}
            b2 = items["B2"]
            self.assertIn("1-0:99.98.0.255", b2["drift_codes"])   # 原文没有的 OBIS 被逮到
            self.assertEqual(b2["decision"], "needs_expert")       # 护栏强制打回
            self.assertIn("number_drift", b2["flags"])
            self.assertIn("ambiguity", b2["flags"])
            self.assertTrue(b2["in_expert_queue"])

    def test_pending_when_no_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            items = {i["stable_req_id"]: i for i in cbs.build_behavior_spec(out, reviews)["items"]}
            b3 = items["B3"]
            self.assertFalse(b3["derived"])
            self.assertEqual(b3["decision"], "pending")
            self.assertTrue(b3["in_expert_queue"])

    def test_write_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reviews = write_fixture(out)
            model = cbs.build_behavior_spec(out, reviews)
            written = cbs.write_behavior_spec(out, model)
            self.assertEqual(set(written), {"cosem_behavior_spec.json", "cosem_behavior_spec.md"})
            md = (out / "cosem_behavior_spec.md").read_text(encoding="utf-8")
            self.assertIn("编码漂移", md)


if __name__ == "__main__":
    unittest.main()
