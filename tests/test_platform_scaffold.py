from __future__ import annotations

import json
import unittest
from pathlib import Path

from doc_ir import blocks_to_doc_ir
from kb_schema import validate_kb_file, validate_kb_payload
from llm_pipeline import build_stub_review, classify_review_risk, load_review_pipeline, review_requirements, write_jsonl
from review_state import RequirementReviewState
from table_pattern_engine import load_table_patterns, match_table_pattern


ROOT = Path(__file__).resolve().parents[1]


class PlatformScaffoldTests(unittest.TestCase):
    def test_blocks_to_doc_ir_preserves_table_rows(self) -> None:
        blocks = [
            {
                "block_id": "BLK-1",
                "order": 1,
                "type": "table",
                "table_id": "TBL-1",
                "table_title": "Table 1",
                "headers": ["A", "B"],
                "text": "A | B",
                "section_path": ["Scope"],
            }
        ]
        table_items = [{"item_id": "TBL-1-R1", "table_block_id": "BLK-1", "fields": {"A": "x"}}]

        doc = blocks_to_doc_ir(blocks=blocks, table_items=table_items, source_path=Path("sample.docx"))

        self.assertEqual(doc.source_format, "docx")
        self.assertEqual(doc.blocks[0].table.rows[0]["item_id"], "TBL-1-R1")

    def test_table_pattern_engine_matches_cosem_object_table(self) -> None:
        patterns = load_table_patterns(ROOT / "domain_packs" / "dlms_cosem" / "table_patterns.yaml")
        table = {"headers": ["#", "Object/attribute name", "CL", "Value"], "table_title": "COSEM objects"}

        matches = match_table_pattern(table, patterns)

        self.assertTrue(any(match["pattern_id"] == "cosem_object_table" for match in matches))

    def test_table_pattern_engine_matches_security_policy_bit_table(self) -> None:
        patterns = load_table_patterns(ROOT / "domain_packs" / "dlms_cosem" / "table_patterns.yaml")
        table = {"headers": ["bit", "Security Policy - Security States"], "table_title": "Security policy"}

        matches = match_table_pattern(table, patterns)

        self.assertEqual(matches[0]["pattern_id"], "security_policy_bit_table")

    def test_kb_schema_accepts_existing_kb_and_rejects_missing_fields(self) -> None:
        issues = validate_kb_file(ROOT / "knowledge_bases" / "energy_metering.json")
        self.assertEqual([issue for issue in issues if issue.severity == "error"], [])

        broken = {"kb_id": "broken", "entries": [{"id": "ONE"}]}
        broken_issues = validate_kb_payload(broken)
        self.assertTrue(any("missing required KB field" in issue.message for issue in broken_issues))

    def test_llm_pipeline_routes_high_risk_requirement(self) -> None:
        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        requirement = {"req_id": "AREQ-1", "requirement_type": "security_policy_bit", "confidence": 0.9, "source_refs": ["TBL-1"]}

        self.assertEqual(classify_review_risk(requirement, pipeline), "high_risk")
        review = build_stub_review(requirement, pipeline)
        self.assertEqual(review["decision"], "needs_expert")

    def test_llm_pipeline_builds_review_states(self) -> None:
        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        requirements = [
            {"req_id": "AREQ-1", "requirement_type": "security_policy_bit", "confidence": 0.9, "source_refs": ["TBL-1"]},
            {"req_id": "AREQ-2", "requirement_type": "event_definition", "confidence": 0.9, "source_refs": ["TBL-2"]},
        ]

        reviews, states = review_requirements(requirements, pipeline)

        self.assertEqual(len(reviews), 2)
        self.assertEqual(states[0]["status"], "expert_pending")
        self.assertEqual(states[1]["status"], "accepted")

    def test_review_state_validates_transitions(self) -> None:
        state = RequirementReviewState("AREQ-1")

        state.transition("llm_reviewed", actor="system", reason="stub review")
        state.transition("expert_pending", actor="system", reason="high risk")

        self.assertEqual(state.status, "expert_pending")
        with self.assertRaises(ValueError):
            state.transition("frozen", actor="expert", reason="invalid direct transition")

    def test_api_output_fixture_exists(self) -> None:
        manifest_path = ROOT / "out" / "abnt_nbr_16968_atomizer_v5" / "manifest.json"
        if not manifest_path.exists():
            self.skipTest(f"Local atomizer output fixture not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("quality_report", manifest["files"])

    def test_write_jsonl_writes_utf8_lines(self) -> None:
        path = ROOT / ".tmp_test_review_results.jsonl"
        try:
            count = write_jsonl(path, [{"requirement_id": "AREQ-1", "decision": "accept"}])
            self.assertEqual(count, 1)
            self.assertIn("AREQ-1", path.read_text(encoding="utf-8"))
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
