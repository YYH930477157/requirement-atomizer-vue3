from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import claim_artifacts
import review_state
from api_server import RequirementAPIHandler, TOKEN_HEADER


class AtomicReviewStateWriteTests(unittest.TestCase):
    def test_atomic_write_retries_permission_error_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_states.jsonl"
            path.write_text('{"old": true}\n', encoding="utf-8")
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source: Path, target: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("target is being read")
                real_replace(source, target)

            with patch("review_state.os.replace", side_effect=flaky_replace), \
                    patch("review_state.time.sleep") as sleep:
                review_state._atomic_write_jsonl(path, [{"requirement_id": "SREQ-1"}])

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows, [{"requirement_id": "SREQ-1"}])
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(list(path.parent.glob(f"{path.name}.*.tmp")), [])

    def test_atomic_write_exhausts_retry_budget_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_states.jsonl"
            original = '{"old": true}\n'
            path.write_text(original, encoding="utf-8")

            with patch("review_state.os.replace", side_effect=PermissionError("still locked")) as replace, \
                    patch("review_state.time.sleep") as sleep:
                with self.assertRaisesRegex(PermissionError, "still locked"):
                    review_state._atomic_write_jsonl(path, [{"requirement_id": "SREQ-1"}])

            self.assertEqual(replace.call_count, review_state._REPLACE_ATTEMPTS)
            self.assertEqual(sleep.call_count, review_state._REPLACE_ATTEMPTS - 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(path.parent.glob(f"{path.name}.*.tmp")), [])

    def test_retry_budget_uses_linear_backoff_like_claim_artifacts(self) -> None:
        """8 次 × 线性退避（0.02..0.14s，共 ~0.56s）：Windows AV/索引器常常持锁
        超过旧 5×0.02（80ms）预算；与 claim_artifacts._REPLACE_ATTEMPTS 同口径。"""
        self.assertEqual(review_state._REPLACE_ATTEMPTS, claim_artifacts._REPLACE_ATTEMPTS)
        self.assertEqual(
            review_state._REPLACE_RETRY_DELAY_S,
            claim_artifacts._REPLACE_RETRY_DELAY_S,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_states.jsonl"
            with patch("review_state.os.replace", side_effect=PermissionError("av")) as replace, \
                    patch("review_state.time.sleep") as sleep:
                with self.assertRaises(PermissionError):
                    review_state._atomic_write_jsonl(path, [{"requirement_id": "SREQ-1"}])

            self.assertEqual(replace.call_count, 8)
            delays = [call.args[0] for call in sleep.call_args_list]
            self.assertEqual(delays, [0.02 * (attempt + 1) for attempt in range(7)])
            self.assertAlmostEqual(sum(delays), 0.56, places=6)

    def test_event_projection_failure_does_not_misreport_saved_state_as_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("review_state._append_review_state_event",
                       side_effect=OSError("event log temporarily unavailable")):
                result = review_state.apply_expert_decision(
                    out_dir, "SREQ-1", "accepted", actor="expert", reason="approved")

            states = review_state._read_jsonl(out_dir / "review_states.jsonl")
            self.assertEqual(states[0]["status"], "accepted")
            self.assertEqual(states[0]["history"][0]["reason"], "approved")
            self.assertIn("audit_warning", result)
            self.assertFalse((out_dir / "review_state_events.jsonl").exists())


class ReviewAuthoritySnapshotTests(unittest.TestCase):
    def test_complete_bad_row_is_an_audit_gap_and_later_history_survives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = {
                "requirement_id": "SREQ-1",
                "status": "rejected",
                "history": [{
                    "from_status": "candidate",
                    "to_status": "rejected",
                    "actor": "expert",
                    "reason": "reject",
                    "timestamp": "2026-07-28T00:00:00+00:00",
                }],
                "metadata": {"stable_req_id": "SREQ-1"},
            }
            (root / "review_states.jsonl").write_text(
                "not-json\n" + json.dumps(valid) + "\n",
                encoding="utf-8",
            )

            with self.assertLogs("requirement_atomizer", level="WARNING"):
                snapshot = review_state.read_review_authority_snapshot_readonly(root)

        self.assertEqual(snapshot["states"], [valid])
        self.assertEqual(snapshot["audit_gaps"][0]["physical_line_number"], 1)
        self.assertEqual(snapshot["audit_gaps"][0]["state_ordinal"], 1)
        self.assertEqual(
            snapshot["ordered_records"][0]["history_event"]["to_status"],
            "rejected",
        )
        self.assertEqual(snapshot["ordered_records"][0]["state_ordinal"], 2)


class ReviewActionErrorResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        out_dir = Path(self.temp_dir.name).resolve()
        requirement = {
            "req_id": "AREQ-1",
            "stable_req_id": "SREQ-1",
            "source_id": "SRC-1",
            "source_type": "paragraph",
            "source_refs": ["SRC-1"],
            "section_path": ["4.1"],
            "domain": "interface",
            "object": "indicator output",
            "requirement_type": "functional",
            "requirement": (
                "The product shall support configurable indicator outputs."
            ),
            "condition": "",
            "parameters": {},
            "verification_method": "inspection",
        }
        (out_dir / "atomic_requirements.jsonl").write_text(
            json.dumps(requirement) + "\n",
            encoding="utf-8",
        )
        from api_server import enrich_requirements

        self.current_requirement = enrich_requirements([requirement], out_dir)[0]

        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir
        TestHandler.allowed_origins = {"null"}
        TestHandler.local_token = "test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def post_review_action(self) -> tuple[int, dict]:
        body = json.dumps({
            "requirement_id": "SREQ-1",
            "status": "accepted",
            "expected_target_fingerprint": self.current_requirement[
                "target_fingerprint"
            ],
            "expected_target_publication_revision": self.current_requirement[
                "target_publication_revision"
            ],
            "expected_target_authority_write_revision": self.current_requirement[
                "target_authority_write_revision"
            ],
        }).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(
                "POST",
                "/review-actions",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    TOKEN_HEADER: "test-token",
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            connection.close()

    def test_timeout_and_file_errors_return_retryable_503_json(self) -> None:
        errors = [
            TimeoutError("review state lock timed out"),
            PermissionError("review state file is busy"),
            OSError("review state storage failed"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    patch("api_server.apply_review_action", side_effect=error):
                status, payload = self.post_review_action()

            self.assertEqual(status, 503)
            self.assertEqual(payload, {"error": str(error), "retryable": True})

    def test_value_error_remains_conflict_response(self) -> None:
        with patch("api_server.apply_review_action", side_effect=ValueError("invalid transition")):
            status, payload = self.post_review_action()

        self.assertEqual(status, 409)
        self.assertEqual(payload, {"error": "invalid transition"})


class CorruptReadPathGetTests(unittest.TestCase):
    """抽取轮询路径上的 GET 端点：坏 JSONL 必须返回 503 envelope，不能裸崩断连。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        out_dir = Path(self.temp_dir.name).resolve()
        (out_dir / "blocks.jsonl").write_text('{"broken": \n', encoding="utf-8")
        # 有效 partial（指纹绑定到这份坏文件）才能把读路径推进到 blocks.jsonl 解析
        from ai_extract import AI_PARTIAL_SCHEMA, AI_REQUIREMENTS_PARTIAL, extraction_input_fingerprint
        (out_dir / AI_REQUIREMENTS_PARTIAL).write_text(json.dumps({
            "schema": AI_PARTIAL_SCHEMA,
            "run_id": "run-1",
            "completed": 1,
            "total": 1,
            "complete": False,
            "failed": False,
            "input_fingerprint": extraction_input_fingerprint(out_dir),
            "rows": [{"ai_req_id": "AIR-1", "title": "t", "source_block_ids": ["B1"]}],
        }), encoding="utf-8")

        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir
        TestHandler.allowed_origins = {"null"}
        TestHandler.local_token = "test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.temp_dir.cleanup()

    def get_json(self, path: str) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("GET", path, headers={TOKEN_HEADER: "test-token"})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            connection.close()

    def test_corrupt_blocks_jsonl_returns_retryable_503_envelope(self) -> None:
        for path in ("/omission-actions", "/ai-extraction-status", "/document/pdf"):
            with self.subTest(path=path):
                status, payload = self.get_json(path)
                self.assertEqual(status, 503)
                self.assertTrue(payload["retryable"])
                self.assertTrue(payload["error"])


class InProcessLockFamilySeparationTests(unittest.TestCase):
    """review_states 与 verification_states 是两把独立文件锁；进程内 RLock 也必须
    按锁家族分离，否则线程化 GET 的快照扫描会阻塞另一家族的 POST。"""

    def test_lock_families_use_distinct_process_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            review_lock = review_state._process_lock_for(root, "review_states")
            verification_lock = review_state._process_lock_for(root, "verification_states")
            self.assertIsNot(review_lock, verification_lock)
            # 同家族同键 → 同一把（可重入语义保持）
            self.assertIs(review_lock, review_state._process_lock_for(root, "review_states"))

    def test_verification_lock_is_reachable_while_review_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            entered = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []

            def hold_review_lock() -> None:
                try:
                    with review_state.review_state_lock(root):
                        entered.set()
                        self.assertTrue(release.wait(10))
                except BaseException as exc:  # surfaced in the test thread
                    errors.append(exc)

            holder = threading.Thread(target=hold_review_lock, daemon=True)
            holder.start()
            try:
                self.assertTrue(entered.wait(10))
                verification_done = threading.Event()

                def take_verification_lock() -> None:
                    with review_state.verification_state_lock(root):
                        verification_done.set()

                waiter = threading.Thread(target=take_verification_lock, daemon=True)
                waiter.start()
                # 共享 RLock 的旧实现会让这里超时（verification 永远等不到 review 释放）
                self.assertTrue(
                    verification_done.wait(5),
                    "verification lock is serialized behind a held review lock",
                )
                waiter.join(10)
            finally:
                release.set()
                holder.join(10)
            self.assertEqual(errors, [])


class AuthorityWriteRevisionHashCacheTests(unittest.TestCase):
    """GET /requirements 富集逐行调用 revision：同一快照内未变化行不得重复
    hash 整行+全部 history；快照字节一变（新 sha）即失效。"""

    @staticmethod
    def _write_states(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _state_row(self, requirement_id: str, status: str, history: list[dict]) -> dict:
        return {
            "requirement_id": requirement_id,
            "status": status,
            "history": history,
            "metadata": {"stable_req_id": requirement_id},
            "level": "atomic",
        }

    def test_repeated_enrichment_of_unchanged_snapshot_skips_row_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            states_path = root / "review_states.jsonl"
            row_a = self._state_row("SREQ-1", "accepted", [
                {"from_status": "candidate", "to_status": "accepted",
                 "actor": "expert", "reason": "ok", "timestamp": "2026-08-14T00:00:00+00:00"},
            ])
            row_b = self._state_row("SREQ-2", "rejected", [
                {"from_status": "candidate", "to_status": "rejected",
                 "actor": "expert", "reason": "no", "timestamp": "2026-08-14T00:00:01+00:00"},
            ])
            self._write_states(states_path, [row_a, row_b])
            snapshot = review_state.read_review_authority_snapshot(root)

            real_hash_json = claim_artifacts.hash_json
            calls: list[str] = []

            def counting_hash_json(domain: str, payload) -> str:
                calls.append(str(domain))
                return real_hash_json(domain, payload)

            with patch.object(claim_artifacts, "hash_json", side_effect=counting_hash_json):
                first = review_state.atomic_target_authority_write_revision("SREQ-1", snapshot)
                first_calls = len(calls)
                # 第二次同目标：行/历史哈希命中缓存，只剩最终 binding 哈希
                second = review_state.atomic_target_authority_write_revision("SREQ-1", snapshot)
                second_calls = len(calls) - first_calls
                # 换目标（另一行）：只新算该行的两个哈希 + 最终哈希
                review_state.atomic_target_authority_write_revision("SREQ-2", snapshot)
                third_calls = len(calls) - first_calls - second_calls
                # 再回第一个目标：仍然只剩最终哈希
                review_state.atomic_target_authority_write_revision("SREQ-1", snapshot)
                fourth_calls = len(calls) - first_calls - second_calls - third_calls

            # 1 行匹配：行哈希 + 历史 prefix 哈希 + 最终 binding 哈希 = 3
            self.assertEqual(first_calls, 3)
            self.assertEqual(second_calls, 1)
            self.assertEqual(third_calls, 3)
            self.assertEqual(fourth_calls, 1)
            self.assertEqual(first, second)

            # 缓存值必须与绕过缓存的裸 list 形式逐位一致
            self.assertEqual(
                first,
                review_state.atomic_target_authority_write_revision(
                    "SREQ-1", list(snapshot["states"])
                ),
            )

    def test_snapshot_change_invalidates_cache_and_list_form_is_never_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            states_path = root / "review_states.jsonl"
            row = self._state_row("SREQ-1", "accepted", [
                {"from_status": "candidate", "to_status": "accepted",
                 "actor": "expert", "reason": "ok", "timestamp": "2026-08-14T00:00:00+00:00"},
            ])
            self._write_states(states_path, [row])
            snapshot_before = review_state.read_review_authority_snapshot(root)
            revision_before = review_state.atomic_target_authority_write_revision(
                "SREQ-1", snapshot_before
            )

            # 裸 list 形式反映内存中的即时修改（调用方正在变更的列表绝不缓存）
            mutated = [dict(row) for row in snapshot_before["states"]]
            mutated[0]["status"] = "rejected"
            mutated[0]["history"].append({
                "from_status": "accepted", "to_status": "rejected",
                "actor": "expert", "reason": "changed", "timestamp": "2026-08-14T01:00:00+00:00",
            })
            revision_mutated = review_state.atomic_target_authority_write_revision(
                "SREQ-1", mutated
            )
            self.assertNotEqual(revision_before, revision_mutated)

            # 磁盘字节变化（新裁决原子替换文件）→ 新 sha → 新缓存键，旧条目不可命中
            row["status"] = "rejected"
            row["history"] = mutated[0]["history"]
            self._write_states(states_path, [row])
            snapshot_after = review_state.read_review_authority_snapshot(root)
            self.assertNotEqual(
                snapshot_before["authority_file_sha256"],
                snapshot_after["authority_file_sha256"],
            )
            revision_after = review_state.atomic_target_authority_write_revision(
                "SREQ-1", snapshot_after
            )
            self.assertEqual(revision_mutated, revision_after)


class EffectiveFoldCoordinatorTests(unittest.TestCase):
    """裁决后 effective fold 合并器：突发合并 + 覆盖性不变量（返回前必有
    一个在本次注册之后编号的 pass 完成）。"""

    def test_sequential_covers_each_fold_once(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        passes: list[str] = []
        for _ in range(3):
            coordinator.cover("A", lambda: passes.append("A"))
        self.assertEqual(passes, ["A", "A", "A"])

    def test_concurrent_covers_coalesce_into_few_passes(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        passes = threading.Semaphore(0)
        count = {"passes": 0}
        count_lock = threading.Lock()
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def slow_pass() -> None:
            with count_lock:
                count["passes"] += 1
            passes.release()
            time.sleep(0.3)

        def worker() -> None:
            try:
                barrier.wait(10)
                coordinator.cover("A", slow_pass)
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)

        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        # 6 个并发裁决 → 至多 drain 上限个 pass（旧实现是 6 次串行全量 fold）
        self.assertLessEqual(count["passes"], review_state._EFFECTIVE_FOLD_DRAIN_PASSES)
        self.assertGreaterEqual(count["passes"], 1)

    def test_cover_waits_for_pass_numbered_after_registration(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        order: list[str] = []
        order_lock = threading.Lock()
        state = {"passes": 0}
        first_pass_running = threading.Event()
        release_first_pass = threading.Event()
        errors: list[BaseException] = []

        def gated_pass() -> None:
            with order_lock:
                state["passes"] += 1
                number = state["passes"]
                order.append(f"start-{number}")
            if number == 1:
                first_pass_running.set()
                self.assertTrue(release_first_pass.wait(10))
            with order_lock:
                order.append(f"end-{number}")

        owner = threading.Thread(
            target=lambda: coordinator.cover("A", gated_pass), daemon=True
        )
        owner.start()
        self.assertTrue(first_pass_running.wait(10))

        waiter_done = threading.Event()

        def waiter() -> None:
            try:
                coordinator.cover("A", gated_pass)
                with order_lock:
                    order.append("waiter-returned")
                waiter_done.set()
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        waiter_thread = threading.Thread(target=waiter, daemon=True)
        waiter_thread.start()
        # 第一个 pass 还在跑：waiter 肯定没返回
        self.assertFalse(waiter_done.is_set())
        release_first_pass.set()
        owner.join(20)
        waiter_thread.join(20)

        self.assertEqual(errors, [])
        self.assertTrue(waiter_done.is_set())
        # waiter 只能被「在其注册之后启动」的 pass 释放：必须是第 2 个 pass，
        # 且其完成后才返回——第一个 pass 的完成对它不算数（覆盖性不变量）。
        self.assertEqual(state["passes"], 2)
        self.assertLess(order.index("end-1"), order.index("start-2"))
        self.assertLess(order.index("end-2"), order.index("waiter-returned"))

    def test_failed_pass_is_swallowed_by_hook_wrapper_and_waiters_release(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        attempts = {"count": 0}

        def failing_pass() -> None:
            attempts["count"] += 1
            raise RuntimeError("fold backend down")

        waiter_done = threading.Event()

        def waiter() -> None:
            # 与生产 hook 同型：pass 内吞掉 Exception（logged-and-continue）
            def swallowing_pass() -> None:
                try:
                    failing_pass()
                except Exception:
                    pass
            coordinator.cover("A", swallowing_pass)
            waiter_done.set()

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        thread.join(20)
        self.assertTrue(waiter_done.is_set())
        self.assertEqual(attempts["count"], 1)

    def test_owner_exception_releases_slot_and_next_cover_recovers(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        state = {"fail": True}

        def flaky_pass() -> None:
            if state["fail"]:
                state["fail"] = False
                raise KeyboardInterrupt("hard kill mid-fold")

        with self.assertRaises(KeyboardInterrupt):
            coordinator.cover("A", flaky_pass)

        passes: list[str] = []
        coordinator.cover("A", lambda: passes.append("ok"))
        self.assertEqual(passes, ["ok"])


class EffectiveFoldCrossTrackFairnessTests(unittest.TestCase):
    """P2 活性修复（2026-08-15）：合并器单槽被 A/B 两轨共享，旧实现 owner 让位
    后无公平——4 个持续再注册的 A 轨生产者可让 B 轨等待者零进展饿死 10s+。修复
    后 owner 让位时若有异轨等待者，槽位必须优先让给异轨（双轨都有等待者时交替）；
    只有同轨等待者时同轨可立即重新拿槽（保持既有突发合并行为）。"""

    def test_continuous_a_burst_cannot_starve_b_waiter(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        state_lock = threading.Lock()
        passes = {"A": 0, "B": 0}
        first_pass_started = threading.Event()
        release_first_pass = threading.Event()
        stop = threading.Event()
        errors: list[BaseException] = []

        def a_pass() -> None:
            with state_lock:
                passes["A"] += 1
                number = passes["A"]
            if number == 1:
                first_pass_started.set()
                self.assertTrue(release_first_pass.wait(20))
            time.sleep(0.002)

        def b_pass() -> None:
            with state_lock:
                passes["B"] += 1

        def produce(producer_deadline: float) -> None:
            try:
                while not stop.is_set() and time.monotonic() < producer_deadline:
                    coordinator.cover("A", a_pass)
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        producers = [
            threading.Thread(
                target=produce, args=(time.monotonic() + 12.0,), daemon=True
            )
            for _ in range(4)
        ]
        for thread in producers:
            thread.start()
        self.assertTrue(first_pass_started.wait(20))
        # 首个 pass 卡住期间，其余 3 个生产者全部 park 进等待队列，B 轨等待者
        # 随后注册——这是专家实测的饿死触发面（批量导入循环 + 跨轨并发裁决）。
        time.sleep(0.05)
        release_first_pass.set()

        b_done = threading.Event()

        def b_waiter() -> None:
            try:
                coordinator.cover("B", b_pass)
                b_done.set()
            except BaseException as exc:  # surfaced in the test thread
                errors.append(exc)

        b_thread = threading.Thread(target=b_waiter, daemon=True)
        b_thread.start()
        try:
            # 修复后 B 在首个 A owner 让位后立刻拿槽（亚秒级）；修复前 B 轨在
            # 持续 A 突发下饿死远超 5s（实测 10s+ 零进展，且 cover() 无超时）。
            self.assertTrue(
                b_done.wait(5),
                "B-track waiter starved behind continuous A-track decisions",
            )
            self.assertGreaterEqual(passes["B"], 1)
            self.assertGreaterEqual(passes["A"], 1)
        finally:
            stop.set()
            for thread in producers:
                thread.join(30)
            b_thread.join(30)
        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in producers))
        self.assertFalse(b_thread.is_alive())


class EffectiveFoldCoverTimeoutTests(unittest.TestCase):
    """cover() 有界等待（EFFECTIVE_FOLD_COVER_TIMEOUT_S）：fold 卡死时等待者
    在时限内诚实超时（EffectiveFoldCoverTimeout，TimeoutError 子类 → 调用方
    既有 except (TimeoutError, OSError) 分支映射 retryable 503）。裁决权威写在
    cover() 之前已原子提交，超时绝不回滚；fold 落后被如实记日志，由
    assess_effective_freshness / 下一次裁决追平。"""

    def _root_with_claim_generation(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        (root / "claim_generation.meta.json").write_text("{}", encoding="utf-8")
        return root

    def test_cover_raises_specific_timeout_error_within_bound(self) -> None:
        coordinator = review_state._EffectiveFoldCoordinator()
        owner_pass_started = threading.Event()
        release_owner_pass = threading.Event()

        def stuck_pass() -> None:
            owner_pass_started.set()
            self.assertTrue(release_owner_pass.wait(20))

        owner = threading.Thread(
            target=lambda: coordinator.cover("A", stuck_pass), daemon=True
        )
        owner.start()
        self.assertTrue(owner_pass_started.wait(10))

        raised: list[BaseException] = []

        def b_waiter() -> None:
            try:
                coordinator.cover("B", lambda: None)
            except BaseException as exc:  # surfaced in the test thread
                raised.append(exc)

        started = time.monotonic()
        with patch.object(review_state, "EFFECTIVE_FOLD_COVER_TIMEOUT_S", 0.5):
            waiter = threading.Thread(target=b_waiter, daemon=True)
            waiter.start()
            waiter.join(10)
        elapsed = time.monotonic() - started

        self.assertFalse(waiter.is_alive())
        self.assertEqual(len(raised), 1)
        self.assertIsInstance(raised[0], review_state.EffectiveFoldCoverTimeout)
        self.assertIsInstance(raised[0], TimeoutError)
        self.assertIn("B", str(raised[0]))
        self.assertGreaterEqual(elapsed, 0.45)
        self.assertLess(elapsed, 5)

        # 超时等待者的登记必须清干净：owner 释放后下一个 cover 正常拿槽
        release_owner_pass.set()
        owner.join(10)
        self.assertFalse(owner.is_alive())
        passes: list[str] = []
        coordinator.cover("A", lambda: passes.append("ok"))
        self.assertEqual(passes, ["ok"])

    def test_hook_timeout_keeps_decision_committed_and_logs_fold_lag(self) -> None:
        import claim_review_actions

        root = self._root_with_claim_generation()
        fold_started = threading.Event()
        release_fold = threading.Event()

        def stuck_fold(out_dir, **kwargs):
            fold_started.set()
            self.assertTrue(release_fold.wait(20))

        owner_result: dict = {}
        owner_errors: list[BaseException] = []

        def owner_decide() -> None:
            try:
                owner_result["state"] = review_state.apply_expert_decision(
                    root, "SREQ-1", "accepted", actor="expert", reason="first"
                )
            except BaseException as exc:  # surfaced in the test thread
                owner_errors.append(exc)

        with patch.object(
            claim_review_actions, "fold_effective_ledger", side_effect=stuck_fold
        ):
            owner = threading.Thread(target=owner_decide, daemon=True)
            owner.start()
            self.assertTrue(fold_started.wait(10))
            with patch.object(
                review_state, "EFFECTIVE_FOLD_COVER_TIMEOUT_S", 0.5
            ), self.assertLogs("requirement_atomizer", level="WARNING") as captured:
                with self.assertRaises(review_state.EffectiveFoldCoverTimeout):
                    review_state.apply_expert_decision(
                        root, "SREQ-2", "rejected", actor="expert", reason="second"
                    )
            release_fold.set()
            owner.join(10)

        self.assertEqual(owner_errors, [])
        self.assertFalse(owner.is_alive())
        self.assertEqual(owner_result["state"]["status"], "accepted")
        # 两条裁决都已原子提交：cover 超时绝不回滚权威写
        states = review_state.read_review_authority_snapshot(root)["states"]
        self.assertEqual(
            sorted(str(row["requirement_id"]) for row in states),
            ["SREQ-1", "SREQ-2"],
        )
        self.assertTrue(
            any("fold cover timed out" in line for line in captured.output)
        )


class ExpertDecisionFoldHookTests(unittest.TestCase):
    """apply_expert_decision 的 fold 钩子：同步覆盖语义保持、突发合并、失败
    logged-and-continue（裁决本身已原子提交）。"""

    def _root_with_claim_generation(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        # legacy 布局：governed_artifact_path 直落根目录；只判存在性
        (root / "claim_generation.meta.json").write_text("{}", encoding="utf-8")
        return root

    def test_decision_folds_synchronously_with_track_a(self) -> None:
        import claim_review_actions

        root = self._root_with_claim_generation()
        folds: list[dict] = []

        def recording_fold(out_dir, **kwargs):
            folds.append(dict(kwargs))
            return {"ok": True}

        with patch.object(claim_review_actions, "fold_effective_ledger", side_effect=recording_fold):
            result = review_state.apply_expert_decision(
                root, "SREQ-1", "accepted", actor="expert", reason="approve"
            )

        # 返回前 fold 已经完成（读后写可见性契约）
        self.assertEqual(len(folds), 1)
        self.assertEqual(folds[0]["actor_trigger"], "requirement-review-action")
        self.assertEqual(folds[0]["authority_hook_track"], "A")
        self.assertEqual(result["status"], "accepted")
        states = review_state.read_review_authority_snapshot(root)["states"]
        self.assertEqual(states[0]["status"], "accepted")

    def test_fold_failure_is_logged_and_decision_still_authoritative(self) -> None:
        import claim_review_actions

        root = self._root_with_claim_generation()

        with patch.object(
            claim_review_actions,
            "fold_effective_ledger",
            side_effect=RuntimeError("injected fold failure"),
        ):
            with self.assertLogs("requirement_atomizer", level="WARNING") as captured:
                result = review_state.apply_expert_decision(
                    root, "SREQ-1", "rejected", actor="expert", reason="reject"
                )

        self.assertEqual(result["status"], "rejected")
        self.assertTrue(
            any("expert decision saved; claim effective fold lagged" in line
                for line in captured.output),
        )
        states = review_state.read_review_authority_snapshot(root)["states"]
        self.assertEqual(states[0]["status"], "rejected")

    def test_concurrent_decisions_coalesce_folds(self) -> None:
        import claim_review_actions

        root = self._root_with_claim_generation()
        fold_lock = threading.Lock()
        folds: list[str] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def slow_fold(out_dir, **kwargs):
            with fold_lock:
                folds.append(str(kwargs.get("authority_hook_track")))
            time.sleep(0.2)
            return {"ok": True}

        def decide(index: int) -> None:
            try:
                barrier.wait(10)
                review_state.apply_expert_decision(
                    root, f"SREQ-{index}", "accepted", actor="expert", reason="burst"
                )
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
        # 6 个并发裁决 → fold 至多 drain 上限次（旧实现 6 次串行）
        self.assertLessEqual(len(folds), review_state._EFFECTIVE_FOLD_DRAIN_PASSES)
        self.assertGreaterEqual(len(folds), 1)
        # 每个裁决都已落盘（权威行先于 fold 提交）
        states = review_state.read_review_authority_snapshot(root)["states"]
        self.assertEqual(
            sorted(str(row["requirement_id"]) for row in states),
            [f"SREQ-{index}" for index in range(6)],
        )


if __name__ == "__main__":
    unittest.main()
