from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import claim_reextract_attempts as attempts
from claim_artifacts import atomic_write_jsonl, hash_json
from omission_actions import AI_SUPPLEMENTS


def _hash(value: str) -> str:
    return hash_json("claim-reextract-attempt-test/v1", value)


def _common(attempt_id: str, event_kind: str, suffix: str) -> dict:
    return {
        "attempt_id": attempt_id,
        "proposal_id": "CQP-12345678-9abcdef0",
        "claim_id": "CLM-0123456789abcdef",
        "claim_hash": _hash("claim"),
        "event_kind": event_kind,
        "actor": "expert:yyh",
        "idempotency_key": _hash(suffix),
    }


def _started(attempt_id: str) -> dict:
    return {
        **_common(attempt_id, "reextract_started", "started"),
        "request_idempotency_key": "request-1",
        "route": "openai_compatible",
        "model": "deepseek-chat",
        "route_config_revision": _hash("route-config"),
        "budgets": {
            "max_calls": 1,
            "max_total_tokens": 4000,
            "allow_semantic_verifier": False,
        },
        "preconditions": {"claim_effective_revision": _hash("revision")},
        "focus": {"kind": "text_span", "block_id": "B1", "start": 0, "end": 5},
    }


class ClaimReextractAttemptTests(unittest.TestCase):
    def test_v1_started_event_without_route_revision_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id(
                "CQP-12345678-9abcdef0",
                "request-1",
            )
            started = _started(current_id)
            started["schema"] = "claim-reextract-attempt/v1"
            started.pop("route_config_revision")
            attempts.append_attempt_events(root, [started])

            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(snapshot.rows[0]["schema"], "claim-reextract-attempt/v1")
        self.assertNotIn("route_config_revision", snapshot.rows[0])

    def test_hash_chained_lifecycle_and_idempotent_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            started = _started(current_id)
            attempts.append_attempt_events(root, [started])
            duplicate = attempts.append_attempt_events(root, [started])
            self.assertEqual(duplicate["appended_count"], 0)

            events = [
                {
                    **_common(current_id, "budget_checkpoint", "budget-pre"),
                    "checkpoint": {
                        "phase": "pre_call", "calls": 1, "total_tokens": 4000,
                        "usage_complete": False, "status": "reserved",
                    },
                },
                {
                    **_common(current_id, "budget_checkpoint", "budget-post"),
                    "checkpoint": {
                        "phase": "post_call", "calls": 1, "total_tokens": 523,
                        "usage_complete": True, "status": "settled",
                    },
                },
                {
                    **_common(current_id, "supplement_persisted", "supplement"),
                    "supplement_id": "SUP-0123456789ab",
                    "supplement_hash": _hash("supplement"),
                },
                {
                    **_common(current_id, "requirements_published", "requirements"),
                    "requirements_sha256": _hash("requirements"),
                    "target_publication_revision": _hash("publication"),
                },
                {
                    **_common(current_id, "base_rebuild_published", "base"),
                    "base_generation_id": _hash("base"),
                },
                {
                    **_common(current_id, "effective_folded", "effective"),
                    "document_effective_revision": _hash("document-effective"),
                    "claim_effective_revision": _hash("claim-effective"),
                    "effective_fresh": True,
                },
                {
                    **_common(current_id, "reextract_succeeded", "succeeded"),
                    "outcome": {"code": "covered", "message": "", "retryable": False},
                    "usage": {"calls": 1, "total_tokens": 523, "usage_complete": True},
                },
            ]
            attempts.append_attempt_events(root, events)
            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(snapshot.last_event_seq, 8)
        self.assertEqual(snapshot.rows[-1]["prev_event_hash"], snapshot.rows[-2]["event_hash"])
        state = attempts.derive_attempt_states(snapshot.rows)[current_id]
        self.assertEqual(state["lifecycle"], "succeeded")
        self.assertTrue(state["effective_folded"])

    def test_requirements_without_fold_projects_rebuild_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [
                _started(current_id),
                {
                    **_common(current_id, "supplement_persisted", "supplement"),
                    "supplement_id": "SUP-0123456789ab",
                    "supplement_hash": _hash("supplement"),
                },
                {
                    **_common(current_id, "requirements_published", "requirements"),
                    "requirements_sha256": _hash("requirements"),
                    "target_publication_revision": _hash("publication"),
                },
            ])
            state = attempts.derive_attempt_states(
                attempts.read_attempt_log(root).rows
            )[current_id]

        self.assertEqual(state["lifecycle"], "rebuild_pending")

    def test_illegal_checkpoint_order_and_post_terminal_append_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "lacks a supplement",
            ):
                attempts.append_attempt_events(root, [{
                    **_common(current_id, "requirements_published", "requirements"),
                    "requirements_sha256": _hash("requirements"),
                    "target_publication_revision": _hash("publication"),
                }])

            attempts.append_attempt_events(root, [{
                **_common(current_id, "reextract_failed", "failed"),
                "outcome": {"code": "remote_error", "message": "boom", "retryable": True},
                "usage": {"calls": 1, "total_tokens": None, "usage_complete": False},
            }])
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "continues after a terminal",
            ):
                attempts.append_attempt_events(root, [{
                    **_common(current_id, "budget_checkpoint", "too-late"),
                    "checkpoint": {
                        "phase": "error", "calls": 1, "total_tokens": None,
                        "usage_complete": False, "status": "unknown",
                    },
                }])

    def test_torn_tail_is_never_silently_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            with (root / attempts.CLAIM_REEXTRACT_ATTEMPTS).open("ab") as handle:
                handle.write(b'{"schema":"claim-reextract-attempt/v1"')

            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "torn tail",
            ):
                attempts.read_attempt_log(root)

    def test_failed_atomic_append_preserves_committed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id(
                "CQP-12345678-9abcdef0",
                "request-1",
            )
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            before = path.read_bytes()
            event = {
                **_common(current_id, "budget_checkpoint", "atomic-failure"),
                "checkpoint": {
                    "phase": "pre_call",
                    "calls": 1,
                    "total_tokens": 4000,
                    "usage_complete": False,
                    "status": "reserved",
                },
            }

            # Appends are true append-mode writes now; a failed line write must
            # leave the committed prefix untouched (readers see either the
            # complete previous generation or the complete new one).
            with mock.patch.object(
                attempts,
                "_append_lines_unlocked",
                side_effect=OSError("append unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "append unavailable"):
                    attempts.append_attempt_events(root, [event])

            self.assertEqual(path.read_bytes(), before)
            snapshot = attempts.read_attempt_log(root)
            self.assertEqual(snapshot.last_event_seq, 1)
            self.assertEqual(len(snapshot.rows), 1)


class AttemptLogAppendModeTests(unittest.TestCase):
    """S10 重设计（2026-08-14）：追加改为 append 模式 + 每事件 fsync + 链头
    记忆化 + 启动/周期 compaction。哈希链前缀与读者语义逐字节不变。"""

    def test_appends_never_rewrite_the_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            before = path.read_bytes()

            with mock.patch.object(
                attempts,
                "atomic_write_jsonl",
                side_effect=AssertionError("append must not rewrite the file"),
            ):
                attempts.append_attempt_events(root, [{
                    **_common(current_id, "budget_checkpoint", "append-mode"),
                    "checkpoint": {
                        "phase": "pre_call",
                        "calls": 1,
                        "total_tokens": 4000,
                        "usage_complete": False,
                        "status": "reserved",
                    },
                }])

            after = path.read_bytes()
            snapshot = attempts.read_attempt_log(root)
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))
        self.assertEqual(snapshot.last_event_seq, 2)

    def test_chained_append_reuses_memoized_chain_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            second_start = _started(
                attempts.attempt_id("CQP-12345678-9abcdef0", "request-2")
            )
            second_start["idempotency_key"] = _hash("started-2")
            attempts.append_attempt_events(root, [_started(first_id)])
            attempts.append_attempt_events(root, [second_start])
            # A third append must chain onto the memoized head without any
            # full-file scan: freeze file reads and it still succeeds.
            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("append must not rescan the log"),
            ):
                attempts.append_attempt_events(root, [{
                    **_common(first_id, "budget_checkpoint", "memo-chain"),
                    "checkpoint": {
                        "phase": "pre_call",
                        "calls": 1,
                        "total_tokens": 100,
                        "usage_complete": False,
                        "status": "reserved",
                    },
                }])
            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(snapshot.last_event_seq, 3)
        self.assertEqual(
            snapshot.rows[-1]["prev_event_hash"],
            snapshot.rows[-2]["event_hash"],
        )
        self.assertEqual(
            snapshot.prefix_sha256,
            attempts.sha256_bytes(snapshot.prefix_bytes),
        )

    def test_torn_tail_from_crashed_append_is_repaired_by_write_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            committed = path.read_bytes()
            # Simulate a crash mid-line: readers must keep failing closed...
            with path.open("ab") as handle:
                handle.write(b'{"schema":"claim-reextract-attempt/v1"')
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "torn tail",
            ):
                attempts.read_attempt_log(root)

            # ...and the write side (recovery/append) heals back to the last
            # complete generation before appending its own events.
            attempts.recover_interrupted_attempts(root)
            healed = path.read_bytes()
            snapshot = attempts.read_attempt_log(root)

        self.assertTrue(healed.startswith(committed))
        self.assertNotIn(b'{"schema":"claim-reextract-attempt/v1"', healed[len(committed):])
        # The orphaned started attempt was terminalized by recovery on top of
        # the healed prefix.
        self.assertEqual(snapshot.last_event_seq, 2)
        self.assertEqual(snapshot.rows[-1]["event_kind"], "reextract_interrupted")

    def test_compaction_rewrites_canonical_file_via_atomic_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS

            skipped = attempts.compact_attempt_log(root)
            self.assertFalse(skipped["compacted"])
            self.assertEqual(skipped["rows"], 1)

            before = path.read_bytes()
            forced = attempts.compact_attempt_log(root, force=True)
            self.assertTrue(forced["compacted"])
            after = path.read_bytes()
            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(after, before)
        self.assertEqual(snapshot.last_event_seq, 1)

    def test_memoized_read_invalidates_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(first_id)])
            first = attempts.read_attempt_log(root)
            again = attempts.read_attempt_log(root)
            self.assertIs(first.rows, again.rows)

            second_start = _started(
                attempts.attempt_id("CQP-12345678-9abcdef0", "request-2")
            )
            second_start["idempotency_key"] = _hash("started-2")
            attempts.append_attempt_events(root, [second_start])
            third = attempts.read_attempt_log(root)

        self.assertIsNot(first.rows, third.rows)
        self.assertEqual(third.last_event_seq, 2)


