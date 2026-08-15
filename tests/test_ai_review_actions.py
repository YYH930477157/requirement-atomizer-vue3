"""ai_review_actions 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import multiprocessing
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import claim_review_actions
import review_state
from ai_review_actions import (
    ai_req_id,
    apply_ai_review_action,
    read_ai_review_authority_snapshot,
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

            snapshot = read_ai_review_authority_snapshot(Path(td))
            self.assertEqual(snapshot["ordered_records"][0]["append_ordinal"], 2)
            self.assertEqual(snapshot["audit_gaps"][0]["append_ordinal"], 1)

    def test_snapshot_preserves_every_ordered_transition_for_one_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            apply_ai_review_action(out, "AI-1", "rejected", reason="first")
            apply_ai_review_action(out, "AI-1", "accepted", reason="restored")

            snapshot = read_ai_review_authority_snapshot(out)

            self.assertEqual(
                [record["state"]["status"] for record in snapshot["ordered_records"]],
                ["rejected", "accepted"],
            )
            self.assertEqual(
                [record["append_ordinal"] for record in snapshot["ordered_records"]],
                [1, 2],
            )
            self.assertNotEqual(
                snapshot["ordered_records"][0]["source_event_revision"],
                snapshot["ordered_records"][1]["source_event_revision"],
            )
            self.assertEqual(snapshot["states"]["AI-1"]["status"], "accepted")
            self.assertEqual(snapshot["audit_gaps"], [])

    def test_unterminated_tail_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ai_review_states.jsonl"
            valid = '{"ai_req_id":"AI-1","status":"accepted"}\n'
            path.write_text(valid + '{"ai_req_id":', encoding="utf-8")

            with self.assertLogs("requirement_atomizer", level="WARNING"):
                states = read_ai_review_states(Path(td))

            self.assertEqual(states["AI-1"]["status"], "accepted")
            self.assertEqual(path.read_text(encoding="utf-8"), valid)


class AiReviewFoldHookTests(unittest.TestCase):
    """apply_ai_review_action 的 fold 钩子：同步覆盖语义保持、与 A 轨共享同一
    per-root 合并器（混合突发仍合并成最少 pass）、失败 logged-and-continue。"""

    def _root_with_claim_generation(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        (root / "claim_generation.meta.json").write_text("{}", encoding="utf-8")
        return root

    def test_decision_folds_synchronously_with_track_b(self) -> None:
        root = self._root_with_claim_generation()
        folds: list[dict] = []

        def recording_fold(out_dir, **kwargs):
            folds.append(dict(kwargs))
            return {"ok": True}

        with patch.object(claim_review_actions, "fold_effective_ledger", side_effect=recording_fold):
            state = apply_ai_review_action(root, "AI-1", "accepted", actor="tester")

        self.assertEqual(len(folds), 1)
        self.assertEqual(folds[0]["actor_trigger"], "ai-review-action")
        self.assertEqual(folds[0]["authority_hook_track"], "B")
        self.assertEqual(state["status"], "accepted")
        self.assertEqual(read_ai_review_states(root)["AI-1"]["status"], "accepted")

    def test_fold_failure_is_logged_and_decision_still_authoritative(self) -> None:
        root = self._root_with_claim_generation()

        with patch.object(
            claim_review_actions,
            "fold_effective_ledger",
            side_effect=RuntimeError("injected B fold failure"),
        ):
            with self.assertLogs("requirement_atomizer", level="WARNING") as captured:
                state = apply_ai_review_action(root, "AI-1", "rejected", actor="tester")

        self.assertEqual(state["status"], "rejected")
        self.assertTrue(
            any("AI review saved; claim effective fold lagged" in line
                for line in captured.output),
        )
        self.assertEqual(read_ai_review_states(root)["AI-1"]["status"], "rejected")

    def test_concurrent_b_decisions_coalesce_folds_via_shared_coordinator(self) -> None:
        root = self._root_with_claim_generation()
        fold_lock = threading.Lock()
        folds: list[str] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def slow_fold(out_dir, **kwargs):
            with fold_lock:
                folds.append(str(kwargs.get("authority_hook_track")))
            time.sleep(0.3)
            return {"ok": True}

        def decide(index: int) -> None:
            try:
                barrier.wait(10)
                apply_ai_review_action(root, f"AI-{index}", "accepted", actor="burst")
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        with patch.object(claim_review_actions, "fold_effective_ledger", side_effect=slow_fold):
            threads = [
                threading.Thread(target=decide, args=(index,), daemon=True)
                for index in range(6)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)

        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertLessEqual(len(folds), review_state._EFFECTIVE_FOLD_DRAIN_PASSES)
        self.assertGreaterEqual(len(folds), 1)
        states = read_ai_review_states(root)
        self.assertEqual(
            sorted(states),
            [f"AI-{index}" for index in range(6)],
        )

    def test_mixed_track_decisions_fold_once_per_track(self) -> None:
        """同一 root 上 A/B 两轨并发裁决：共享合并器，各轨至多一两个 pass。"""
        root = self._root_with_claim_generation()
        fold_lock = threading.Lock()
        folds: list[str] = []
        errors: list[BaseException] = []
        start = threading.Barrier(2)

        def slow_fold(out_dir, **kwargs):
            with fold_lock:
                folds.append(str(kwargs.get("authority_hook_track")))
            time.sleep(0.3)
            return {"ok": True}

        def decide_a() -> None:
            try:
                start.wait(10)
                review_state.apply_expert_decision(
                    root, "SREQ-1", "accepted", actor="expert", reason="mixed"
                )
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        def decide_b() -> None:
            try:
                start.wait(10)
                apply_ai_review_action(root, "AI-1", "accepted", actor="mixed")
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        with patch.object(claim_review_actions, "fold_effective_ledger", side_effect=slow_fold):
            threads = [
                threading.Thread(target=decide_a, daemon=True),
                threading.Thread(target=decide_b, daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)

        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        # 每轨各完成自己的覆盖 pass（旧实现同样 2 次，但混合突发下不再放大）
        self.assertEqual(set(folds), {"A", "B"})
        self.assertLessEqual(len(folds), 4)
        self.assertEqual(
            review_state.read_review_authority_snapshot(root)["states"][0]["status"],
            "accepted",
        )
        self.assertEqual(read_ai_review_states(root)["AI-1"]["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
