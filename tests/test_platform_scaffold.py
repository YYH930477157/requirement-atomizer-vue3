from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from atomic_requirement_schema import validate_atomic_requirement_payload, validate_atomic_requirements
from api_server import enrich_requirements, is_allowed_origin, token_is_valid
from atomize import assert_valid_atomic_requirements
from doc_ir import blocks_to_doc_ir
from kb_schema import validate_kb_file, validate_kb_payload
from llm_review_schema import validate_llm_review_result_payload, validate_llm_review_results
from llm_pipeline import (
    append_review_state_events,
    assert_valid_review_results,
    build_stub_review,
    classify_review_risk,
    load_review_pipeline,
    merge_review_policy,
    read_jsonl,
    review_requirements,
    write_jsonl,
)
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

    def test_atomic_requirement_schema_accepts_valid_candidate(self) -> None:
        candidate = {
            "req_id": "AREQ-000001",
            "stable_req_id": "SREQ-0123456789ABCDEF",
            "source_id": "BLK-000001",
            "source_type": "paragraph",
            "source_refs": ["BLK-000001"],
            "section_path": ["Scope"],
            "domain": "communication",
            "domain_tags": ["dlms_cosem"],
            "object": "",
            "requirement_type": "communication",
            "requirement": "The meter shall support xDLMS GET service.",
            "condition": None,
            "parameters": {},
            "verification_method": "test",
            "ambiguity": False,
            "review_questions": [],
            "confidence": 0.68,
            "kb_matches": [],
            "generated_by": "rule_based_atomizer_v1",
        }

        issues = validate_atomic_requirement_payload(candidate)

        self.assertEqual([issue for issue in issues if issue.severity == "error"], [])

    def test_atomic_requirement_schema_rejects_missing_and_malformed_fields(self) -> None:
        broken = {
            "req_id": "REQ-1",
            "stable_req_id": "SREQ-not-hex",
            "source_id": "BLK-000001",
            "source_type": "paragraph",
            "source_refs": "BLK-000001",
            "domain": "communication",
            "object": "",
            "requirement_type": "communication",
            "requirement": "",
            "verification_method": "test",
            "ambiguity": False,
            "confidence": 1.2,
            "generated_by": "rule_based_atomizer_v1",
        }

        issues = validate_atomic_requirements([broken])
        messages = [issue.message for issue in issues if issue.severity == "error"]

        self.assertTrue(any("invalid req_id" in message for message in messages))
        self.assertTrue(any("invalid stable_req_id" in message for message in messages))
        self.assertTrue(any("source_refs must be a list" in message for message in messages))
        self.assertTrue(any("requirement must be a non-empty string" in message for message in messages))
        self.assertTrue(any("confidence must be between 0 and 1" in message for message in messages))

    def test_atomizer_rejects_invalid_atomic_requirements_before_writing(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid atomic requirements"):
            assert_valid_atomic_requirements(
                [
                    {
                        "req_id": "REQ-1",
                        "stable_req_id": "SREQ-not-hex",
                        "source_id": "BLK-1",
                    }
                ]
            )

    def test_llm_review_schema_accepts_valid_stub_review(self) -> None:
        review = {
            "task_id": "REVIEW-SREQ-0123456789ABCDEF",
            "requirement_id": "SREQ-0123456789ABCDEF",
            "source_refs": ["TBL-000001"],
            "decision": "needs_expert",
            "revised_requirement": "The meter shall support xDLMS GET service.",
            "review_notes": ["Stub review routed to high_risk."],
            "expert_questions": ["Confirm applicability."],
            "confidence": 0.5,
        }

        issues = validate_llm_review_result_payload(review)

        self.assertEqual([issue for issue in issues if issue.severity == "error"], [])

    def test_llm_review_schema_rejects_invalid_decision_and_confidence(self) -> None:
        broken = {
            "task_id": "",
            "source_refs": "TBL-000001",
            "decision": "approve",
            "confidence": 1.5,
            "review_notes": ["ok"],
            "expert_questions": [42],
        }

        issues = validate_llm_review_results([broken])
        messages = [issue.message for issue in issues if issue.severity == "error"]

        self.assertTrue(any("task_id must be a non-empty string" in message for message in messages))
        self.assertTrue(any("source_refs must be a list" in message for message in messages))
        self.assertTrue(any("invalid decision" in message for message in messages))
        self.assertTrue(any("confidence must be between 0 and 1" in message for message in messages))
        self.assertTrue(any("expert_questions must contain strings" in message for message in messages))

    def test_llm_pipeline_rejects_invalid_reviews_before_writing(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid llm review results"):
            assert_valid_review_results(
                [
                    {
                        "task_id": "REVIEW-1",
                        "source_refs": [],
                        "decision": "approve",
                        "confidence": 0.8,
                    }
                ]
            )

    def test_llm_pipeline_routes_high_risk_requirement(self) -> None:
        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        requirement = {"req_id": "AREQ-1", "requirement_type": "security_policy_bit", "confidence": 0.9, "source_refs": ["TBL-1"]}

        self.assertEqual(classify_review_risk(requirement, pipeline), "high_risk")
        review = build_stub_review(requirement, pipeline)
        self.assertEqual(review["decision"], "needs_expert")

    def test_domain_pack_mandatory_review_types_route_to_expert(self) -> None:
        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        pipeline = merge_review_policy(pipeline, ROOT / "domain_packs" / "dlms_cosem" / "pack.yaml")
        requirement = {
            "req_id": "AREQ-1",
            "requirement_type": "cosem_attribute_access",
            "confidence": 0.9,
            "source_refs": ["TBL-1"],
            "review_questions": ["Confirm whether this attribute access is mandatory."],
        }

        self.assertEqual(classify_review_risk(requirement, pipeline), "mandatory_review")
        review = build_stub_review(requirement, pipeline)
        self.assertEqual(review["decision"], "needs_expert")
        self.assertEqual(review["model_route"]["model"], "local-strict-reviewer")
        self.assertEqual(review["expert_questions"], ["Confirm whether this attribute access is mandatory."])
        self.assertEqual(review["confidence"], 0.5)

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

    def test_llm_pipeline_uses_stable_requirement_id_when_available(self) -> None:
        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        requirements = [
            {
                "req_id": "AREQ-1",
                "stable_req_id": "SREQ-0123456789ABCDEF",
                "requirement_type": "event_definition",
                "confidence": 0.9,
                "source_refs": ["TBL-2"],
            }
        ]

        reviews, states = review_requirements(requirements, pipeline)

        self.assertEqual(reviews[0]["requirement_id"], "SREQ-0123456789ABCDEF")
        self.assertEqual(reviews[0]["req_id"], "AREQ-1")
        self.assertEqual(states[0]["requirement_id"], "SREQ-0123456789ABCDEF")
        self.assertEqual(states[0]["metadata"]["req_id"], "AREQ-1")

    def test_append_review_state_events_preserves_existing_events(self) -> None:
        first_state = {
            "requirement_id": "SREQ-1",
            "status": "accepted",
            "history": [
                {
                    "from_status": "candidate",
                    "to_status": "llm_reviewed",
                    "actor": "llm_pipeline",
                    "reason": "decision=accept",
                    "timestamp": "2026-06-10T00:00:00+00:00",
                }
            ],
            "metadata": {"req_id": "AREQ-1"},
        }
        second_state = {
            "requirement_id": "SREQ-2",
            "status": "expert_pending",
            "history": [
                {
                    "from_status": "candidate",
                    "to_status": "llm_reviewed",
                    "actor": "llm_pipeline",
                    "reason": "decision=needs_expert",
                    "timestamp": "2026-06-10T00:01:00+00:00",
                }
            ],
            "metadata": {"req_id": "AREQ-2"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_state_events.jsonl"
            self.assertEqual(append_review_state_events(path, [first_state]), 1)
            self.assertEqual(append_review_state_events(path, [second_state]), 1)

            rows = read_jsonl(path)

        self.assertEqual([row["requirement_id"] for row in rows], ["SREQ-1", "SREQ-2"])
        self.assertEqual([row["req_id"] for row in rows], ["AREQ-1", "AREQ-2"])
        self.assertEqual(rows[0]["to_status"], "llm_reviewed")
        self.assertEqual(rows[0]["status_after"], "llm_reviewed")

    def test_api_enriches_requirements_by_stable_req_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "llm_review_results.jsonl",
                [{"requirement_id": "SREQ-1", "decision": "accept"}],
            )
            write_jsonl(
                out_dir / "review_states.jsonl",
                [{"requirement_id": "SREQ-1", "status": "accepted"}],
            )

            enriched = enrich_requirements([{"req_id": "AREQ-1", "stable_req_id": "SREQ-1"}], out_dir)

        self.assertEqual(enriched[0]["review"]["decision"], "accept")
        self.assertEqual(enriched[0]["review_state"]["status"], "accepted")

    def test_api_cors_rejects_non_local_origins(self) -> None:
        allowed = {"http://127.0.0.1:8770", "http://localhost:8770", "null"}

        self.assertTrue(is_allowed_origin("http://127.0.0.1:8770", allowed))
        self.assertTrue(is_allowed_origin("", allowed))
        self.assertFalse(is_allowed_origin("https://example.com", allowed))

    def test_api_token_accepts_header_or_query_value(self) -> None:
        params = {"token": ["secret"]}

        self.assertTrue(token_is_valid("secret", {"X-Requirement-Atomizer-Token": "secret"}, {}))
        self.assertTrue(token_is_valid("secret", {}, params))
        self.assertFalse(token_is_valid("secret", {}, {}))
        self.assertTrue(token_is_valid("", {}, {}))

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

    def test_pyproject_declares_dependencies_and_cli_scripts(self) -> None:
        payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        dependencies = payload["project"]["dependencies"]
        scripts = payload["project"]["scripts"]

        self.assertIn("python-docx>=1.1.0", dependencies)
        self.assertIn("PyYAML>=6.0.0", dependencies)
        self.assertEqual(scripts["requirement-atomizer"], "atomize:main")
        self.assertEqual(scripts["requirement-review"], "llm_pipeline:main")
        self.assertEqual(scripts["validate-atomic-requirements"], "atomic_requirement_schema:main")
        self.assertEqual(scripts["validate-llm-reviews"], "llm_review_schema:main")

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
