from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import omission_actions
from agent_loop import (
    build_candidates,
    main,
    rule_decider_v1,
    run_agent_loop,
)
from agent_state import load_analysis_state
from decide_trace import DECIDE_TRACE_FILE, validate_decide_trace


class _FakeState:
    def __init__(
        self,
        *,
        ready: bool = False,
        gaps: tuple[str, ...] = (),
        failed: tuple[str, ...] = (),
        questions: int = 0,
    ) -> None:
        self.run_id = "fake-run"
        self.readiness = {
            "verdict": "READY" if ready else "NEEDS WORK",
            "reasons": [] if ready else ["blocked"],
        }
        self.coverage_gap_block_ids = gaps
        self.failed_section_block_ids = failed
        self.open_questions = tuple({"clarification_id": f"CLR-{i}"} for i in range(questions))
        self.failed_sections = len(failed)
        self.requirement_count = 0

    @property
    def open_question_count(self) -> int:
        return len(self.open_questions)

    def state_digest(self) -> dict:
        return {
            "counts": {
                "requirements": self.requirement_count,
                "coverage_gaps": len(self.coverage_gap_block_ids),
                "open_questions": self.open_question_count,
            },
            "ready_gate": "pass" if self.readiness["verdict"] == "READY" else "blocked",
            "blocked_reasons": list(self.readiness["reasons"]),
        }


def _read_traces(out: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (out / DECIDE_TRACE_FILE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _seed_real_gap(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        json.dumps({
            "block_id": "B1",
            "order": 1,
            "text": "The meter shall log events.",
            "requirement_like": True,
            "noise": False,
        }) + "\n",
        encoding="utf-8",
    )
    (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")
    (out / "ai_extract_quality.json").write_text(
        json.dumps({"failed_sections": 1, "failed_section_block_ids": ["B1"]}),
        encoding="utf-8",
    )


class RuleDeciderTests(unittest.TestCase):
    def test_ready_stops_even_when_other_inputs_exist(self) -> None:
        state = _FakeState(ready=True, gaps=("B2",), questions=1)
        candidates = build_candidates(state)
        action, _reason = rule_decider_v1(state, candidates)
        self.assertEqual(candidates, ["stop"])
        self.assertEqual(action, "stop")

    def test_resample_uses_first_sorted_block_id(self) -> None:
        state = _FakeState(gaps=("B9", "B3"), failed=("B7",))
        candidates = build_candidates(state)
        action, _reason = rule_decider_v1(state, candidates)
        self.assertEqual(action, "resample_section:B3")

    def test_hard_question_is_asked_when_no_resample_exists(self) -> None:
        state = _FakeState(questions=1)
        candidates = build_candidates(state)
        action, _reason = rule_decider_v1(state, candidates)
        self.assertEqual(action, "ask_clarification")

    def test_otherwise_stops(self) -> None:
        state = _FakeState()
        candidates = build_candidates(state)
        action, _reason = rule_decider_v1(state, candidates)
        self.assertEqual(action, "stop")


class AgentLoopTests(unittest.TestCase):
    def test_every_iteration_appends_a_schema_valid_rule_trace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(ready=True)
            summary = run_agent_loop(out, state_loader=lambda _out: state)
            traces = _read_traces(out)

        self.assertEqual(summary["iterations"], 1)
        self.assertEqual(traces[0]["decider"], "rule")
        self.assertTrue(validate_decide_trace(traces[0]))

    def test_failed_action_is_excluded_from_later_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(gaps=("B1",))
            calls: list[str] = []

            def runner(_out: Path, action: str, _state: _FakeState) -> dict:
                calls.append(action)
                raise RuntimeError("boom")

            summary = run_agent_loop(
                out, max_iterations=4, state_loader=lambda _out: state, tool_runner=runner
            )
            traces = _read_traces(out)

        self.assertEqual(calls, ["resample_section:B1"])
        self.assertEqual([row["action"] for row in traces], ["resample_section:B1", "stop"])
        self.assertEqual(traces[0]["result"]["status"], "error")
        self.assertEqual(summary["termination_reason"], "stopped")

    def test_successful_clarification_is_not_repeated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(questions=1)
            calls: list[str] = []

            def runner(_out: Path, action: str, _state: _FakeState) -> dict:
                calls.append(action)
                return {"status": "ok", "summary": "report written"}

            run_agent_loop(
                out, max_iterations=4, state_loader=lambda _out: state, tool_runner=runner
            )
            traces = _read_traces(out)

        self.assertEqual(calls, ["ask_clarification"])
        self.assertEqual([row["action"] for row in traces], ["ask_clarification", "stop"])

    def test_budget_exhaustion_has_exact_rows_and_final_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            state = _FakeState(gaps=("B1",))

            def runner(_out: Path, _action: str, _state: _FakeState) -> dict:
                return {"status": "ok", "summary": "completed but state stayed blocked"}

            summary = run_agent_loop(
                out, max_iterations=3, state_loader=lambda _out: state, tool_runner=runner
            )
            traces = _read_traces(out)

        self.assertEqual(len(traces), 3)
        self.assertEqual(traces[-1]["result"]["status"], "skipped")
        self.assertEqual(summary["termination_reason"], "budget_exhausted")

    def test_last_action_reaching_ready_is_not_mislabeled_budget_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            blocked = _FakeState(gaps=("B1",))
            ready = _FakeState(ready=True)
            loads = iter((blocked, ready))

            summary = run_agent_loop(
                out,
                max_iterations=1,
                state_loader=lambda _out: next(loads),
                tool_runner=lambda _out, _action, _state: {
                    "status": "ok",
                    "summary": "gap resolved",
                },
            )
            traces = _read_traces(out)

        self.assertEqual(traces[-1]["result"]["status"], "ok")
        self.assertEqual(summary["termination_reason"], "ready")
        self.assertEqual(summary["readiness"], "READY")

    def test_real_zero_llm_loop_never_calls_targeted_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_real_gap(out)
            with mock.patch.object(omission_actions, "targeted_reextract") as targeted:
                summary = run_agent_loop(out, max_iterations=3)
            traces = _read_traces(out)

        targeted.assert_not_called()
        self.assertEqual(traces[0]["result"]["status"], "skipped")
        self.assertEqual(summary["tokens_used"], 0)
        self.assertEqual(summary["tokens_max"], 0)

    def test_cli_rejects_iteration_limit_above_fifty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                code = main(["--out-dir", td, "--max-iterations", "51"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
