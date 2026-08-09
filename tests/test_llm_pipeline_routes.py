from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from llm_client import LLMClientConfig, LLMConnectionError
from llm_pipeline import (
    DEFAULT_PIPELINE_PATH,
    active_review_prompt_version,
    batch_review_enabled,
    effective_review_scope,
    llm_cache_key,
    llm_cache_key_batch,
    llm_config_from_route,
    load_review_pipeline,
    read_jsonl,
    read_llm_review_cache,
    review_batch_count,
    run_review_pipeline,
    write_jsonl,
)
from llm_pipeline import REVIEW_BATCH_PROMPT_VERSION as REVIEW_BATCH_PROMPT_VERSION_CONSTANT


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


class EnvironmentRouteOverrideTests(unittest.TestCase):
    def test_llm_route_can_be_overridden_from_desktop_environment(self) -> None:
        route = {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:14b",
            "api_key_env": "RATOMIZER_LLM_API_KEY",
            "temperature": 0,
            "max_tokens": 1024,
            "timeout_s": 60,
            "max_retries": 3,
        }
        overrides = {
            "RATOMIZER_LLM_BASE_URL": "https://example.test/v1",
            "RATOMIZER_LLM_MODEL": "glm-4-plus",
            "RATOMIZER_LLM_API_KEY_ENV": "CUSTOM_LLM_KEY",
            "RATOMIZER_LLM_TEMPERATURE": "0.2",
            "RATOMIZER_LLM_MAX_TOKENS": "2048",
            "RATOMIZER_LLM_TIMEOUT_S": "15",
            "RATOMIZER_LLM_MAX_RETRIES": "0",
        }
        with patch.dict("os.environ", overrides, clear=False):
            config = llm_config_from_route(route)

        self.assertEqual(config.base_url, "https://example.test/v1")
        self.assertEqual(config.model, "glm-4-plus")
        self.assertEqual(config.api_key_env, "CUSTOM_LLM_KEY")
        self.assertEqual(config.temperature, 0.2)
        self.assertEqual(config.max_tokens, 2048)
        self.assertEqual(config.timeout_s, 15.0)
        self.assertEqual(config.max_retries, 0)

    def test_concurrency_env_override_reaches_route_payload(self) -> None:
        """GUI「AI 抽取并发」此前只影响 ai_extract/analyze——审查管线与装配富化被 yaml 锁死在 4。
        concurrency 进覆盖表后，同一设置对全部 LLM 环节生效。"""
        from llm_pipeline import apply_llm_environment_overrides

        payload = {"base_url": "http://x/v1", "model": "m", "concurrency": 4}
        with patch.dict("os.environ", {"RATOMIZER_LLM_CONCURRENCY": "8"}, clear=False):
            merged = apply_llm_environment_overrides(payload)
        self.assertEqual(int(merged["concurrency"]), 8)   # 消费方 int() 转换

        with patch.dict("os.environ", {}, clear=False):
            import os as _os
            _os.environ.pop("RATOMIZER_LLM_CONCURRENCY", None)
            merged = apply_llm_environment_overrides(payload)
        self.assertEqual(int(merged["concurrency"]), 4)   # 未设 env 保持 yaml 值


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


def write_pipeline_config(
    path: Path,
    base_url: str,
    *,
    default_route: str = "openai_compatible",
    connection_failure_abort: int | None = None,
) -> None:
    abort_line = f"\n    connection_failure_abort: {connection_failure_abort}" if connection_failure_abort is not None else ""
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
    concurrency: 2{abort_line}
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


def _request_user_content(body: dict[str, Any]) -> str:
    return str(body["messages"][1]["content"])


def _is_batch_request(body: dict[str, Any]) -> bool:
    try:
        parsed = json.loads(_request_user_content(body))
    except Exception:
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("requirements"), list)


def _batch_requirement_ids(body: dict[str, Any]) -> list[str]:
    parsed = json.loads(_request_user_content(body))
    return [str(item.get("requirement_id") or "") for item in parsed.get("requirements", [])]


