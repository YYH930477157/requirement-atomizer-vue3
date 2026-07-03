"""requirements_analysis_rules 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
