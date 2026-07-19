from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import review_state
from api_server import RequirementAPIHandler, TOKEN_HEADER


class AtomicReviewStateWriteTests(unittest.TestCase):
    def test_atomic_write_retries_permission_error_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_states.jsonl"
            path.write_text('{"old": true}\n', encoding="utf-8")
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source: Path, target: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("target is being read")
                real_replace(source, target)

            with patch("review_state.os.replace", side_effect=flaky_replace), \
                    patch("review_state.time.sleep") as sleep:
                review_state._atomic_write_jsonl(path, [{"requirement_id": "SREQ-1"}])

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows, [{"requirement_id": "SREQ-1"}])
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(list(path.parent.glob(f"{path.name}.*.tmp")), [])

    def test_atomic_write_exhausts_retry_budget_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_states.jsonl"
            original = '{"old": true}\n'
            path.write_text(original, encoding="utf-8")

            with patch("review_state.os.replace", side_effect=PermissionError("still locked")) as replace, \
                    patch("review_state.time.sleep") as sleep:
                with self.assertRaisesRegex(PermissionError, "still locked"):
                    review_state._atomic_write_jsonl(path, [{"requirement_id": "SREQ-1"}])

            self.assertEqual(replace.call_count, review_state._REPLACE_ATTEMPTS)
            self.assertEqual(sleep.call_count, review_state._REPLACE_ATTEMPTS - 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(path.parent.glob(f"{path.name}.*.tmp")), [])

    def test_event_projection_failure_does_not_misreport_saved_state_as_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("review_state._append_review_state_event",
                       side_effect=OSError("event log temporarily unavailable")):
                result = review_state.apply_expert_decision(
                    out_dir, "SREQ-1", "accepted", actor="expert", reason="approved")

            states = review_state._read_jsonl(out_dir / "review_states.jsonl")
            self.assertEqual(states[0]["status"], "accepted")
            self.assertEqual(states[0]["history"][0]["reason"], "approved")
            self.assertIn("audit_warning", result)
            self.assertFalse((out_dir / "review_state_events.jsonl").exists())


class ReviewActionErrorResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        out_dir = Path(self.temp_dir.name).resolve()

        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir
        TestHandler.allowed_origins = {"null"}
        TestHandler.local_token = "test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def post_review_action(self) -> tuple[int, dict]:
        body = json.dumps({"requirement_id": "SREQ-1", "status": "accepted"}).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(
                "POST",
                "/review-actions",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    TOKEN_HEADER: "test-token",
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            connection.close()

    def test_timeout_and_file_errors_return_retryable_503_json(self) -> None:
        errors = [
            TimeoutError("review state lock timed out"),
            PermissionError("review state file is busy"),
            OSError("review state storage failed"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    patch("api_server.apply_review_action", side_effect=error):
                status, payload = self.post_review_action()

            self.assertEqual(status, 503)
            self.assertEqual(payload, {"error": str(error), "retryable": True})

    def test_value_error_remains_conflict_response(self) -> None:
        with patch("api_server.apply_review_action", side_effect=ValueError("invalid transition")):
            status, payload = self.post_review_action()

        self.assertEqual(status, 409)
        self.assertEqual(payload, {"error": "invalid transition"})


class CorruptReadPathGetTests(unittest.TestCase):
    """抽取轮询路径上的 GET 端点：坏 JSONL 必须返回 503 envelope，不能裸崩断连。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        out_dir = Path(self.temp_dir.name).resolve()
        (out_dir / "blocks.jsonl").write_text('{"broken": \n', encoding="utf-8")
        # 有效 partial（指纹绑定到这份坏文件）才能把读路径推进到 blocks.jsonl 解析
        from ai_extract import AI_PARTIAL_SCHEMA, AI_REQUIREMENTS_PARTIAL, extraction_input_fingerprint
        (out_dir / AI_REQUIREMENTS_PARTIAL).write_text(json.dumps({
            "schema": AI_PARTIAL_SCHEMA,
            "run_id": "run-1",
            "completed": 1,
            "total": 1,
            "complete": False,
            "failed": False,
            "input_fingerprint": extraction_input_fingerprint(out_dir),
            "rows": [{"ai_req_id": "AIR-1", "title": "t", "source_block_ids": ["B1"]}],
        }), encoding="utf-8")

        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir
        TestHandler.allowed_origins = {"null"}
        TestHandler.local_token = "test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def get_json(self, path: str) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("GET", path, headers={TOKEN_HEADER: "test-token"})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            connection.close()

    def test_corrupt_blocks_jsonl_returns_retryable_503_envelope(self) -> None:
        for path in ("/omission-actions", "/ai-extraction-status", "/document/pdf"):
            with self.subTest(path=path):
                status, payload = self.get_json(path)
                self.assertEqual(status, 503)
                self.assertTrue(payload["retryable"])
                self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
