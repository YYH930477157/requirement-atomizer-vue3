"""评审队列统一事件链（队列收敛第 2 步）回归。

覆盖：链 append/幂等重放/撕裂尾恢复/中部损坏 fail-closed/链哈希验证；
omission 与内部核对写路径经队列后旧文件行形状与旧 writer 逐字节等价；
崩溃窗口投影补齐；omission CAS 与内部核对 expected_evidence_fingerprint
写时 CAS 的正反例；旧包（无队列文件）可读可写；API 409 契约形状。
"""
from __future__ import annotations

import json
import multiprocessing
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import api_server
import clarification_check_states as check_states
import clarification_report as cr
import omission_actions
import review_queue
from result_package import initialize_result_package


def _write_blocks(out: Path, *blocks: dict) -> None:
    with (out / "blocks.jsonl").open("w", encoding="utf-8") as handle:
        for block in blocks:
            handle.write(json.dumps(block, ensure_ascii=False) + "\n")


def _seed_internal_report(out: Path) -> dict:
    """Seed one internal clarification question and return its report entry."""
    (out / "ai_requirements.jsonl").write_text(
        json.dumps({
            "ai_req_id": "AIR-1",
            "title": "T",
            "module": "计量",
            "source_section": "4",
            "source_quote": "source text",
            "suspicion_reasons": ["引用非逐字"],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return cr.run_report(out)["entries"][0]


def _draft(**overrides) -> dict:
    draft = {
        "subject_kind": review_queue.SUBJECT_KIND_OMISSION,
        "subject_id": "OMI-1",
        "subject_fingerprint": "fp-1",
        "idempotency_key": "key-1",
        "event_kind": "decided",
        "actor": "reviewer",
        "recorded_at": "2026-08-28T00:00:00+00:00",
        "reason": "triaged",
        "payload": {"omission_id": "OMI-1", "status": "non_requirement"},
    }
    draft.update(overrides)
    return draft


def _queue_path(out: Path) -> Path:
    return out / review_queue.REVIEW_QUEUE_EVENTS


class ReviewQueueChainTests(unittest.TestCase):
    def test_append_builds_contiguous_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_queue.append_review_queue_event(out, _draft())
            review_queue.append_review_queue_event(
                out, _draft(idempotency_key="key-2", subject_id="OMI-2",
                            subject_fingerprint="fp-2")
            )
            review_queue.append_review_queue_event(
                out, _draft(idempotency_key="key-3", subject_id="OMI-3",
                            subject_fingerprint="fp-3")
            )

            rows = review_queue.read_review_queue_events(out)
            raw = _queue_path(out).read_bytes()

        self.assertEqual([row["event_seq"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0]["prev_event_hash"], review_queue._GENESIS_PREV_EVENT_HASH)
        for previous, row in zip(rows, rows[1:]):
            self.assertEqual(row["prev_event_hash"], previous["event_hash"])
            self.assertNotEqual(row["event_hash"], previous["event_hash"])
        for row in rows:
            self.assertEqual(row["event_hash"], review_queue.compute_event_hash(row))
            self.assertEqual(
                row["event_id"],
                review_queue.build_event_id(row["event_seq"], row["idempotency_key"]),
            )
            self.assertEqual(row["schema"], review_queue.REVIEW_QUEUE_EVENT_SCHEMA)
            self.assertEqual(row["legacy_source_store"], "omission_states.jsonl")
        # 文件行是规范 JSON（排序键、紧凑、LF 结尾）。
        for line, row in zip(raw.splitlines(keepends=True), rows):
            self.assertEqual(line, review_queue._canonical_bytes(row) + b"\n")

    def test_idempotent_replay_returns_existing_event_without_new_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first, replayed_first = review_queue.append_review_queue_event(out, _draft())
            self.assertFalse(replayed_first)
            second, replayed_second = review_queue.append_review_queue_event(
                out, _draft(payload={"omission_id": "OMI-1", "status": "resolved"})
            )
            rows = review_queue.read_review_queue_events(out)

        self.assertTrue(replayed_second)
        self.assertEqual(second, first)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payload"], first["payload"])

    def test_authority_write_revision_counts_subject_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            for key, subject in (("k1", "OMI-1"), ("k2", "OMI-1"), ("k3", "OMI-2")):
                review_queue.append_review_queue_event(
                    out, _draft(idempotency_key=key, subject_id=subject)
                )
            rows = review_queue.read_review_queue_events(out)

        self.assertEqual([row["authority_write_revision"] for row in rows], [1, 2, 1])

    def test_torn_tail_is_recovered_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_queue.append_review_queue_event(out, _draft())
            review_queue.append_review_queue_event(
                out, _draft(idempotency_key="key-2", subject_id="OMI-2")
            )
            path = _queue_path(out)
            # 模拟中断写残片：完整文件之后跟一段无行终止符的半行。
            path.write_bytes(path.read_bytes() + b'{"schema": "rev')

            rows = review_queue.read_review_queue_events(out)
            self.assertEqual([row["event_seq"] for row in rows], [1, 2])
            # 恢复后文件回到规范形态，后续 append 可继续接链。
            review_queue.append_review_queue_event(
                out, _draft(idempotency_key="key-3", subject_id="OMI-3")
            )
            rows = review_queue.read_review_queue_events(out)
            final = path.read_bytes()

        self.assertEqual([row["event_seq"] for row in rows], [1, 2, 3])
        self.assertTrue(final.endswith(b"\n"))

    def test_midfile_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_queue.append_review_queue_event(out, _draft())
            review_queue.append_review_queue_event(
                out, _draft(idempotency_key="key-2", subject_id="OMI-2")
            )
            review_queue.append_review_queue_event(
                out, _draft(idempotency_key="key-3", subject_id="OMI-3")
            )
            # 首行是被完整终止的坏行（io_utils 纪律：已终止的坏行不恢复，响亮抛错）。
            lines = _queue_path(out).read_text(encoding="utf-8").splitlines(keepends=True)
            lines[0] = "not-json\n"
            _queue_path(out).write_text("".join(lines), encoding="utf-8")

            with self.assertRaises(review_queue.ReviewQueueError):
                review_queue.read_review_queue_events(out)

    def test_chain_hash_tamper_fails_closed(self) -> None:
        for mutate in ("payload", "prev_event_hash", "event_seq"):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as td:
                out = Path(td)
                review_queue.append_review_queue_event(out, _draft())
                review_queue.append_review_queue_event(
                    out, _draft(idempotency_key="key-2", subject_id="OMI-2")
                )
                rows = review_queue.read_review_queue_events(out)
                if mutate == "payload":
                    rows[0]["payload"]["status"] = "resolved"
                elif mutate == "prev_event_hash":
                    rows[1]["prev_event_hash"] = rows[1]["event_hash"]
                else:
                    rows[0]["event_seq"] = 9
                _queue_path(out).write_bytes(
                    b"".join(review_queue._canonical_bytes(row) + b"\n" for row in rows)
                )

                with self.assertRaises(review_queue.ReviewQueueError):
                    review_queue.read_review_queue_events(out)

    def test_unknown_subject_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(review_queue.ReviewQueueError):
                review_queue.append_review_queue_event(
                    Path(td), _draft(subject_kind="atom")
                )


class OmissionDualWriteTests(unittest.TestCase):
    def test_projection_matches_legacy_writer_byte_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(
                out,
                {"block_id": "B1", "text": "The meter shall log events."},
                {"block_id": "B2", "text": "The meter shall expose alarms."},
            )
            first = omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", reason="标题",
                actor="reviewer",
            )
            second = omission_actions.apply_omission_action(
                out, block_id="B2", status="needs_extraction",
            )

            raw = (out / omission_actions.OMISSION_STATES).read_text(encoding="utf-8")
            lines = raw.splitlines(keepends=True)
            events = review_queue.read_review_queue_events(out)

        # 旧 writer 行形状（基准：按旧插入键序、ensure_ascii=False、LF 追加）。
        self.assertEqual(len(lines), 2)
        for line, state in zip(lines, (first, second)):
            expected = json.dumps(state, ensure_ascii=False) + "\n"
            self.assertEqual(line, expected)
            self.assertEqual(
                list(json.loads(line, object_pairs_hook=dict)),
                ["omission_id", "status", "block_id", "source_fingerprint",
                 "reason", "actor", "recorded_at"],
            )
        self.assertIsNone(json.loads(lines[1])["actor"])
        self.assertIn("标题", lines[0])  # 非 ASCII 不转义，与旧 writer 一致
        # 队列侧：payload 与投影行逐字段一致，事件按主体分派。
        self.assertEqual([event["subject_kind"] for event in events], ["omission"] * 2)
        self.assertEqual([event["payload"] for event in events], [first, second])
        self.assertEqual(
            [event["event_kind"] for event in events],
            ["decided", "queued"],
        )

    def test_crash_window_projection_is_repaired_on_next_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(
                out,
                {"block_id": "B1", "text": "The meter shall log events."},
                {"block_id": "B2", "text": "The meter shall expose alarms."},
            )
            first = omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )
            # 模拟崩溃窗口：队列事件已落、旧文件投影未落。
            (out / omission_actions.OMISSION_STATES).write_text("", encoding="utf-8")

            second = omission_actions.apply_omission_action(
                out, block_id="B2", status="issue_confirmed", actor="reviewer",
            )
            states = omission_actions.read_omission_states(out)
            events = review_queue.read_review_queue_events(out)
            # 旧文件按事件序补齐缺失投影，再追加本次投影——队列有事件而旧文件
            # 缺行的状态被下一次 apply 闭合。
            rows = [
                json.loads(line)
                for line in (out / omission_actions.OMISSION_STATES)
                .read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(events), 2)
        self.assertEqual(
            list(states),
            [first["omission_id"], second["omission_id"]],
        )
        self.assertEqual([row["omission_id"] for row in rows],
                         [first["omission_id"], second["omission_id"]])

    def test_conflict_cascades_to_no_queue_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            with self.assertRaises(omission_actions.OmissionConflictError):
                omission_actions.apply_omission_action(
                    out, block_id="B1", status="non_requirement",
                    expected_source_fingerprint="stale",
                )

            self.assertFalse(_queue_path(out).exists())
            self.assertFalse((out / omission_actions.OMISSION_STATES).exists())

    def test_explicit_idempotency_key_replay_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            first = omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
                idempotency_key="retry-1",
            )
            second = omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
                idempotency_key="retry-1",
            )
            events = review_queue.read_review_queue_events(out)
            rows = (out / omission_actions.OMISSION_STATES).read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(second, first)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(rows), 1)

    def test_old_package_without_queue_file_is_readable_and_writable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            legacy_id = omission_actions.make_omission_id("B1", "The meter shall log events.")
            legacy_row = {
                "omission_id": legacy_id,
                "status": "needs_extraction",
                "block_id": "B1",
                "source_fingerprint": omission_actions.omission_source_fingerprint(
                    "B1", "The meter shall log events."
                ),
                "reason": "legacy",
                "actor": "old-exe",
                "recorded_at": "2026-01-01T00:00:00+00:00",
            }
            (out / omission_actions.OMISSION_STATES).write_text(
                json.dumps(legacy_row, ensure_ascii=False) + "\n", encoding="utf-8",
            )

            before = omission_actions.read_omission_states(out)
            state = omission_actions.apply_omission_action(
                out, block_id="B1", status="resolved", actor="reviewer",
            )
            after = omission_actions.read_omission_states(out)
            events = review_queue.read_review_queue_events(out)
            rows = (out / omission_actions.OMISSION_STATES).read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(list(before), [legacy_id])  # 旧包读路径不受影响
        # 首次写入创建队列并只链接本次事件——不做历史回填（设计 §4.3）。
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"], state)
        self.assertEqual(len(rows), 2)
        self.assertEqual(after[legacy_id]["status"], "resolved")

    def test_queue_and_projection_land_in_governed_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "input.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(root, input_path=source, requested_stages=["atomize"])
            out = root  # package_v1：分析根即包根，state 类落 .ratomizer/state/
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})

            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )

            state_dir = root / ".ratomizer" / "state"
            queue_in_state_dir = (state_dir / review_queue.REVIEW_QUEUE_EVENTS).is_file()
            omission_in_state_dir = (state_dir / omission_actions.OMISSION_STATES).is_file()

        self.assertTrue(queue_in_state_dir)
        self.assertTrue(omission_in_state_dir)


