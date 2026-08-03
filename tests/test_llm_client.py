from __future__ import annotations

import json
import os
import io
import threading
import time
import urllib.error
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

from llm_client import (
    LLMBudgetExceeded,
    LLMClientConfig,
    LLMConnectionError,
    LLMRequestBudget,
    LLMResponseError,
    _read_error_body,
    mark_budget_checkpoint_durable,
    chat_json,
    _post_json,
)


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
    def test_restore_settled_checkpoint_preserves_cumulative_budget(self) -> None:
        budget = LLMRequestBudget(max_calls=2, max_tokens=100_000)
        reservation = budget.reserve({"messages": [], "max_tokens": 32})
        budget.commit(reservation, {"total_tokens": 25})

        restored = LLMRequestBudget.from_settled_snapshot(budget.snapshot())
        before = restored.snapshot()
        self.assertEqual(before["attempted_calls"], 1)
        self.assertEqual(before["tokens"], 25)
        reservation = restored.reserve({"messages": [], "max_tokens": 32})
        restored.commit(reservation, {"total_tokens": 30})
        after = restored.snapshot()
        self.assertEqual(after["attempted_calls"], 2)
        self.assertEqual(after["tokens"], 55)
        with self.assertRaises(LLMBudgetExceeded):
            restored.reserve({"messages": [], "max_tokens": 32})

    def test_restore_rejects_an_unsettled_reservation(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        budget.reserve({"messages": [], "max_tokens": 32})
        with self.assertRaisesRegex(ValueError, "unsettled"):
            LLMRequestBudget.from_settled_snapshot(budget.snapshot())

    def test_request_budget_checkpoint_failure_blocks_network_and_rolls_back_reserve(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)

        def checkpoint(snapshot: dict) -> None:
            if snapshot["attempted_calls"]:
                raise RuntimeError("checkpoint unavailable")

        budget.set_checkpoint(checkpoint)
        with MockOpenAIService([]) as service:
            with self.assertRaisesRegex(RuntimeError, "checkpoint unavailable"):
                chat_json(
                    LLMClientConfig(
                        base_url=service.base_url,
                        model="mock-model",
                        api_key_env="",
                        timeout_s=2,
                        max_retries=0,
                    ),
                    "system",
                    "user",
                    _request_budget=budget,
                )

        self.assertEqual(service.requests, [])
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["attempted_calls"], 0)
        self.assertEqual(snapshot["reserved_tokens"], 0)

    def test_durable_checkpoint_failure_retains_reserved_budget(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)

        def checkpoint(snapshot: dict) -> None:
            if snapshot["attempted_calls"]:
                error = OSError("second sink unavailable")
                mark_budget_checkpoint_durable(error)
                raise error

        budget.set_checkpoint(checkpoint)
        with self.assertRaisesRegex(OSError, "second sink unavailable"):
            budget.reserve({"messages": [], "max_tokens": 32})

        snapshot = budget.snapshot()
        self.assertEqual(snapshot["attempted_calls"], 1)
        self.assertGreater(snapshot["reserved_tokens"], 0)
        with self.assertRaises(LLMBudgetExceeded):
            budget.reserve({"messages": [], "max_tokens": 32})

    def test_post_response_checkpoint_failure_never_retries_paid_request(self) -> None:
        budget = LLMRequestBudget(max_calls=2, max_tokens=100_000)
        failed_once = False

        def checkpoint(snapshot: dict) -> None:
            nonlocal failed_once
            if (
                not failed_once
                and snapshot["attempted_calls"] == 1
                and snapshot["reserved_tokens"] == 0
                and snapshot["tokens"] == 7
            ):
                failed_once = True
                raise OSError("settled checkpoint unavailable")

        budget.set_checkpoint(checkpoint)
        responses = [
            {"body": {**openai_response({}), "usage": {"total_tokens": 7}}},
            {"body": {**openai_response({}), "usage": {"total_tokens": 7}}},
        ]
        with MockOpenAIService(responses) as service:
            stats: dict[str, int] = {}
            with self.assertRaisesRegex(OSError, "settled checkpoint unavailable"):
                _post_json(
                    LLMClientConfig(
                        base_url=service.base_url,
                        model="mock-model",
                        api_key_env="",
                        timeout_s=2,
                        max_retries=1,
                    ),
                    {"model": "mock-model", "messages": [], "max_tokens": 32},
                    _request_budget=budget,
                    _request_stats=stats,
                )

        self.assertEqual(len(service.requests), 1)
        self.assertEqual(stats, {"call_count": 1})
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["attempted_calls"], 1)
        self.assertEqual(snapshot["failed_calls"], 0)
        self.assertEqual(snapshot["tokens"], 7)
        self.assertEqual(snapshot["reserved_tokens"], 0)

    def test_checkpoint_owner_swap_blocks_reserve_until_new_owner_is_durable(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        old_snapshots: list[int] = []
        new_snapshots: list[int] = []
        replacement_entered = threading.Event()
        release_replacement = threading.Event()
        reserve_finished = threading.Event()

        def old_owner(snapshot: dict) -> None:
            old_snapshots.append(int(snapshot["attempted_calls"]))

        def new_owner(snapshot: dict) -> None:
            calls = int(snapshot["attempted_calls"])
            new_snapshots.append(calls)
            if calls == 0:
                replacement_entered.set()
                self.assertTrue(release_replacement.wait(timeout=2))

        budget.set_checkpoint(old_owner)
        swap_thread = threading.Thread(
            target=lambda: budget.swap_checkpoint(old_owner, new_owner)
        )
        swap_thread.start()
        self.assertTrue(replacement_entered.wait(timeout=2))

        reservation_ids: list[int] = []

        def reserve() -> None:
            reservation_ids.append(
                budget.reserve({"messages": [], "max_tokens": 1})
            )
            reserve_finished.set()

        reserve_thread = threading.Thread(target=reserve)
        reserve_thread.start()
        self.assertFalse(reserve_finished.wait(timeout=0.05))
        release_replacement.set()
        swap_thread.join(timeout=2)
        reserve_thread.join(timeout=2)

        self.assertFalse(swap_thread.is_alive())
        self.assertFalse(reserve_thread.is_alive())
        self.assertEqual(old_snapshots, [0])
        self.assertEqual(new_snapshots[:2], [0, 1])
        self.assertIs(budget.checkpoint(), new_owner)
        budget.commit(reservation_ids[0], {"total_tokens": 1})

    def test_request_budget_checkpoint_tracks_reserve_and_commit(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        checkpoints: list[dict] = []
        budget.set_checkpoint(lambda snapshot: checkpoints.append(dict(snapshot)))

        reservation = budget.reserve({"messages": [], "max_tokens": 1})
        budget.commit(reservation, {"total_tokens": 7})

        self.assertEqual(checkpoints[0]["attempted_calls"], 0)
        self.assertEqual(checkpoints[1]["attempted_calls"], 1)
        self.assertGreater(checkpoints[1]["reserved_tokens"], 0)
        self.assertEqual(checkpoints[2]["reserved_tokens"], 0)
        self.assertEqual(checkpoints[2]["tokens"], 7)

    def test_request_budget_serializes_concurrent_checkpoint_snapshots(self) -> None:
        budget = LLMRequestBudget(max_calls=2, max_tokens=100_000)
        checkpoints: list[int] = []
        first_entered = threading.Event()
        release_first = threading.Event()

        def checkpoint(snapshot: dict) -> None:
            calls = int(snapshot["attempted_calls"])
            if calls == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(timeout=2))
            checkpoints.append(calls)

        budget.set_checkpoint(checkpoint)
        reservations: list[int] = []

        def reserve() -> None:
            reservations.append(
                budget.reserve({"messages": [], "max_tokens": 1})
            )

        first = threading.Thread(target=reserve)
        second = threading.Thread(target=reserve)
        first.start()
        self.assertTrue(first_entered.wait(timeout=2))
        second.start()
        time.sleep(0.05)
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(checkpoints[:3], [0, 1, 2])
        self.assertEqual(len(reservations), 2)
        for reservation in reservations:
            budget.commit(reservation, {"total_tokens": 1})

    def test_request_budget_checkpoint_does_not_hold_state_lock(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        publication_lock = threading.Lock()
        checkpoint_started = threading.Event()
        snapshot_finished = threading.Event()
        errors: list[BaseException] = []

        def checkpoint(snapshot: dict) -> None:
            if snapshot["attempted_calls"]:
                checkpoint_started.set()
                with publication_lock:
                    pass

        budget.set_checkpoint(checkpoint)
        publication_lock.acquire()

        def reserve() -> None:
            try:
                budget.reserve({"messages": [], "max_tokens": 1})
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def take_snapshot() -> None:
            try:
                budget.snapshot()
                snapshot_finished.set()
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        reserve_thread = threading.Thread(target=reserve)
        snapshot_thread = threading.Thread(target=take_snapshot)
        reserve_thread.start()
        self.assertTrue(checkpoint_started.wait(timeout=2))
        snapshot_thread.start()
        try:
            self.assertTrue(
                snapshot_finished.wait(timeout=2),
                "checkpoint callback retained the budget state lock",
            )
        finally:
            publication_lock.release()
        reserve_thread.join(timeout=2)
        snapshot_thread.join(timeout=2)

        self.assertFalse(reserve_thread.is_alive())
        self.assertFalse(snapshot_thread.is_alive())
        self.assertEqual(errors, [])

    def test_request_budget_blocks_json_repair_before_second_http_call(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        with MockOpenAIService([
            {"body": {**openai_response("not json"), "usage": {"total_tokens": 10}}},
        ]) as service:
            with self.assertRaises(LLMBudgetExceeded):
                chat_json(
                    LLMClientConfig(
                        base_url=service.base_url,
                        model="mock-model",
                        api_key_env="",
                        timeout_s=2,
                        max_retries=0,
                    ),
                    "system",
                    "user",
                    _request_budget=budget,
                )

        self.assertEqual(len(service.requests), 1)
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["attempted_calls"], 1)
        self.assertEqual(snapshot["tokens"], 10)
        self.assertTrue(snapshot["denied"])
        self.assertEqual(snapshot["termination_reason"], "call_budget_exhausted")

    def test_request_budget_blocks_oversized_request_before_network(self) -> None:
        budget = LLMRequestBudget(max_calls=2, max_tokens=10)
        with MockOpenAIService([]) as service:
            with self.assertRaises(LLMBudgetExceeded):
                chat_json(
                    LLMClientConfig(
                        base_url=service.base_url,
                        model="mock-model",
                        api_key_env="",
                        timeout_s=2,
                        max_retries=0,
                        max_tokens=100,
                    ),
                    "system",
                    "user",
                    _request_budget=budget,
                )

        self.assertEqual(service.requests, [])
        self.assertEqual(budget.snapshot()["termination_reason"], "token_budget_exhausted")

    def test_request_budget_settles_to_reported_usage(self) -> None:
        budget = LLMRequestBudget(max_calls=2, max_tokens=100_000)
        response = {
            **openai_response({"ok": True}),
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }
        with MockOpenAIService([{"body": response}]) as service:
            result = chat_json(
                LLMClientConfig(
                    base_url=service.base_url,
                    model="mock-model",
                    api_key_env="",
                    timeout_s=2,
                    max_retries=0,
                ),
                "system",
                "user",
                _request_budget=budget,
            )

        self.assertEqual(result, {"ok": True})
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["attempted_calls"], 1)
        self.assertEqual(snapshot["tokens"], 10)
        self.assertTrue(snapshot["usage_complete"])

    def test_request_budget_charges_conservative_reservation_when_usage_missing(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        with MockOpenAIService([{"body": openai_response({"ok": True})}]) as service:
            result = chat_json(
                LLMClientConfig(
                    base_url=service.base_url,
                    model="mock-model",
                    api_key_env="",
                    timeout_s=2,
                    max_retries=0,
                    max_tokens=100,
                ),
                "system",
                "user",
                _request_budget=budget,
            )
        self.assertTrue(result["ok"])
        snapshot = budget.snapshot()
        self.assertGreater(snapshot["tokens"], 100)
        self.assertFalse(snapshot["usage_complete"])

    def test_request_budget_rejects_zero_bool_negative_and_conflicting_usage(self) -> None:
        invalid_usage = (
            {"total_tokens": 0},
            {"total_tokens": True},
            {"total_tokens": -7},
            {"prompt_tokens": 7, "total_tokens": 5},
            {"completion_tokens": 7, "total_tokens": 5},
            {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 1},
        )
        for usage in invalid_usage:
            with self.subTest(usage=usage):
                budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, usage)
                snapshot = budget.snapshot()
                self.assertGreater(snapshot["tokens"], 0)
                self.assertFalse(snapshot["usage_complete"])

    def test_request_budget_reservation_uses_the_actual_http_serialization(self) -> None:
        payload = {"messages": [{"content": "辅助输出"}], "max_tokens": 10}
        expected = len(json.dumps(payload).encode("utf-8")) + 10 + 256
        self.assertEqual(LLMRequestBudget._token_ceiling(payload), expected)

    def test_request_budget_serializes_concurrent_reservations(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        barrier = threading.Barrier(3)
        reservations: list[int] = []
        failures: list[Exception] = []

        def reserve() -> None:
            barrier.wait()
            try:
                reservations.append(budget.reserve({"messages": [], "max_tokens": 1}))
            except Exception as exc:
                failures.append(exc)

        workers = [threading.Thread(target=reserve) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(timeout=2)

        self.assertEqual(len(reservations), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], LLMBudgetExceeded)
        budget.commit(reservations[0], {"total_tokens": 1})
        self.assertEqual(budget.snapshot()["attempted_calls"], 1)

    def test_request_budget_blocks_rate_limit_retry_before_second_http_attempt(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100_000)
        with MockOpenAIService([
            {"status": 429, "headers": {"Retry-After": "0"},
             "body": {"error": "rate limit"}},
        ]) as service, patch("llm_client.time.sleep", return_value=None):
            with self.assertRaises(LLMBudgetExceeded):
                chat_json(
                    LLMClientConfig(
                        base_url=service.base_url,
                        model="mock-model",
                        api_key_env="",
                        timeout_s=2,
                        max_retries=0,
                    ),
                    "system",
                    "user",
                    _request_budget=budget,
                )
        self.assertEqual(len(service.requests), 1)
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["attempted_calls"], 1)
        self.assertEqual(snapshot["failed_calls"], 1)
        self.assertFalse(snapshot["usage_complete"])

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

    def test_chat_json_with_meta_aggregates_usage_across_calls(self) -> None:
        """usage 汇聚覆盖首发+修复重发（Phase 1.5 tokens 口径：全部决策底层调用）。"""
        from llm_client import chat_json_with_meta

        bad = {"choices": [{"message": {"content": "not json"}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
        good = {"choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 14, "completion_tokens": 3, "total_tokens": 17}}
        with MockOpenAIService([{"body": bad}, {"body": good}]) as service:
            data, meta = chat_json_with_meta(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                "system",
                "user",
            )

        self.assertEqual(data, {"ok": True})
        self.assertEqual(len(service.requests), 2)
        self.assertEqual(meta["usage"], {"prompt_tokens": 24, "completion_tokens": 5, "total_tokens": 29})
        self.assertTrue(meta["usage_complete"])
        self.assertEqual(meta["call_count"], 2)
        self.assertEqual(meta["failed_call_count"], 0)

    def test_chat_json_with_meta_marks_missing_usage_as_partial(self) -> None:
        """端点不返回 usage → 计 0 且 usage_complete=False（不得估算冒充精确值）。"""
        from llm_client import chat_json_with_meta

        body = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        with MockOpenAIService([{"body": body}]) as service:
            _data, meta = chat_json_with_meta(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                "system",
                "user",
            )

        self.assertEqual(meta["usage"]["total_tokens"], 0)
        self.assertFalse(meta["usage_complete"])

    def test_aggregate_usage_normalizes_each_round_before_summing(self) -> None:
        """审计 H4：逐轮归一——{total:100}+{prompt:15,completion:10} = 125；
        旧"全或无"兜底会把明细轮丢弃只报 100。"""
        from llm_client import _aggregate_usage

        meta = _aggregate_usage([
            {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100},
            {"prompt_tokens": 15, "completion_tokens": 10},
        ])

        self.assertEqual(meta["usage"]["total_tokens"], 125)
        self.assertEqual(meta["usage"]["prompt_tokens"], 105)
        self.assertEqual(meta["usage"]["completion_tokens"], 20)
        self.assertTrue(meta["usage_complete"])

    def test_aggregate_usage_detail_round_before_total_round(self) -> None:
        """审计 H4 反向混合：{prompt:70,completion:30}+{total:25} = 125（旧兜底报 25）。"""
        from llm_client import _aggregate_usage

        meta = _aggregate_usage([
            {"prompt_tokens": 70, "completion_tokens": 30},
            {"total_tokens": 25},
        ])

        self.assertEqual(meta["usage"]["total_tokens"], 125)
        self.assertTrue(meta["usage_complete"])   # 一轮双明细、一轮 total——两轮均可计量

    def test_aggregate_usage_rejects_nonpositive_bool_and_conflicting_counts(self) -> None:
        from llm_client import _aggregate_usage

        for usage in (
            {"total_tokens": 0},
            {"total_tokens": True},
            {"total_tokens": -7},
            {"prompt_tokens": 7, "total_tokens": 5},
            {"completion_tokens": 7, "total_tokens": 5},
            {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 1},
        ):
            with self.subTest(usage=usage):
                meta = _aggregate_usage([usage])
                self.assertEqual(meta["usage"]["total_tokens"], 0)
                self.assertFalse(meta["usage_complete"])

    def test_chat_json_with_meta_normalizes_mixed_usage_per_round(self) -> None:
        """审计 H4 共用路径：首发带 total、修复轮只带双明细 → total 逐轮归一为 125。"""
        from llm_client import chat_json_with_meta

        bad = {"choices": [{"message": {"content": "not json"}}],
               "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
        good = {"choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 10}}
        with MockOpenAIService([{"body": bad}, {"body": good}]) as service:
            data, meta = chat_json_with_meta(
                LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                "system",
                "user",
            )

        self.assertEqual(data, {"ok": True})
        self.assertEqual(meta["usage"]["total_tokens"], 125)
        self.assertTrue(meta["usage_complete"])

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

    def test_chat_json_with_meta_counts_each_provider_retry_attempt(self) -> None:
        from llm_client import chat_json_with_meta

        with MockOpenAIService([
            {"status": 500, "body": {"error": "try again"}},
            {"body": {**openai_response({"ok": True}), "usage": {"total_tokens": 7}}},
        ]) as service, patch("llm_client.time.sleep", return_value=None):
            data, meta = chat_json_with_meta(
                LLMClientConfig(
                    base_url=service.base_url,
                    model="mock-model",
                    api_key_env="",
                    timeout_s=2,
                    max_retries=1,
                ),
                "system",
                "user",
            )
        self.assertTrue(data["ok"])
        self.assertEqual(meta["call_count"], 2)
        self.assertEqual(meta["failed_call_count"], 1)
        self.assertFalse(meta["usage_complete"])

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


class AttemptPolicyVersionDeclarationTests(unittest.TestCase):
    """S9（review-2026-08-03）：request_succeeded 分支（2xx 后本地 checkpoint/trace
    失败不再重发 HTTP）直接改变 provider attempt 次数，属于 attempt policy 行为面，
    版本常量必须随之 bump 并带显式声明——防止 lineage 自述与实际策略漂移。"""

    def test_policy_version_bumped_for_post_2xx_no_retry(self) -> None:
        import llm_client

        self.assertEqual(llm_client.LLM_ATTEMPT_POLICY_VERSION, "llm-attempt-policy-v2")
        policy = llm_client.llm_attempt_policy()
        self.assertEqual(policy["version"], "llm-attempt-policy-v2")

    def test_version_constant_carries_declaration_comment(self) -> None:
        from pathlib import Path

        source = Path("llm_client.py").read_text(encoding="utf-8")
        marker = "LLM_ATTEMPT_POLICY_VERSION = "
        index = source.index(marker)
        declaration_window = source[max(0, index - 800): index]
        self.assertIn("2xx", declaration_window)
        self.assertIn("request_succeeded", declaration_window)


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
