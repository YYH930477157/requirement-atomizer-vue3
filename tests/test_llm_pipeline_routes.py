from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from llm_client import LLMConnectionError
from llm_pipeline import read_jsonl, run_review_pipeline, write_jsonl


ROOT = Path(__file__).resolve().parents[1]


class ScriptedOpenAIService:
    def __init__(self, handler: Any):
        self.handler = handler
        self.requests: list[dict[str, Any]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                service.requests.append(body)
                response = service.handler(body, len(service.requests))
                status = int(response.get("status", 200))
                payload = response.get("body", {})
                body_bytes = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> "ScriptedOpenAIService":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def openai_review(decision: str = "accept", confidence: float = 0.88) -> dict[str, Any]:
    payload = {
        "decision": decision,
        "risk": "low_risk" if decision == "accept" else "high_risk",
        "confidence": confidence,
        "review_notes": ["mock llm review"],
        "expert_questions": [],
    }
    return openai_review_payload(payload)


def openai_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def write_pipeline_config(path: Path, base_url: str, *, default_route: str = "openai_compatible") -> None:
    path.write_text(
        f"""
schema_version: "0.2"
pipeline_id: "test_review_pipeline"
model_routing:
  low_risk:
    provider: "stub"
    model: "local-rule-reviewer"
  high_risk:
    provider: "stub"
    model: "local-strict-reviewer"
risk_policy:
  high_risk_types:
    - "security_policy_bit"
  low_confidence_threshold: 0.75
model_routes:
  default: "{default_route}"
  openai_compatible:
    base_url: "{base_url}"
    model: "mock-review-model"
    api_key_env: ""
    temperature: 0.0
    max_tokens: 512
    timeout_s: 2
    max_retries: 0
    concurrency: 2
review_scope:
  mode: targeted
  confidence_below: 0.75
  always_review_ambiguous: true
  always_review_source_types: ["paragraph", "table_row"]
  always_review_types: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def requirement(
    stable_id: str,
    *,
    requirement_type: str = "event_definition",
    confidence: float = 0.9,
    ambiguity: bool = False,
    source_type: str = "table_row",
) -> dict[str, Any]:
    return {
        "req_id": stable_id.replace("SREQ", "AREQ"),
        "stable_req_id": stable_id,
        "source_id": f"SRC-{stable_id[-4:]}",
        "source_type": source_type,
        "source_refs": [f"SRC-{stable_id[-4:]}"],
        "section_path": ["Scope"],
        "domain": "dlms_cosem",
        "object": "Object",
        "requirement_type": requirement_type,
        "requirement": f"{stable_id} shall be reviewed.",
        "parameters": {},
        "verification_method": "test",
        "ambiguity": ambiguity,
        "review_questions": [],
        "confidence": confidence,
        "kb_matches": [{"name": "DLMS", "definition": "meter protocol"}],
        "generated_by": "rule_based_atomizer_v1",
    }


class LLMPipelineRouteTests(unittest.TestCase):
    def test_targeted_route_reviews_only_selected_requirements_and_marks_generated_by(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            rows = [
                requirement("SREQ-0000000000000001", confidence=0.91),
                requirement("SREQ-0000000000000002", confidence=0.70),
                requirement("SREQ-0000000000000003", ambiguity=True),
                requirement("SREQ-0000000000000004", requirement_type="cosem_attribute_access", confidence=0.96),
                requirement("SREQ-0000000000000005", source_type="paragraph", confidence=0.84),
                requirement("SREQ-0000000000000006", source_type="paragraph", confidence=0.90),
            ]
            write_jsonl(out_dir / "atomic_requirements.jsonl", rows)

            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir,
                    pipeline_path=pipeline_path,
                    domain_pack_path=ROOT / "domain_packs" / "dlms_cosem" / "pack.yaml",
                    route="openai_compatible",
                    scope="targeted",
                )

            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(len(service.requests), 4)
        self.assertEqual(summary["llm_reviewed"], 4)
        self.assertEqual(summary["rule_stub"], 2)
        self.assertEqual(summary["llm_failed"], 0)
        self.assertEqual([review["generated_by"] for review in reviews].count("llm:mock-review-model"), 4)
        self.assertEqual([review["generated_by"] for review in reviews].count("rule_stub"), 2)

    def test_default_stub_route_does_not_call_openai_compatible_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(out_dir / "atomic_requirements.jsonl", [requirement("SREQ-0000000000000007", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            write_pipeline_config(pipeline_path, "http://127.0.0.1:9/v1", default_route="stub")

            summary = run_review_pipeline(out_dir, pipeline_path=pipeline_path)
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_reviewed"], 0)
        self.assertEqual(summary["rule_stub"], 1)
        self.assertEqual(summary["llm_failed"], 0)
        self.assertEqual(reviews[0]["generated_by"], "rule_stub")

    def test_llm_review_cache_skips_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    requirement("SREQ-0000000000000011", confidence=0.70),
                    requirement("SREQ-0000000000000012", confidence=0.71),
                ],
            )

            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                first = run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")
                second = run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")

            cache_rows = read_jsonl(out_dir / "llm_review_cache.jsonl")

        self.assertEqual(first["llm_reviewed"], 2)
        self.assertEqual(second["llm_reviewed"], 2)
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(len(cache_rows), 2)

    def test_single_llm_failure_falls_back_to_stub_without_failing_batch(self) -> None:
        def handler(body: dict[str, Any], count: int) -> dict[str, Any]:
            prompt = body["messages"][-1]["content"]
            if "SREQ-00000000000000FF" in prompt:
                return {"status": 500, "body": {"error": "boom"}}
            return {"body": openai_review()}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    requirement("SREQ-00000000000000AA", confidence=0.70),
                    requirement("SREQ-00000000000000FF", confidence=0.70),
                    requirement("SREQ-00000000000000BB", confidence=0.70),
                ],
            )

            with ScriptedOpenAIService(handler) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")

            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        failed = next(review for review in reviews if review["stable_req_id"] == "SREQ-00000000000000FF")
        self.assertEqual(summary["llm_failed"], 1)
        self.assertEqual(summary["rule_stub"], 1)
        self.assertEqual(summary["llm_reviewed"], 2)
        self.assertEqual(failed["generated_by"], "rule_stub")
        self.assertTrue(any(note.startswith("llm_unavailable:") for note in failed["review_notes"]))

    def test_schema_invalid_llm_review_triggers_repair_request(self) -> None:
        responses = [
            {"decision": "approve", "confidence": 0.91, "review_notes": [], "expert_questions": []},
            {"decision": "accept", "confidence": 0.91, "review_notes": ["repaired"], "expert_questions": []},
        ]

        def handler(body: dict[str, Any], count: int) -> dict[str, Any]:
            return {"body": openai_review_payload(responses.pop(0))}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(out_dir / "atomic_requirements.jsonl", [requirement("SREQ-0000000000000091", confidence=0.70)])

            with ScriptedOpenAIService(handler) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")

            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertEqual(summary["llm_failed"], 0)
        self.assertEqual(len(service.requests), 2)
        self.assertIn("schema validation failed", service.requests[1]["messages"][-1]["content"])
        self.assertEqual(reviews[0]["decision"], "accept")

    def test_first_five_connection_failures_abort_as_service_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [requirement(f"SREQ-00000000000001{index:02X}", confidence=0.70) for index in range(6)],
            )

            with ScriptedOpenAIService(lambda body, count: {"status": 500, "body": {"error": "down"}}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with self.assertRaises(LLMConnectionError):
                    run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")

    def test_small_batch_all_connection_failures_abort_as_service_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [requirement("SREQ-0000000000000201", confidence=0.70), requirement("SREQ-0000000000000202", confidence=0.70)],
            )

            with ScriptedOpenAIService(lambda body, count: {"status": 500, "body": {"error": "down"}}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with self.assertRaises(LLMConnectionError):
                    run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")

    def test_401_auth_failures_abort_as_service_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [requirement("SREQ-0000000000000301", confidence=0.70), requirement("SREQ-0000000000000302", confidence=0.70)],
            )

            with ScriptedOpenAIService(lambda body, count: {"status": 401, "body": {"error": "invalid api key"}}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with self.assertRaisesRegex(LLMConnectionError, "invalid api key"):
                    run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")


if __name__ == "__main__":
    unittest.main()