class AttemptLogCompactionSkipTests(unittest.TestCase):
    """Compaction 的跳过条件 = “已是 canonical”（2026-08-14 修复）。

    compaction 从不删行（尝试历史是付费工作幂等重放的基底），所以一旦
    行数/字节超过阈值，旧条件 (canonical AND rows<=MAX AND bytes<=MAX) 在
    EVERY recovery（启动 + 每次队列执行）都失败并做一次 byte-identical 的
    整历史原子重写。修复后：canonical == raw_bytes 即跳过，与阈值无关；
    阈值只保留为报告输入（over_threshold）。撕裂尾部仍会愈合（写入侧
    load 先截断，canonical != raw 时重写路径依然可达）。"""

    def _terminal_history(self, root: Path) -> bytes:
        current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
        attempts.append_attempt_events(root, [
            _started(current_id),
            {
                **_common(current_id, "reextract_failed", "failed"),
                "outcome": {
                    "code": "remote_error",
                    "message": "boom",
                    "retryable": True,
                },
                "usage": {"calls": 1, "total_tokens": None, "usage_complete": False},
            },
        ])
        return (root / attempts.CLAIM_REEXTRACT_ATTEMPTS).read_bytes()

    def test_over_threshold_canonical_log_compacts_zero_times(self) -> None:
        writes: list[Path] = []
        real_writer = attempts.atomic_write_jsonl

        def counting_writer(path, rows):
            writes.append(Path(path))
            return real_writer(path, rows)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            committed = self._terminal_history(root)
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            self.assertGreater(len(committed), 8)

            with mock.patch.object(attempts, "_ATTEMPT_LOG_COMPACT_MAX_ROWS", 1), \
                    mock.patch.object(attempts, "_ATTEMPT_LOG_COMPACT_MAX_BYTES", 8), \
                    mock.patch.object(
                        attempts, "atomic_write_jsonl", side_effect=counting_writer,
                    ):
                first = attempts.compact_attempt_log(root)
                # Startup and EVERY queue execute run recovery; none of them may
                # rewrite the (already canonical) over-threshold history.
                for _ in range(3):
                    attempts.recover_interrupted_attempts(root)
                skipped = attempts.compact_attempt_log(root)
            after = path.read_bytes()
            snapshot = attempts.read_attempt_log(root)

        self.assertFalse(first["compacted"])
        self.assertTrue(first["over_threshold"])
        self.assertFalse(skipped["compacted"])
        self.assertTrue(skipped["over_threshold"])
        self.assertEqual(writes, [])
        self.assertEqual(after, committed)
        self.assertEqual(snapshot.last_event_seq, 2)

    def test_torn_tail_still_heals_without_threshold_escape(self) -> None:
        writes: list[Path] = []
        real_writer = attempts.atomic_write_jsonl

        def counting_writer(path, rows):
            writes.append(Path(path))
            return real_writer(path, rows)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            committed = self._terminal_history(root)
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            # Crash mid-line: readers must stay fail-closed on the torn tail.
            with path.open("ab") as handle:
                handle.write(b'{"schema":"claim-reextract-attempt/v1"')
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "torn tail",
            ):
                attempts.read_attempt_log(root)

            # Even under zero budget the healing must happen: the write-side
            # load truncates the uncommitted partial line back to the last
            # complete generation, so the file ends up canonical again.
            with mock.patch.object(attempts, "_ATTEMPT_LOG_COMPACT_MAX_ROWS", 1), \
                    mock.patch.object(attempts, "_ATTEMPT_LOG_COMPACT_MAX_BYTES", 8), \
                    mock.patch.object(
                        attempts, "atomic_write_jsonl", side_effect=counting_writer,
                    ):
                result = attempts.compact_attempt_log(root)
            healed = path.read_bytes()
            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(healed, committed)
        self.assertFalse(result["compacted"])
        self.assertEqual(writes, [])
        self.assertEqual(snapshot.last_event_seq, 2)
        self.assertEqual(snapshot.prefix_bytes, committed)

    def test_force_still_rewrites_canonical_history(self) -> None:
        writes: list[Path] = []
        real_writer = attempts.atomic_write_jsonl

        def counting_writer(path, rows):
            writes.append(Path(path))
            return real_writer(path, rows)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            committed = self._terminal_history(root)
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS

            with mock.patch.object(
                attempts, "atomic_write_jsonl", side_effect=counting_writer,
            ):
                forced = attempts.compact_attempt_log(root, force=True)
            after = path.read_bytes()
            snapshot = attempts.read_attempt_log(root)

        self.assertTrue(forced["compacted"])
        self.assertEqual(len(writes), 1)
        self.assertEqual(after, committed)
        self.assertEqual(snapshot.last_event_seq, 2)


