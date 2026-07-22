from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_loop
from agent_decider import AgentDeciderError, llm_decide
from llm_client import LLMClientConfig


def _config(**overrides) -> LLMClientConfig:
    base = dict(
        base_url="http://127.0.0.1:9/unused",
        model="mock-model",
        api_key_env="",
        timeout_s=1,
        max_retries=0,
        max_tokens=256,
    )
    base.update(overrides)
    return LLMClientConfig(**base)


class LlmDecideTests(unittest.TestCase):
    def test_valid_pick_returns_action_reason_and_usage(self) -> None:
        data = {"action": "stop", "reason": "Nothing actionable."}
        meta = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "usage_complete": True}
        with mock.patch("agent_decider.chat_json_with_meta", return_value=(data, meta)):
            action, reason, got_meta = llm_decide(_config(), {"counts": {}}, ["stop"])

        self.assertEqual(action, "stop")
        self.assertEqual(reason, "Nothing actionable.")
        self.assertEqual(got_meta["usage"]["total_tokens"], 15)

    def test_action_outside_candidates_raises(self) -> None:
        data = {"action": "invented", "reason": "x"}
        meta = {"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "usage_complete": True}
        with mock.patch("agent_decider.chat_json_with_meta", return_value=(data, meta)):
            with self.assertRaises(AgentDeciderError):
                llm_decide(_config(), {}, ["stop"])

    def test_call_failure_raises_for_rule_fallback(self) -> None:
        with mock.patch("agent_decider.chat_json_with_meta", side_effect=RuntimeError("boom")):
            with self.assertRaises(AgentDeciderError):
                llm_decide(_config(), {}, ["stop"])

    def test_empty_candidates_rejected_without_call(self) -> None:
        with mock.patch("agent_decider.chat_json_with_meta") as call:
            with self.assertRaises(AgentDeciderError):
                llm_decide(_config(), {}, [])
        call.assert_not_called()


class _FakeState:
    def __init__(self, *, gaps: tuple[str, ...] = (), questions: int = 0) -> None:
        self.run_id = "fake-run"
        self.readiness = {"verdict": "NEEDS WORK", "reasons": ["blocked"]}
        self.coverage_gap_block_ids = gaps
        self.failed_section_block_ids = ()
        self.pending_extraction_block_ids = ()
        self.open_questions = tuple({"clarification_id": f"CLR-{i}"} for i in range(questions))
        self.failed_sections = 0
        self.requirement_count = 0

    @property
    def open_question_count(self) -> int:
        return len(self.open_questions)

    @property
    def unqueued_gap_block_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.coverage_gap_block_ids))

    def state_digest(self) -> dict:
        return {
            "counts": {
                "requirements": 0,
                "coverage_gaps": len(self.coverage_gap_block_ids),
                "open_questions": self.open_question_count,
            },
            "ready_gate": "blocked",
            "blocked_reasons": ["blocked"],
        }


def _read_traces(out: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (out / "decide_trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class LlmDeciderLoopTests(unittest.TestCase):
    def _runner(self, calls: list[str]):
        def runner(_out: Path, action: str, _state: _FakeState) -> dict:
            calls.append(action)
            return {"status": "ok", "summary": f"ran {action}"}
        return runner

    def test_llm_pick_is_traced_as_llm_with_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(questions=1)
            meta = {"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                    "usage_complete": True}
            with mock.patch(
                "agent_loop.llm_decide",
                return_value=("ask_clarification", "model picked it", meta),
            ) as decide:
                summary = agent_loop.run_agent_loop(
                    out,
                    max_iterations=3,
                    decider="llm",
                    llm_config=_config(),
                    state_loader=lambda _out: state,
                    tool_runner=self._runner([]),
                )
            traces = _read_traces(out)

        llm_traces = [t for t in traces if t["decider"] == "llm"]
        self.assertTrue(llm_traces)
        self.assertEqual(llm_traces[0]["action"], "ask_clarification")
        self.assertEqual(llm_traces[0]["budget"]["tokens_used"], 10)
        self.assertEqual(summary["decider_usage"]["llm"], len(llm_traces))
        self.assertEqual(summary["tokens_used"], 10 * len(llm_traces))
        self.assertEqual(summary["token_accounting"], "complete")
        decide.assert_called()

    def test_llm_failure_falls_back_to_rule_per_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(questions=1)
            with mock.patch(
                "agent_loop.llm_decide", side_effect=AgentDeciderError("endpoint down")
            ):
                summary = agent_loop.run_agent_loop(
                    out,
                    max_iterations=3,
                    decider="llm",
                    llm_config=_config(),
                    state_loader=lambda _out: state,
                    tool_runner=self._runner([]),
                )
            traces = _read_traces(out)

        self.assertEqual(summary["decider_usage"], {"rule": 2, "llm": 0})
        self.assertTrue(all(t["decider"] == "rule" for t in traces))
        self.assertIn("llm 决策失败回退", traces[0]["reason"])
        self.assertEqual(summary["tokens_used"], 0)

    def test_exhausted_token_budget_skips_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(gaps=("B1",))
            meta = {"usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
                    "usage_complete": True}
            with mock.patch(
                "agent_loop.llm_decide",
                return_value=("queue_all_gaps", "picked", meta),
            ) as decide:
                summary = agent_loop.run_agent_loop(
                    out,
                    max_iterations=5,
                    decider="llm",
                    max_tokens=10,
                    llm_config=_config(),
                    state_loader=lambda _out: state,
                    tool_runner=self._runner([]),
                )
            traces = _read_traces(out)

        # 第一轮 llm 花满 10；第二轮起 tokens_used>=max_tokens → 不再发起决策调用
        self.assertEqual(decide.call_count, 1)
        self.assertIn("llm 决策预算耗尽回退", traces[1]["reason"])
        self.assertEqual(summary["tokens_used"], 10)

    def test_stop_only_candidates_skip_llm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState()
            with mock.patch("agent_loop.llm_decide") as decide:
                summary = agent_loop.run_agent_loop(
                    out,
                    max_iterations=2,
                    decider="llm",
                    llm_config=_config(),
                    state_loader=lambda _out: state,
                    tool_runner=self._runner([]),
                )
            traces = _read_traces(out)

        decide.assert_not_called()
        self.assertEqual(summary["tokens_used"], 0)
        self.assertTrue(all(t["decider"] == "rule" for t in traces))

    def test_llm_requires_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(agent_loop.AgentLoopInputError):
                agent_loop.run_agent_loop(Path(td), decider="llm", llm_config=None)


if __name__ == "__main__":
    unittest.main()