def batch_reviews_body(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """批量审查合法响应：{choices:[{message:{content: json({reviews:[...]})}}]}。"""
    return {"body": {"choices": [{"message": {"content": json.dumps({"reviews": reviews})}}]}}


def batch_illegal_body() -> dict[str, Any]:
    """批量审查结构非法响应（无 reviews 列表）→ 触发拆半。"""
    return {"body": {"choices": [{"message": {"content": json.dumps({"unexpected": "shape"})}}]}}


def batch_review_item(
    requirement_id: str,
    *,
    decision: str = "accept",
    revised_requirement: str | None = None,
    related_requirement_ids: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "requirement_id": requirement_id,
        "decision": decision,
        "risk": "low_risk",
        "confidence": 0.9,
        "review_notes": ["batch mock"],
        "expert_questions": [],
    }
    if revised_requirement is not None:
        item["revised_requirement"] = revised_requirement
    if related_requirement_ids is not None:
        item["related_requirement_ids"] = related_requirement_ids
    return item


def _reviews_by_id(out_dir: Path) -> dict[str, dict[str, Any]]:
    reviews = read_jsonl(out_dir / "llm_review_results.jsonl")
    return {str(row.get("requirement_id") or row.get("stable_req_id") or ""): row for row in reviews}


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

    def test_cache_fingerprint_covers_prompt_policy_and_effective_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline_path = Path(tmp) / "review_pipeline.yaml"
            write_pipeline_config(pipeline_path, "http://127.0.0.1:9/v1")
            pipeline = load_review_pipeline(pipeline_path)
            row = requirement("SREQ-0000000000000013", confidence=0.70)
            targeted = effective_review_scope(pipeline, "targeted")

            base_key = llm_cache_key(row, "mock-review-model", pipeline, targeted)
            changed_prompt = dict(row)
            changed_prompt["requirement"] = "Changed requirement text."
            changed_policy = replace(
                pipeline,
                risk_policy={**pipeline.risk_policy, "mandatory_review_types": ["event_definition"]},
            )

            self.assertNotEqual(
                base_key,
                llm_cache_key(changed_prompt, "mock-review-model", pipeline, targeted),
            )
            self.assertNotEqual(
                base_key,
                llm_cache_key(row, "mock-review-model", changed_policy, targeted),
            )
            self.assertNotEqual(
                base_key,
                llm_cache_key(row, "mock-review-model", pipeline, effective_review_scope(pipeline, "all")),
            )

    def test_policy_change_invalidates_cache_and_mandatory_policy_is_consistent_on_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [requirement("SREQ-0000000000000014", confidence=0.90)],
            )

            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", scope="all",
                )
                policy_text = pipeline_path.read_text(encoding="utf-8").replace(
                    "risk_policy:\n",
                    "risk_policy:\n  mandatory_review_types:\n    - \"event_definition\"\n",
                    1,
                )
                pipeline_path.write_text(policy_text, encoding="utf-8")
                run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", scope="all",
                )
                fresh_review = read_jsonl(out_dir / "llm_review_results.jsonl")[0]
                run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", scope="all",
                )
                cached_review = read_jsonl(out_dir / "llm_review_results.jsonl")[0]

            cache_rows = read_jsonl(out_dir / "llm_review_cache.jsonl")

        self.assertEqual(len(service.requests), 2)
        self.assertEqual(len(cache_rows), 2)
        self.assertEqual(fresh_review["risk"], "mandatory_review")
        self.assertEqual(fresh_review["decision"], "needs_expert")
        self.assertEqual(cached_review, fresh_review)

    def test_legacy_cache_row_is_ignored_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            row = requirement("SREQ-0000000000000015", confidence=0.70)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [row])
            write_jsonl(
                out_dir / "llm_review_cache.jsonl",
                [{
                    "stable_req_id": row["stable_req_id"],
                    "model": "mock-review-model",
                    "prompt_version": "m2-review-v1",
                    "review": {"decision": "accept", "risk": "low_risk"},
                }],
            )

            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", scope="all",
                )

        self.assertEqual(len(service.requests), 1)

    def test_review_cache_reader_repairs_torn_final_record(self) -> None:
        valid_row = {
            "stable_req_id": "SREQ-1",
            "model": "m",
            "prompt_version": "p",
            "input_fingerprint": "f",
            "review": {"decision": "accept"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "llm_review_cache.jsonl"
            valid_line = json.dumps(valid_row) + "\n"
            cache.write_text(valid_line + '{"stable_req_id":', encoding="utf-8")

            with self.assertLogs("requirement_atomizer", level="WARNING"):
                rows = read_llm_review_cache(cache)

            self.assertEqual(len(rows), 1)
            self.assertEqual(cache.read_text(encoding="utf-8"), valid_line)

    def test_openai_review_reports_progress_for_each_completed_llm_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    requirement("SREQ-0000000000000A01", confidence=0.70),
                    requirement("SREQ-0000000000000A02", confidence=0.70),
                    requirement("SREQ-0000000000000A03", confidence=0.70),
                ],
            )
            events: list[dict[str, Any]] = []

            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                run_review_pipeline(
                    out_dir,
                    pipeline_path=pipeline_path,
                    route="openai_compatible",
                    progress_callback=events.append,
                )

        llm_progress = [event for event in events if event.get("stage") == "llm_review"]
        self.assertEqual([event["completed"] for event in llm_progress], [1, 2, 3])
        self.assertTrue(all(event["total"] == 3 for event in llm_progress))
        self.assertEqual(llm_progress[-1]["percent"], 100)

    def test_llm_review_limit_caps_real_llm_calls_but_keeps_all_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [requirement(f"SREQ-000000000000L{index:02d}", confidence=0.70) for index in range(6)],
            )
            events: list[dict[str, Any]] = []

            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir,
                    pipeline_path=pipeline_path,
                    route="openai_compatible",
                    llm_review_limit=2,
                    progress_callback=events.append,
                )

            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")
            states = read_jsonl(out_dir / "review_states.jsonl")

        self.assertEqual(len(service.requests), 2)
        self.assertEqual(len(reviews), 6)
        self.assertEqual(len(states), 6)
        self.assertEqual(summary["requirements"], 6)
        self.assertEqual(summary["llm_reviewed"], 2)
        self.assertEqual(summary["rule_stub"], 4)
        self.assertEqual([review["generated_by"] for review in reviews].count("llm:mock-review-model"), 2)
        self.assertEqual([review["generated_by"] for review in reviews].count("rule_stub"), 4)
        llm_progress = [event for event in events if event.get("stage") == "llm_review"]
        self.assertEqual([event["completed"] for event in llm_progress], [1, 2])
        self.assertTrue(all(event["total"] == 2 for event in llm_progress))

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

    def test_consecutive_connection_failures_abort_mid_batch(self) -> None:
        def handler(body: dict[str, Any], count: int) -> dict[str, Any]:
            if count <= 3:
                return {"body": openai_review()}
            return {"status": 500, "body": {"error": "connection lost"}}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [requirement(f"SREQ-00000000000004{index:02X}", confidence=0.70) for index in range(10)],
            )

            with ScriptedOpenAIService(handler) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url, connection_failure_abort=3)
                with self.assertRaisesRegex(LLMConnectionError, "consecutive connection failures"):
                    run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")

    def test_connection_abort_cancels_queued_reviews_without_waiting_for_full_queue(self) -> None:
        call_count = 0
        lock = threading.Lock()

        def fake_review(requirement_row: dict[str, Any], pipeline: Any, client_config: LLMClientConfig) -> dict[str, Any]:
            nonlocal call_count
            with lock:
                call_count += 1
                current_call = call_count
            if current_call <= 5:
                return {
                    "task_id": f"REVIEW-{requirement_row['stable_req_id']}",
                    "requirement_id": requirement_row["stable_req_id"],
                    "req_id": requirement_row["req_id"],
                    "stable_req_id": requirement_row["stable_req_id"],
                    "source_refs": requirement_row["source_refs"],
                    "risk": "low_risk",
                    "decision": "accept",
                    "revised_requirement": requirement_row["requirement"],
                    "review_notes": ["mock"],
                    "expert_questions": [],
                    "confidence": 0.9,
                    "model_route": {"provider": "openai_compatible"},
                    "generated_by": "llm:mock-review-model",
                }
            time.sleep(0.05)
            raise LLMConnectionError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            rows = [requirement(f"SREQ-00000000000005{index:02X}", confidence=0.70) for index in range(65)]
            write_jsonl(out_dir / "atomic_requirements.jsonl", rows)
            pipeline_path = tmp_path / "review_pipeline.yaml"
            write_pipeline_config(pipeline_path, "http://127.0.0.1:9/v1", connection_failure_abort=2)

            started = time.perf_counter()
            with patch("llm_pipeline.build_openai_review", side_effect=fake_review):
                with self.assertRaisesRegex(LLMConnectionError, "consecutive connection failures"):
                    run_review_pipeline(out_dir, pipeline_path=pipeline_path, route="openai_compatible")
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.8)
        self.assertLess(call_count, len(rows))


