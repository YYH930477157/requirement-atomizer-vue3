from __future__ import annotations

import json
import os
import io
import threading
import urllib.error
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

from llm_client import LLMClientConfig, LLMConnectionError, LLMResponseError, _read_error_body, chat_json


def openai_response(payload: dict[str, Any] | str) -> dict[str, Any]:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return {"choices": [{"message": {"content": content}}]}


class MockOpenAIService:
    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                service.requests.append(body)
                service.headers.append({key: value for key, value in self.headers.items()})
                response = service.responses.pop(0)
                status = int(response.get("status", 200))
                payload = response.get("body", {})
                headers = dict(response.get("headers", {}))
                body_bytes = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, str(value))
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

    def __enter__(self) -> "MockOpenAIService":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class LLMClientTests(unittest.TestCase):
    def test_read_error_body_closes_http_error_response(self) -> None:
        body = io.BytesIO(b'{"error":"boom"}')
        error = urllib.error.HTTPError("http://example.test", 500, "Internal Server Error", {}, body)

        raw = _read_error_body(error)

        self.assertEqual(raw, '{"error":"boom"}')
        self.assertTrue(body.closed)

    def test_chat_json_posts_openai_request_and_reads_json_object(self) -> None:
        os.environ["RATOMIZER_TEST_KEY"] = "secret-token"
        try:
            with MockOpenAIService([{"body": openai_response({"decision": "accept", "confidence": 0.92})}]) as service:
                result = chat_json(
                    LLMClientConfig(
                        base_url=service.base_url,
                        model="mock-model",
                        api_key_env="RATOMIZER_TEST_KEY",
                        timeout_s=2,
                        max_retries=0,
                    ),
                    "system prompt",
                    "user prompt",
                )
        finally:
            os.environ.pop("RATOMIZER_TEST_KEY", None)

        self.assertEqual(result["decision"], "accept")
        self.assertEqual(service.requests[0]["model"], "mock-model")
        self.assertEqual(service.requests[0]["messages"][0]["role"], "system")
        self.assertEqual(service.headers[0]["Authorization"], "Bearer secret-token")

    def test_chat_json_logs_call_duration(self) -> None:
        """慢的可见性：每次 LLM 调用记 model/时长/attempt（mimo-pro 单次 50-130s，无日志只能感觉卡）。"""
        os.environ["RATOMIZER_TEST_KEY"] = "secret-token"
        try:
            with MockOpenAIService([{"body": openai_response({"ok": True})}]) as service:
                with self.assertLogs("requirement_atomizer", level="INFO") as captured:
                    chat_json(
                        LLMClientConfig(base_url=service.base_url, model="mock-model",
                                        api_key_env="RATOMIZER_TEST_KEY", timeout_s=2, max_retries=0),
                        "s", "u")
        finally:
            os.environ.pop("RATOMIZER_TEST_KEY", None)

        line = next(m for m in captured.output if "LLM 调用" in m)
        self.assertIn("model=mock-model", line)
        self.assertIn("dur=", line)
        self.assertIn("attempt=1", line)

    def test_trace_records_full_messages_and_response(self) -> None:
        """消息级追踪：启用后每次调用在 llm_trace.jsonl 落一行完整收发（prompt+响应全文）。"""
        import tempfile
        from pathlib import Path
        import llm_client

        os.environ["RATOMIZER_TEST_KEY"] = "secret-token"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                trace = Path(tmp) / "llm_trace.jsonl"
                llm_client.set_trace_path(trace)
                try:
                    with MockOpenAIService([{"body": openai_response({"answer": 42})}]) as service:
                        chat_json(
                            LLMClientConfig(base_url=service.base_url, model="mock-model",
                                            api_key_env="RATOMIZER_TEST_KEY", timeout_s=2, max_retries=0),
                            "system-prompt-marker", "user-prompt-marker")
                finally:
                    llm_client.set_trace_path(None)
                rows = [json.loads(l) for l in trace.read_text(encoding="utf-8").splitlines()]
        finally:
            os.environ.pop("RATOMIZER_TEST_KEY", None)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["model"], "mock-model")
        self.assertEqual(row["messages"][0]["content"], "system-prompt-marker")
        self.assertEqual(row["messages"][1]["content"], "user-prompt-marker")
        self.assertIn("choices", row["response"])            # 响应全文（含 usage/reasoning 若有）
        self.assertIn("dur_s", row)

    def test_trace_disabled_writes_nothing(self) -> None:
        import tempfile
        from pathlib import Path
        import llm_client

        llm_client.set_trace_path(None)
        os.environ["RATOMIZER_TEST_KEY"] = "secret-token"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with MockOpenAIService([{"body": openai_response({"ok": True})}]) as service:
                    chat_json(
                        LLMClientConfig(base_url=service.base_url, model="mock-model",
                                        api_key_env="RATOMIZER_TEST_KEY", timeout_s=2, max_retries=0),
                        "s", "u")
                self.assertEqual(list(Path(tmp).glob("*.jsonl")), [])
        finally:
            os.environ.pop("RATOMIZER_TEST_KEY", None)

    def test_chat_json_strips_markdown_fences(self) -> None:
        fenced = "```json\n{\"decision\":\"accept\",\"confidence\":0.9}\n```"
        with MockOpenAIService([{"body": openai_response(fenced)}]) as service:
            result = chat_json(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                "system",
                "user",
            )

        self.assertEqual(result, {"decision": "accept", "confidence": 0.9})

    def test_bad_json_triggers_one_repair_request(self) -> None:
        with MockOpenAIService(
            [
                {"body": openai_response("not json")},
                {"body": openai_response({"decision": "needs_expert", "confidence": 0.61})},
            ]
        ) as service:
            result = chat_json(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                "system",
                "user",
            )

        self.assertEqual(result["decision"], "needs_expert")
        self.assertEqual(len(service.requests), 2)
        self.assertIn("Only output valid JSON", service.requests[1]["messages"][-1]["content"])

    def test_truncated_response_escalates_max_tokens(self) -> None:
        """finish_reason=length → max_tokens 倍升重试（test3 实证：截断 JSON 走修复重发
        同预算仍被截,整章稳定失败——必须升级预算而非修复）。"""
        truncated = {"choices": [{"message": {"content": '{"requirements": [{"title": "partial'}, "finish_reason": "length"}]}
        complete = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}
        with MockOpenAIService([{"body": truncated}, {"body": complete}]) as service:
            result = chat_json(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                timeout_s=2, max_retries=0, max_tokens=100),
                "system",
                "user",
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(service.requests[0]["max_tokens"], 100)
        self.assertEqual(service.requests[1]["max_tokens"], 200)

    def test_empty_content_escalates_max_tokens(self) -> None:
        """空 content（推理模型 reasoning 吃光预算的可见输出）同样触发升级重试。"""
        empty = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        complete = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}
        with MockOpenAIService([{"body": empty}, {"body": complete}]) as service:
            result = chat_json(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                timeout_s=2, max_retries=0, max_tokens=100),
                "system",
                "user",
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(service.requests[1]["max_tokens"], 200)

    def test_escalation_stops_at_cap(self) -> None:
        """已到升级上限的截断原样返回交下游修复,不再多发请求。"""
        from llm_client import _chat_content

        truncated = {"choices": [{"message": {"content": '{"partial'}, "finish_reason": "length"}]}
        with MockOpenAIService([{"body": truncated}]) as service:
            content = _chat_content(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                timeout_s=2, max_retries=0, max_tokens=32768),
                [{"role": "user", "content": "u"}],
            )

        self.assertEqual(content, '{"partial')
        self.assertEqual(len(service.requests), 1)   # 到顶不升级,零额外请求

    def test_json_array_triggers_one_repair_request(self) -> None:
        with MockOpenAIService(
            [
                {"body": openai_response([{"decision": "accept", "confidence": 0.9}])},
                {"body": openai_response({"decision": "accept", "confidence": 0.9})},
            ]
        ) as service:
            result = chat_json(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                "system",
                "user",
            )

        self.assertEqual(result["decision"], "accept")
        self.assertEqual(len(service.requests), 2)
        self.assertIn("Only output valid JSON", service.requests[1]["messages"][-1]["content"])

    def test_bad_json_after_repair_raises_response_error(self) -> None:
        with MockOpenAIService(
            [
                {"body": openai_response("not json")},
                {"body": openai_response("still not json")},
            ]
        ) as service:
            with self.assertRaises(LLMResponseError):
                chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                    "system",
                    "user",
                )

    def test_retries_500_before_success(self) -> None:
        with MockOpenAIService(
            [
                {"status": 500, "body": {"error": "try again"}},
                {"body": openai_response({"decision": "accept", "confidence": 0.9})},
            ]
        ) as service:
            sleeps: list[float] = []
            with patch("llm_client.time.sleep", side_effect=lambda value: sleeps.append(value)):
                result = chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=1),
                    "system",
                    "user",
                )

        self.assertEqual(result["decision"], "accept")
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(sleeps, [1.0])

    def test_429_retry_after_controls_sleep_delay(self) -> None:
        with MockOpenAIService(
            [
                {"status": 429, "headers": {"Retry-After": "0"}, "body": {"error": "rate limit"}},
                {"body": openai_response({"decision": "accept", "confidence": 0.9})},
            ]
        ) as service:
            sleeps: list[float] = []
            with patch("llm_client.time.sleep", side_effect=lambda value: sleeps.append(value)):
                result = chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=1),
                    "system",
                    "user",
                )

        self.assertEqual(result["decision"], "accept")
        self.assertEqual(sleeps, [0.0])

    def test_429_storm_survives_beyond_normal_retry_budget(self) -> None:
        """429 独立预算（test7 教训：140 次限流、3 次重试打光 → 10 章整体失败=17% 内容丢）。
        max_retries=0 时连吃 5 个 429 仍坚持到成功——限流不占普通重试预算。"""
        responses = [{"status": 429, "headers": {"Retry-After": "0"}, "body": {"error": "rate limit"}}] * 5
        responses.append({"body": openai_response({"ok": True})})
        with MockOpenAIService(responses) as service:
            sleeps: list[float] = []
            with patch("llm_client.time.sleep", side_effect=lambda value: sleeps.append(value)):
                result = chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                    timeout_s=2, max_retries=0),
                    "system", "user")

        self.assertEqual(result["ok"], True)
        self.assertEqual(len(service.requests), 6)          # 5 次限流 + 1 次成功
        self.assertEqual(len(sleeps), 5)                    # 每次限流都退避（Retry-After=0）

    def test_429_budget_exhaustion_still_raises(self) -> None:
        from llm_client import RATE_LIMIT_MIN_ATTEMPTS

        responses = [{"status": 429, "headers": {"Retry-After": "0"},
                      "body": {"error": "rate limit"}}] * (RATE_LIMIT_MIN_ATTEMPTS + 1)
        with MockOpenAIService(responses) as service:
            with patch("llm_client.time.sleep", side_effect=lambda value: None):
                with self.assertRaisesRegex(LLMConnectionError, "429"):
                    chat_json(
                        LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                        timeout_s=2, max_retries=0),
                        "system", "user")

    def test_401_auth_error_is_connection_error_for_fast_fail(self) -> None:
        with MockOpenAIService([{"status": 401, "body": {"error": "invalid api key"}}]) as service:
            with self.assertRaisesRegex(LLMConnectionError, "invalid api key"):
                chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                    "system",
                    "user",
                )


