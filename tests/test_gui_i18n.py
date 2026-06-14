from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from gui import fluent, i18n
from llm_review_schema import VALID_DECISIONS


ROOT = Path(__file__).resolve().parents[1]
EMITTED_RISKS = {"low_risk", "high_risk", "mandatory_review"}


class GuiI18nTests(unittest.TestCase):
    def test_risk_vocab_covered(self) -> None:
        self.assertLessEqual(EMITTED_RISKS, set(i18n.RISK_LABELS))

    def test_decision_vocab_covered(self) -> None:
        self.assertLessEqual(VALID_DECISIONS, set(i18n.DECISION_LABELS))

    def test_domain_pack_types_have_labels(self) -> None:
        payload = yaml.safe_load((ROOT / "domain_packs" / "dlms_cosem" / "requirement_patterns.yaml").read_text(encoding="utf-8"))
        domain_types = {str(pattern["domain_type"]) for pattern in payload["patterns"]}
        self.assertLessEqual(domain_types, set(i18n.TYPE_LABELS))

    def test_unknown_type_label_is_humanized(self) -> None:
        self.assertEqual(i18n.type_label("custom_pack_type"), "Custom Pack Type")

    def test_confidence_color_has_three_distinct_bands(self) -> None:
        colors = {
            fluent.confidence_color(0.9),
            fluent.confidence_color(0.78),
            fluent.confidence_color(0.5),
        }
        self.assertEqual(len(colors), 3)

    def test_type_colors_by_raw_type(self) -> None:
        self.assertEqual(fluent.type_colors("cosem_attribute_access"), fluent.TYPE_TOKENS["default"])
        self.assertEqual(fluent.type_colors("access_control"), fluent.TYPE_TOKENS["access"])
        self.assertEqual(fluent.type_colors("security_policy_state"), fluent.TYPE_TOKENS["security"])


if __name__ == "__main__":
    unittest.main()
