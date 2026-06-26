from __future__ import annotations

import json
import http.client
import os
import tempfile
import threading
import time
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
    run_review_pipeline,
    write_jsonl,
)
from output_writer import build_quality_report
from requirement_kb.schema import validate_kb_file, validate_kb_payload
from review_state import RequirementReviewState, apply_expert_decision
from table_pattern_engine import load_table_patterns, match_table_pattern


ROOT = Path(__file__).resolve().parents[1]


class TestAPIServer:
    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread):
        self.server = server
        self.thread = thread

    @property
    def server_port(self) -> int:
        return int(self.server.server_port)

    def shutdown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def post_json(self, path: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server_port, timeout=5)
        try:
            connection.request("POST", path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            return response.status, parsed
        finally:
            connection.close()


class PlatformScaffoldTests(unittest.TestCase):
    def test_package_root_prefers_pyinstaller_meipass_resources(self) -> None:
        import resources

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe_dir = root / "dist-backend"
            meipass = root / "_MEI12345"
            exe_dir.mkdir()
            (meipass / "llm_agents").mkdir(parents=True)

            with patch.object(resources.sys, "frozen", True, create=True), \
                    patch.object(resources.sys, "executable", str(exe_dir / "ratomizer-desktop.exe")), \
                    patch.object(resources.sys, "_MEIPASS", str(meipass), create=True):
                self.assertEqual(resources.package_root(), meipass.resolve())

    def test_package_root_prefers_electron_resource_parent_for_backend_exe(self) -> None:
        import resources

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources_root = root / "resources"
            backend_dir = resources_root / "backend"
            backend_dir.mkdir(parents=True)
            (resources_root / "llm_agents").mkdir()
            meipass = root / "_MEI12345"
            meipass.mkdir()

            with patch.object(resources.sys, "frozen", True, create=True), \
                    patch.object(resources.sys, "executable", str(backend_dir / "ratomizer-desktop.exe")), \
                    patch.object(resources.sys, "_MEIPASS", str(meipass), create=True):
                self.assertEqual(resources.package_root(), resources_root.resolve())

    def start_api_server(self, out_dir: Path, *, token: str = "") -> TestAPIServer:
        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir.resolve()
        TestHandler.allowed_origins = {"http://127.0.0.1:5173", "http://127.0.0.1:8770", "null"}
        TestHandler.local_token = token
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return TestAPIServer(server, thread)

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

    def test_append_review_state_events_deduplicates_existing_events(self) -> None:
        state = {
            "requirement_id": "SREQ-1",
            "status": "accepted",
            "history": [
                {
                    "from_status": "candidate",
                    "to_status": "llm_reviewed",
                    "actor": "llm_pipeline",
                    "reason": "decision=accept",
                    "timestamp": "2026-06-10T00:00:00+00:00",
                },
                {
                    "from_status": "llm_reviewed",
                    "to_status": "accepted",
                    "actor": "llm_pipeline",
                    "reason": "low-risk acceptance",
                    "timestamp": "2026-06-10T00:00:01+00:00",
                },
            ],
            "metadata": {"req_id": "AREQ-1", "stable_req_id": "SREQ-1"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_state_events.jsonl"
            self.assertEqual(append_review_state_events(path, [state]), 2)
            self.assertEqual(append_review_state_events(path, [state]), 0)

            rows = read_jsonl(path)

        self.assertEqual(len(rows), 2)

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
                status, _ = server.post_json("/review-actions", {"requirement_id": "SREQ-1", "status": "accepted"})
                self.assertEqual(status, 401)

                status, payload = server.post_json(
                    "/review-actions",
                    {
                        "requirement_id": "SREQ-1",
                        "status": "accepted",
                        "actor": "vue3-test",
                        "reason": "accepted in Vue3 UI",
                    },
                    headers={"X-Requirement-Atomizer-Token": "secret-token"},
                )
                self.assertEqual(status, 200)
            finally:
                server.shutdown()

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
                status, _ = server.post_json("/review-actions", {"requirement_id": "SREQ-1", "status": "accepted"})
                self.assertEqual(status, 401)
            finally:
                server.shutdown()

            states = read_jsonl(out_dir / "review_states.jsonl")

        self.assertEqual(states, [])

    def test_api_translation_endpoint_returns_llm_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            server = self.start_api_server(out_dir, token="secret-token")
            try:
                with patch("api_server.translate_requirement_text") as translate:
                    translate.return_value = "读取客户端应支持 xDLMS 服务：使用 GET 的块传输。"
                    status, payload = server.post_json(
                        "/translations",
                        {
                            "requirement_id": "SREQ-1",
                            "text": 'Reading client shall support xDLMS Service: Block transfer with "GET".',
                        },
                        headers={"X-Requirement-Atomizer-Token": "secret-token"},
                    )
                    self.assertEqual(status, 200)
            finally:
                server.shutdown()

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

    def test_apply_expert_decision_serializes_concurrent_writes(self) -> None:
        import review_state as review_state_module

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            original_read_jsonl = review_state_module._read_jsonl
            barrier = threading.Barrier(2)

            def slow_read(path: Path) -> list[dict]:
                rows = original_read_jsonl(path)
                if path.name == "review_states.jsonl":
                    try:
                        barrier.wait(timeout=1)
                    except threading.BrokenBarrierError:
                        pass
                return rows

            with patch("review_state._read_jsonl", side_effect=slow_read):
                threads = [
                    threading.Thread(
                        target=apply_expert_decision,
                        args=(out_dir, f"SREQ-{index}", "accepted"),
                        kwargs={"actor": f"expert-{index}"},
                    )
                    for index in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual({state["requirement_id"] for state in states}, {"SREQ-0", "SREQ-1"})
        self.assertEqual({event["requirement_id"] for event in events}, {"SREQ-0", "SREQ-1"})

    def test_review_state_lock_recovers_stale_lock_file(self) -> None:
        import review_state as review_state_module

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            lock_path = out_dir / "review_states.lock"
            lock_path.write_text("stale", encoding="ascii")
            old_time = time.time() - 3600
            os.utime(lock_path, (old_time, old_time))

            with review_state_module.review_state_lock(out_dir, timeout_s=0.2, stale_after_s=0.0):
                self.assertTrue(lock_path.exists())

            self.assertFalse(lock_path.exists())

    def test_review_pipeline_preserves_existing_expert_decision_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    {
                        "req_id": "AREQ-1",
                        "stable_req_id": "SREQ-1",
                        "source_id": "SRC-1",
                        "source_type": "table_row",
                        "source_refs": ["SRC-1"],
                        "section_path": ["Scope"],
                        "domain": "dlms_cosem",
                        "object": "Clock",
                        "requirement_type": "event_definition",
                        "requirement": "Clock event shall be recorded.",
                        "parameters": {},
                        "verification_method": "test",
                        "ambiguity": False,
                        "review_questions": [],
                        "confidence": 0.95,
                        "kb_matches": [],
                        "generated_by": "rule_based_atomizer_v1",
                    }
                ],
            )
            apply_expert_decision(out_dir, "SREQ-1", "rejected", actor="expert", reason="not applicable")

            summary = run_review_pipeline(out_dir, route="stub", domain_pack_path=None)
            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(states[0]["status"], "rejected")
        self.assertEqual(states[0]["history"][-1]["actor"], "expert")
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual([event["actor"] for event in events].count("expert"), 1)

    def test_review_pipeline_preserves_existing_vue3_ui_decision_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    {
                        "req_id": "AREQ-1",
                        "stable_req_id": "SREQ-1",
                        "source_id": "SRC-1",
                        "source_type": "table_row",
                        "source_refs": ["SRC-1"],
                        "section_path": ["Scope"],
                        "domain": "dlms_cosem",
                        "object": "Clock",
                        "requirement_type": "event_definition",
                        "requirement": "Clock event shall be recorded.",
                        "parameters": {},
                        "verification_method": "test",
                        "ambiguity": False,
                        "review_questions": [],
                        "confidence": 0.95,
                        "kb_matches": [],
                        "generated_by": "rule_based_atomizer_v1",
                    }
                ],
            )
            apply_expert_decision(out_dir, "SREQ-1", "rejected", actor="vue3-ui", reason="manual reject from UI")

            summary = run_review_pipeline(out_dir, route="stub", domain_pack_path=None)
            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(states[0]["status"], "rejected")
        self.assertEqual(states[0]["history"][-1]["actor"], "vue3-ui")
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual([event["actor"] for event in events], ["vue3-ui"])

    def test_review_pipeline_does_not_append_ignored_auto_events_after_expert_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    {
                        "req_id": "AREQ-1",
                        "stable_req_id": "SREQ-1",
                        "source_id": "SRC-1",
                        "source_type": "table_row",
                        "source_refs": ["SRC-1"],
                        "section_path": ["Scope"],
                        "domain": "dlms_cosem",
                        "object": "Clock",
                        "requirement_type": "event_definition",
                        "requirement": "Clock event shall be recorded.",
                        "parameters": {},
                        "verification_method": "test",
                        "ambiguity": False,
                        "review_questions": [],
                        "confidence": 0.95,
                        "kb_matches": [],
                        "generated_by": "rule_based_atomizer_v1",
                    }
                ],
            )
            apply_expert_decision(out_dir, "SREQ-1", "rejected", actor="expert", reason="not applicable")

            run_review_pipeline(out_dir, route="stub", domain_pack_path=None)
            run_review_pipeline(out_dir, route="stub", domain_pack_path=None)
            states = read_jsonl(out_dir / "review_states.jsonl")
            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(states[0]["status"], "rejected")
        self.assertEqual([event["actor"] for event in events], ["expert"])

    def test_review_pipeline_writes_merged_states_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    {
                        "req_id": "AREQ-1",
                        "stable_req_id": "SREQ-1",
                        "source_id": "SRC-1",
                        "source_type": "table_row",
                        "source_refs": ["SRC-1"],
                        "section_path": ["Scope"],
                        "domain": "dlms_cosem",
                        "object": "Clock",
                        "requirement_type": "event_definition",
                        "requirement": "Clock event shall be recorded.",
                        "parameters": {},
                        "verification_method": "test",
                        "ambiguity": False,
                        "review_questions": [],
                        "confidence": 0.95,
                        "kb_matches": [],
                        "generated_by": "rule_based_atomizer_v1",
                    }
                ],
            )
            with patch("llm_pipeline.atomic_write_jsonl") as atomic_write:
                atomic_write.side_effect = lambda path, rows: write_jsonl(path, rows)

                run_review_pipeline(out_dir, route="stub", domain_pack_path=None)

            written = [call.args[0].name for call in atomic_write.call_args_list]

        self.assertIn("review_states.jsonl", written)

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
        self.assertIn("desktop_backend", py_modules)
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
