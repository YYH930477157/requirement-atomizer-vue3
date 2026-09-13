from __future__ import annotations

import unittest

from requirements_analysis import _enrich_key
from requirements_analysis_agent import validate_llm_item


class AnalysisGuardHardeningTests(unittest.TestCase):
    def test_non_substantive_llm_text_is_flagged(self) -> None:
        issues = validate_llm_item(
            {"software_requirement_text": "好的"},
            {"source_quote": "系统应保存告警"},
        )
        self.assertIn("software requirement text is empty or non-substantive", issues)

    def test_non_substantive_text_is_not_adopted(self) -> None:
        from requirements_analysis import _apply_llm_item

        item = {"ownership": "software", "software_requirement_text": "原始需求"}
        ok, issues = _apply_llm_item(
            item, {"source_quote": "系统应保存告警"},
            {"software_requirement_text": "好的", "developer_guidance": ["记录告警"]},
            {"template_refs": "", "section_context": "", "doc_context": ""},
        )
        self.assertTrue(ok)
        self.assertEqual(item["software_requirement_text"], "待澄清")
        self.assertTrue(any("non-substantive" in issue for issue in issues))

    def test_document_context_numbers_are_not_evidence(self) -> None:
        issues = validate_llm_item(
            {"software_requirement_text": "系统应在 60 秒内保存告警"},
            {"source_quote": "系统应保存告警"},
            context_text="其它章节默认周期为 60 秒",
        )
        self.assertTrue(any("fabricated number not in source: 60" in issue for issue in issues))

    def test_cache_key_uses_all_request_fields_and_is_delimited(self) -> None:
        base = {"description": "ab", "title": "c"}
        changed = {"description": "a", "title": "bc"}
        self.assertNotEqual(_enrich_key(base, "m"), _enrich_key(changed, "m"))
        self.assertNotEqual(_enrich_key(base, "m", route_fingerprint="route-a"),
                            _enrich_key(base, "m", route_fingerprint="route-b"))


if __name__ == "__main__":
    unittest.main()