class AdaptiveRateGateTests(unittest.TestCase):
    """429 自适应闸门（0714 批次一 S2）：全局冷却 + 在飞上限 AIMD。
    真实数据:EN 54321 全量跑并发 4 时 164/781 次 429,各线程独立退避互不通气。"""

    def setUp(self) -> None:
        from llm_client import _reset_rate_gates
        _reset_rate_gates()

    def tearDown(self) -> None:
        from llm_client import _reset_rate_gates
        _reset_rate_gates()

    def test_rate_limit_halves_inflight_and_recovers_additively(self) -> None:
        from llm_client import GATE_RECOVERY_SUCCESSES, _AdaptiveRateGate
        clock = [0.0]
        gate = _AdaptiveRateGate(now_fn=lambda: clock[0])
        gate.acquire()
        gate.acquire()                                   # 模拟 2 在飞
        gate.on_rate_limited(5.0)
        snap = gate.snapshot()
        self.assertEqual(snap["limit"], 1)               # 2//2=1（AIMD 砍半,下限 1）
        self.assertEqual(snap["pause_until"], 5.0)       # 全局冷却期
        gate.release()
        gate.release()
        for _ in range(GATE_RECOVERY_SUCCESSES):
            gate.on_success()
        self.assertEqual(gate.snapshot()["limit"], 2)    # 连续成功加法恢复 +1

    def test_success_without_prior_rate_limit_keeps_uncapped(self) -> None:
        from llm_client import _AdaptiveRateGate
        gate = _AdaptiveRateGate()
        for _ in range(20):
            gate.on_success()
        self.assertIsNone(gate.snapshot()["limit"])      # 未限流不设上限

    def test_pause_blocks_new_acquires_until_cooldown(self) -> None:
        import time as _time

        from llm_client import _AdaptiveRateGate
        gate = _AdaptiveRateGate()
        gate.acquire()
        gate.on_rate_limited(0.15)
        gate.release()
        started = _time.monotonic()
        gate.acquire()                                   # 须等冷却期过
        elapsed = _time.monotonic() - started
        gate.release()
        self.assertGreaterEqual(elapsed, 0.10)

    def test_inflight_limit_blocks_second_acquire(self) -> None:
        import time as _time

        from llm_client import _AdaptiveRateGate
        gate = _AdaptiveRateGate()
        gate.acquire()
        gate.on_rate_limited(0.0)                        # limit=1,无冷却
        acquired: list[int] = []

        def worker() -> None:
            gate.acquire()
            acquired.append(1)
            gate.release()

        th = threading.Thread(target=worker, daemon=True)
        th.start()
        _time.sleep(0.05)
        self.assertEqual(acquired, [])                   # 在飞上限挡住第二个
        gate.release()
        th.join(timeout=2)
        self.assertEqual(acquired, [1])

    def test_429_updates_shared_gate_for_endpoint(self) -> None:
        from llm_client import _gate_for
        with MockOpenAIService([
            {"status": 429, "headers": {"Retry-After": "0"}, "body": {"error": "rate limit"}},
            {"body": openai_response({"ok": True})},
        ]) as service:
            with patch("llm_client.time.sleep", side_effect=lambda value: None):
                result = chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                    timeout_s=2, max_retries=0),
                    "system", "user")
            self.assertTrue(result["ok"])
            snap = _gate_for(service.base_url).snapshot()
        self.assertEqual(snap["limit"], 1)               # 命中 429 后该端点闸门收紧
        self.assertEqual(snap["active"], 0)              # 权柄全部归还(无泄漏)

    def test_adaptive_disabled_by_env(self) -> None:
        import llm_client
        with MockOpenAIService([
            {"status": 429, "headers": {"Retry-After": "0"}, "body": {"error": "rate limit"}},
            {"body": openai_response({"ok": True})},
        ]) as service:
            with patch.dict(os.environ, {"RATOMIZER_LLM_ADAPTIVE": "0"}):
                with patch("llm_client.time.sleep", side_effect=lambda value: None):
                    result = chat_json(
                        LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="",
                                        timeout_s=2, max_retries=0),
                        "system", "user")
        self.assertTrue(result["ok"])
        with llm_client._GATES_LOCK:
            self.assertEqual(llm_client._GATES, {})      # 关闭时不创建闸门(行为=旧退避)


if __name__ == "__main__":
    unittest.main()