def _omission_worker(out_dir: str, index: int) -> None:
    omission_actions.apply_omission_action(
        Path(out_dir), block_id=f"B{index}", status="non_requirement",
        actor=f"worker-{index}",
    )


class OmissionConcurrencyTests(unittest.TestCase):
    def test_concurrent_processes_share_one_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, *[
                {"block_id": f"B{i}", "text": f"Requirement sentence number {i}."}
                for i in range(4)
            ])
            context = multiprocessing.get_context("spawn")
            workers = [
                context.Process(target=_omission_worker, args=(str(out), i))
                for i in range(4)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(30)
                self.assertEqual(worker.exitcode, 0)

            events = review_queue.read_review_queue_events(out)
            states = omission_actions.read_omission_states(out)

        self.assertEqual([event["event_seq"] for event in events], [1, 2, 3, 4])
        self.assertEqual(len(states), 4)


class ClarificationDualWriteTests(unittest.TestCase):
    def test_projection_matches_legacy_writer_byte_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = check_states.apply_clarification_check_action(
                out, "CLR-1", "deferred", evidence_fingerprint="e1", actor="A",
            )
            second = check_states.apply_clarification_check_action(
                out, "CLR-1", "verified_ok", evidence_fingerprint="e1", actor="B",
                blocker_level="blocking", module="计量",
            )

            raw = (out / check_states.CHECK_STATES_FILE).read_text(encoding="utf-8")
            events = review_queue.read_review_queue_events(out)

        # 旧 writer 行形状（基准：整历史重写，逐行 json.dumps ensure_ascii=False）。
        self.assertEqual(
            raw,
            json.dumps(first, ensure_ascii=False) + "\n"
            + json.dumps(second, ensure_ascii=False) + "\n",
        )
        for line, row in zip(raw.splitlines(), (first, second)):
            self.assertEqual(
                list(json.loads(line, object_pairs_hook=dict)),
                ["clarification_id", "action", "state", "evidence_fingerprint",
                 "blocker_level", "module", "signal", "source_id", "actor",
                 "timestamp", "note"],
            )
        self.assertIn("计量", raw)  # 非 ASCII 不转义
        self.assertEqual(
            [event["subject_kind"] for event in events],
            [review_queue.SUBJECT_KIND_CLARIFICATION_INTERNAL] * 2,
        )
        self.assertEqual([event["payload"] for event in events], [first, second])
        self.assertEqual([event["event_kind"] for event in events],
                         ["deferred", "decided"])
        self.assertEqual(
            [event["subject_fingerprint"] for event in events], ["e1", "e1"]
        )

    def test_crash_window_projection_is_repaired_on_next_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            first = check_states.apply_clarification_check_action(
                out, "CLR-1", "verified_ok", evidence_fingerprint="e1", actor="A",
            )
            # 模拟崩溃窗口：队列事件已落、旧文件投影未落。
            (out / check_states.CHECK_STATES_FILE).write_text("", encoding="utf-8")

            second = check_states.apply_clarification_check_action(
                out, "CLR-2", "deferred", evidence_fingerprint="e2", actor="B",
            )
            history = check_states.read_clarification_check_history(out)
            events = review_queue.read_review_queue_events(out)

        self.assertEqual(len(events), 2)
        self.assertEqual(history, [first, second])

    def test_batch_appends_contiguous_events_under_one_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            stored = check_states.apply_clarification_check_actions_batch(out, [
                {"clarification_id": "CLR-1", "action": "verified_ok",
                 "evidence_fingerprint": "e1", "actor": "A"},
                {"clarification_id": "CLR-2", "action": "issue_confirmed",
                 "evidence_fingerprint": "e2", "actor": "A"},
                {"clarification_id": "CLR-3", "action": "deferred",
                 "evidence_fingerprint": "e3", "actor": "A"},
            ])
            events = review_queue.read_review_queue_events(out)

        self.assertEqual(len(stored), 3)
        self.assertEqual([event["event_seq"] for event in events], [1, 2, 3])
        self.assertEqual([event["event_kind"] for event in events],
                         ["decided", "decided", "deferred"])

    def test_replay_with_explicit_key_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            actions = [
                {"clarification_id": "CLR-1", "action": "verified_ok",
                 "evidence_fingerprint": "e1", "actor": "A",
                 "idempotency_key": "import-1"},
            ]
            first = check_states.apply_clarification_check_actions_batch(out, actions)
            second = check_states.apply_clarification_check_actions_batch(out, actions)
            events = review_queue.read_review_queue_events(out)
            history = check_states.read_clarification_check_history(out)

        self.assertEqual(second, first)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(history), 1)