if __name__ == "__main__":
    unittest.main()


class ReviewPipelineConcurrencyWiringTests(unittest.TestCase):
    """0714 提速:审查管线的 concurrency 必须从 env 覆盖后的 payload 读——
    此前 run_review_pipeline 读原始 yaml,GUI 并发设置对审核阶段恒不生效(33 分钟瓶颈)。"""

    def test_run_review_pipeline_applies_env_overrides_before_concurrency_read(self) -> None:
        import inspect
        import llm_pipeline
        src = inspect.getsource(llm_pipeline.review_requirements_with_openai)
        self.assertIn("apply_llm_environment_overrides", src)
        self.assertLess(src.index("apply_llm_environment_overrides"),
                        src.index('route_payload.get("concurrency"'))


class ReviewBatchOptimizationTests(unittest.TestCase):
    def _write_rows(self, out_dir: Path, count: int) -> list[dict[str, Any]]:
        rows = [requirement(f"SREQ-BATCH-{index:04d}", confidence=0.70)
                for index in range(1, count + 1)]
        write_jsonl(out_dir / "atomic_requirements.jsonl", rows)
        return rows

    def test_batch_count_contract_and_default_tool_loop_guard(self) -> None:
        for raw, expected in [("0", 0), ("1", 1), ("15", 15), ("21", 20), ("3.5", 0), ("x", 0)]:
            with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": raw}):
                self.assertEqual(review_batch_count(), expected)
        with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
            default_pipeline = load_review_pipeline(DEFAULT_PIPELINE_PATH)
            self.assertFalse(batch_review_enabled(default_pipeline))
            self.assertEqual(active_review_prompt_version(), "m2-review-v3")

    def test_fifteen_plus_one_requirements_use_two_batch_calls(self) -> None:
        batch_sizes: list[int] = []

        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            ids = _batch_requirement_ids(body)
            batch_sizes.append(len(ids))
            return batch_reviews_body([batch_review_item(rid) for rid in reversed(ids)])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            self._write_rows(out, 16)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", scope="all",
                    )
        self.assertEqual(batch_sizes, [15, 1])
        self.assertEqual(summary["llm_reviewed"], 16)
        self.assertEqual(summary["rule_stub"], 0)

    def test_missing_duplicate_and_out_of_batch_ids_fail_closed_per_item(self) -> None:
        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            ids = _batch_requirement_ids(body)
            return batch_reviews_body([
                batch_review_item(ids[2]),
                batch_review_item(ids[0]),
                batch_review_item(ids[0], decision="revise"),
                batch_review_item("SREQ-GHOST"),
            ])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            rows = self._write_rows(out, 3)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", scope="all",
                    )
            reviews = _reviews_by_id(out)
        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertEqual(summary["rule_stub"], 2)
        self.assertEqual(summary["llm_failed"], 2)
        self.assertEqual(reviews[rows[2]["stable_req_id"]]["generated_by"], "llm:mock-review-model")
        for row in rows[:2]:
            review = reviews[row["stable_req_id"]]
            self.assertEqual(review["decision"], "needs_expert")
            self.assertEqual(review["generated_by"], "rule_stub")
            self.assertEqual(review["model_route"]["provider"], "stub")

    def test_drift_and_ghost_merge_do_not_contaminate_valid_item(self) -> None:
        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            ids = _batch_requirement_ids(body)
            return batch_reviews_body([
                batch_review_item(ids[0], decision="revise",
                                  revised_requirement=f"{ids[0]} shall be reviewed with 999."),
                batch_review_item(ids[1], decision="merge",
                                  related_requirement_ids=["SREQ-OUTSIDE"]),
                batch_review_item(ids[2]),
            ])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            rows = self._write_rows(out, 3)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", scope="all",
                    )
            reviews = _reviews_by_id(out)
        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertEqual(summary["llm_failed"], 2)
        self.assertEqual(reviews[rows[2]["stable_req_id"]]["decision"], "accept")
        self.assertEqual(reviews[rows[0]["stable_req_id"]]["decision"], "needs_expert")
        self.assertEqual(reviews[rows[1]["stable_req_id"]]["decision"], "needs_expert")

    def test_malformed_batch_splits_and_preserves_actual_subbatch_boundary(self) -> None:
        all_ids: list[str] = []

        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            ids = _batch_requirement_ids(body)
            if not all_ids:
                all_ids.extend(ids)
            if len(ids) == 4:
                return batch_illegal_body()
            reviews = [batch_review_item(rid) for rid in ids]
            if ids == all_ids[:2]:
                reviews[0] = batch_review_item(
                    ids[0], decision="merge", related_requirement_ids=[all_ids[2]])
            return batch_reviews_body(reviews)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            rows = self._write_rows(out, 4)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", scope="all",
                    )
            reviews = _reviews_by_id(out)
        self.assertEqual(len(service.requests), 3)
        self.assertEqual(summary["llm_reviewed"], 3)
        self.assertEqual(summary["llm_failed"], 1)
        self.assertEqual(reviews[rows[0]["stable_req_id"]]["decision"], "needs_expert")

    def test_split_exhaustion_falls_back_to_existing_single_review(self) -> None:
        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            if _is_batch_request(body):
                return batch_illegal_body()
            return {"body": openai_review()}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            self._write_rows(out, 2)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", scope="all",
                    )
        self.assertEqual(len(service.requests), 5)
        self.assertEqual(summary["llm_reviewed"], 2)
        self.assertEqual(summary["llm_failed"], 0)

    def test_exact_batch_cache_skips_second_run_and_group_change_misses(self) -> None:
        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            ids = _batch_requirement_ids(body)
            return batch_reviews_body([batch_review_item(rid) for rid in ids])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            rows = self._write_rows(out, 3)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    run_review_pipeline(out, pipeline_path=pipeline_path, domain_pack_path=None,
                                        route="openai_compatible", scope="all")
                    run_review_pipeline(out, pipeline_path=pipeline_path, domain_pack_path=None,
                                        route="openai_compatible", scope="all")
                    rows.append(requirement("SREQ-BATCH-0004", confidence=0.70))
                    write_jsonl(out / "atomic_requirements.jsonl", rows)
                    run_review_pipeline(out, pipeline_path=pipeline_path, domain_pack_path=None,
                                        route="openai_compatible", scope="all")
            cache_rows = read_jsonl(out / "llm_review_cache.jsonl")
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(len(cache_rows), 7)

    def test_policy_floor_and_llm_limit_remain_per_requirement(self) -> None:
        def handler(body: dict[str, Any], _count: int) -> dict[str, Any]:
            ids = _batch_requirement_ids(body)
            return batch_reviews_body([batch_review_item(rid) for rid in ids])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            rows = self._write_rows(out, 5)
            with ScriptedOpenAIService(handler) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                text = pipeline_path.read_text(encoding="utf-8").replace(
                    "risk_policy:\n", "risk_policy:\n  mandatory_review_types:\n    - event_definition\n", 1)
                pipeline_path.write_text(text, encoding="utf-8")
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", scope="all", llm_review_limit=3,
                    )
            reviews = _reviews_by_id(out)
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(summary["llm_reviewed"], 3)
        self.assertEqual(summary["rule_stub"], 2)
        for row in rows[:3]:
            review = reviews[row["stable_req_id"]]
            self.assertEqual(review["decision"], "needs_expert")
            self.assertEqual(review["generated_by"], "llm:mock-review-model")

    def test_initial_batch_connection_failure_aborts_before_fanout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            self._write_rows(out, 30)
            with ScriptedOpenAIService(
                    lambda _body, _count: {"status": 500, "body": {"error": "down"}}) as service:
                pipeline_path = root / "pipeline.yaml"
                write_pipeline_config(pipeline_path, service.base_url)
                with patch.dict("os.environ", {"RATOMIZER_REVIEW_BATCH": "15"}):
                    with self.assertRaisesRegex(LLMConnectionError, "initial review batch failed"):
                        run_review_pipeline(
                            out, pipeline_path=pipeline_path, domain_pack_path=None,
                            route="openai_compatible", scope="all",
                        )
        self.assertEqual(len(service.requests), 1)
