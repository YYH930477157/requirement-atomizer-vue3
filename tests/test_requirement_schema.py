from __future__ import annotations

import unittest

import requirement_schema as rs


def make_item(**kw) -> dict:
    base = {
        "stable_req_id": "S1", "type": "functional", "object": "X", "original": "orig",
        "behavior": "orig", "derived": False, "acceptance": [], "decision": "pending",
        "expert_questions": [], "review_notes": [], "drift_codes": [], "int_notes": [],
        "confidence": 0.7, "source_refs": ["BLK-1"], "section_path": ["4 Security"],
        "in_expert_queue": True,
    }
    base.update(kw)
    return base


class MappersTests(unittest.TestCase):
    def test_map_labels(self) -> None:
        self.assertIn("安全", rs.map_labels("verify integrity of the master key"))
        self.assertIn("事件记录", rs.map_labels("log the reboot event"))
        self.assertIn("通信协议", rs.map_labels("support GET and SET service"))
        self.assertEqual(rs.map_labels("nothing relevant here"), ["通信协议"])  # 默认

    def test_classify_type(self) -> None:
        self.assertEqual(rs.classify_type("the meter shall log events"), "functional")
        self.assertEqual(rs.classify_type("accuracy shall be 0.5 class"), "non_functional")
        self.assertEqual(rs.classify_type("the value shall not exceed 5"), "constraint")

    def test_classify_priority(self) -> None:
        self.assertEqual(rs.classify_priority(["安全"], "accept", 0.9), "P0")
        self.assertEqual(rs.classify_priority(["通信协议"], "pending", 0.7), "P2")
        self.assertEqual(rs.classify_priority(["通信协议"], "accept", 0.9), "P1")

    def test_map_status(self) -> None:
        self.assertEqual(rs.map_status("accept"), "confirmed")
        self.assertEqual(rs.map_status("needs_expert"), "draft")


class ToRequirementTests(unittest.TestCase):
    def test_required_fields_and_nonempty_quote(self) -> None:
        item = make_item(derived=True, decision="accept",
                         behavior="The meter shall verify the integrity of the new key.",
                         original="raw key integrity text", acceptance=["check 1"])
        req = rs.to_requirement(item, "REQ-001")
        for field in ("id", "title", "description", "type", "priority", "status",
                      "source_section", "source_quote", "labels", "acceptance_criteria",
                      "dependencies", "parent", "children", "notes"):
            self.assertIn(field, req)
        self.assertTrue(req["source_quote"])                 # 必填非空
        self.assertTrue(req["labels"])                        # 至少一个
        self.assertNotIn(req["type"], ("pending",))
        self.assertNotIn(req["priority"], ("pending",))
        self.assertEqual(req["status"], "confirmed")
        self.assertEqual(req["source_section"], "4 Security")
        self.assertIn("安全", req["labels"])
        self.assertEqual(req["priority"], "P0")               # 安全 → P0

    def test_pending_item_still_complete(self) -> None:
        req = rs.to_requirement(make_item(), "REQ-009")
        self.assertEqual(req["status"], "draft")
        self.assertTrue(req["description"])
        self.assertTrue(req["source_quote"])


class DocTests(unittest.TestCase):
    def test_build_doc_structure_and_analysis(self) -> None:
        model = {"items": [
            make_item(derived=True, decision="accept",
                      original="log the reboot event", behavior="The meter shall log the reboot event."),
            make_item(derived=True, decision="needs_expert", drift_codes=["1-0:99.98.0.255"],
                      original="key", behavior="write OBIS 1-0:99.98.0.255"),
        ]}
        doc = rs.build_requirements_doc(model, source="abnt", extracted_at="2026-06-14T10:00:00")
        self.assertEqual(set(doc), {"meta", "requirements", "analysis"})
        self.assertEqual(doc["analysis"]["total_count"], 2)
        self.assertEqual(doc["analysis"]["validation_result"]["domain_checklist_total"],
                         len(rs.COVERAGE_CHECKLIST))
        self.assertTrue(doc["analysis"]["gaps"])              # 大量域缺失 → 有 gap
        self.assertEqual(len(doc["analysis"]["conflicts"]), 1)  # 一条 drift → conflict
        self.assertEqual(doc["meta"]["source"], "abnt")

    def test_coverage_gaps(self) -> None:
        reqs = [{"labels": ["安全"]}, {"labels": ["事件记录"]}]
        gaps, passed = rs.coverage_gaps(reqs)
        self.assertEqual(passed, 2)
        self.assertEqual(len(gaps), len(rs.COVERAGE_CHECKLIST) - 2)


if __name__ == "__main__":
    unittest.main()
