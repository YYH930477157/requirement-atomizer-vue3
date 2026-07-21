from __future__ import annotations

import unittest

from ai_extract import (
    _downgrade_cross_block_verbatim,
    _process_raw_requirements,
    _supplement_uncovered_compliance,
)
from compliance import build_compliance_payload


CERT_TEXT = "Valid Certificate according to the standard STN EN 62053-22 - for the active energy component."
DOC_TEXT = "EU declaration of conformity or Declaration of Conformity."
TECH_TEXT = "The electricity meter shall measure active energy in both directions."


def _block(bid: str, text: str) -> dict:
    return {"block_id": bid, "text": text, "section_path": ["1 General"], "requirement_like": True}


class SupplementUncoveredComplianceTests(unittest.TestCase):
    """确定性合规兜底：LLM 漏抽合规块 → 补 draft 行进 ai_requirements（漏抽即入澄清,不静默漏）。"""

    def test_adds_rows_for_uncovered_compliance_blocks(self) -> None:
        blocks = [_block("BLK-000017", CERT_TEXT), _block("BLK-000019", DOC_TEXT), _block("BLK-000100", TECH_TEXT)]

        supplemented = _supplement_uncovered_compliance([], blocks)

        self.assertEqual(len(supplemented), 2)
        by_id = {row["ai_req_id"]: row for row in supplemented}
        cert = by_id["COMP-DET-BLK-000017"]
        self.assertEqual(cert["source_quote"], CERT_TEXT)   # 逐字引句
        self.assertEqual(cert["compliance_instrument"], "STN EN 62053-22")   # 正则文号
        self.assertEqual(cert["status"], "draft")
        self.assertEqual(cert["type"], "compliance")
        self.assertEqual(cert["source_mapping"], "deterministic_fallback")
        self.assertIn("确定性合规兜底（LLM 未覆盖）", cert["suspicion_reasons"])
        self.assertTrue(cert["compliance_obligations"])
        doc = by_id["COMP-DET-BLK-000019"]
        self.assertEqual(doc["source_quote"], DOC_TEXT)

    def test_skips_blocks_already_covered_by_llm(self) -> None:
        blocks = [_block("BLK-000017", CERT_TEXT), _block("BLK-000019", DOC_TEXT)]
        llm_req = {
            "ai_req_id": "AIR-1",
            "title": "证书交付",
            "description": CERT_TEXT,
            "type": "compliance",
            "priority": "P0",
            "status": "draft",
            "source_quote": CERT_TEXT,
            "source_block_ids": ["BLK-000017"],
        }

        supplemented = _supplement_uncovered_compliance([llm_req], blocks)

        self.assertEqual(len(supplemented), 2)
        self.assertEqual(supplemented[0]["ai_req_id"], "AIR-1")
        self.assertEqual(supplemented[1]["ai_req_id"], "COMP-DET-BLK-000019")

    def test_noop_without_compliance_blocks(self) -> None:
        blocks = [_block("BLK-000100", TECH_TEXT)]
        reqs = [{"ai_req_id": "AIR-1", "source_quote": TECH_TEXT}]

        supplemented = _supplement_uncovered_compliance(reqs, blocks)

        self.assertEqual(len(supplemented), 1)

    def test_fallback_rows_flow_into_compliance_payload(self) -> None:
        """补行进 requirements 列表后,compliance json 经 build_compliance_payload 自然投影。"""
        blocks = [_block("BLK-000017", CERT_TEXT)]
        supplemented = _supplement_uncovered_compliance([], blocks)

        payload = build_compliance_payload(supplemented)

        self.assertEqual(payload["count"], 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], "COMP-DET-BLK-000017")
        self.assertEqual(item["instrument"], "STN EN 62053-22")
        self.assertTrue(item["obligations"])
        self.assertEqual(item["source_quote"], CERT_TEXT)


class CrossBlockVerbatimDowngradeTests(unittest.TestCase):
    """跨块逐字降级：quote 跨块拼接逐字命中全文 → 硬标"引用非逐字"改挂软标"引用跨段"。"""

    def test_downgrades_quote_verbatim_across_blocks(self) -> None:
        blocks = [
            _block("B1", "The meter shall store daily load profiles"),
            _block("B2", "for at least 400 days in nonvolatile memory."),
        ]
        req = {
            "source_quote": "The meter shall store daily load profiles for at least 400 days in nonvolatile memory.",
            "suspicion_reasons": ["引用非逐字"],
        }

        _downgrade_cross_block_verbatim([req], blocks)

        self.assertEqual(req["suspicion_reasons"], ["引用跨段"])

    def test_keeps_hard_flag_for_true_rephrase(self) -> None:
        blocks = [_block("B1", "The meter shall store daily load profiles.")]
        req = {
            "source_quote": "The device must keep yearly consumption records permanently.",
            "suspicion_reasons": ["引用非逐字"],
        }

        _downgrade_cross_block_verbatim([req], blocks)

        self.assertEqual(req["suspicion_reasons"], ["引用非逐字"])


class VerbatimTieringTests(unittest.TestCase):
    """引用三层分流：标点差异→软标；跨段拼装→软标；真改写→硬标。"""

    def _section(self, text: str) -> dict:
        return {"text": text, "heading": "7.3 Display", "block_ids": []}

    def test_punctuation_only_difference_flags_soft_tier(self) -> None:
        source = ("Each numerical element of the electronic display must be able to display "
                  "all numbers from zero (0) to nine (9).")
        quote = ("Each numerical element of the electronic display must be able to display "
                 "all numbers from zero(0)to nine(9)")
        raw = [{"title": "Display digits", "description": "Display shows digits.", "source_quote": quote}]

        results = _process_raw_requirements(raw, self._section(source))

        self.assertEqual(len(results), 1)
        reasons = results[0].get("suspicion_reasons") or []
        self.assertIn("引用标点差异", reasons)
        self.assertNotIn("引用非逐字", reasons)

    def test_true_rephrase_keeps_hard_tier(self) -> None:
        source = ("Each numerical element of the electronic display must be able to display "
                  "all numbers from zero (0) to nine (9).")
        quote = "The interface shall present metering digits clearly to the reader at all times."
        raw = [{"title": "Display digits", "description": "Display shows digits.", "source_quote": quote}]

        results = _process_raw_requirements(raw, self._section(source))

        self.assertEqual(len(results), 1)
        reasons = results[0].get("suspicion_reasons") or []
        self.assertIn("引用非逐字", reasons)
        self.assertNotIn("引用标点差异", reasons)

    def test_exact_quote_has_no_verbatim_flag(self) -> None:
        source = "The electricity meter shall measure active energy in both directions."
        raw = [{"title": "Measure energy", "description": "Measures energy.", "source_quote": source}]

        results = _process_raw_requirements(raw, self._section(source))

        reasons = results[0].get("suspicion_reasons") or []
        self.assertNotIn("引用非逐字", reasons)
        self.assertNotIn("引用标点差异", reasons)
        self.assertNotIn("引用跨段", reasons)


if __name__ == "__main__":
    unittest.main()
