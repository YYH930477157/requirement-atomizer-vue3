"""Tests for WS-D2/D3/D4 prompt governance and agent_eval extensions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval import (
    CATEGORIES,
    EVAL_RUNNER_VERSION,
    _adjudication_audit_case,
    _doc_map_coverage_case,
    evaluate_cases,
)
from adjudication_bank import (
    load_bank,
    render_negative_exemplars,
    select_negative_exemplars,
)
from doc_map import DOC_MAP_PROMPT_VERSION
from reconcile import RECONCILE_PROMPT_VERSION
from adjudicate import ADJUDICATE_PROMPT_VERSION
from prompt_registry import is_registered


class PromptRegressionAnchorTests(unittest.TestCase):
    def test_new_prompts_registered(self):
        for version in (DOC_MAP_PROMPT_VERSION, RECONCILE_PROMPT_VERSION, ADJUDICATE_PROMPT_VERSION):
            self.assertTrue(is_registered(version), f"{version} must be in prompt registry")

    def test_real_modules_export_prompt_versions(self):
        # 真值回归锚（D2）：三个新 prompt 来自真实实现模块（非骨架），版本常量可导入
        # 且与注册表登记逐字一致；prompt 文本变更必须 bump 版本（注册表 lint 盯着）。
        self.assertEqual(DOC_MAP_PROMPT_VERSION, "doc-map-prompt-v1")
        self.assertEqual(RECONCILE_PROMPT_VERSION, "reconcile-prompt-v1")
        self.assertEqual(ADJUDICATE_PROMPT_VERSION, "adjudicate-prompt-v1")


class AgentEvalExtensionTests(unittest.TestCase):
    def test_eval_runner_version_bumped(self):
        self.assertEqual(EVAL_RUNNER_VERSION, "agent-eval-v3")

    def test_categories_include_new_metrics(self):
        self.assertIn("adjudication_audit", CATEGORIES)
        self.assertIn("doc_map_coverage", CATEGORIES)

    def test_adjudication_audit_false_accept_detected(self):
        case = {
            "case_id": "adjudication-audit-001",
            "category": "adjudication_audit",
            "expected": {"verdict": "reject", "adjudication_decision": "accept"},
        }
        detail = _adjudication_audit_case(case, reviewed=set())
        self.assertEqual(detail["judge"], "auto")
        self.assertFalse(detail["passed"])
        self.assertEqual(detail["truth"], "reject")

    def test_adjudication_audit_manual_without_truth(self):
        case = {
            "case_id": "adjudication-audit-002",
            "category": "adjudication_audit",
            "expected": {"verdict": "reject"},
        }
        detail = _adjudication_audit_case(case, reviewed=set())
        self.assertEqual(detail["judge"], "manual")

    def test_doc_map_coverage_missing_blocks(self):
        case = {
            "case_id": "doc-map-coverage-001",
            "category": "doc_map_coverage",
            "expected": {
                "covered_block_ids": ["BLK-001", "BLK-002"],
                "mapped_block_ids": ["BLK-001"],
            },
        }
        detail = _doc_map_coverage_case(case, reviewed=set())
        self.assertEqual(detail["judge"], "auto")
        self.assertFalse(detail["passed"])
        self.assertEqual(detail["missing_block_ids"], ["BLK-002"])

    def test_evaluate_cases_schema_only_new_categories(self):
        cases = [
            {
                "case_id": "adjudication-audit-001",
                "category": "adjudication_audit",
                "expected": {"verdict": "reject"},
            },
            {
                "case_id": "doc-map-coverage-001",
                "category": "doc_map_coverage",
                "expected": {"covered_block_ids": ["BLK-001"]},
            },
        ]
        report = evaluate_cases(cases)
        self.assertIn("adjudication_audit", report)
        self.assertIn("doc_map_coverage", report)
        # adjudication_audit 缺 adjudication_decision 真值 → manual/schema_only
        self.assertIn("adjudication_audit", report["schema_only_categories"])


class NegativeFewShotTests(unittest.TestCase):
    def test_select_negative_exemplars_matches_module_and_text(self):
        bank = load_bank(None)
        bank["rejected"]["R1"] = {
            "module": "Event",
            "title": "Bad event requirement",
            "description": "The meter shall log every event without filtering",
            "reason": "unmeasurable acceptance",
        }
        bank["rejected"]["R2"] = {
            "module": "Display",
            "title": "Bad display requirement",
            "description": "Show all data",
            "reason": "vague",
        }
        exemplars = select_negative_exemplars(bank, "Event", "event log filter", k=2)
        self.assertEqual(len(exemplars), 1)
        self.assertEqual(exemplars[0]["title"], "Bad event requirement")

    def test_render_negative_exemplars_includes_reason(self):
        ex = [{"module": "Event", "title": "Bad", "description": "x", "reason": "y"}]
        text = render_negative_exemplars(ex)
        self.assertIn("拒绝原因：y", text)


if __name__ == "__main__":
    unittest.main()