class AttemptLogScaleBenchmarkTests(unittest.TestCase):
    """S10（2026-08-03 记录，2026-08-14 重设计）：_append_unlocked 原先每次
    追加整文件原子重写（O(N²)；N=300 实测 366.8s、N=50 共 11.2s）。现改为
    append 模式 + 每事件 fsync + 链头 memoization，N 次追加应近线性。本测试
    只挡数量级回归（如退化回整文件重写），不是精确性能门。"""

    def test_sequential_appends_scale_baseline(self) -> None:
        import time

        event_count = 300
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started_at = time.monotonic()
            for index in range(event_count):
                event = _started(
                    attempts.attempt_id("CQP-12345678-9abcdef0", f"request-{index}")
                )
                event["idempotency_key"] = _hash(f"started-{index}")
                attempts.append_attempt_events(root, [event])
            elapsed = time.monotonic() - started_at
            snapshot = attempts.read_attempt_log(root)
            self.assertEqual(len(snapshot.rows), event_count)
            # 旧实现 N=300 为 366.8s；上限 60s 只挡退化回 O(N²) 的回归。
            self.assertLess(
                elapsed,
                60.0,
                f"attempt log append regression: {elapsed:.2f}s for {event_count} events",
            )


class AttemptLogStableReadTests(unittest.TestCase):
    def test_stable_read_retries_transient_torn_tail_from_active_append(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            full = path.read_bytes()
            torn = full + b'{"schema":"claim-reextract-attempt/v1"'
            reads = iter([torn, torn + b"x", full, full])
            original = Path.read_bytes

            def fake_read(self: Path) -> bytes:
                if self == path:
                    return next(reads)
                return original(self)

            with mock.patch.object(Path, "read_bytes", fake_read):
                snapshot = attempts.read_attempt_log_stable(root, delay_seconds=0)

        self.assertEqual(snapshot.last_event_seq, 1)
        self.assertEqual(snapshot.prefix_bytes, full)

    def test_stable_read_does_not_call_identical_partial_bytes_permanent(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            full = path.read_bytes()
            torn = full + b'{"schema":"claim-reextract-attempt/v1"'
            reads = iter([torn, torn, full, full])
            original = Path.read_bytes

            def fake_read(self: Path) -> bytes:
                if self == path:
                    return next(reads)
                return original(self)

            with mock.patch.object(Path, "read_bytes", fake_read):
                snapshot = attempts.read_attempt_log_stable(
                    root, max_attempts=4, delay_seconds=0,
                )

        self.assertEqual(snapshot.last_event_seq, 1)
        self.assertEqual(snapshot.prefix_bytes, full)

    def test_stable_read_does_not_return_a_valid_but_changing_first_read(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_id = attempts.attempt_id(
                "CQP-12345678-9abcdef0", "request-1"
            )
            attempts.append_attempt_events(root, [_started(first_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            first = path.read_bytes()
            attempts.append_attempt_events(root, [{
                **_common(first_id, "reextract_failed", "failed"),
                "outcome": {
                    "code": "test_failure",
                    "message": "fixture",
                    "retryable": False,
                },
                "usage": {
                    "calls": 0,
                    "total_tokens": 0,
                    "usage_complete": True,
                },
            }])
            second = path.read_bytes()
            reads = iter([first, second, second])
            original = Path.read_bytes

            def fake_read(self: Path) -> bytes:
                if self == path:
                    return next(reads)
                return original(self)

            with mock.patch.object(Path, "read_bytes", fake_read):
                snapshot = attempts.read_attempt_log_stable(
                    root, delay_seconds=0,
                )

        self.assertEqual(snapshot.last_event_seq, 2)
        self.assertEqual(snapshot.prefix_bytes, second)

    def test_stable_read_fails_closed_on_permanent_torn_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            with (root / attempts.CLAIM_REEXTRACT_ATTEMPTS).open("ab") as handle:
                handle.write(b'{"schema":"claim-reextract-attempt/v1"')

            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "torn tail",
            ):
                attempts.read_attempt_log_stable(
                    root, max_attempts=3, delay_seconds=0
                )

    def test_stable_read_matches_plain_read_when_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])

            plain = attempts.read_attempt_log(root)
            stable = attempts.read_attempt_log_stable(root, delay_seconds=0)

        self.assertEqual(plain.prefix_sha256, stable.prefix_sha256)
        self.assertEqual(plain.last_event_seq, stable.last_event_seq)

    def test_stable_read_of_missing_log_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = attempts.read_attempt_log_stable(Path(tmp), delay_seconds=0)
        self.assertEqual(snapshot.last_event_seq, 0)
        self.assertEqual(snapshot.rows, [])

    def test_recovery_terminalizes_orphaned_reserved_call_with_unknown_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [
                _started(current_id),
                {
                    **_common(current_id, "budget_checkpoint", "budget-pre"),
                    "checkpoint": {
                        "phase": "pre_call",
                        "calls": 1,
                        "total_tokens": 0,
                        "usage_complete": True,
                        "status": "reserved",
                    },
                },
            ])

            recovered = attempts.recover_interrupted_attempts(root)
            second = attempts.recover_interrupted_attempts(root)
            rows = attempts.read_attempt_log(root).rows
            state = attempts.derive_attempt_states(rows)[current_id]

        self.assertEqual(recovered["interrupted"], 1)
        self.assertEqual(second["appended_count"], 0)
        self.assertEqual(state["lifecycle"], "interrupted")
        self.assertEqual(rows[-1]["event_kind"], "reextract_interrupted")
        self.assertEqual(rows[-1]["usage"], {
            "calls": 1,
            "total_tokens": None,
            "usage_complete": False,
        })

    def test_recovery_reconciles_published_patch_without_duplicate_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            row = {
                "ai_req_id": "AIR-recovered",
                "title": "Configurable output",
                "description": "The output is configurable.",
                "source_section": "4.1",
                "source_quote": "The output shall be configurable.",
                "source_block_ids": ["B1"],
            }
            patch = {
                "schema": "ai-supplement/v2",
                "supplement_id": "SUP-0123456789ab",
                "origin": {
                    "kind": "claim_queue",
                    "claim_id": "CLM-0123456789abcdef",
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "attempt_id": current_id,
                },
                "upserts": [row],
            }
            atomic_write_jsonl(root / AI_SUPPLEMENTS, [patch])
            atomic_write_jsonl(root / "ai_requirements.jsonl", [row])
            before = (root / "ai_requirements.jsonl").read_bytes()
            attempts.append_attempt_events(root, [
                _started(current_id),
                {
                    **_common(current_id, "budget_checkpoint", "budget-post"),
                    "checkpoint": {
                        "phase": "post_call",
                        "calls": 1,
                        "total_tokens": 523,
                        "usage_complete": True,
                        "status": "settled",
                    },
                },
            ])

            recovered = attempts.recover_interrupted_attempts(root)
            rows = attempts.read_attempt_log(root).rows
            state = attempts.derive_attempt_states(rows)[current_id]
            provenance = attempts.require_published_attempt(
                root,
                attempt_id=current_id,
                requirements_sha256=rows[-1]["requirements_sha256"],
            )
            after = (root / "ai_requirements.jsonl").read_bytes()

        self.assertEqual(recovered["recovered"], 1)
        self.assertEqual(state["lifecycle"], "rebuild_pending")
        self.assertEqual(
            [item["event_kind"] for item in rows[-2:]],
            ["supplement_persisted", "requirements_published"],
        )
        self.assertEqual(provenance["started"]["attempt_id"], current_id)
        self.assertEqual(after, before)


class AttemptAppendPermissionRetryTests(unittest.TestCase):
    """P2 一致性（2026-08-15）：true-append 写路径（open("ab") / 撕裂尾截断
    open("r+b")）此前是裸写——Windows AV/索引器瞬时占用会让 open 以
    PermissionError 失败，直接中止持锁追加。与 review_state/desktop_tasks 的
    替换重试及翻译日志同口径：8 次尝试 × 0.02s×(1..7) 线性退避，预算耗尽
    原样重抛（响亮失败）。

    原子性口径（文档化）：被拒的 open 落盘零字节，因此重试是干净的；每次
    尝试只追加完整的 canonical 行，且已 fsync 的行在重试时跳过——一行只落
    一次。写中途失败留下的至多是撕裂尾（读者侧 fail-closed + 写侧截断），
    不会出现胶着的半行进入已提交世代。"""

    def _attempt_log_path(self, root: Path) -> Path:
        # 与生产路径完全一致的解析（resolve + claim_artifact_path），保证
        # PurePath 相等比较成立。
        return attempts.claim_artifact_path(
            root.expanduser().resolve(),
            attempts.CLAIM_REEXTRACT_ATTEMPTS,
        )

    def _denied_open_patcher(self, path: Path, failures: int | None):
        """让目标文件的追加类 open（"ab"/"r+b"）前 ``failures`` 次抛
        PermissionError；``failures=None`` 表示永远拒绝。"""
        real_open = Path.open
        state = {"denied": 0}

        def selective_open(self: Path, mode: str = "r", *args, **kwargs):
            if (
                self == path
                and mode in {"a", "ab", "r+b"}
                and (failures is None or state["denied"] < failures)
            ):
                state["denied"] += 1
                raise PermissionError(13, "Permission denied", str(self))
            return real_open(self, mode, *args, **kwargs)

        return mock.patch.object(Path, "open", selective_open), state

    def _budget_checkpoint(self, current_id: str, suffix: str) -> dict:
        return {
            **_common(current_id, "budget_checkpoint", suffix),
            "checkpoint": {
                "phase": "pre_call",
                "calls": 1,
                "total_tokens": 4000,
                "usage_complete": False,
                "status": "reserved",
            },
        }

    def test_transient_permission_error_on_append_open_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = self._attempt_log_path(root)
            before = path.read_bytes()

            patcher, state = self._denied_open_patcher(path, failures=2)
            with patcher:
                result = attempts.append_attempt_events(
                    root,
                    [self._budget_checkpoint(current_id, "retry-append")],
                )

            self.assertEqual(state["denied"], 2)
            self.assertEqual(result["appended_count"], 1)
            after = path.read_bytes()
            self.assertTrue(after.startswith(before))
            self.assertTrue(after.endswith(b"\n"))
            snapshot = attempts.read_attempt_log(root)
            self.assertEqual(snapshot.last_event_seq, 2)

    def test_persistent_permission_error_raises_loud_and_keeps_log_well_formed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = self._attempt_log_path(root)
            before = path.read_bytes()

            patcher, state = self._denied_open_patcher(path, failures=None)
            with patcher:
                with self.assertRaises(PermissionError):
                    attempts.append_attempt_events(
                        root,
                        [self._budget_checkpoint(current_id, "denied-append")],
                    )

            # 8 次预算全部耗尽后才重抛——裸写（旧代码）第 1 次就穿透。
            self.assertEqual(state["denied"], attempts._APPEND_RETRY_ATTEMPTS)
            raw = path.read_bytes()
            self.assertEqual(raw, before)
            # 无胶着半行：已提交前缀完好且仍可完整解析。
            self.assertTrue(raw.endswith(b"\n"))
            snapshot = attempts.read_attempt_log(root)
            self.assertEqual(snapshot.last_event_seq, 1)
            self.assertEqual(snapshot.prefix_bytes, before)

    def test_retry_after_partial_batch_skips_already_committed_lines(self) -> None:
        # 批内第 2 行写入被拒：第 1 行已 fsync 落盘，重试必须只补第 2 行，
        # 不得重复追加第 1 行（旧行为：无重试，PermissionError 直接穿出）。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            path.write_bytes(b"")
            real_open = Path.open
            calls = {"n": 0}

            class _DenySecondLineHandle:
                def __init__(self, handle) -> None:
                    self._handle = handle
                    self._writes = 0

                def write(self, data):
                    self._writes += 1
                    if self._writes >= 2:
                        raise PermissionError(13, "Permission denied")
                    return self._handle.write(data)

                def flush(self):
                    self._handle.flush()

                def fileno(self):
                    return self._handle.fileno()

                def close(self):
                    self._handle.close()

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    self.close()
                    return False

            def selective_open(self: Path, mode: str = "r", *args, **kwargs):
                if self == path and mode == "ab":
                    calls["n"] += 1
                    if calls["n"] == 1:
                        return _DenySecondLineHandle(real_open(self, "ab"))
                return real_open(self, mode, *args, **kwargs)

            with mock.patch.object(Path, "open", selective_open):
                attempts._append_lines_unlocked(
                    path,
                    [b'{"event":1}\n', b'{"event":2}\n'],
                )

            self.assertEqual(calls["n"], 2)
            self.assertEqual(path.read_bytes(), b'{"event":1}\n{"event":2}\n')

    def test_transient_permission_error_on_torn_tail_truncate_is_retried(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            raw = b'{"a":1}\n{"torn'
            path.write_bytes(raw)

            patcher, state = self._denied_open_patcher(path, failures=1)
            with patcher:
                healed = attempts._truncate_torn_tail(path, raw)

            self.assertEqual(state["denied"], 1)
            self.assertEqual(healed, b'{"a":1}\n')
            self.assertEqual(path.read_bytes(), b'{"a":1}\n')


class AttemptLogMemoIdentityTests(unittest.TestCase):
    """stat 身份加固（2026-08-15）：memo 键从 (size, mtime_ns, ctime_ns) 升级为
    含 (st_ino, st_dev)。Windows 的 os.replace 可被「同尺寸原子替换 + os.utime
    还原 mtime + SetFileTime 还原创建时间（st_ctime_ns）」完全伪造——旧三元组
    命中，memo 继续吐旧行（NTFS 时间戳量子化时无需 SetFileTime 也偶发成立）。
    新键：原子替换必换文件身份 → 必 miss 重扫；st_ino==0 的文件系统退化为旧
    三元组强度（不劣化）。"""

    @staticmethod
    def _restore_creation_time(path: Path, ctime_ns: int) -> bool:
        """Windows：SetFileTime 显式还原创建时间。ctypes 签名必须齐全，
        否则 64 位句柄被截断成 int，SetFileTime 静默失败。"""
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ]
        kernel32.SetFileTime.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateFileW(
            str(path), 0x0100, 0, None, 3, 0x80, None,
        )  # FILE_WRITE_ATTRIBUTES / OPEN_EXISTING
        if not handle:
            return False
        try:
            value = ctime_ns // 100 + 116444736000000000  # 1970 纪元→1601 纪元（100ns 单位）
            file_time = wintypes.FILETIME(value & 0xFFFFFFFF, (value >> 32) & 0xFFFFFFFF)
            return bool(kernel32.SetFileTime(handle, ctypes.byref(file_time), None, None))
        finally:
            kernel32.CloseHandle(handle)

    @unittest.skipUnless(
        sys.platform == "win32",
        "creation-time restore spoof is Windows-specific; on POSIX st_ctime "
        "cannot be restored by utime so the legacy triple already invalidates",
    )
    def test_samesize_atomic_replace_with_restored_mtime_invalidates_memo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(first_id)])
            first = attempts.read_attempt_log(root)
            again = attempts.read_attempt_log(root)
            self.assertIs(first.rows, again.rows)

            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            before = path.stat()
            tmp_file = path.with_name(path.name + ".spoof.tmp")
            tmp_file.write_bytes(path.read_bytes())
            os.replace(tmp_file, path)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertTrue(
                self._restore_creation_time(path, before.st_ctime_ns),
                "spoof fixture must be able to restore creation time",
            )
            after = path.stat()
            # 前置断言：旧三元组被完全伪造（同尺寸 + mtime/ctime 均已还原）。
            self.assertEqual(
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns),
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            )
            # 文件身份已换（os.replace 给路径换上 tmp 的身份）——修复的失效条件。
            self.assertNotEqual(
                (before.st_dev, before.st_ino),
                (after.st_dev, after.st_ino),
                "atomic replace must change file identity on this filesystem",
            )

            third = attempts.read_attempt_log(root)

        # 旧键（红）：memo 命中，rows 列表对象被复用；新键：重扫得到新列表。
        self.assertIsNot(first.rows, third.rows)
        self.assertEqual(first.rows, third.rows)
        self.assertEqual(third.last_event_seq, 1)


if __name__ == "__main__":
    unittest.main()
