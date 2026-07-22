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
    rule_decider_v2,
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
        pending: tuple[str, ...] = (),
        questions: int = 0,
    ) -> None:
        self.run_id = "fake-run"
        self.readiness = {
            "verdict": "READY" if ready else "NEEDS WORK",
            "reasons": [] if ready else ["blocked"],
        }
        self.coverage_gap_block_ids = gaps
        self.failed_section_block_ids = failed
        self.pending_extraction_block_ids = pending
        self.open_questions = tuple({"clarification_id": f"CLR-{i}"} for i in range(questions))
        self.failed_sections = len(failed)
        self.requirement_count = 0

    @property
    def open_question_count(self) -> int:
        return len(self.open_questions)

    @property
    def unqueued_gap_block_ids(self) -> tuple[str, ...]:
        pending = set(self.pending_extraction_block_ids)
        return tuple(
            block_id
            for block_id in sorted(set(self.coverage_gap_block_ids) | set(self.failed_section_block_ids))
            if block_id not in pending
        )

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
        action, _reason = rule_decider_v2(state, candidates)
        self.assertEqual(candidates, ["stop"])
        self.assertEqual(action, "stop")

    def test_gaps_yield_one_batch_queue_action(self) -> None:
        state = _FakeState(gaps=("B9", "B3"), failed=("B7",))
        candidates = build_candidates(state)
        action, _reason = rule_decider_v2(state, candidates)
        self.assertEqual(candidates, ["queue_all_gaps", "stop"])
        self.assertEqual(action, "queue_all_gaps")

    def test_pending_gaps_are_not_requeued(self) -> None:
        state = _FakeState(gaps=("B9", "B3"), pending=("B3", "B9"))
        candidates = build_candidates(state)
        action, _reason = rule_decider_v2(state, candidates)
        self.assertNotIn("queue_all_gaps", candidates)
        self.assertEqual(action, "stop")

    def test_hard_question_is_asked_when_no_resample_exists(self) -> None:
        state = _FakeState(questions=1)
        candidates = build_candidates(state)
        action, _reason = rule_decider_v2(state, candidates)
        self.assertEqual(action, "ask_clarification")

    def test_otherwise_stops(self) -> None:
        state = _FakeState()
        candidates = build_candidates(state)
        action, _reason = rule_decider_v2(state, candidates)
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

        self.assertEqual(calls, ["queue_all_gaps"])
        self.assertEqual([row["action"] for row in traces], ["queue_all_gaps", "stop"])
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
        self.assertEqual([row["action"] for row in traces], ["queue_all_gaps", "stop"])
        self.assertEqual(traces[0]["result"]["status"], "ok")
        self.assertEqual(summary["tokens_used"], 0)
        self.assertEqual(summary["tokens_max"], 0)

    def test_second_run_does_not_requeue_or_duplicate_omission_rows(self) -> None:
        """跨运行幂等（test3 实测缺陷：同一批 block 被重复登记 needs_extraction）。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_real_gap(out)
            first = run_agent_loop(out, max_iterations=3)
            second = run_agent_loop(out, max_iterations=3)
            omission_rows = [
                json.loads(line)
                for line in (out / "omission_states.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            traces = _read_traces(out)

        self.assertEqual(len(omission_rows), 1)
        self.assertEqual(omission_rows[0]["status"], "needs_extraction")
        self.assertEqual(
            [row["action"] for row in traces],
            ["queue_all_gaps", "stop", "stop"],
        )
        self.assertEqual(first["counts"]["coverage_gaps"], second["counts"]["coverage_gaps"])
        self.assertEqual(second["termination_reason"], "stopped")

    def test_cli_rejects_iteration_limit_above_fifty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with redirect_stdout(StringIO()):
                code = main(["--out-dir", td, "--max-iterations", "51"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
