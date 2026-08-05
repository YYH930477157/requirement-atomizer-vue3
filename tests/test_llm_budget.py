"""WS3 统一预算单 + 三级路由 + 成本看板 + llm_client 钩子挂载点 测试。

覆盖简报四项验收门禁（全部用本地 mock HTTP，禁止真实 LLM 调用）：
* 注入式耗尽演练：超限调用被事前拦截 + provenance stub + NEEDS WORK
* 80% 预警与余量拦截均触发
* 增量重跑见 test_incremental_rerun.py
* 三级路由门禁：结构假设环节不出现大模型调用
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any

import llm_client
from llm_client import LLMBudgetExceeded, LLMClientConfig, chat_json

import llm_budget
from llm_budget import (
    DEFAULT_STAGE_ROUTES,
    LLM_BUDGET_SCHEMA,
    LLM_BUDGET_VERSION,
    ROUTE_LARGE,
    ROUTE_SMALL,
    STAGE_DEFAULT,
    STAGE_DRILLDOWN,
    STAGE_FUNCTIONAL_EXTRACT,
    STAGE_STRUCTURE_HYPOTHESIS,
    StageRouteViolation,
    LLMBudgetLedger,
    cost_report,
    validate_stage_routes,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - jsonschema 是运行依赖
    jsonschema = None


# 内联最小本地 mock HTTP 服务（与 test_llm_client.MockOpenAIService 同构），避免跨测试文件
# import 依赖（显式 ``python -m unittest tests.test_llm_budget`` 运行时 tests/ 不在 sys.path）。
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockOpenAIService:
    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                service.requests.append(body)
                response = service.responses.pop(0)
                payload = response.get("body", {})
                body_bytes = json.dumps(payload).encode("utf-8")
                self.send_response(int(response.get("status", 200)))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = __import__("threading").Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> "MockOpenAIService":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "llm_budget.schema.json"


def _ok_response(total_tokens: int = 10) -> dict[str, Any]:
    """合法 JSON content + 可信 usage（prompt+completion == total）的 mock 响应。"""
    return {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {
            "total_tokens": total_tokens,
            "prompt_tokens": total_tokens - 2,
            "completion_tokens": 2,
        },
    }


def _payload(max_tokens: int = 100) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": "hello world"}], "max_tokens": max_tokens}


class _BudgetTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        # 全局钩子必须在每个测试后清零，杜绝跨测试串扰。
        llm_client.clear_document_budget_hook()


class LLMBudgetConstructionTests(_BudgetTestCase):
    def test_for_document_estimates_caps_from_clause_count(self) -> None:
        ledger = LLMBudgetLedger.for_document("doc-1", clause_count=10)
        # 功能抽取按条款候选数 × 1.2 估算（方案 §5.1 第 13 周口径）。
        self.assertEqual(ledger.sub_budgets[STAGE_FUNCTIONAL_EXTRACT]["max_calls"], 12)
        self.assertGreater(ledger.sub_budgets[STAGE_FUNCTIONAL_EXTRACT]["max_tokens"], 0)
        # 默认路由表齐全。
        self.assertEqual(ledger.stage_routes[STAGE_DRILLDOWN], ROUTE_LARGE)

    def test_for_document_without_clause_count_uses_fixed_defaults(self) -> None:
        ledger = LLMBudgetLedger.for_document("doc-2")
        self.assertEqual(
            ledger.sub_budgets[STAGE_STRUCTURE_HYPOTHESIS]["max_calls"],
            llm_budget.DEFAULT_SUB_BUDGETS[STAGE_STRUCTURE_HYPOTHESIS]["max_calls"],
        )

    def test_sub_budget_and_route_overrides(self) -> None:
        ledger = LLMBudgetLedger.for_document(
            "doc-3",
            sub_budget_overrides={STAGE_DEFAULT: {"max_calls": 5}},
            stage_route_overrides={STAGE_DRILLDOWN: ROUTE_SMALL},
        )
        self.assertEqual(ledger.sub_budgets[STAGE_DEFAULT]["max_calls"], 5)
        self.assertEqual(ledger.stage_routes[STAGE_DRILLDOWN], ROUTE_SMALL)

    def test_empty_document_id_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LLMBudgetLedger("", {"default": {"max_calls": 1, "max_tokens": 100}})


class BudgetInterceptTests(_BudgetTestCase):
    def test_intercept_consumes_call_and_settle_charges_real_usage(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.settle({"total_tokens": 42, "prompt_tokens": 40, "completion_tokens": 2})
        snap = ledger.snapshot()
        self.assertEqual(snap["consumed"]["default"]["calls"], 1)
        self.assertEqual(snap["consumed"]["default"]["tokens"], 42)
        self.assertEqual(snap["consumed"]["default"]["reserved_tokens"], 0)
        self.assertTrue(snap["consumed"]["default"]["usage_complete"])

    def test_intercept_blocks_before_http_when_call_budget_exhausted(self) -> None:
        """验收门禁#2：超限调用被事前拦截（第二次直接抛，不进入 HTTP）。"""
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 1, "max_tokens": 1_000_000}})
        payload = _payload()
        ledger.intercept(payload)  # 第 1 次 OK
        ledger.settle({"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2})
        with self.assertRaises(LLMBudgetExceeded):
            ledger.intercept(payload)  # 第 2 次 → 事前拦截
        snap = ledger.snapshot()
        self.assertIn("default", snap["exhausted_stages"])
        self.assertTrue(snap["document_needs_work"])

    def test_intercept_blocks_when_token_budget_exhausted(self) -> None:
        """验收门禁#3：余量拦截——预估 token 超剩余余量时发出前拦截。"""
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 100, "max_tokens": 50}})
        with self.assertRaises(LLMBudgetExceeded):
            ledger.intercept(_payload(max_tokens=100))  # ceiling 远超 50
        snap = ledger.snapshot()
        self.assertEqual(snap["exhausted_stages"].get("default"), "token_budget_exhausted")

    def test_settle_missing_usage_charges_ceiling_and_marks_incomplete(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.settle(None)  # usage 不可信 → 保守按 ceiling 计
        snap = ledger.snapshot()
        self.assertFalse(snap["consumed"]["default"]["usage_complete"])
        self.assertGreater(snap["consumed"]["default"]["tokens"], 0)

    def test_charge_failed_charges_ceiling_and_counts_failed(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.charge_failed()
        snap = ledger.snapshot()
        self.assertEqual(snap["consumed"]["default"]["failed_calls"], 1)
        self.assertFalse(snap["consumed"]["default"]["usage_complete"])


class ThresholdTests(_BudgetTestCase):
    def test_80_percent_warning_triggered_at_checkpoint(self) -> None:
        """验收门禁#3：累计达子预算 80% 触发黄色预警（checkpoint 落盘时点）。"""
        ledger = LLMBudgetLedger(
            "d", {"default": {"max_calls": 10, "max_tokens": 100_000_000}}, out_dir=None,
        )
        payload = _payload()
        for _ in range(8):
            ledger.intercept(payload)
            ledger.settle({"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2})
        snap = ledger.snapshot()
        metrics = {w["metric"] for w in snap["warnings"] if w["stage"] == "default"}
        self.assertIn("calls", metrics)  # 8/10 = 0.8 ≥ 0.8

    def test_100_percent_marks_exhausted_and_needs_work(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 2, "max_tokens": 100_000_000}})
        payload = _payload()
        ledger.intercept(payload)
        ledger.settle({"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2})
        ledger.intercept(payload)
        ledger.settle({"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2})
        with self.assertRaises(LLMBudgetExceeded):
            ledger.intercept(payload)
        snap = ledger.snapshot()
        self.assertIn("default", snap["exhausted_stages"])
        self.assertTrue(snap["document_needs_work"])


class CacheAndRouteTests(_BudgetTestCase):
    def test_record_cache_hit_is_zero_cost_entry(self) -> None:
        """缓存命中记 T=0 零成本条目（计 cache_hits，不增 calls/tokens）而非跳过记账。"""
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.settle({"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2})
        ledger.record_cache_hit()
        ledger.record_cache_hit()
        snap = ledger.snapshot()
        self.assertEqual(snap["consumed"]["default"]["calls"], 1)
        self.assertEqual(snap["consumed"]["default"]["cache_hits"], 2)

    def test_record_route_distribution(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.record_route("small")
        ledger.record_route("stub")
        ledger.record_route("small")
        snap = ledger.snapshot()
        self.assertEqual(snap["route_distribution"], {"small": 2, "stub": 1})


class DegradationTests(_BudgetTestCase):
    def test_functional_extract_degradation_forces_document_needs_work(self) -> None:
        """验收门禁#2：功能直抽产出因预算耗尽降级 → 强制文档级 NEEDS WORK。"""
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        self.assertFalse(ledger.document_needs_work)
        ledger.mark_degraded(STAGE_FUNCTIONAL_EXTRACT, "budget_exhausted")
        self.assertTrue(ledger.document_needs_work)
        self.assertEqual(ledger.snapshot()["degraded_stages"][STAGE_FUNCTIONAL_EXTRACT], "budget_exhausted")

    def test_other_stage_degradation_alone_does_not_force_needs_work(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.mark_degraded(STAGE_STRUCTURE_HYPOTHESIS, "budget_exhausted")
        # 结构假设降级记录在案，但 NEEDS WORK 仅功能直抽（核心交付物）强制。
        self.assertFalse(ledger.document_needs_work)


class ThreeTierRouteTests(_BudgetTestCase):
    def test_default_routes_pass_gate(self) -> None:
        validate_stage_routes()  # 默认表不抛
        self.assertEqual(DEFAULT_STAGE_ROUTES[STAGE_STRUCTURE_HYPOTHESIS], ROUTE_SMALL)

    def test_structure_hypothesis_large_model_rejected(self) -> None:
        """可执行门禁：结构假设环节不得出现大模型调用（方案 §5.1 第 15 周）。"""
        with self.assertRaises(StageRouteViolation):
            validate_stage_routes({STAGE_STRUCTURE_HYPOTHESIS: ROUTE_LARGE})

    def test_for_document_rejects_invalid_route_override(self) -> None:
        with self.assertRaises(StageRouteViolation):
            LLMBudgetLedger.for_document(
                "d", stage_route_overrides={STAGE_FUNCTIONAL_EXTRACT: ROUTE_LARGE},
            )


class SnapshotAndPersistenceTests(_BudgetTestCase):
    def test_snapshot_round_trip_preserves_state(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.settle({"total_tokens": 7, "prompt_tokens": 5, "completion_tokens": 2})
        ledger.record_cache_hit()
        ledger.record_route("small")
        snap = ledger.snapshot()
        restored = LLMBudgetLedger.from_snapshot(snap)
        self.assertEqual(restored.document_id, "d")
        self.assertEqual(restored.snapshot()["consumed"]["default"]["calls"], 1)
        self.assertEqual(restored.snapshot()["consumed"]["default"]["tokens"], 7)
        self.assertEqual(restored.snapshot()["consumed"]["default"]["cache_hits"], 1)
        self.assertEqual(restored.snapshot()["route_distribution"], {"small": 1})

    def test_snapshot_validates_against_schema(self) -> None:
        if jsonschema is None:
            self.skipTest("jsonschema not installed")
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.settle({"total_tokens": 7, "prompt_tokens": 5, "completion_tokens": 2})
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(ledger.snapshot(), schema)  # 不抛即通过

    def test_save_load_round_trip_and_resume(self) -> None:
        """落盘续算：save 后 load 恢复累计消耗，from_snapshot 不二次累加（幂等键同源）。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            ledger = LLMBudgetLedger(
                "d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}}, out_dir=out_dir,
            )
            ledger.intercept(_payload())
            ledger.settle({"total_tokens": 7, "prompt_tokens": 5, "completion_tokens": 2})
            snap_before = ledger.snapshot()
            ledger.save()

            restored = LLMBudgetLedger.load(out_dir)
            self.assertIsNotNone(restored)
            assert restored is not None
            snap_after = restored.snapshot()
            # 续算：累计消耗原样恢复，幂等键不变。
            self.assertEqual(snap_after["consumed"]["default"]["calls"], 1)
            self.assertEqual(snap_after["consumed"]["default"]["tokens"], 7)
            self.assertEqual(snap_after["idempotency_key"], snap_before["idempotency_key"])
            # 续算后继续扣减不重置。
            restored.intercept(_payload())
            restored.settle({"total_tokens": 3, "prompt_tokens": 2, "completion_tokens": 1})
            self.assertEqual(restored.snapshot()["consumed"]["default"]["calls"], 2)
            self.assertEqual(restored.snapshot()["consumed"]["default"]["tokens"], 10)

    def test_idempotency_key_stable_for_identical_state(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 10, "max_tokens": 1_000_000}})
        ledger.intercept(_payload())
        ledger.settle({"total_tokens": 7, "prompt_tokens": 5, "completion_tokens": 2})
        k1 = ledger.snapshot()["idempotency_key"]
        k2 = ledger.snapshot()["idempotency_key"]
        self.assertEqual(k1, k2)
        self.assertTrue(str(k1).startswith("sha256:"))

    def test_load_missing_returns_none(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(LLMBudgetLedger.load(Path(tmp)))

    def test_from_snapshot_rejects_wrong_schema(self) -> None:
        with self.assertRaises(ValueError):
            LLMBudgetLedger.from_snapshot({"schema": "wrong", "version": LLM_BUDGET_VERSION})


class LLMClientHookTests(_BudgetTestCase):
    def test_hook_none_by_default_zero_behavior(self) -> None:
        """硬边界：默认钩子 None = 零行为改变。"""
        self.assertIsNone(llm_client.get_document_budget_hook())

    def test_attach_makes_post_json_charge_budget(self) -> None:
        """钩子挂载后，chat_json 经 _post_json 从预算单扣减（真实本地 HTTP mock）。"""
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 5, "max_tokens": 10_000_000}})
        ledger.attach()
        self.assertIs(llm_client.get_document_budget_hook(), ledger)
        with MockOpenAIService([{"body": _ok_response(10)}]) as service:
            config = LLMClientConfig(
                base_url=service.base_url, model="mock-model",
                api_key_env="", timeout_s=2, max_retries=0,
            )
            chat_json(config, "system", "user")
        snap = ledger.snapshot()
        self.assertEqual(snap["consumed"]["default"]["calls"], 1)
        self.assertEqual(snap["consumed"]["default"]["tokens"], 10)
        self.assertEqual(len(service.requests), 1)

    def test_hook_intercepts_before_http_when_exhausted(self) -> None:
        """验收门禁#2（事前拦截）：预算耗尽后下一次调用在 HTTP 发出前被拦截。"""
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 2, "max_tokens": 10_000_000}})
        ledger.attach()
        responses = [{"body": _ok_response(10)}, {"body": _ok_response(10)}, {"body": _ok_response(10)}]
        with MockOpenAIService(responses) as service:
            config = LLMClientConfig(
                base_url=service.base_url, model="mock-model",
                api_key_env="", timeout_s=2, max_retries=0,
            )
            chat_json(config, "s", "u")  # call 1
            chat_json(config, "s", "u")  # call 2
            with self.assertRaises(LLMBudgetExceeded):
                chat_json(config, "s", "u")  # call 3 → 事前拦截
            self.assertEqual(len(service.requests), 2)  # 第 3 次没发 HTTP
        snap = ledger.snapshot()
        self.assertEqual(snap["consumed"]["default"]["calls"], 2)
        self.assertIn("default", snap["exhausted_stages"])

    def test_detach_restores_no_hook_behavior(self) -> None:
        ledger = LLMBudgetLedger("d", {"default": {"max_calls": 1, "max_tokens": 10_000_000}})
        ledger.attach()
        ledger.detach()
        self.assertIsNone(llm_client.get_document_budget_hook())


class CostReportTests(_BudgetTestCase):
    def test_cost_report_three_columns(self) -> None:
        """成本看板三列：分环节累计调用/token占比、缓存命中率、路由分布（无新增埋点）。"""
        ledger = LLMBudgetLedger("d", {
            "default": {"max_calls": 10, "max_tokens": 1_000},
            STAGE_FUNCTIONAL_EXTRACT: {"max_calls": 20, "max_tokens": 2_000},
        })
        with ledger.enter_stage(STAGE_FUNCTIONAL_EXTRACT):
            ledger.intercept(_payload())
            ledger.settle({"total_tokens": 100, "prompt_tokens": 90, "completion_tokens": 10})
            ledger.record_cache_hit()
        ledger.record_route("small")
        report = cost_report(ledger)
        self.assertEqual(report["schema"], "llm-budget-cost-report/v1")
        stages = {s["stage"]: s for s in report["stages"]}
        self.assertIn(STAGE_FUNCTIONAL_EXTRACT, stages)
        self.assertEqual(stages[STAGE_FUNCTIONAL_EXTRACT]["calls"], 1)
        self.assertGreater(stages[STAGE_FUNCTIONAL_EXTRACT]["calls_ratio"], 0)
        self.assertEqual(stages[STAGE_FUNCTIONAL_EXTRACT]["cache_hits"], 1)
        # cache_hit_rate = cache_hits / (cache_hits + paid_calls) = 1/(1+1) = 0.5
        self.assertEqual(report["cache_hit_rate"], 0.5)
        self.assertEqual(report["route_distribution"], {"small": 1})

    def test_enter_stage_scopes_intercept_to_correct_subbudget(self) -> None:
        ledger = LLMBudgetLedger("d", {
            "default": {"max_calls": 10, "max_tokens": 1_000_000},
            STAGE_FUNCTIONAL_EXTRACT: {"max_calls": 1, "max_tokens": 1_000_000},
        })
        with ledger.enter_stage(STAGE_FUNCTIONAL_EXTRACT):
            ledger.intercept(_payload())
            ledger.settle({"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2})
            with self.assertRaises(LLMBudgetExceeded):
                ledger.intercept(_payload())  # functional_extract 子预算耗尽
        # default 子预算未动。
        self.assertEqual(ledger.snapshot()["consumed"]["default"]["calls"], 0)


class FunctionalExtractDegradationTests(_BudgetTestCase):
    """验收门禁#2 的 provenance stub 半段：functional_extract LLM 失败时 provenance 如实标 stub。"""

    def test_functional_extract_routes_to_stub_when_chat_raises(self) -> None:
        from functional_extract import extract_functional_requirements

        sections = [{"section_id": "1.1", "section_path": ["1", "1.1"], "heading": "X", "text": "shall do A", "block_ids": ["B1"]}]

        def raising_chat(system: str, user: str) -> dict[str, Any]:
            raise RuntimeError("simulated budget exhaustion / LLM failure")

        items, route = extract_functional_requirements(sections, chat=raising_chat, route="openai_compatible")
        self.assertEqual(route, "stub")
        self.assertTrue(items)
        self.assertEqual(items[0]["source_kind"], "functional_extract")
        # 预算耗尽降级 → 编排侧 mark_degraded(functional_extract) → document_needs_work（见 DegradationTests）


if __name__ == "__main__":
    unittest.main()
