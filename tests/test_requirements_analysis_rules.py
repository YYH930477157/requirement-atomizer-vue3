"""requirements_analysis_rules 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from requirements_analysis_rules import classify_ownership


class ClassifyOwnershipTests(unittest.TestCase):
    def test_classifies_protocol_behavior_as_software(self) -> None:
        req = {
            "title": "GET service",
            "description": "The meter shall support xDLMS GET service for Clock object.",
            "module": "通信协议",
            "source_quote": "support xDLMS GET service",
        }

        decision = classify_ownership(req)

        assert decision["ownership"] == "software"
        assert decision["ownership_source"] == "rule"
        assert decision["ownership_confidence"] >= 0.75

    def test_classifies_metering_chip_as_hardware(self) -> None:
        req = {
            "description": "计量芯片型号为 Att7022e，火线采样类型为 CT。",
            "module": "计量",
        }

        decision = classify_ownership(req)

        assert decision["ownership"] == "hardware"
        assert "计量芯片" in decision["ownership_reason"]

    def test_hardware_source_does_not_hide_clock_software_action(self) -> None:
        req = {"description": "软件应从计量芯片读取时钟并同步系统时间。"}

        decision = classify_ownership(req)

        assert decision["ownership"] == "software"
        assert decision["ownership_confidence"] >= 0.8
        assert "时钟" in decision["ownership_reason"]

    def test_hardware_local_occurrence_does_not_hide_later_software_occurrence(self) -> None:
        req = {
            "title": "时钟计数器型号",
            "description": "软件应同步时钟并记录事件。",
        }

        decision = classify_ownership(req)

        assert decision["ownership"] == "software"
        assert decision["ownership_confidence"] >= 0.8

    def test_hardware_context_in_another_field_does_not_hide_software_term(self) -> None:
        req = {
            "title": "时钟功能",
            "description": "芯片型号由硬件选型确定。",
        }

        decision = classify_ownership(req)

        assert decision["ownership"] == "software"
        assert "时钟" in decision["ownership_reason"]

    def test_classifies_baudrate_hardware_limit_as_co_design(self) -> None:
        req = {
            "description": "波特率最大值与硬件相关，需要驱动适配。",
            "module": "协议栈",
        }

        decision = classify_ownership(req)

        assert decision["ownership"] == "co_design"
        assert decision["ownership_confidence"] >= 0.7

    def test_low_signal_defaults_to_software_with_low_confidence(self) -> None:
        req = {"description": "The meter shall support this feature."}

        decision = classify_ownership(req)

        assert decision["ownership"] == "software"
        assert decision["ownership_confidence"] < 0.7

    def test_does_not_treat_english_keyword_substrings_as_software_signal(self) -> None:
        req = {
            "description": "The mechanical transaction counter is part of the enclosure.",
            "module": "enclosure",
        }

        decision = classify_ownership(req)

        assert decision["ownership"] == "hardware"
        assert "mechanical" in decision["ownership_reason"]

    def test_p1_rule_does_not_match_p10(self) -> None:
        req = {"description": "P10 port is a mechanical interface on this variant."}

        decision = classify_ownership(req)

        assert decision["ownership"] == "hardware"

    def test_classifies_precise_english_physical_terms_as_hardware(self) -> None:
        samples = {
            "battery": "The product shall include a replaceable battery.",
            "service life": "The product shall have a service life of ten years.",
            "lifetime": "The product lifetime shall be at least ten years.",
            "enclosure": "The enclosure shall resist ordinary handling.",
            "housing": "The housing shall use a durable material.",
            "ingress protection": "The product shall provide ingress protection.",
            "power consumption": "The product power consumption shall remain below the limit.",
            "power supply": "The product shall include an isolated power supply.",
            "three-phase": "The product shall use a three-phase connection.",
            "powered from all three phases": "The product shall be powered from all three phases.",
            "va": "The burden shall not exceed 2 VA.",
        }

        for term, text in samples.items():
            with self.subTest(term=term):
                decision = classify_ownership({"description": text})

                self.assertEqual(decision["ownership"], "hardware")
                self.assertIn(term, decision["ownership_reason"])

    def test_reviewed_agent_eval_ownership_cases_do_not_regress(self) -> None:
        cases_dir = (
            Path(__file__).resolve().parents[1]
            / "golden_sets"
            / "agent_eval_v1"
            / "cases"
            / "classify"
        )
        case_paths = sorted(cases_dir.glob("case-*.json"))
        self.assertEqual(len(case_paths), 12)

        ownership_verdicts = {"software", "hardware", "co_design"}
        checked = 0
        for case_path in case_paths:
            case = json.loads(case_path.read_text(encoding="utf-8"))
            expected = case["expected"]["verdict"]
            text = case["input"]["text"]
            requirement = {"source_quote": text, "description": text, "title": ""}
            decision = classify_ownership(requirement)
            if expected not in ownership_verdicts:
                continue

            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(decision["ownership"], expected)
            checked += 1

        self.assertEqual(checked, 7)


if __name__ == "__main__":
    unittest.main()
