from __future__ import annotations

import json
import tempfile
import threading
import tomllib
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from atomic_requirement_schema import validate_atomic_requirement_payload, validate_atomic_requirements
from api_server import RequirementAPIHandler, enrich_requirements, is_allowed_origin, token_is_valid
from atomize import assert_valid_atomic_requirements
from atomize import AtomizerInputError, apply_table_pattern_shadow
from doc_ir import blocks_to_doc_ir
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
from output_writer import build_quality_report
from requirement_kb.schema import validate_kb_file, validate_kb_payload
from review_state import RequirementReviewState, apply_expert_decision
from table_pattern_engine import load_table_patterns, match_table_pattern


ROOT = Path(__file__).resolve().parents[1]


class PlatformScaffoldTests(unittest.TestCase):
    def start_api_server(self, out_dir: Path, *, token: str = "") -> ThreadingHTTPServer:
        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir.resolve()
        TestHandler.allowed_origins = {"http://127.0.0.1:5173", "http://127.0.0.1:8770", "null"}
        TestHandler.local_token = token
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

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
                "page_number": 3,
            }
        ]
        table_items = [{"item_id": "TBL-1-R1", "table_block_id": "BLK-1", "fields": {"A": "x"}}]

        doc = blocks_to_doc_ir(blocks=blocks, table_items=table_items, source_path=Path("sample.docx"))

        self.assertEqual(doc.source_format, "docx")
        self.assertEqual(doc.blocks[0].provenance.page_ref, "3")
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

    def test_table_pattern_shadow_writes_matches_to_blocks_and_rows(self) -> None:
        blocks = [
            {
                "block_id": "BLK-1",
                "type": "table",
                "table_id": "TBL-1",
                "table_title": "COSEM objects",
                "headers": ["#", "Object/attribute name", "CL", "Value"],
            }
        ]
        table_items = [{"item_id": "TBL-1-R1", "table_block_id": "BLK-1"}]

        summary = apply_table_pattern_shadow(blocks, table_items, ROOT / "domain_packs" / "dlms_cosem")

        self.assertEqual(summary["tables_total"], 1)
        self.assertEqual(summary["tables_with_pattern"], 1)
        self.assertEqual(blocks[0]["pattern_matches"][0]["pattern_id"], "cosem_object_table")
        self.assertEqual(table_items[0]["pattern_matches"][0]["generic_type"], "inherited_context_table")
        report = build_quality_report(blocks, table_items, [], [], pattern_shadow=summary)
        self.assertEqual(report["pattern_engine_shadow"]["by_pattern_id"]["cosem_object_table"], 1)

    def test_table_pattern_shadow_requires_table_patterns_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(AtomizerInputError, "table_patterns.yaml"):
                apply_table_pattern_shadow([], [], Path(tmp))

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
        self.assertTrue(is_allowed_origin("file://", allowed))
        self.assertFalse(is_allowed_origin("https://example.com", allowed))

    def test_api_token_accepts_header_and_rejects_query_value(self) -> None:
        params = {"token": ["secret"]}

        self.assertTrue(token_is_valid("secret", {"X-Requirement-Atomizer-Token": "secret"}, {}))
        self.assertFalse(token_is_valid("secret", {}, params))
        self.assertFalse(token_is_valid("secret", {}, {}))
        self.assertTrue(token_is_valid("", {}, {}))

    def test_api_review_action_requires_token_and_writes_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "review_states.jsonl", [{"requirement_id": "SREQ-1", "status": "expert_pending"}])
            server = self.start_api_server(out_dir, token="secret-token")
            try:
                forbidden = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/review-actions",
                    data=json.dumps({"requirement_id": "SREQ-1", "status": "accepted"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(forbidden, timeout=5)
                self.assertEqual(raised.exception.code, 401)
                raised.exception.close()

                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/review-actions",
                    data=json.dumps(
                        {
                            "requirement_id": "SREQ-1",
                            "status": "accepted",
                            "actor": "vue3-test",
                            "reason": "accepted in Vue3 UI",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Requirement-Atomizer-Token": "secret-token"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["history"][-1]["actor"], "vue3-test")
        self.assertEqual(states[0]["status"], "accepted")
        self.assertEqual(events[-1]["to_status"], "accepted")

    def test_api_review_action_rejects_write_when_token_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            server = self.start_api_server(out_dir)
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/review-actions",
                    data=json.dumps({"requirement_id": "SREQ-1", "status": "accepted"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 401)
                raised.exception.close()
            finally:
                server.shutdown()
                server.server_close()

            states = read_jsonl(out_dir / "review_states.jsonl")

        self.assertEqual(states, [])

    def test_api_translation_endpoint_returns_llm_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            server = self.start_api_server(out_dir, token="secret-token")
            try:
                with patch("api_server.translate_requirement_text") as translate:
                    translate.return_value = "读取客户端应支持 xDLMS 服务：使用 GET 的块传输。"
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/translations",
                        data=json.dumps(
                            {
                                "requirement_id": "SREQ-1",
                                "text": 'Reading client shall support xDLMS Service: Block transfer with "GET".',
                            }
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json", "X-Requirement-Atomizer-Token": "secret-token"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["requirement_id"], "SREQ-1")
        self.assertEqual(payload["translation"], "读取客户端应支持 xDLMS 服务：使用 GET 的块传输。")
        translate.assert_called_once_with(
            'Reading client shall support xDLMS Service: Block transfer with "GET".',
            requirement_id="SREQ-1",
            output_dir=out_dir.resolve(),
        )

    def test_review_state_validates_transitions(self) -> None:
        state = RequirementReviewState("AREQ-1")

        state.transition("llm_reviewed", actor="system", reason="stub review")
        state.transition("expert_pending", actor="system", reason="high risk")

        self.assertEqual(state.status, "expert_pending")
        with self.assertRaises(ValueError):
            state.transition("frozen", actor="expert", reason="invalid direct transition")

    def test_apply_expert_decision_updates_state_and_appends_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "review_states.jsonl",
                [
                    {
                        "requirement_id": "SREQ-1",
                        "status": "expert_pending",
                        "history": [
                            {
                                "from_status": "llm_reviewed",
                                "to_status": "expert_pending",
                                "actor": "llm_pipeline",
                                "reason": "risk=mandatory_review",
                                "timestamp": "2026-06-10T00:00:00+00:00",
                            }
                        ],
                        "metadata": {"req_id": "AREQ-1", "stable_req_id": "SREQ-1"},
                    }
                ],
            )

            updated = apply_expert_decision(
                out_dir,
                "SREQ-1",
                "accepted",
                actor="expert",
                reason="confirmed by reviewer",
            )

            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(states[0]["status"], "accepted")
        self.assertEqual(states[0]["history"][-1]["from_status"], "expert_pending")
        self.assertEqual(states[0]["history"][-1]["to_status"], "accepted")
        self.assertEqual(events[-1]["requirement_id"], "SREQ-1")
        self.assertEqual(events[-1]["req_id"], "AREQ-1")
        self.assertEqual(events[-1]["stable_req_id"], "SREQ-1")
        self.assertEqual(events[-1]["status_after"], "accepted")
        self.assertEqual(events[-1]["current_status"], "accepted")
        self.assertEqual(events[-1]["actor"], "expert")
        self.assertEqual(events[-1]["reason"], "confirmed by reviewer")

    def test_apply_expert_decision_creates_missing_state_and_removes_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)

            updated = apply_expert_decision(out_dir, "SREQ-NEW", "rejected", actor="expert", reason="not applicable")

            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")
            temp_files = list(out_dir.glob("*.tmp"))

        self.assertEqual(updated["requirement_id"], "SREQ-NEW")
        self.assertEqual(updated["status"], "rejected")
        self.assertEqual(states[0]["requirement_id"], "SREQ-NEW")
        self.assertEqual(states[0]["status"], "rejected")
        self.assertEqual(events[-1]["from_status"], "candidate")
        self.assertEqual(events[-1]["to_status"], "rejected")
        self.assertEqual(temp_files, [])

    def test_apply_expert_decision_rejects_invalid_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Unknown review status"):
                apply_expert_decision(Path(tmp), "SREQ-1", "approved", actor="expert")

    def test_apply_expert_decision_same_status_does_not_duplicate_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "review_states.jsonl",
                [
                    {
                        "requirement_id": "SREQ-1",
                        "status": "accepted",
                        "history": [
                            {
                                "from_status": "expert_pending",
                                "to_status": "accepted",
                                "actor": "expert",
                                "reason": "confirmed",
                                "timestamp": "2026-06-10T00:00:00+00:00",
                            }
                        ],
                        "metadata": {"req_id": "AREQ-1", "stable_req_id": "SREQ-1"},
                    }
                ],
            )

            updated = apply_expert_decision(out_dir, "SREQ-1", "accepted", actor="expert", reason="repeat")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(events, [])

    def test_apply_expert_decision_overrides_candidate_to_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updated = apply_expert_decision(Path(tmp), "SREQ-1", "accepted", actor="expert")

        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(updated["history"][-1]["from_status"], "candidate")
        self.assertEqual(updated["history"][-1]["to_status"], "accepted")

    def test_apply_expert_decision_overrides_accepted_to_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "review_states.jsonl",
                [
                    {
                        "requirement_id": "SREQ-1",
                        "status": "accepted",
                        "history": [],
                        "metadata": {"req_id": "AREQ-1"},
                    }
                ],
            )

            updated = apply_expert_decision(out_dir, "SREQ-1", "rejected", actor="expert")

        self.assertEqual(updated["status"], "rejected")
        self.assertEqual(updated["history"][-1]["from_status"], "accepted")
        self.assertEqual(updated["history"][-1]["to_status"], "rejected")

    def test_apply_expert_decision_can_reopen_rejected_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "review_states.jsonl",
                [
                    {
                        "requirement_id": "SREQ-1",
                        "status": "rejected",
                        "history": [],
                        "metadata": {"req_id": "AREQ-1"},
                    }
                ],
            )

            updated = apply_expert_decision(out_dir, "SREQ-1", "expert_pending", actor="expert")

        self.assertEqual(updated["status"], "expert_pending")
        self.assertEqual(updated["history"][-1]["from_status"], "rejected")
        self.assertEqual(updated["history"][-1]["to_status"], "expert_pending")

    def test_apply_expert_decision_cannot_override_frozen_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "review_states.jsonl", [{"requirement_id": "SREQ-1", "status": "frozen"}])

            with self.assertRaisesRegex(ValueError, "Cannot override frozen review state"):
                apply_expert_decision(out_dir, "SREQ-1", "rejected", actor="expert")

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
        py_modules = payload["tool"]["setuptools"]["py-modules"]

        self.assertEqual(payload["project"]["dynamic"], ["version"])
        self.assertEqual(payload["tool"]["setuptools"]["dynamic"]["version"]["attr"], "version.__version__")
        self.assertIn("python-docx>=1.1.0", dependencies)
        self.assertIn("PyYAML>=6.0.0", dependencies)
        self.assertIn("openpyxl>=3.1.0", dependencies)
        self.assertIn("pdfplumber>=0.11", dependencies)
        self.assertIn("engineering_composer", py_modules)
        self.assertIn("llm_client", py_modules)
        self.assertNotIn("kb_api", py_modules)
        self.assertNotIn("kb_matching", py_modules)
        self.assertNotIn("kb_query", py_modules)
        self.assertNotIn("kb_schema", py_modules)
        self.assertNotIn("kb_server", py_modules)
        self.assertNotIn("obsidian_kb", py_modules)
        self.assertNotIn("validate_vault", py_modules)
        self.assertEqual(scripts["ratomizer"], "cli:main")
        self.assertEqual(scripts["requirement-atomizer"], "atomize:main")
        self.assertEqual(scripts["requirement-review"], "llm_pipeline:main")
        self.assertEqual(scripts["requirement-kb"], "requirement_kb.cli:main")
        self.assertEqual(scripts["requirement-kb-server"], "requirement_kb.server:main")
        self.assertEqual(scripts["validate-kb"], "requirement_kb.schema:main")
        self.assertEqual(scripts["validate-vault"], "requirement_kb.vault:main")
        self.assertEqual(scripts["validate-atomic-requirements"], "atomic_requirement_schema:main")
        self.assertEqual(scripts["validate-llm-reviews"], "llm_review_schema:main")
        self.assertIn("requirement_kb*", payload["tool"]["setuptools"]["packages"]["find"]["include"])
        self.assertEqual(payload["project"]["optional-dependencies"]["gui"], ["PySide6>=6.6"])
        self.assertEqual(payload["project"]["optional-dependencies"]["package"], ["pyinstaller>=6.0"])
        self.assertEqual(payload["project"]["gui-scripts"]["ratomizer-gui"], "gui.app:main")
        self.assertEqual(payload["tool"]["setuptools"]["package-data"]["gui"], ["theme.qss.template"])

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
