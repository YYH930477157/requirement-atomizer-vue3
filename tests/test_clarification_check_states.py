"""Cross-process persistence tests for internal clarification acknowledgements."""
from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

import clarification_check_states as states


def _write_check_state(out_dir: str, index: int) -> None:
    states.apply_clarification_check_action(
        Path(out_dir),
        f"CLR-{index}",
        "verified_ok",
        evidence_fingerprint=f"evidence-{index}",
        actor=f"worker-{index}",
    )


class ClarificationCheckStateTests(unittest.TestCase):
    def test_action_validation_and_latest_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with self.assertRaises(ValueError):
                states.apply_clarification_check_action(
                    out, "CLR-1", "unknown", evidence_fingerprint="e1"
                )
            first = states.apply_clarification_check_action(
                out, "CLR-1", "deferred", evidence_fingerprint="e1", actor="A"
            )
            second = states.apply_clarification_check_action(
                out, "CLR-1", "verified_ok", evidence_fingerprint="e1", actor="B",
                blocker_level="blocking", module="计量",
            )
            latest = states.read_clarification_check_states(out)
            history = states.read_clarification_check_history(out)

        self.assertEqual(first["action"], "deferred")
        self.assertEqual(second["action"], "verified_ok")
        self.assertEqual(second["state"], "verified_ok")
        self.assertEqual(second["blocker_level"], "blocking")
        self.assertEqual(second["module"], "计量")
        self.assertTrue(second["timestamp"].endswith("+00:00"))
        self.assertEqual(latest["CLR-1"]["actor"], "B")
        self.assertEqual(len(history), 2)

    def test_blocker_level_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                states.apply_clarification_check_action(
                    Path(td), "CLR-1", "verified_ok",
                    evidence_fingerprint="e1", blocker_level="P0",
                )

    def test_corrupt_historical_line_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = out / states.CHECK_STATES_FILE
            path.write_text(
                "not-json\n"
                + json.dumps({
                    "clarification_id": "CLR-1",
                    "action": "verified_ok",
                    "evidence_fingerprint": "e1",
                })
                + "\n",
                encoding="utf-8",
            )
            latest = states.read_clarification_check_states(out)
        self.assertEqual(latest["CLR-1"]["action"], "verified_ok")

    def test_existing_lock_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / states.CHECK_STATES_LOCK).write_text("other-process", encoding="ascii")
            with self.assertRaises(TimeoutError):
                with states.clarification_check_state_lock(
                    out, timeout_s=0.02, stale_after_s=-1
                ):
                    self.fail("lock should not be acquired")

    def test_concurrent_processes_do_not_lose_or_interleave_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            context = multiprocessing.get_context("spawn")
            workers = [context.Process(target=_write_check_state, args=(str(out), i)) for i in range(6)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(20)
                self.assertEqual(worker.exitcode, 0)

            history = states.read_clarification_check_history(out)
            latest = states.read_clarification_check_states(out)

        self.assertEqual(len(history), 6)
        self.assertEqual(set(latest), {f"CLR-{i}" for i in range(6)})


if __name__ == "__main__":
    unittest.main()
