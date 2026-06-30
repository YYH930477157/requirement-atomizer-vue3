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

    def test_classify_type_non_functional_capacity_and_performance(self) -> None:
        """F2 回归：扩 non_functional 触发词——容量约束(至少N条记录)、性能/时序、可靠性。"""
        # 容量约束正则（须命中带修饰词的真实表述）
        self.assertEqual(rs.classify_type("There must be at least 12 billing records."), "non_functional")
        self.assertEqual(rs.classify_type("keep a minimum of 3 entries per profile"), "non_functional")
        self.assertEqual(rs.classify_type("maximum of 100 days storage"), "non_functional")
        # 性能/时序/可靠性/环境
        self.assertEqual(rs.classify_type("response time shall be within 5 seconds"), "non_functional")
        self.assertEqual(rs.classify_type("the MTBF shall be at least 10 years"), "non_functional")
        self.assertEqual(rs.classify_type("temperature range -25 to 70 C"), "non_functional")
        self.assertEqual(rs.classify_type("storage capacity for load profile"), "non_functional")

    def test_classify_type_capacity_terms_do_not_false_positive(self) -> None:
        """F2 回归：裸 maximum/at least/records 不得误伤功能性逻辑。"""
        # "maximum of 9s" 是累加器归零逻辑（功能性），不因 maximum 误判
        self.assertEqual(rs.classify_type("reaches the maximum of 9s"), "functional")
        # "at least one association" 不匹配『数字+容量名词』（one 非 \d+）
        self.assertEqual(rs.classify_type("there shall be at least one association"), "functional")
        # "collect event records" 是功能性动作，不因 records 误判
        self.assertEqual(rs.classify_type("the meter shall collect event records"), "functional")

    def test_classify_priority(self) -> None:
        # 保守优先级：安全标签不再自动 P0；待审/低置信 → P2
        self.assertEqual(rs.classify_priority(["安全"], "accept", 0.9), "P1")
        self.assertEqual(rs.classify_priority(["通信协议"], "pending", 0.7), "P2")
        self.assertEqual(rs.classify_priority(["通信协议"], "accept", 0.5), "P2")
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
        self.assertEqual(req["priority"], "P1")               # 保守：安全标签不自动 P0

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
