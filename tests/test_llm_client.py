from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

from llm_client import LLMClientConfig, LLMConnectionError, LLMResponseError, chat_json


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

    def test_401_auth_error_is_connection_error_for_fast_fail(self) -> None:
        with MockOpenAIService([{"status": 401, "body": {"error": "invalid api key"}}]) as service:
            with self.assertRaisesRegex(LLMConnectionError, "invalid api key"):
                chat_json(
                    LLMClientConfig(base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0),
                    "system",
                    "user",
                )


if __name__ == "__main__":
    unittest.main()