class ClarificationWriteCasTests(unittest.TestCase):
    def test_expected_fingerprint_match_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            entry = _seed_internal_report(out)
            stored = check_states.apply_clarification_check_action(
                out, entry["clarification_id"], "verified_ok",
                evidence_fingerprint=entry["evidence_fingerprint"], actor="reviewer",
                expected_evidence_fingerprint=entry["evidence_fingerprint"],
            )
            states = check_states.read_clarification_check_states(out)

        self.assertEqual(states[entry["clarification_id"]]["state"], "verified_ok")
        self.assertEqual(stored["state"], "verified_ok")

    def test_expected_fingerprint_mismatch_conflicts_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            entry = _seed_internal_report(out)
            with self.assertRaises(check_states.ClarificationCheckConflictError):
                check_states.apply_clarification_check_action(
                    out, entry["clarification_id"], "verified_ok",
                    evidence_fingerprint=entry["evidence_fingerprint"],
                    actor="reviewer",
                    expected_evidence_fingerprint="stale-fingerprint",
                )

            states = check_states.read_clarification_check_states(out)
            events = review_queue.read_review_queue_events(out)

        self.assertEqual(states, {})
        self.assertEqual(events, [])

    def test_batch_expected_fingerprint_mismatch_is_all_or_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            entry = _seed_internal_report(out)
            with self.assertRaises(check_states.ClarificationCheckConflictError):
                check_states.apply_clarification_check_actions_batch(out, [
                    {"clarification_id": entry["clarification_id"],
                     "action": "verified_ok",
                     "evidence_fingerprint": entry["evidence_fingerprint"],
                     "expected_evidence_fingerprint": entry["evidence_fingerprint"]},
                    {"clarification_id": "CLR-GONE",
                     "action": "verified_ok",
                     "evidence_fingerprint": "e2",
                     "expected_evidence_fingerprint": "e2"},
                ])

            self.assertEqual(check_states.read_clarification_check_states(out), {})
            self.assertEqual(review_queue.read_review_queue_events(out), [])

    def test_unpassed_expected_fingerprint_keeps_legacy_no_intercept(self) -> None:
        """xlsx 导入等未声明期望指纹的路径保持旧行为：写时不拦。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            entry = _seed_internal_report(out)
            stored = check_states.apply_clarification_check_action(
                out, entry["clarification_id"], "verified_ok",
                evidence_fingerprint="stale-but-recorded", actor="importer",
            )
            states = check_states.read_clarification_check_states(out)
            report = cr.run_report(out)

        self.assertEqual(states[entry["clarification_id"]]["state"], "verified_ok")
        self.assertEqual(stored["evidence_fingerprint"], "stale-but-recorded")
        # 读侧 evidence_fingerprint 失效逻辑一字不动：指纹不匹配的确认不消解。
        self.assertFalse(report["entries"][0]["check_state_current"])


@contextmanager
def _api(out_dir: Path):
    class TestHandler(api_server.RequirementAPIHandler):
        pass

    TestHandler.output_dir = out_dir.resolve()
    TestHandler.package_root = out_dir.resolve()
    TestHandler.allowed_origins = set(api_server.DEFAULT_ALLOWED_ORIGINS)
    # POST 端点要求配置 token（api_server.do_POST 的 401 门），与 test_api_server
    # 的带 token POST 用法一致。
    TestHandler.local_token = "review-queue-test-token"
    server = api_server.ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class ClarificationCheckConflictHttpShapeTests(unittest.TestCase):
    def test_batch_conflict_maps_to_structured_409(self) -> None:
        from urllib.error import HTTPError

        from clarification_check_states import ClarificationCheckConflictError

        status_code = 0
        payload: dict = {}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_internal_report(out)
            with _api(out) as base_url, patch(
                "clarification_report.batch_apply_internal_checks",
                side_effect=ClarificationCheckConflictError(
                    "clarification evidence changed; refresh before confirming"
                ),
            ):
                request = Request(
                    base_url + "/clarification-check-actions/batch",
                    data=json.dumps({"checks": [
                        {"clarification_id": "CLR-1", "action": "verified_ok",
                         "evidence_fingerprint": "e1"},
                    ]}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        api_server.TOKEN_HEADER: "review-queue-test-token",
                    },
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=5) as response:
                        self.fail(f"expected 409, got {response.status}")
                except HTTPError as error:
                    status_code = error.code
                    payload = json.loads(error.read().decode("utf-8"))
                    error.close()

        self.assertEqual(status_code, 409)
        self.assertEqual(
            payload["error"],
            "clarification evidence changed; refresh before confirming",
        )
        self.assertTrue(payload["retryable"])
        self.assertTrue(payload["needs_reconfirmation"])


if __name__ == "__main__":
    unittest.main()
