"""第 9 项（方案 §14）：RATOMIZER_BUDGET_MODE off/observe/enforce 语义。

- off（默认）：行为面零变化（legacy ``RATOMIZER_LLM_BUDGET`` 开关独管，开启即 enforce）；
- observe：账本开启、逐调用记账 + 超限预警，**不阻断**（exhausted 标记照记）；
- enforce：账本开启 + 既有事前拦截（LLMBudgetExceeded）。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import llm_budget
from llm_budget import LLMBudgetLedger, budget_enabled, budget_mode
from llm_client import LLMBudgetExceeded

PAYLOAD = {"messages": [{"role": "user", "content": "x" * 200}], "max_tokens": 400}


def _ledger() -> LLMBudgetLedger:
    return LLMBudgetLedger("doc-budget-mode-test",
                           {"default": {"max_calls": 1, "max_tokens": 100}})


class BudgetModeTests(unittest.TestCase):
    def test_mode_matrix_and_unknown_rejected(self) -> None:
        env = {"RATOMIZER_BUDGET_MODE": "", "RATOMIZER_LLM_BUDGET": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("RATOMIZER_BUDGET_MODE", None)
            os.environ.pop("RATOMIZER_LLM_BUDGET", None)
            self.assertEqual(budget_mode(), "off")
            self.assertFalse(budget_enabled())          # 默认关（零行为变化）
            os.environ["RATOMIZER_LLM_BUDGET"] = "1"
            self.assertTrue(budget_enabled())           # legacy 开关照旧（开启即 enforce）
            os.environ.pop("RATOMIZER_LLM_BUDGET", None)
            for mode in ("observe", "enforce"):
                os.environ["RATOMIZER_BUDGET_MODE"] = mode
                self.assertEqual(budget_mode(), mode)
                self.assertTrue(budget_enabled())       # observe/enforce 强制开账本
            os.environ["RATOMIZER_BUDGET_MODE"] = "sometimes"
            with self.assertRaises(ValueError):
                budget_mode()

    def test_observe_warns_and_passes_over_limit(self) -> None:
        with mock.patch.dict(os.environ, {"RATOMIZER_BUDGET_MODE": "observe"}), \
                self.assertLogs("requirement_atomizer", level="WARNING") as logs:
            ledger = _ledger()
            ledger.intercept(PAYLOAD)   # 已超 token 顶
            ledger.intercept(PAYLOAD)   # 再超 call 顶
        self.assertTrue(any("budget:observe" in line and "放行不阻断" in line
                            for line in logs.output))
        # exhausted 标记照记（成本事实不因放行而抹掉）
        self.assertEqual(ledger._exhausted.get("default"), "token_budget_exhausted")

    def test_enforce_raises_over_limit(self) -> None:
        with mock.patch.dict(os.environ, {"RATOMIZER_BUDGET_MODE": "enforce"}):
            ledger = _ledger()
            with self.assertRaises(LLMBudgetExceeded):
                ledger.intercept(PAYLOAD)

    def test_off_with_legacy_switch_keeps_enforce(self) -> None:
        with mock.patch.dict(os.environ, {"RATOMIZER_LLM_BUDGET": "1"}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_BUDGET_MODE", None)
            self.assertEqual(budget_mode(), "off")
            ledger = _ledger()
            with self.assertRaises(LLMBudgetExceeded):
                ledger.intercept(PAYLOAD)


if __name__ == "__main__":
    unittest.main()
