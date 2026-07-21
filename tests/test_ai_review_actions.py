"""ai_review_actions 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path

from ai_review_actions import (
    ai_req_id,
    apply_ai_review_action,
    read_ai_review_states,
    source_ai_requirement_id,
)


def _append_ai_review_rows(out_dir: str, prefix: str, count: int, start_event) -> None:
    start_event.wait(10)
    for index in range(count):
        apply_ai_review_action(
            Path(out_dir),
            f"{prefix}-{index}",
            "accepted",
            actor=prefix,
        )


def _hold_ai_review_lock(out_dir: str, ready_event, release_event) -> None:
    from ai_review_actions import _ai_review_state_lock

    with _ai_review_state_lock(Path(out_dir)):
        ready_event.set()
        if not release_event.wait(10):
            raise RuntimeError("test did not release AI review lock")


class OwnershipOverrideTests(unittest.TestCase):
    def test_persists_ownership_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            state = apply_ai_review_action(
                tmp_path,
                "AI-1",
                "accepted",
                module_override="时钟需求",
                ownership_override="co_design",
                reason="硬件 RTC 依赖需要确认",
                actor="tester",
            )

            assert state["ownership_override"] == "co_design"
            states = read_ai_review_states(tmp_path)
            assert states["AI-1"]["ownership_override"] == "co_design"

    def test_rejects_invalid_ownership_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as ctx:
                apply_ai_review_action(Path(td), "AI-1", "accepted", ownership_override="firmware")
            assert "unknown ownership" in str(ctx.exception)

    def test_rejects_blank_or_overlong_module_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            for invalid in ("   ", "模" * 21):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    apply_ai_review_action(out, "AI-1", "accepted", module_override=invalid)


class SourceAiRequirementIdTests(unittest.TestCase):
    """三处（api_server/ai_extract/requirements_analysis）共用的唯一主键实现。"""

    def test_explicit_id_wins_over_content_hash(self) -> None:
        req = {"ai_req_id": "AIR-explicit", "source_quote": "q", "title": "t"}
        assert source_ai_requirement_id(req) == "AIR-explicit"

    def test_falls_back_to_content_hash(self) -> None:
        req = {"source_section": "4", "source_quote": "q", "title": "t"}
        assert source_ai_requirement_id(req) == ai_req_id(req)


class AiReviewStateConcurrencyTests(unittest.TestCase):
    def test_concurrent_processes_append_complete_rows_without_loss(self) -> None:
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as td:
            start_event = context.Event()
            processes = [
                context.Process(
                    target=_append_ai_review_rows,
                    args=(td, f"worker-{index}", 12, start_event),
                )
                for index in range(2)
            ]
            for process in processes:
                process.start()
            start_event.set()
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)

            states = read_ai_review_states(Path(td))
            lines = (Path(td) / "ai_review_states.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 24)
        self.assertEqual(len(states), 24)
        self.assertEqual({row["actor"] for row in states.values()}, {"worker-0", "worker-1"})

    def test_reader_waits_for_cross_process_writer_lock(self) -> None:
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            apply_ai_review_action(out, "AI-1", "accepted")
            ready_event = context.Event()
            release_event = context.Event()
            holder = context.Process(
                target=_hold_ai_review_lock,
                args=(td, ready_event, release_event),
            )
            holder.start()
            self.assertTrue(ready_event.wait(10))

            started = threading.Event()
            finished = threading.Event()

            def read_states() -> None:
                started.set()
                read_ai_review_states(out)
                finished.set()

            reader = threading.Thread(target=read_states)
            reader.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.wait(0.2))
            release_event.set()
            reader.join(10)
            holder.join(10)

            self.assertFalse(reader.is_alive())
            self.assertEqual(holder.exitcode, 0)
            self.assertTrue(finished.is_set())

    def test_corrupt_historical_row_is_reported_and_later_state_survives(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ai_review_states.jsonl"
            path.write_text(
                '{"ai_req_id":\n'
                '{"ai_req_id":"AI-1","status":"accepted"}\n',
                encoding="utf-8",
            )

            with self.assertLogs("requirement_atomizer", level="WARNING") as captured:
                states = read_ai_review_states(Path(td))

            self.assertEqual(states["AI-1"]["status"], "accepted")
            self.assertIn("line 1", captured.output[0])

    def test_unterminated_tail_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ai_review_states.jsonl"
            valid = '{"ai_req_id":"AI-1","status":"accepted"}\n'
            path.write_text(valid + '{"ai_req_id":', encoding="utf-8")

            with self.assertLogs("requirement_atomizer", level="WARNING"):
                states = read_ai_review_states(Path(td))

            self.assertEqual(states["AI-1"]["status"], "accepted")
            self.assertEqual(path.read_text(encoding="utf-8"), valid)


if __name__ == "__main__":
    unittest.main()
