"""S1-1 WS3 预算接线收口测试。

验收面（来自简报）：
* RATOMIZER_LLM_BUDGET 开 → desktop_tasks 挂文档预算单（attach），落盘 llm_budget.json
  （cost-report 数据源，非 available=false）；超额调用 pre-flight 拦截。
* functional_extract 降级路径调 mark_degraded（核心交付物降级强制 document_needs_work）。
* document_needs_work 接入澄清报告与就绪门（blocking → NEEDS WORK）。

开关默认关：既有行为逐字节不变（attach 返回 None，澄清报告无 budget 条目）。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BudgetNeedsWorkClarificationTests(unittest.TestCase):
    """document_needs_work → 阻塞级澄清项 → 就绪门 NEEDS WORK。"""

    def test_document_needs_work_surfaces_as_blocking_clarification(self) -> None:
        from clarification_report import BLOCKER_BLOCKING, collect_questions
        from llm_budget import LLMBudgetLedger, STAGE_FUNCTIONAL_EXTRACT

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            ledger = LLMBudgetLedger.for_document("doc1", out_dir=out)
            ledger.mark_degraded(STAGE_FUNCTIONAL_EXTRACT, "test_degraded")
            ledger.save(out)
            self.assertTrue(ledger.document_needs_work)
            entries = collect_questions(out)
            hits = [e for e in entries if e.get("signal") == "budget:document_needs_work"]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["blocker_level"], BLOCKER_BLOCKING)
            # blocking 条目存在 → unresolved_blocking>0 → readiness NEEDS WORK（就绪门接入）
            blocking = [e for e in entries if e.get("blocker_level") == BLOCKER_BLOCKING]
            self.assertTrue(any(e.get("signal") == "budget:document_needs_work" for e in blocking))

    def test_no_ledger_means_no_budget_entry(self) -> None:
        from clarification_report import collect_questions

        with tempfile.TemporaryDirectory() as tmp:
            entries = collect_questions(Path(tmp))
            self.assertEqual(
                [e for e in entries if e.get("signal") == "budget:document_needs_work"], []
            )

    def test_ledger_without_needs_work_means_no_budget_entry(self) -> None:
        from clarification_report import collect_questions
        from llm_budget import LLMBudgetLedger

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            ledger = LLMBudgetLedger.for_document("doc1", out_dir=out)
            ledger.save(out)  # document_needs_work stays False
            self.assertFalse(ledger.document_needs_work)
            entries = collect_questions(out)
            self.assertEqual(
                [e for e in entries if e.get("signal") == "budget:document_needs_work"], []
            )


class FunctionalExtractDegradationTests(unittest.TestCase):
    """functional_extract 降级 stub 时在活动预算单上 mark_degraded。"""

    def test_degradation_to_stub_marks_budget_ledger(self) -> None:
        import functional_extract as fe
        from llm_budget import LLMBudgetLedger, STAGE_FUNCTIONAL_EXTRACT

        def bad_chat(system_prompt: str, user_prompt: str) -> dict:
            raise RuntimeError("boom")

        ledger = LLMBudgetLedger.for_document("doc1")
        ledger.attach()
        try:
            sections = [{"block_ids": ["B1"], "text": "The meter shall log events.",
                         "title": "t"}]
            items, route = fe.extract_functional_requirements(
                sections, chat=bad_chat, route="openai_compatible"
            )
            self.assertEqual(route, "stub")
            self.assertTrue(ledger.document_needs_work)
            self.assertIn(STAGE_FUNCTIONAL_EXTRACT, ledger.snapshot()["degraded_stages"])
        finally:
            ledger.detach()

    def test_stub_route_is_not_degradation(self) -> None:
        """route=stub 是请求本意，不算降级，不触发 mark_degraded。"""
        import functional_extract as fe
        from llm_budget import LLMBudgetLedger

        ledger = LLMBudgetLedger.for_document("doc1")
        ledger.attach()
        try:
            sections = [{"block_ids": ["B1"], "text": "shall log", "title": "t"}]
            items, route = fe.extract_functional_requirements(sections, route="stub")
            self.assertEqual(route, "stub")
            self.assertFalse(ledger.document_needs_work)
        finally:
            ledger.detach()


class DesktopBudgetAttachTests(unittest.TestCase):
    """desktop_tasks run/chain 入口按开关挂/卸文档预算单。"""

    def test_switch_off_attach_returns_none(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            old = os.environ.pop("RATOMIZER_LLM_BUDGET", None)
            try:
                self.assertIsNone(desktop_tasks._attach_budget_ledger_for_run(out, out / "in.docx"))
            finally:
                if old is not None:
                    os.environ["RATOMIZER_LLM_BUDGET"] = old

    def test_switch_on_attaches_and_detaches_and_persists(self) -> None:
        import llm_client
        import desktop_tasks
        from llm_budget import LLMBudgetLedger

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.dict(os.environ, {"RATOMIZER_LLM_BUDGET": "1"}):
                ledger = desktop_tasks._attach_budget_ledger_for_run(out, out / "in.docx")
                self.assertIsNotNone(ledger)
                self.assertIs(llm_client.get_document_budget_hook(), ledger)
                desktop_tasks._detach_budget_ledger(ledger)
                self.assertIsNone(llm_client.get_document_budget_hook())
            # detach 前 save 落盘 llm_budget.json → cost-report 数据源就绪
            self.assertIsNotNone(LLMBudgetLedger.load(out))

    def test_over_budget_call_is_intercepted_pre_flight(self) -> None:
        """预算耗尽时 intercept 在 HTTP 发出前抛 LLMBudgetExceeded（调用方 stub catch 接管）。"""
        from llm_budget import LLMBudgetLedger, STAGE_FUNCTIONAL_EXTRACT
        from llm_client import LLMBudgetExceeded

        ledger = LLMBudgetLedger.for_document(
            "doc1",
            sub_budget_overrides={
                STAGE_FUNCTIONAL_EXTRACT: {"max_calls": 0, "max_tokens": 100},
            },
        )
        with ledger.enter_stage(STAGE_FUNCTIONAL_EXTRACT):
            with self.assertRaises(LLMBudgetExceeded):
                # 一个极小 payload；max_calls=0 → 立即 call-exhausted 拦截
                ledger.intercept({"model": "m", "messages": [{"role": "user", "content": "x"}]})
        self.assertTrue(ledger.document_needs_work)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
