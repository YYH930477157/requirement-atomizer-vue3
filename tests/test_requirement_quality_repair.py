"""Domain-neutral routing and validated display fields must not hide obligations."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tender_regions import classify_tender_region, tender_region_spans


class RequirementQualityRepairTests(unittest.TestCase):
    def test_legend_labels_and_punctuation_are_context_but_real_body_is_kept(self):
        import functional_extract as fe
        for text, expected in [("Key",True), ("--- `,,`",True),
                               ("Key shall be at least 8 bytes.",False),
                               ("Key\nThe valve shall close.",False),
                               ("Απαιτήσεις",False), ("≤ ±",False)]:
            section={"block_ids":["B1"],"text":text,"heading":""}
            blocks={"B1":{"type":"paragraph","text":text}}
            self.assertEqual(fe._section_is_heading_only(section,blocks,set()),expected)
            self.assertFalse(fe._section_is_heading_only(section,blocks,{"B1"}))

    def test_split_conditional_prohibition_is_blocked_even_when_all_words_remain(self):
        import functional_extract as fe
        source = "The pump shall not exceed 4 bar without showing an error flag."
        section = {"text":source, "block_ids":["B1"], "section_id":"4.1"}
        wrong = "The pump shall not exceed 4 bar. The pump shall operate without showing an error flag."
        findings = fe._preservation_findings(section, wrong)
        self.assertTrue(any(f["kind"] == "conditional_relation" and f["severity"] == "blocking" for f in findings))
        self.assertFalse(fe._preservation_findings(section, source))
        item = {"functional_requirement_id":"FRE-test", "source_block_ids":["B1"],
                "source_quote":source, "objective":wrong, "behaviors":[]}
        report = fe.conservation_report([section], [item])
        self.assertFalse(report["ok"])
        with self.assertRaises(fe.FunctionalConservationError):
            fe.raise_if_unconserved(report)

    def test_section_number_does_not_hide_a_real_numeric_constraint(self):
        import functional_extract as fe
        section = {"section_id": "4", "section_path": ["4"],
                   "text": "The device shall store 4 alarm records.",
                   "block_ids": ["B1"]}
        findings = fe._preservation_findings(
            section,
            "The device shall store alarm records.",
            {"4"},
        )
        self.assertTrue(any(f["kind"] == "number" and f["token"] == "4" for f in findings))
        self.assertFalse(fe._preservation_findings(
            {**section, "text": "The device shall store records defined in 4."},
            "The device shall store records defined in .",
            {"4"},
        ))

    def test_line_wrapped_conditional_prohibition_is_still_blocked(self):
        import functional_extract as fe
        source = "The valve shall not open\nwithout authentication."
        findings = fe._preservation_findings(
            {"section_id": "S1", "text": source, "block_ids": ["B1"]},
            "The valve shall not open. The valve shall operate without authentication.",
        )
        self.assertTrue(any(f["kind"] == "conditional_relation" for f in findings))

    def test_retired_inline_mode_is_rejected_without_changing_default(self):
        from pipeline_plan import resolve_translation_mode
        import functional_extract as fe
        with self.assertRaises(ValueError):
            resolve_translation_mode(override="functional")
        self.assertEqual(resolve_translation_mode(), "full")
        self.assertNotIn("objective_zh", fe._package_system_prompt())

    def test_generic_declaration_does_not_exclude_technical_following_sections(self):
        blocks = [
            {"block_id": "H1", "type": "heading", "text": "9.2 Declaration"},
            {"block_id": "B1", "type": "paragraph", "text": "The indicator shall show failures."},
            {"block_id": "H2", "type": "heading", "text": "9.3 Information"},
            {"block_id": "B2", "type": "paragraph", "text": "The device shall display status."},
        ]
        self.assertIsNone(classify_tender_region(blocks[0]))
        self.assertEqual(tender_region_spans(blocks), {})

    def test_specific_bid_declarations_still_route_to_procurement(self):
        for title in ("Bidder declaration", "Tender Declaration", "Declaration by the bidder"):
            with self.subTest(title=title):
                self.assertEqual(classify_tender_region({"type":"heading", "text":title}),
                                 "tender_instructions")

    def test_conformity_declaration_resets_procurement_span(self):
        blocks = [
            {"block_id":"H1", "type":"heading", "text":"Instructions to Bidders"},
            {"block_id":"B1", "type":"paragraph", "text":"The bidder shall submit a bid."},
            {"block_id":"H2", "type":"heading", "text":"7.2 Declaration of conformity"},
            {"block_id":"B2", "type":"paragraph", "text":"The apparatus shall comply with the standard."},
        ]
        spans = tender_region_spans(blocks)
        self.assertEqual(spans["B1"], "tender_instructions")
        self.assertEqual(spans["B2"], "tender_technical")

    def test_review_view_does_not_retain_rejected_raw_translation_or_alias(self):
        from api_server import _project_functional_review_view
        item = {"functional_requirement_id":"FRE-test", "source_block_ids":["B1"],
                "objective":"The device shall record alarms.",
                "behaviors":["Record alarms.", "Retain records."],
                "functional_behaviors_zh":["记录报警。"], "behaviors_zh":["记录报警。"]}
        original = copy.deepcopy(item)
        with tempfile.TemporaryDirectory() as raw:
            with patch("ai_review_actions.read_ai_review_authority_snapshot", return_value={"states":{}}):
                result = _project_functional_review_view(Path(raw), [item], {"fingerprint":"test"})[0]
        self.assertNotIn("functional_behaviors_zh", result)
        self.assertNotIn("behaviors_zh", result)
        self.assertEqual(result["behaviors"], original["behaviors"])
        self.assertEqual(item, original)

    def test_translation_projection_rejects_polarity_mismatch(self):
        from api_server import _functional_translation_projection
        item = {
            "source_block_ids": ["B1"],
            "objective": "The valve shall not close when power is lost.",
            "behaviors": [],
        }
        index = {"B1": [{
            "source": "The valve shall close when power is lost.",
            "translation": "断电时阀门应关闭。",
        }]}
        projected = _functional_translation_projection(item, index)
        self.assertNotIn("functional_objective_zh", projected)

    def test_title_translation_does_not_use_a_numeric_prefix_match(self):
        from api_server import _functional_title_translation
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "annotation_translations.json").write_text(
                json.dumps({"items": {
                    "wrong": {"status": "accepted", "source_head": "10 Scope", "translation": "范围十"},
                    "right": {"status": "accepted", "source_head": "1 Scope", "translation": "范围一"},
                }}, ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(_functional_title_translation(root, "1 Scope"), "范围一")
            self.assertEqual(_functional_title_translation(root, "1"), "")

    def test_translation_prompt_does_not_assume_all_meters_are_electrical(self):
        from api_server import TRANSLATION_SYSTEM_PROMPT, TRANSLATION_LANGUAGE_REQUIREMENTS
        import functional_extract as fe
        self.assertNotIn('meter 译「电表」', TRANSLATION_LANGUAGE_REQUIREMENTS)
        self.assertNotIn('translator for DLMS/COSEM', TRANSLATION_SYSTEM_PROMPT)
        for prompt in (fe._system_prompt(), fe._package_system_prompt()):
            self.assertNotIn('你是 DLMS/COSEM 电表标准', prompt)
            self.assertIn('not ... without', prompt)


if __name__ == '__main__':
    unittest.main()
