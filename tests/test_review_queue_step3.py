"""评审队列收敛第 3 步：A/B 专家裁决双写切换回归。

覆盖（任务七类）：
- A/B 各自裁决 → 队列事件 + 旧文件行字节形状与旧 writer 一致（键序/ensure_ascii/
  LF/整文件重写或 append 的行序语义）；
- 幂等键重放不追加、不重复投影（且重放跳过锁外 fold——与第 2 步语义一致）；
- 崩溃窗口：队列有事件、旧文件缺行 → 下次写入补齐投影且 merge 语义正确
  （A 轨行原位替换/追加 + 行序保持；B 轨 append 前缀补齐）；
- CAS 失配仍抛原异常（A 轨 ReviewAuthorityConflict / B 轨 AIReviewAuthorityConflict，
  携带 current_revision 材料）且链与文件零变化；
- 裁决后 effective fold 仍被触发（B 轨 E2E：真实直抽产物 → 专家接受 → fold →
  effective 可读；A/B 轨 track 断言；锁序：fold 在队列/状态锁全部释放之后）；
- 旧包兼容：无队列文件的目录上读写照常，首次写入只链接本次事件（无历史回填）；
- 哈希链跨 subject_kind 连续（omission/内部核对/atom_expert/ai_review 混排追加
  链不断）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import ai_review_actions
import clarification_check_states as check_states
import omission_actions
import review_queue
import review_state
from result_package import initialize_result_package


def _write_blocks(out: Path, *blocks: dict) -> None:
    with (out / "blocks.jsonl").open("w", encoding="utf-8") as handle:
        for block in blocks:
            handle.write(json.dumps(block, ensure_ascii=False) + "\n")


def _queue_path(out: Path) -> Path:
    return out / review_queue.REVIEW_QUEUE_EVENTS


def _read_states_file(out: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (out / "review_states.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_ai_states_file(out: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (out / "ai_review_states.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _strip_token(state: dict) -> dict:
    """apply 返回值附带 target_authority_write_revision；投影行/事件 payload 不含它。"""
    row = dict(state)
    row.pop("target_authority_write_revision", None)
    row.pop("audit_warning", None)
    return row


class AtomExpertDualWriteTests(unittest.TestCase):
    """A 轨 apply_expert_decision：队列先落 + 旧文件逐字节投影。"""

    def test_projection_matches_legacy_writer_byte_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert", reason="通过",
            )
            second = review_state.apply_expert_decision(
                out, "SREQ-2", "rejected", actor="expert",
            )
            # 同一 requirement 改判：history 追加、行原位替换（整文件重写语义）。
            third = review_state.apply_expert_decision(
                out, "SREQ-1", "needs_discussion", actor="expert", reason="再看",
            )
            raw = (out / "review_states.jsonl").read_text(encoding="utf-8")
            events = review_queue.read_review_queue_events(out)
            states = _read_states_file(out)

        lines = raw.splitlines(keepends=True)
        # 旧 writer 行形状（基准：_atomic_write_jsonl——每行 json.dumps(row,
        # ensure_ascii=False) + LF；行序 = states 列表序，改判行原位替换）。
        self.assertEqual(len(lines), 2)
        for line, state in zip(lines, (third, second)):
            self.assertEqual(line, json.dumps(_strip_token(state), ensure_ascii=False) + "\n")
            self.assertEqual(
                list(json.loads(line, object_pairs_hook=dict)),
                ["requirement_id", "status", "history", "metadata", "level"],
            )
        self.assertIn("通过", raw)  # 非 ASCII 不转义，与旧 writer 一致
        self.assertEqual(
            [json.loads(line)["requirement_id"] for line in lines],
            ["SREQ-1", "SREQ-2"],
        )
        # to_dict 的 history 事件键序（from_status/to_status/actor/reason/timestamp）
        first_event = json.loads(lines[0], object_pairs_hook=dict)["history"][0]
        self.assertEqual(
            list(first_event),
            ["from_status", "to_status", "actor", "reason", "timestamp"],
        )
        # 队列侧：payload 与投影行逐字段一致；事件按主体分派。
        self.assertEqual(
            [event["subject_kind"] for event in events],
            [review_queue.SUBJECT_KIND_ATOM_EXPERT] * 3,
        )
        self.assertEqual(
            [event["payload"] for event in events],
            [_strip_token(first), _strip_token(second), _strip_token(third)],
        )
        self.assertEqual([event["subject_id"] for event in events],
                         ["SREQ-1", "SREQ-2", "SREQ-1"])
        self.assertEqual([event["event_kind"] for event in events],
                         ["decided", "decided", "decided"])
        self.assertEqual(
            [event["legacy_source_store"] for event in events],
            ["review_states.jsonl"] * 3,
        )
        # 事件指纹 = 本主体既有权威身份公式（写盘后对更新行集的物理写修订）。
        # events[2] 是 SREQ-1 的最后一次裁决——其指纹与当前行集的修订一致。
        self.assertEqual(
            events[2]["subject_fingerprint"],
            review_state.atomic_target_authority_write_revision("SREQ-1", states),
        )

    def test_repeat_same_status_appends_no_queue_event(self) -> None:
        """同状态重复点击：旧 writer 只重写文件不追加事件侧账本——队列对称。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            events = review_queue.read_review_queue_events(out)
            rows = _read_states_file(out)

        self.assertEqual(len(events), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["history"]), 1)

    def test_explicit_idempotency_key_replay_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
                idempotency_key="retry-1",
            )
            second = review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
                idempotency_key="retry-1",
            )
            events = review_queue.read_review_queue_events(out)
            rows = _read_states_file(out)

        self.assertEqual(_strip_token(second), _strip_token(first))
        self.assertEqual(len(events), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["history"]), 1)

    def test_crash_window_projection_is_repaired_with_merge_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            # 旧包存量行（队列出现之前的历史，合法形态——不做历史回填）。
            legacy_row = {
                "requirement_id": "SREQ-0",
                "status": "llm_reviewed",
                "history": [{
                    "from_status": "candidate", "to_status": "llm_reviewed",
                    "actor": "llm", "reason": "", "timestamp": "2026-01-01T00:00:00",
                }],
                "metadata": {"stable_req_id": "SREQ-0"},
                "level": "atomic",
            }
            (out / "review_states.jsonl").write_text(
                json.dumps(legacy_row, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            first = review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            # 模拟崩溃窗口：队列事件已落、旧文件投影未落（SREQ-1 行被丢）。
            remaining = [
                row for row in _read_states_file(out)
                if row["requirement_id"] != "SREQ-1"
            ]
            (out / "review_states.jsonl").write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False) + "\n" for row in remaining
                ),
                encoding="utf-8",
            )

            second = review_state.apply_expert_decision(
                out, "SREQ-2", "rejected", actor="expert",
            )
            rows = _read_states_file(out)
            events = review_queue.read_review_queue_events(out)
            authority = review_state.read_review_authority_snapshot(out)

        self.assertEqual(len(events), 2)
        # merge 语义：存量行在前，补投影按事件序回填（SREQ-1 追加于其后），
        # 本次裁决（SREQ-2）最后追加——与旧 writer "读-改-写整列表" 一致。
        self.assertEqual(
            [row["requirement_id"] for row in rows],
            ["SREQ-0", "SREQ-1", "SREQ-2"],
        )
        self.assertEqual(rows[0], legacy_row)
        self.assertEqual(rows[1], _strip_token(first))
        self.assertEqual(rows[2], _strip_token(second))
        self.assertEqual(authority["states"], rows)

    def test_write_revision_cas_mismatch_leaves_files_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            before_states = (out / "review_states.jsonl").read_bytes()
            before_events = _queue_path(out).read_bytes()
            with self.assertRaises(review_state.ReviewAuthorityConflict) as ctx:
                review_state.apply_expert_decision(
                    out, "SREQ-1", "rejected", actor="expert",
                    expected_target_authority_write_revision="stale-revision",
                )
            # 原 409 材料：current_revision 是重算的真实权威值，不是提交值。
            self.assertIn("review authority changed", str(ctx.exception))
            self.assertNotEqual(ctx.exception.current_revision, "stale-revision")
            self.assertEqual((out / "review_states.jsonl").read_bytes(), before_states)
            self.assertEqual(_queue_path(out).read_bytes(), before_events)

    def test_subject_fingerprint_cas_mismatch_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "atomic_requirements.jsonl").write_text(
                json.dumps({
                    "requirement_id": "SREQ-1", "title": "The meter shall log events.",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(review_state.ReviewAuthorityConflict) as ctx:
                review_state.apply_expert_decision(
                    out, "SREQ-1", "accepted", actor="expert",
                    expected_target_fingerprint="stale-fingerprint",
                )
            self.assertIn("atomic requirement changed", str(ctx.exception))

            self.assertFalse((out / "review_states.jsonl").exists())
            self.assertFalse(_queue_path(out).exists())

    def test_frozen_cannot_be_overridden_and_nothing_lands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            frozen_row = {
                "requirement_id": "SREQ-F", "status": "frozen",
                "history": [{
                    "from_status": "accepted", "to_status": "frozen",
                    "actor": "expert", "reason": "", "timestamp": "2026-01-01T00:00:00",
                }],
                "metadata": {}, "level": "atomic",
            }
            (out / "review_states.jsonl").write_text(
                json.dumps(frozen_row, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                review_state.apply_expert_decision(
                    out, "SREQ-F", "accepted", actor="expert",
                )
            self.assertFalse(_queue_path(out).exists())
            self.assertEqual(_read_states_file(out), [frozen_row])

    def test_old_package_without_queue_file_is_readable_and_writable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            legacy_row = {
                "requirement_id": "SREQ-OLD", "status": "accepted",
                "history": [{
                    "from_status": "candidate", "to_status": "accepted",
                    "actor": "old-exe", "reason": "", "timestamp": "2026-01-01T00:00:00",
                }],
                "metadata": {}, "level": "atomic",
            }
            (out / "review_states.jsonl").write_text(
                json.dumps(legacy_row, ensure_ascii=False) + "\n", encoding="utf-8",
            )

            before = review_state.read_review_authority_snapshot(out)
            state = review_state.apply_expert_decision(
                out, "SREQ-NEW", "expert_pending", actor="expert",
            )
            after = review_state.read_review_authority_snapshot(out)
            events = review_queue.read_review_queue_events(out)

        self.assertEqual([row["requirement_id"] for row in before["states"]],
                         ["SREQ-OLD"])
        # 首次写入创建队列并只链接本次事件——不做历史回填（设计 §4.3）。
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"], _strip_token(state))
        self.assertEqual(
            [row["requirement_id"] for row in after["states"]],
            ["SREQ-OLD", "SREQ-NEW"],
        )


class AiReviewDualWriteTests(unittest.TestCase):
    """B 轨 apply_ai_review_action：队列先落 + 旧文件 append 投影。"""

    def test_projection_matches_legacy_writer_byte_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert", reason="通过",
                module_override="计量",
            )
            second = ai_review_actions.apply_ai_review_action(
                out, "AIR-2", "needs_discussion", actor="expert",
                level="functional",
                source_fingerprint_value="src-fp",
                review_subject_fingerprint_value="subj-fp",
                review_anchor_fingerprint_value="anchor-fp",
            )
            third = ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "rejected", actor="expert",
            )
            raw = (out / "ai_review_states.jsonl").read_text(encoding="utf-8")
            events = review_queue.read_review_queue_events(out)
            states = ai_review_actions.read_ai_review_states(out)

        # 旧 writer 行形状（基准：append + fsync，逐行 json.dumps(ensure_ascii=False)）。
        rows = [_strip_token(first), _strip_token(second), _strip_token(third)]
        self.assertEqual(
            raw,
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        )
        # 行键序 = 旧 writer 的构造序（可选键按传入顺序追加在 recorded_at 之后）。
        self.assertEqual(
            list(json.loads(raw.splitlines()[0], object_pairs_hook=dict)),
            ["ai_req_id", "status", "module_override", "ownership_override",
             "reason", "actor", "recorded_at"],
        )
        self.assertEqual(
            list(json.loads(raw.splitlines()[1], object_pairs_hook=dict)),
            ["ai_req_id", "status", "module_override", "ownership_override",
             "reason", "actor", "recorded_at", "level", "source_fingerprint",
             "review_subject_fingerprint", "review_anchor_fingerprint"],
        )
        self.assertIn("通过", raw)  # 非 ASCII 不转义
        # 追加写 last-wins：读者取每 ai_req_id 最新一行。
        self.assertEqual(states["AIR-1"]["status"], "rejected")
        # 队列侧：payload 与投影行逐字段一致。
        self.assertEqual(
            [event["subject_kind"] for event in events],
            [review_queue.SUBJECT_KIND_AI_REVIEW] * 3,
        )
        self.assertEqual([event["payload"] for event in events], rows)
        self.assertEqual(
            [event["legacy_source_store"] for event in events],
            ["ai_review_states.jsonl"] * 3,
        )
        # 事件指纹 = 本主体既有权威身份公式（对追加后字节的物理写修订，与
        # 返回给调用方的 CAS 代币同源）。
        self.assertEqual(
            events[1]["subject_fingerprint"],
            second["target_authority_write_revision"],
        )

    def test_explicit_idempotency_key_replay_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
                idempotency_key="retry-1",
            )
            second = ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
                idempotency_key="retry-1",
            )
            events = review_queue.read_review_queue_events(out)
            file_rows = _read_ai_states_file(out)

        self.assertEqual(_strip_token(second), _strip_token(first))
        self.assertEqual(len(events), 1)
        self.assertEqual(len(file_rows), 1)

    def test_crash_window_projection_is_repaired_on_next_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
            )
            # 模拟崩溃窗口：队列事件已落、旧文件投影未落。
            (out / "ai_review_states.jsonl").write_text("", encoding="utf-8")

            second = ai_review_actions.apply_ai_review_action(
                out, "AIR-2", "rejected", actor="expert",
            )
            file_rows = _read_ai_states_file(out)
            events = review_queue.read_review_queue_events(out)
            states = ai_review_actions.read_ai_review_states(out)

        self.assertEqual(len(events), 2)
        # append-only 前缀补齐：按事件序回填 AIR-1，再追加本次 AIR-2。
        self.assertEqual([row["ai_req_id"] for row in file_rows], ["AIR-1", "AIR-2"])
        self.assertEqual(file_rows[0], _strip_token(first))
        self.assertEqual(file_rows[1], _strip_token(second))
        self.assertEqual(states["AIR-1"]["status"], "accepted")

    def test_write_revision_cas_mismatch_leaves_files_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
            )
            before_states = (out / "ai_review_states.jsonl").read_bytes()
            before_events = _queue_path(out).read_bytes()
            with self.assertRaises(
                ai_review_actions.AIReviewAuthorityConflict
            ) as ctx:
                ai_review_actions.apply_ai_review_action(
                    out, "AIR-1", "rejected", actor="expert",
                    expected_target_authority_write_revision="stale-revision",
                )
            self.assertIn("AI review authority changed", str(ctx.exception))
            self.assertNotEqual(ctx.exception.current_revision, "stale-revision")
            self.assertEqual((out / "ai_review_states.jsonl").read_bytes(), before_states)
            self.assertEqual(_queue_path(out).read_bytes(), before_events)

    def test_old_package_without_queue_file_is_readable_and_writable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            legacy_row = {
                "ai_req_id": "AIR-OLD", "status": "accepted",
                "module_override": None, "ownership_override": None,
                "reason": "", "actor": "old-exe",
                "recorded_at": "2026-01-01T00:00:00+00:00",
            }
            (out / "ai_review_states.jsonl").write_text(
                json.dumps(legacy_row, ensure_ascii=False) + "\n", encoding="utf-8",
            )

            before = ai_review_actions.read_ai_review_states(out)
            state = ai_review_actions.apply_ai_review_action(
                out, "AIR-NEW", "expert_pending", actor="expert",
            )
            after = ai_review_actions.read_ai_review_states(out)
            events = review_queue.read_review_queue_events(out)

        self.assertEqual(list(before), ["AIR-OLD"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"], _strip_token(state))
        self.assertEqual(sorted(after), ["AIR-NEW", "AIR-OLD"])


class EffectiveFoldHookTests(unittest.TestCase):
    """红线：fold 触发时机/协调器/超时语义一字不动——锁外触发、track 正确、
    幂等重放跳过。"""

    @staticmethod
    def _with_claim_generation(out: Path) -> None:
        (out / "claim_generation.meta.json").write_text("{}", encoding="utf-8")

    def test_a_track_decision_triggers_fold_outside_locks(self) -> None:
        order: list[str] = []
        real_state_lock = review_state.review_state_lock
        real_queue_lock = review_queue.review_queue_lock

        @contextmanager
        def recording_state_lock(*args, **kwargs):
            with real_state_lock(*args, **kwargs):
                yield
            order.append("state-lock-exit")

        @contextmanager
        def recording_queue_lock(*args, **kwargs):
            with real_queue_lock(*args, **kwargs):
                yield
            order.append("queue-lock-exit")

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._with_claim_generation(out)
            with patch(
                "review_state.cover_effective_fold_after_decision",
                side_effect=lambda *a, **k: order.append("fold-call"),
            ) as fold_hook, patch(
                "review_state.review_state_lock", recording_state_lock,
            ), patch(
                "review_queue.review_queue_lock", recording_queue_lock,
            ):
                review_state.apply_expert_decision(
                    out, "SREQ-1", "accepted", actor="expert",
                )

        fold_hook.assert_called_with(
            out,
            actor_trigger="requirement-review-action",
            authority_hook_track="A",
        )
        # 锁序红线：fold 在队列锁与状态锁全部退出之后才触发（claim 锁族在
        # 队列/状态锁之外获取——锁序不能反转）。
        self.assertEqual(
            order, ["state-lock-exit", "queue-lock-exit", "fold-call"],
        )

    def test_b_track_decision_triggers_fold_outside_locks(self) -> None:
        order: list[str] = []
        real_lock = ai_review_actions._ai_review_state_lock

        @contextmanager
        def recording_lock(*args, **kwargs):
            with real_lock(*args, **kwargs):
                yield
            order.append("ai-state-lock-exit")

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._with_claim_generation(out)
            with patch(
                "review_state.cover_effective_fold_after_decision",
                side_effect=lambda *a, **k: order.append("fold-call"),
            ) as fold_hook, patch(
                "ai_review_actions._ai_review_state_lock", recording_lock,
            ):
                ai_review_actions.apply_ai_review_action(
                    out, "AIR-1", "accepted", actor="expert",
                )

        fold_hook.assert_called_once()
        self.assertEqual(fold_hook.call_args.kwargs["authority_hook_track"], "B")
        self.assertEqual(fold_hook.call_args.kwargs["actor_trigger"], "ai-review-action")
        self.assertEqual(order, ["ai-state-lock-exit", "fold-call"])

    def test_no_claim_generation_skips_fold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with patch(
                "review_state.cover_effective_fold_after_decision",
            ) as fold_hook:
                review_state.apply_expert_decision(
                    out, "SREQ-1", "accepted", actor="expert",
                )
                ai_review_actions.apply_ai_review_action(
                    out, "AIR-1", "accepted", actor="expert",
                )
            fold_hook.assert_not_called()

    def test_idempotent_replay_skips_fold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._with_claim_generation(out)
            ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
                idempotency_key="retry-1",
            )
            with patch(
                "review_state.cover_effective_fold_after_decision",
            ) as fold_hook:
                ai_review_actions.apply_ai_review_action(
                    out, "AIR-1", "accepted", actor="expert",
                    idempotency_key="retry-1",
                )
            fold_hook.assert_not_called()


class CrossSubjectChainTests(unittest.TestCase):
    """哈希链跨 subject_kind 连续：四类主体混排追加链不断。"""

    def test_mixed_subjects_share_one_contiguous_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )
            check_states.apply_clarification_check_action(
                out, "CLR-1", "verified_ok", evidence_fingerprint="e1", actor="A",
            )
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
            )
            omission_actions.apply_omission_action(
                out, block_id="B1", status="issue_confirmed", actor="reviewer",
            )
            events = review_queue.read_review_queue_events(out)

        self.assertEqual(
            [event["subject_kind"] for event in events],
            [
                review_queue.SUBJECT_KIND_OMISSION,
                review_queue.SUBJECT_KIND_CLARIFICATION_INTERNAL,
                review_queue.SUBJECT_KIND_ATOM_EXPERT,
                review_queue.SUBJECT_KIND_AI_REVIEW,
                review_queue.SUBJECT_KIND_OMISSION,
            ],
        )
        self.assertEqual([event["event_seq"] for event in events], [1, 2, 3, 4, 5])
        for previous, row in zip(events, events[1:]):
            self.assertEqual(row["prev_event_hash"], previous["event_hash"])
        for row in events:
            self.assertEqual(
                row["legacy_source_store"],
                review_queue.SUBJECT_KIND_LEGACY_STORES[row["subject_kind"]],
            )


