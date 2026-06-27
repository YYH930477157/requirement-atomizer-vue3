from __future__ import annotations

import unittest

from llm_review_schema import validate_llm_review_result_payload


class LLMReviewSchemaTests(unittest.TestCase):
    def test_null_required_fields_are_flagged_as_missing(self) -> None:
        # 回归护栏：补全阶段(complete_llm_review_payload)总注入 decision/confidence 键，
        # 模型省略时为 None。只检查键存在会让 None 通过、架空 schema 修复回路，
        # 把畸形响应静默洗成合法审查。None 必须算缺失。
        row = {"task_id": "REVIEW-1", "source_refs": [], "risk": "low",
               "decision": None, "confidence": None}
        errors = [i.message for i in validate_llm_review_result_payload(row) if i.severity == "error"]
        self.assertIn("missing required field: decision", errors)
        self.assertIn("missing required field: confidence", errors)

    def test_absent_required_keys_are_flagged(self) -> None:
        fields = {i.path.rsplit(".", 1)[-1]
                  for i in validate_llm_review_result_payload({"risk": "low"})}
        self.assertTrue({"task_id", "source_refs", "decision", "confidence"} <= fields)

    def test_wellformed_review_with_zero_confidence_is_valid(self) -> None:
        # confidence=0 / source_refs=[] 是合法值，不能被误判为缺失
        row = {"task_id": "REVIEW-2", "source_refs": [], "decision": "accept", "confidence": 0}
        self.assertEqual(validate_llm_review_result_payload(row), [])


if __name__ == "__main__":
    unittest.main()
