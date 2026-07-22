from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_policy import AGENT_POLICY_VERSION
from decide_trace import (
    DECIDE_TRACE_FILE,
    DECIDE_TRACE_VERSION,
    DecideTraceValidationError,
    append_decide_trace,
    validate_decide_trace,
)


def valid_trace(iteration: int = 1) -> dict:
    action = f"resample_section:BLK-{iteration}"
    return {
        "trace_version": DECIDE_TRACE_VERSION,
        "run_id": "run-001",
        "iteration": iteration,
        "ts": "2026-07-22T12:00:00Z",
        "policy_version": AGENT_POLICY_VERSION,
        "state_digest": {
            "counts": {"requirements": 4, "coverage_gaps": 1, "open_questions": 0},
            "ready_gate": "blocked",
            "blocked_reasons": ["coverage_gap"],
        },
        "candidates": [action, "ask_clarification", "stop"],
        "action": action,
        "decider": "rule",
        "reason": "A deterministic coverage gap remains in this block.",
        "budget": {
            "iterations_used": iteration,
            "iterations_max": 100,
            "tokens_used": 0,
            "tokens_max": 0,
        },
        "result": {"status": "ok", "summary": "The section was queued."},
    }


class DecideTraceSchemaTests(unittest.TestCase):
    def test_valid_trace_passes_schema(self) -> None:
        self.assertEqual(validate_decide_trace(valid_trace())["iteration"], 1)

    def test_missing_required_field_is_rejected(self) -> None:
        trace = valid_trace()
        trace.pop("reason")
        with self.assertRaises(DecideTraceValidationError):
            validate_decide_trace(trace)

    def test_action_must_be_one_of_candidates(self) -> None:
        trace = valid_trace()
        trace["action"] = "invented_action"
        with self.assertRaises(DecideTraceValidationError):
            validate_decide_trace(trace)


class DecideTraceConcurrencyTests(unittest.TestCase):
    def test_two_writers_append_without_losing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)

            def writer(start: int) -> None:
                for iteration in range(start, start + 40):
                    append_decide_trace(out_dir, valid_trace(iteration))

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(writer, 1), executor.submit(writer, 41)]
                for future in futures:
                    future.result()

            rows = [
                json.loads(line)
                for line in (out_dir / DECIDE_TRACE_FILE).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 80)
        self.assertEqual({row["iteration"] for row in rows}, set(range(1, 81)))
        self.assertTrue(all(validate_decide_trace(row) for row in rows))


if __name__ == "__main__":
    unittest.main()