class GovernedStateDirTests(unittest.TestCase):
    """package_v1：队列与两个旧文件都落 .ratomizer/state/（governed 寻址）。"""

    def test_queue_and_projections_land_in_governed_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "input.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(
                root, input_path=source, requested_stages=["atomize"],
            )
            _write_blocks(root, {"block_id": "B1", "text": "The meter shall log events."})

            review_state.apply_expert_decision(
                root, "SREQ-1", "accepted", actor="expert",
            )
            ai_review_actions.apply_ai_review_action(
                root, "AIR-1", "accepted", actor="expert",
            )
            state_dir = root / ".ratomizer" / "state"
            names = {path.name for path in state_dir.iterdir()}

        self.assertIn(review_queue.REVIEW_QUEUE_EVENTS, names)
        self.assertIn("review_states.jsonl", names)
        self.assertIn("ai_review_states.jsonl", names)


class DirectModeFoldE2ETests(unittest.TestCase):
    """E2E：真实直抽产物 → 专家接受（level=functional）→ fold → effective 可读。

    搭建复用 tests/test_claim_functional_store.py 的 DirectMode 全闭链路前段
    （注入 chat 的真实直抽 + claim shadow 发布）；本测试只钉第 3 步的红线：
    裁决经队列+投影双写后，锁外的 effective fold 照常触发且 effective 可读。
    """

    def test_expert_accept_folds_effective_after_queue_dual_write(self) -> None:
        import desktop_tasks
        import functional_extract as fe

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "blocks.jsonl").write_text(
                '{"block_id":"B1","section_path":["4.1"],"text":"The meter shall log events."}\n',
                encoding="utf-8",
            )
            (out / "chunks.jsonl").write_text(
                '{"section_path":["4.1"],"heading":"4.1",'
                '"text":"The meter shall log events.","block_ids":["B1"]}\n',
                encoding="utf-8",
            )
            sections = [{
                "section_id": "4.1", "section_path": ["4.1"], "heading": "4.1",
                "text": "The meter shall log events.", "block_ids": ["B1"],
            }]

            def chat(system: str, user: str) -> dict:
                return {"items": [{
                    "objective": "The meter shall log events.",
                    "behaviors": ["log events"],
                    "source_quote": "The meter shall log events.",
                    "source_block_ids": ["B1"],
                }]}

            result = fe.run_functional_extract(
                out, sections=sections, chat=chat, route="openai_compatible")
            self.assertEqual(result["execution_status"], "ok")
            desktop_tasks._publish_functional_claim_shadow(
                out, route="openai_compatible")

            from ai_review_actions import (
                review_anchor_fingerprint,
                review_subject_fingerprint,
                source_ai_requirement_id,
                source_fingerprint,
            )
            from requirements_analysis_rules import _read_functional_requirements_payload
            item = _read_functional_requirements_payload(out)["items"][0]
            rid = source_ai_requirement_id(item)
            state = ai_review_actions.apply_ai_review_action(
                out, rid, "accepted",
                level="functional", actor="expert",
                source_fingerprint_value=source_fingerprint(item),
                review_subject_fingerprint_value=review_subject_fingerprint(item),
                review_anchor_fingerprint_value=review_anchor_fingerprint(item),
            )

            events = review_queue.read_review_queue_events(out)
            ai_rows = _read_ai_states_file(out)
            effective = [
                json.loads(line) for line in
                (out / "claim_effective_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            effective_meta = json.loads(
                (out / "claim_effective.meta.json").read_text(encoding="utf-8"))

        # 队列 + 投影双写都在场，payload 即落盘行。
        self.assertEqual(
            [event["subject_kind"] for event in events],
            [review_queue.SUBJECT_KIND_AI_REVIEW],
        )
        self.assertEqual(events[0]["subject_id"], rid)
        self.assertEqual(events[0]["payload"], _strip_token(state))
        self.assertEqual(ai_rows[-1], _strip_token(state))
        self.assertEqual(ai_rows[-1].get("level"), "functional")
        # fold 已跑：effective ledger 非空可读、meta 可解析（apply 返回即代表
        # 覆盖性 fold pass 完成或如实超时——此处断言其在锁外正常完成）。
        self.assertTrue(effective)
        self.assertTrue(effective_meta)


if __name__ == "__main__":
    unittest.main()
