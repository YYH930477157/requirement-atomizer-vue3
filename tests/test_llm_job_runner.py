"""M8（§18）LLMJobRunner：统一调用机械的离线测试。

矩阵（全部离线：本地 mock OpenAI 服务 / 注入 chat，禁止真实 LLM）：
① 成功路径：缓存 miss→命中、attempt ledger 行携带 stage/processor/unit_id 与
   usage/duration/cache/model；call_context 同步进 llm_trace；
② 缓存二跑零 provider 调用（outcome=cache_hit，服务调用数不变）；
③ 连接失败：failed + retry_kind=connection + 不写缓存 + ledger error 在案；
④ 预算透传：request_budget 记账钩被真实调用；
⑤ batch：并发 + 汇总 ok/failed/cached/tokens + partial 语义。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any
from pathlib import Path

tests_dir = str(Path(__file__).resolve().parent)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

from test_llm_client import MockOpenAIService, openai_response  # noqa: E402

from llm_client import LLMClientConfig, LLMRequestBudget  # noqa: E402
from llm_job_runner import (  # noqa: E402
    LLM_JOB_ATTEMPTS_FILENAME,
    LLM_JOB_ATTEMPT_SCHEMA,
    LLM_JOB_RUNNER_VERSION,
    EXECUTION_FAILED,
    EXECUTION_OK,
    EXECUTION_PARTIAL,
    LLMJob,
    LLMJobRunner,
)
from paid_cache_store import PaidCacheStore  # noqa: E402


def _config(base_url: str) -> LLMClientConfig:
    return LLMClientConfig(base_url=base_url, model="mock-model",
                           api_key_env="RATOMIZER_TEST_KEY",
                           timeout_s=2, max_retries=0)


def _job(**overrides) -> LLMJob:
    fields = dict(stage="functional-extract", processor="clause_family",
                  unit_id="UNIT-X", system_prompt="sys", user_prompt="usr",
                  route="openai_compatible")
    fields.update(overrides)
    return LLMJob(**fields)


class LLMJobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["RATOMIZER_TEST_KEY"] = "secret"
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self) -> None:
        os.environ.pop("RATOMIZER_TEST_KEY", None)

    def _read_attempts(self) -> list[dict]:
        path = self.root / LLM_JOB_ATTEMPTS_FILENAME
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_success_writes_ledger_with_attribution_and_cache(self) -> None:
        cache = PaidCacheStore(self.root, "llm_jobs.jsonl")
        with MockOpenAIService([{"body": openai_response({"answer": 1})}]) as service:
            runner = LLMJobRunner(self.root, route_config=_config(service.base_url),
                                  cache=cache)
            result = runner.run(_job())
        self.assertTrue(result.ok)
        self.assertEqual(result.execution_status, EXECUTION_OK)
        self.assertEqual(result.data["answer"], 1)
        self.assertEqual(result.model, "mock-model")
        self.assertGreaterEqual(result.usage.get("total_tokens", 0), 0)
        rows = self._read_attempts()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["schema"], LLM_JOB_ATTEMPT_SCHEMA)
        self.assertEqual(row["runner_version"], LLM_JOB_RUNNER_VERSION)
        self.assertEqual(row["stage"], "functional-extract")
        self.assertEqual(row["processor"], "clause_family")
        self.assertEqual(row["unit_id"], "UNIT-X")
        self.assertEqual(row["outcome"], "initial")
        self.assertEqual(row["retry_kind"], "none")
        self.assertEqual(row["cache"], "write")
        self.assertEqual(row["execution_status"], EXECUTION_OK)

    def test_second_run_hits_cache_with_zero_provider_calls(self) -> None:
        cache = PaidCacheStore(self.root, "llm_jobs.jsonl")
        with MockOpenAIService([
            {"body": openai_response({"answer": 1})},
            {"body": openai_response({"answer": "should-not-be-called"})},
        ]) as service:
            runner = LLMJobRunner(self.root, route_config=_config(service.base_url),
                                  cache=cache)
            first = runner.run(_job())
            second = runner.run(_job(), salt="2")
        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertTrue(second.from_cache)
        self.assertEqual(second.data["answer"], 1)
        self.assertEqual(second.call_count, 0)
        self.assertEqual(second.usage.get("total_tokens", 0), 0)
        rows = self._read_attempts()
        self.assertEqual(rows[-1]["outcome"], "cache_hit")
        self.assertEqual(rows[-1]["cache"], "hit")

    def test_connection_failure_is_failed_retriable_and_never_cached(self) -> None:
        cache = PaidCacheStore(self.root, "llm_jobs.jsonl")
        runner = LLMJobRunner(
            self.root, route_config=_config("http://127.0.0.1:9/v1"),
            cache=cache)
        result = runner.run(_job())
        self.assertFalse(result.ok)
        self.assertEqual(result.execution_status, EXECUTION_FAILED)
        self.assertIn("LLMConnectionError", result.error)
        rows = self._read_attempts()
        self.assertEqual(rows[-1]["outcome"], "error")
        self.assertEqual(rows[-1]["retry_kind"], "connection")
        self.assertFalse((self.root / "llm_jobs.jsonl").exists())

    def test_request_budget_hook_is_used(self) -> None:
        seen: list[Any] = []

        def chat(config, system, user, *, request_budget=None):
            seen.append(request_budget)
            return {"answer": 1}, {"usage": {"total_tokens": 5}, "call_count": 1}

        runner = LLMJobRunner(self.root, route_config=_config("http://x.invalid/v1"),
                              request_budget="BUDGET-MARKER", chat_with_meta=chat)
        result = runner.run(_job())
        self.assertTrue(result.ok)
        self.assertEqual(seen, ["BUDGET-MARKER"])

    def test_batch_summary_and_partial_semantics(self) -> None:
        def chat_factory(fail_on: str):
            def chat(config, system, user, *, request_budget=None):
                if user == fail_on:
                    from llm_client import LLMConnectionError
                    raise LLMConnectionError("boom")
                return {"ok": True}, {"usage": {"total_tokens": 3}, "call_count": 1}
            return chat

        runner = LLMJobRunner(self.root, route_config=_config("http://x.invalid/v1"),
                              chat_with_meta=chat_factory("usr-b"))
        batch = runner.run_many([_job(), _job(user_prompt="usr-b"), _job(unit_id="U2")],
                                concurrency=2)
        self.assertEqual(batch["total"], 3)
        self.assertEqual(batch["ok"], 2)
        self.assertEqual(batch["failed"], 1)
        self.assertEqual(batch["execution_status"], EXECUTION_PARTIAL)
        self.assertEqual(batch["total_tokens"], 6)
        # ledger 三行，失败行 retry_kind=connection
        rows = self._read_attempts()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(1 for r in rows if r["retry_kind"] == "connection"), 1)

    def test_attempt_id_stable_for_same_fingerprint_and_salt(self) -> None:
        cache = PaidCacheStore(self.root, "llm_jobs.jsonl")

        def chat(config, system, user, *, request_budget=None):
            return {"answer": 1}, {"usage": {}, "call_count": 1}

        runner = LLMJobRunner(self.root, route_config=_config("http://x.invalid/v1"),
                              cache=cache, chat_with_meta=chat)
        first = runner.run(_job())
        again = runner.run(_job())          # 缓存命中路径也带同一 attempt 基（salt 同）
        self.assertEqual(first.attempt_id, again.attempt_id)
        other = runner.run(_job(user_prompt="different"))
        self.assertNotEqual(first.attempt_id, other.attempt_id)

    def test_trace_carries_job_context(self) -> None:
        import llm_client

        trace = self.root / "llm_trace.jsonl"
        llm_client.set_trace_path(trace)
        try:
            with MockOpenAIService([{"body": openai_response({"answer": 1})}]) as service:
                runner = LLMJobRunner(self.root,
                                      route_config=_config(service.base_url))
                runner.run(_job())
        finally:
            llm_client.set_trace_path(None)
        rows = [json.loads(line) for line in
                trace.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["context"]["stage"], "functional-extract")
        self.assertEqual(rows[0]["context"]["unit_id"], "UNIT-X")


if __name__ == "__main__":
    unittest.main()
