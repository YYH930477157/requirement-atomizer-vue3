"""API server 安全回归。

锁定 token 校验用常量时间比较（防时序侧信道），并保留：无配置 token 时放行、
token 不匹配时拒绝。可独立运行，无网络/LLM 依赖。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import api_server
import ai_review_actions
import claim_artifacts
import claim_catalog
import claim_ledger
import claim_review_actions
import desktop_tasks
from result_package import initialize_result_package, resolve_analysis_root
from tests.test_claim_artifacts import _catalog, _publish, _requirement
from tests.test_claim_review_actions import _publish_a_track
from tests.test_claim_review_event_v2 import _source_exclusion_evidence


@contextmanager
def _claim_api(out_dir: Path, *, local_token: str = ""):
    class TestHandler(api_server.RequirementAPIHandler):
        pass

    TestHandler.output_dir = out_dir.resolve()
    TestHandler.package_root = out_dir.resolve()
    TestHandler.allowed_origins = set(api_server.DEFAULT_ALLOWED_ORIGINS)
    TestHandler.local_token = local_token
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


def _http_json(base_url: str, path: str) -> tuple[int, dict]:
    try:
        with urlopen(base_url + path, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        finally:
            exc.close()


@contextmanager
def _package_api(package_root: Path):
    class TestHandler(api_server.RequirementAPIHandler):
        pass

    TestHandler.package_root = package_root.resolve()
    TestHandler.output_dir = resolve_analysis_root(package_root)
    TestHandler.allowed_origins = set(api_server.DEFAULT_ALLOWED_ORIGINS)
    TestHandler.local_token = ""
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


@contextmanager
def _broken_package_api(package_root: Path):
    """marker/journal 损坏时布局探测本身会抛，这里直接钉住分析根来测端点错误面。"""
    class TestHandler(api_server.RequirementAPIHandler):
        pass

    TestHandler.package_root = package_root.resolve()
    TestHandler.output_dir = package_root.resolve()
    TestHandler.allowed_origins = set(api_server.DEFAULT_ALLOWED_ORIGINS)
    TestHandler.local_token = ""
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


class ResultPackageEndpointTests(unittest.TestCase):
    def test_exposes_package_root_and_internal_analysis_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(root, input_path=source, requested_stages=["atomize"])

            with _package_api(root) as base_url:
                status, payload = _http_json(base_url, "/result-package")

            self.assertEqual(status, 200)
            self.assertEqual(payload["layout"], "package_v1")
            self.assertEqual(payload["package_root"], str(root.resolve()))
            self.assertEqual(payload["analysis_root"], str(resolve_analysis_root(root)))
            self.assertEqual(payload["package"]["analysis_status"], "running")

    def test_corrupt_marker_returns_structured_503(self) -> None:
        # S1 回归：marker 损坏时 /result-package 返回结构化 503，不掐断连接。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result-package.json").write_text("{broken", encoding="utf-8")

            with _broken_package_api(root) as base_url:
                status, payload = _http_json(base_url, "/result-package")

            self.assertEqual(status, 503)
            self.assertEqual(payload["error"], "result_package_unavailable")
            self.assertTrue(payload["retryable"])

    def test_corrupt_marker_returns_structured_503_from_other_get_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result-package.json").write_text("{broken", encoding="utf-8")

            with _broken_package_api(root) as base_url:
                status, payload = _http_json(base_url, "/review-states")

            self.assertEqual(status, 503)
            self.assertEqual(payload["error"], "result_package_unavailable")
            self.assertTrue(payload["retryable"])

    def test_interrupted_publication_journal_returns_structured_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(root, input_path=source, requested_stages=["atomize"])
            journal = root / ".ratomizer" / "stages" / ".result-package-publication.json"
            journal.write_text("{}", encoding="utf-8")

            with _broken_package_api(root) as base_url:
                status, payload = _http_json(base_url, "/result-package")

            self.assertEqual(status, 503)
            self.assertEqual(payload["error"], "result_package_unavailable")

    def test_verify_detects_modified_deliverable(self) -> None:
        # S5：显式完整校验（打开已有结果）——交付物哈希与 marker 不一致时返回
        # result_package_modified 并提示"结果文件已被修改"；不带 verify 保持纯存在性检查
        from result_package import commit_analysis_completion, package_artifact_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.docx"
            source.write_bytes(b"fixture")
            package = initialize_result_package(
                root, input_path=source, requested_stages=["atomize"],
            )
            run_id = package["active_attempt"]["run_id"]
            manifest = package_artifact_path(root, "run_manifest", for_write=True)
            manifest.write_text(json.dumps({
                "manifest_version": 2,
                "stages": {"atomize": {"status": "ok", "attempt_run_id": run_id}},
            }), encoding="utf-8")
            package_artifact_path(root, "summary_md", for_write=True).write_text(
                "# done\n", encoding="utf-8",
            )
            commit_analysis_completion(root, run_id=run_id, completed_stages=["atomize"])
            (root / "summary.md").write_text("tampered\n", encoding="utf-8")

            with _package_api(root) as base_url:
                plain_status, _plain = _http_json(base_url, "/result-package")
                status, payload = _http_json(base_url, "/result-package?verify=1")

        self.assertEqual(plain_status, 200)
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "result_package_modified")
        self.assertFalse(payload["retryable"])
        self.assertIn("结果文件已被修改", payload["detail"])


def _http_post_json(
    base_url: str,
    path: str,
    payload: dict,
    *,
    token: str = "",
) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers[api_server.TOKEN_HEADER] = token
    request = Request(
        base_url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        finally:
            exc.close()


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


class VerificationActionFingerprintHttpTests(unittest.TestCase):
    """S1-6：POST /verification-actions 必须回传最新 ``evidence_fingerprint``。

    修复前响应只回 ``verification``/``lifecycle_state``，前端保存成功后无法同步本地行
    指纹，第二次保存必携旧（空）指纹→假 409（高频缺陷，实测复现）。验收：响应回传
    指纹 + 三连保存无 409；携过时指纹仍被拒（CAS 真实生效，不是放行一切）。
    """

    TOKEN = "verification-http-test-token"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.rid = "FRE-save0001"
        self.item = {
            "functional_requirement_id": self.rid,
            "objective": "表具应记录掉电事件",
            "behaviors": ["掉电时写日志"],
            "description": "表具应记录掉电事件",
            "source_section": "4.2.1",
            "source_quote": "The meter shall log power failure events.",
            "source_block_ids": ["BLK-001"],
        }
        (self.out / "functional_requirements.json").write_text(
            json.dumps({"producer": "functional-extract-v1", "items": [self.item]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_response_returns_evidence_fingerprint_and_three_saves_do_not_409(self) -> None:
        from requirement_schema import requirement_structural_fingerprint
        expected_fp = requirement_structural_fingerprint(self.item)
        with _claim_api(self.out, local_token=self.TOKEN) as base:
            # 第一次：首次回写不携 expected → 通过，响应必须回传 evidence_fingerprint
            s1, p1 = _http_post_json(base, "/verification-actions", {
                "requirement_id": self.rid,
                "verification": {"implemented": "done"},
                "actor": "tester",
            }, token=self.TOKEN)
            self.assertEqual(s1, 200, p1)
            self.assertEqual(p1.get("evidence_fingerprint"), expected_fp)
            # 第二次：携响应回传的指纹 → 通过（无 409）
            s2, p2 = _http_post_json(base, "/verification-actions", {
                "requirement_id": self.rid,
                "verification": {"implemented": "done"},
                "actor": "tester",
                "expected_evidence_fingerprint": p1["evidence_fingerprint"],
            }, token=self.TOKEN)
            self.assertEqual(s2, 200, p2)
            # 第三次：再携最新指纹 → 通过（三连保存无 409）
            s3, p3 = _http_post_json(base, "/verification-actions", {
                "requirement_id": self.rid,
                "verification": {"implemented": "done"},
                "actor": "tester",
                "expected_evidence_fingerprint": p2["evidence_fingerprint"],
            }, token=self.TOKEN)
            self.assertEqual(s3, 200, p3)

    def test_repeated_save_with_genuinely_stale_fingerprint_still_409(self) -> None:
        # 对照：携【过时/不匹配】指纹仍应被拒——CAS 真实生效，修复不是放行一切。
        with _claim_api(self.out, local_token=self.TOKEN) as base:
            s_bad, p_bad = _http_post_json(base, "/verification-actions", {
                "requirement_id": self.rid,
                "verification": {"implemented": "done"},
                "actor": "tester",
                "expected_evidence_fingerprint": "stale-not-matching",
            }, token=self.TOKEN)
            self.assertEqual(s_bad, 409)
            self.assertTrue(p_bad.get("needs_reconfirmation"))


class TokenIsValidTests(unittest.TestCase):
    def test_no_expected_token_allows_through(self) -> None:
        # 未配置 token（本地无鉴权场景）→ 任意请求放行
        self.assertTrue(api_server.token_is_valid("", {api_server.TOKEN_HEADER: "x"}, {}))
        self.assertTrue(api_server.token_is_valid("", {}, {}))

    def test_matching_header_token_accepted(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: token}
        self.assertTrue(api_server.token_is_valid(token, headers, {}))

    def test_mismatching_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: "wrong"}
        self.assertFalse(api_server.token_is_valid(token, headers, {}))

    def test_missing_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        self.assertFalse(api_server.token_is_valid(token, {}, {}))

    def test_comparison_uses_constant_time_function(self) -> None:
        """S1 回归：token 须走 hmac.compare_digest，而非字符串 == 短路。

        解析源码确认比较路径常量时间：compare_digest 的核心约束是『两串等长才比较内容、
        否则恒为 False 但耗时与内容无关』；等长内容相同须接受、不同须拒绝。
        """
        import inspect
        src = inspect.getsource(api_server.token_is_valid)
        self.assertIn("compare_digest", src)  # 实现里含常量时间比较
        self.assertNotIn("== expected_token", src)  # 不再裸用 == 比较整串

    def test_equal_length_but_different_token_rejected(self) -> None:
        # compare_digest 对等长但内容不同的串恒 False（也是 == 短路会误判的场景）
        token = "aaaaaaaaaaaaaaaa"
        headers = {api_server.TOKEN_HEADER: "aaaaaaaaaaaaaaab"}  # 同长度末字节不同
        self.assertFalse(api_server.token_is_valid(token, headers, {}))


class ClaimLedgerHttpTests(unittest.TestCase):
    ENDPOINTS = (
        "/claim-catalog",
        "/claim-ledger",
        "/claim-coverage-groups",
        "/claim-metrics",
        "/claim-review-events",
        "/claim-queue",
    )

    def _seed(self, root: Path) -> None:
        _publish(root, _catalog())
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="real-http-test",
        )

    def _seed_stale_protocol(self, root: Path) -> None:
        # S11 夹具：committed base 的 artifact_protocol_version 落后于当前协议
        self._seed(root)
        generation_path = root / claim_artifacts.CLAIM_GENERATION_META
        generation = json.loads(generation_path.read_text(encoding="utf-8"))
        generation["artifact_protocol_version"] = "claim-artifacts-v6"
        claim_artifacts.atomic_write_json(generation_path, generation)

    def test_stale_claim_protocol_maps_to_base_migration_required_on_gets(self) -> None:
        # S11：陈旧 claim 产物协议不再是裸 500 风格错误——GET 视图统一映射为
        # 结构化 503 base_migration_required，文案含迁移指引
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_stale_protocol(root)

            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

        for path, (status, payload) in zip(self.ENDPOINTS, responses):
            self.assertEqual(status, 503, path)
            self.assertEqual(payload["error"], "base_migration_required", path)
            self.assertIn("请重跑 atomize", payload["detail"], path)

    def test_stale_claim_protocol_maps_to_base_migration_required_on_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_stale_protocol(root)

            with _claim_api(root, local_token="s11-token") as base_url:
                status, payload = _http_post_json(
                    base_url, "/claim-maintenance", {}, token="s11-token",
                )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "base_migration_required")
        self.assertIn("请重跑 atomize", payload["detail"])

    def test_stale_claim_protocol_fold_returns_structured_dict(self) -> None:
        # S11：fold 写路径同样走结构化 base_migration_required，不抛裸协议错误
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_stale_protocol(root)

            result = claim_review_actions.fold_effective_ledger(
                root, actor_trigger="s11-fold-test",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "base_migration_required")

    def test_document_pdf_returns_503_for_unreadable_existing_claim_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            (root / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B1", "order": 1, "type": "paragraph",
                "text": catalog["catalog"][0]["text"],
                "section_path": ["4 Functions"], "noise": False,
            }) + "\n", encoding="utf-8")
            _publish(root, catalog)
            claim_review_actions.fold_effective_ledger(
                root, actor_trigger="annotation-http-error-test"
            )
            # 撕裂 effective ledger（非 pending 的不可读快照）：维持裸文案 retryable 503；
            # pending journal 的机器码 effective_recovery_pending 映射由
            # RecoveryPendingHeavyViewTests 单独锁定。
            (root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER).write_text(
                '{"broken": ', encoding="utf-8",
            )
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/document/pdf")

            after = _file_bytes(root)

        self.assertEqual(status, 503)
        self.assertTrue(payload["retryable"])
        self.assertIn("claim annotation snapshot unavailable", payload["error"])
        self.assertEqual(after, before)

    @staticmethod
    def _changed_catalog() -> dict:
        text = "The product shall provide a separately configurable auxiliary output."
        return claim_catalog.build_claim_catalog([{
            "block_id": "B1",
            "order": 1,
            "type": "paragraph",
            "text": text,
            "raw_text": text,
            "text_repair_checked": True,
            "text_repair_version": "identity-v1",
            "raw_to_repaired_spans": [{
                "raw_start": 0,
                "raw_end": len(text),
                "repaired_start": 0,
                "repaired_end": len(text),
                "operation": "equal",
            }],
            "section_path": ["4 Functions"],
            "noise": False,
        }], [])

    def test_six_claim_gets_return_real_http_200_with_one_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

        self.assertTrue(all(status == 200 for status, _payload in responses))
        payloads = [payload for _status, payload in responses]
        self.assertTrue(all(payload["available"] for payload in payloads))
        self.assertEqual(
            len({payload["document_effective_revision"] for payload in payloads}),
            1,
        )
        for payload in payloads:
            if payload["schema"] != "claim-metrics-view/v1":
                self.assertEqual(payload["limit"], 100)
                self.assertEqual(payload["offset"], 0)
        queue = payloads[-1]
        self.assertEqual(queue["compat_omission_total"], 0)
        self.assertTrue(queue["compat_omission_revision"].startswith("sha256:"))

    def test_normal_claim_gets_leave_every_artifact_byte_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

            after = _file_bytes(root)

        self.assertTrue(all(status == 200 for status, _payload in responses))
        self.assertEqual(after, before)

    def _append_orphan_attempt(self, root: Path) -> None:
        import claim_reextract_attempts as attempts

        attempt_id = attempts.attempt_id("CQP-12345678-9abcdef0", "orphan-request")
        attempts.append_attempt_events(root, [{
            "attempt_id": attempt_id,
            "proposal_id": "CQP-12345678-9abcdef0",
            "claim_id": "CLM-0123456789abcdef",
            "claim_hash": claim_artifacts.hash_json("claim-http-attempt/v1", "claim"),
            "event_kind": "reextract_started",
            "actor": "expert:yyh",
            "idempotency_key": claim_artifacts.hash_json(
                "claim-http-attempt/v1", "started"
            ),
            "request_idempotency_key": "orphan-request",
            "route": "openai_compatible",
            "model": "deepseek-chat",
            "route_config_revision": claim_artifacts.hash_json(
                "claim-http-attempt/v1", "route-config"
            ),
            "budgets": {
                "max_calls": 1,
                "max_total_tokens": 4000,
                "allow_semantic_verifier": False,
            },
            "preconditions": {
                "claim_effective_revision": claim_artifacts.hash_json(
                    "claim-http-attempt/v1", "revision"
                ),
            },
            "focus": {"kind": "text_span", "block_id": "B1", "start": 0, "end": 5},
        }])

    def test_claim_gets_never_recover_interrupted_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            self._append_orphan_attempt(root)
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

            after = _file_bytes(root)

        self.assertTrue(all(status == 200 for status, _payload in responses))
        self.assertEqual(after, before)

    def test_queue_get_is_served_while_extraction_lease_is_live(self) -> None:
        from omission_actions import extraction_operation_lock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            self._append_orphan_attempt(root)
            with extraction_operation_lock(root, operation="claim-reextract"):
                with _claim_api(root) as base_url:
                    status, payload = _http_json(base_url, "/claim-queue")

        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertIn("attempt_log_revision", payload)

    def test_six_claim_gets_return_unavailable_http_200_for_legacy_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

        self.assertTrue(all(status == 200 for status, _payload in responses))
        for _status, payload in responses:
            self.assertFalse(payload["available"])
            self.assertIsNone(payload["base_generation_id"])
            self.assertIsNone(payload["document_effective_revision"])
            self.assertIsNone(payload["event_prefix_sha256"])

    def test_pending_effective_journal_returns_503_without_any_get_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            journal = root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL
            journal.write_bytes(b'{"unfinished":true}')
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

            after = _file_bytes(root)

        self.assertTrue(all(status == 503 for status, _payload in responses))
        self.assertTrue(all(
            payload["error"] == "effective_recovery_pending"
            and payload["retryable"] is True
            for _status, payload in responses
        ))
        self.assertEqual(after, before)

    def test_pending_journal_wins_over_legacy_migration_for_all_claim_gets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # publish_shadow_generation intentionally creates the legacy v1
            # effective snapshot; do not fold it before adding the WAL.
            _publish(root, _catalog())
            journal = root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL
            journal.write_bytes(b'{"unfinished":true}')
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

            after = _file_bytes(root)

        self.assertTrue(all(status == 503 for status, _payload in responses))
        self.assertTrue(all(
            payload["error"] == "effective_recovery_pending"
            and payload["retryable"] is True
            for _status, payload in responses
        ))
        self.assertEqual(after, before)

    def test_legacy_effective_requires_migration_for_all_claim_gets_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Phase 0 publication commits the internally consistent legacy v1
            # snapshot. GETs must request out-of-band migration, never fold it.
            _publish(root, _catalog())
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                responses = [_http_json(base_url, path) for path in self.ENDPOINTS]

            after = _file_bytes(root)

        self.assertTrue(all(status == 503 for status, _payload in responses))
        self.assertTrue(all(
            payload["error"] == "effective_migration_required"
            and payload["retryable"] is True
            for _status, payload in responses
        ))
        self.assertEqual(after, before)

    def test_torn_review_authority_returns_retryable_503_without_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            authority = root / "ai_review_states.jsonl"
            authority.write_bytes(b'{"ai_req_id":"AIR-1"')
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/claim-metrics")

            after = _file_bytes(root)

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "claim_artifact_unavailable")
        self.assertTrue(payload["retryable"])
        self.assertEqual(after, before)

    def test_live_authority_audit_gap_is_stale_and_http_get_is_read_only(self) -> None:
        for track in ("A", "B"):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if track == "A":
                    _publish_a_track(root, _catalog())
                    claim_review_actions.fold_effective_ledger(
                        root,
                        actor_trigger="http-a-track-audit-gap-seed",
                    )
                    authority = root / "review_states.jsonl"
                else:
                    self._seed(root)
                    authority = root / "ai_review_states.jsonl"
                existing = authority.read_bytes() if authority.is_file() else b""
                authority.write_bytes(existing + b"not-json\n")
                before = _file_bytes(root)

                with _claim_api(root) as base_url:
                    status, payload = _http_json(base_url, "/claim-metrics")

                after = _file_bytes(root)

                self.assertEqual(status, 200)
                self.assertFalse(payload["effective_fresh"])
                self.assertIn(
                    "review_authority_changed",
                    payload["freshness_reasons"],
                )
                self.assertTrue(payload["health"]["authority_audit_gap"])
                self.assertFalse(payload["document_ready"])
                self.assertEqual(after, before)

    def test_claim_pagination_errors_are_http_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            with _claim_api(root) as base_url:
                responses = [
                    _http_json(base_url, f"/claim-ledger?{query}")
                    for query in (
                        "limit=0",
                        "limit=501",
                        "limit=abc",
                        "offset=-1",
                        "offset=abc",
                    )
                ]
                compat_cases = {
                    "compat_limit=0": "claim compat_limit must be between 1 and 500",
                    "compat_limit=501": "claim compat_limit must be between 1 and 500",
                    "compat_limit=abc": "invalid claim compat_limit",
                    "compat_offset=-1": "claim compat_offset must be non-negative",
                    "compat_offset=abc": "invalid claim compat_offset",
                }
                compat_responses = {
                    query: _http_json(base_url, f"/claim-queue?{query}")
                    for query in compat_cases
                }

        self.assertTrue(all(status == 400 for status, _payload in responses))
        self.assertTrue(all(
            payload["retryable"] is False for _status, payload in responses
        ))
        for query, expected in compat_cases.items():
            status, payload = compat_responses[query]
            self.assertEqual(status, 400, query)
            self.assertEqual(payload["error"], expected, query)
            self.assertFalse(payload["retryable"], query)

    def test_compat_omission_pagination_slices_with_real_totals(self) -> None:
        import omission_actions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            blocks = [
                {"block_id": f"B{index}", "text": f"omitted block {index}"}
                for index in range(4)
            ]
            claim_artifacts.atomic_write_jsonl(root / "blocks.jsonl", blocks)
            claim_artifacts.atomic_write_jsonl(
                root / omission_actions.OMISSION_STATES,
                [
                    {
                        "omission_id": omission_actions.make_omission_id(
                            block["block_id"], block["text"],
                        ),
                        "block_id": block["block_id"],
                        "status": "needs_extraction",
                        "reason": "compat pagination probe",
                    }
                    for block in blocks
                ],
            )
            with _claim_api(root) as base_url:
                status, payload = _http_json(
                    base_url, "/claim-queue?compat_limit=2&compat_offset=1",
                )
                status_rest, rest = _http_json(
                    base_url, "/claim-queue?compat_limit=2&compat_offset=3",
                )
                status_unpaged, unpaged = _http_json(base_url, "/claim-queue")

        self.assertEqual(status, 200)
        self.assertEqual(payload["compat_omission_total"], 4)
        self.assertEqual(payload["compat_omission_limit"], 2)
        self.assertEqual(payload["compat_omission_offset"], 1)
        self.assertEqual(status_rest, 200)
        self.assertEqual(rest["compat_omission_offset"], 3)
        self.assertEqual(status_unpaged, 200)
        self.assertEqual(len(unpaged["compat_omissions"]), 4)
        # Unpaged contract: limit equals the returned row count.
        self.assertEqual(unpaged["compat_omission_limit"], 4)
        stable_order = [
            row["omission_id"] for row in unpaged["compat_omissions"]
        ]
        self.assertEqual(
            [row["omission_id"] for row in payload["compat_omissions"]],
            stable_order[1:3],
        )
        self.assertEqual(
            [row["omission_id"] for row in rest["compat_omissions"]],
            stable_order[3:],
        )
        self.assertEqual(
            payload["compat_omission_revision"],
            unpaged["compat_omission_revision"],
        )

    def test_http_review_events_hide_previous_generation_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            first_catalog = _catalog()
            requirement = _requirement(first_catalog)
            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "rejected",
                actor="http-rollover",
                reason="reject first generation",
                source_fingerprint_value=claim_ledger.target_source_fingerprint(
                    requirement
                ),
                review_subject_fingerprint_value=claim_ledger.target_fingerprint(
                    requirement
                ),
            )
            first = claim_artifacts.load_committed_effective_snapshot(root)
            old_claim_id = first["ledger"][0]["claim_id"]
            self.assertEqual(
                len(claim_review_actions.read_claim_review_events(root).rows),
                1,
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_review_states.jsonl", [])
            _publish(root, self._changed_catalog(), run_id="http-rollover-2")
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="http-rollover-second-generation",
            )

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/claim-review-events")
                filtered_status, filtered = _http_json(
                    base_url,
                    f"/claim-review-events?claim_id={old_claim_id}",
                )

        self.assertEqual(status, 200)
        self.assertEqual(filtered_status, 200)
        self.assertNotEqual(
            first["generation_meta"]["document_generation_id"],
            payload["document_generation_id"],
        )
        self.assertTrue(all(
            event["document_generation_id"] == payload["document_generation_id"]
            and event["catalog_generation_id"] == payload["catalog_generation_id"]
            for event in payload["events"]
        ))
        self.assertEqual(payload["total"], 0)
        self.assertEqual(filtered["total"], 0)
        self.assertEqual(filtered["events"], [])


class ClaimMutationHttpTests(unittest.TestCase):
    TOKEN = "claim-http-test-token"
    @staticmethod
    def _seed(root: Path) -> tuple[dict, dict, dict, list[dict]]:
        _publish(root, _catalog())
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="claim-mutation-http-test",
        )
        base = claim_artifacts.load_committed_claim_base(root)
        snapshot = claim_artifacts.load_committed_effective_snapshot(root)
        claim = base["catalog"][0]
        base_row = base["ledger"][0]
        groups = [
            group
            for group in base["groups"]
            if group["claim_id"] == claim["claim_id"]
        ]
        return snapshot, claim, base_row, groups

    def test_claim_adjudication_real_http_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, claim, base_row, groups = self._seed(root)
            revision = snapshot["effective_ledger"][0]["claim_effective_revision"]
            positive = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )["positive"][0]
            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-adjudications", {
                    "claim_id": claim["claim_id"],
                    "claim_hash": claim["claim_hash"],
                    "adjudication": "reopen",
                    "reason": "coverage requires expert correction",
                    "evidence": _source_exclusion_evidence(claim),
                    "actor": "expert:yyh",
                    "expected_claim_effective_revision": revision,
                    "supersedes_fact_hashes": [positive],
                    "request_idempotency_key": "http-success-1",
                }, token=self.TOKEN)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["event"]["event_kind"], "expert_adjudication")

    def test_claim_adjudication_real_http_stale_revision_is_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _snapshot, claim, _base_row, _groups = self._seed(root)
            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-adjudications", {
                    "claim_id": claim["claim_id"],
                    "claim_hash": claim["claim_hash"],
                    "adjudication": "reopen",
                    "reason": "stale concurrent review",
                    "evidence": _source_exclusion_evidence(claim),
                    "actor": "expert:yyh",
                    "expected_claim_effective_revision": claim_artifacts.hash_json(
                        "claim-http-stale/v1", "stale"
                    ),
                    "request_idempotency_key": "http-stale-1",
                }, token=self.TOKEN)

        self.assertEqual(status, 409)
        self.assertTrue(payload["needs_reconfirmation"])
        self.assertTrue(payload["claim_effective_revision"])

    def test_claim_adjudication_real_http_malformed_evidence_is_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, claim, _base_row, _groups = self._seed(root)
            revision = snapshot["effective_ledger"][0]["claim_effective_revision"]
            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-adjudications", {
                    "claim_id": claim["claim_id"],
                    "claim_hash": claim["claim_hash"],
                    "adjudication": "reopen",
                    "reason": "malformed evidence test",
                    "evidence": {},
                    "actor": "expert:yyh",
                    "expected_claim_effective_revision": revision,
                    "request_idempotency_key": "http-malformed-1",
                }, token=self.TOKEN)

        self.assertEqual(status, 400)
        self.assertIn("evidence", payload["error"])

    def test_claim_queue_execute_real_http_forwards_explicit_budget(self) -> None:
        expected = {
            "schema": "claim-queue-execution/v1",
            "lifecycle": "executed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_queue_execution.execute_claim_queue_proposal",
                return_value=expected,
            ) as execute, _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-queue/execute", {
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "expected_claim_effective_revision": (
                        "sha256:" + "1" * 64
                    ),
                    "expected_ledger_state": "uncertain",
                    "actor": "expert:yyh",
                    "allow_llm": True,
                    "route": "openai_compatible",
                    "maximum_calls": 4,
                    "total_token_budget": 20000,
                    "request_idempotency_key": "http-queue-1",
                    "expected_route_config_revision": "sha256:" + "2" * 64,
                }, token=self.TOKEN)

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected)
        self.assertEqual(execute.call_args.kwargs["maximum_calls"], 4)
        self.assertEqual(execute.call_args.kwargs["total_token_budget"], 20000)
        self.assertEqual(
            execute.call_args.kwargs["expected_route_config_revision"],
            "sha256:" + "2" * 64,
        )

    def test_claim_queue_new_paid_attempt_requires_route_revision_http_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-queue/execute", {
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "expected_claim_effective_revision": "sha256:" + "1" * 64,
                    "expected_ledger_state": "uncertain",
                    "actor": "expert:yyh",
                    "allow_llm": True,
                    "route": "openai_compatible",
                    "maximum_calls": 4,
                    "total_token_budget": 20000,
                    "request_idempotency_key": "http-queue-missing-route-revision",
                }, token=self.TOKEN)

            self.assertEqual(status, 409)
            self.assertTrue(payload["needs_reconfirmation"])
            self.assertIn("revision is required", payload["error"])
            self.assertFalse(
                (root / "claim_reextract_attempts.jsonl").exists()
            )

    def test_claim_queue_execute_omission_conflict_is_structured_409(self) -> None:
        from omission_actions import OmissionConflictError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_queue_execution.execute_claim_queue_proposal",
                side_effect=OmissionConflictError("omission state changed mid-flight"),
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-queue/execute", {
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "expected_claim_effective_revision": "sha256:" + "1" * 64,
                    "expected_ledger_state": "uncertain",
                    "actor": "expert:yyh",
                    "allow_llm": True,
                    "route": "openai_compatible",
                    "maximum_calls": 4,
                    "total_token_budget": 20000,
                    "request_idempotency_key": "http-queue-conflict-1",
                }, token=self.TOKEN)

        self.assertEqual(status, 409)
        self.assertTrue(payload["needs_reconfirmation"])
        self.assertTrue(payload["retryable"])
        self.assertIn("omission state changed", payload["error"])

    def test_claim_queue_execute_torn_attempt_log_is_healed_under_write_lock(self) -> None:
        """Append-mode writers can crash mid-line; queue execute owns the
        extraction lock and must heal the uncommitted torn tail back to the
        last complete generation instead of wedging on a recovery 503. The
        request then proceeds to its normal deterministic validation failure
        (missing paid-confirmation revision), and the log is loadable."""
        import claim_reextract_attempts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt_path = root / claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS
            attempt_path.write_bytes(b'{"schema":"claim-reextract-attempt/v1"')
            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-queue/execute", {
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "expected_claim_effective_revision": "sha256:" + "1" * 64,
                    "expected_ledger_state": "uncertain",
                    "actor": "expert:yyh",
                    "allow_llm": True,
                    "route": "openai_compatible",
                    "maximum_calls": 4,
                    "total_token_budget": 20000,
                    "request_idempotency_key": "http-torn-attempt-1",
                }, token=self.TOKEN)
            after = attempt_path.read_bytes()
            snapshot = claim_reextract_attempts.read_attempt_log(root)

        self.assertEqual(status, 409)
        self.assertIn(
            "route configuration revision is required",
            payload["error"],
        )
        self.assertNotEqual(after, b'{"schema":"claim-reextract-attempt/v1"')
        self.assertEqual(snapshot.last_event_seq, 0)

    def test_claim_queue_execute_forged_attempt_log_is_structured_503(self) -> None:
        import claim_reextract_attempts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt_path = root / claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS
            # A complete but forged line is corruption, not a crash artifact:
            # recovery must fail closed with the structured recovery-required
            # error and never rewrite the file. (Non-canonical key order makes
            # the scanner reject the row as untrusted, not torn.)
            forged = (
                b'{"schema":"claim-reextract-attempt/v2",'
                b'"idempotency_key":"forged"}\n'
            )
            attempt_path.write_bytes(forged)
            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(base_url, "/claim-queue/execute", {
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "expected_claim_effective_revision": "sha256:" + "1" * 64,
                    "expected_ledger_state": "uncertain",
                    "actor": "expert:yyh",
                    "allow_llm": True,
                    "route": "openai_compatible",
                    "maximum_calls": 4,
                    "total_token_budget": 20000,
                    "request_idempotency_key": "http-forged-attempt-1",
                }, token=self.TOKEN)
            after = attempt_path.read_bytes()

        self.assertEqual(status, 503)
        self.assertEqual(
            payload["error"],
            "claim_reextract_attempt_recovery_required",
        )
        self.assertTrue(payload["retryable"])
        self.assertEqual(after, forged)

    @staticmethod
    def _structural_override_payload() -> dict:
        return {
            "claim_id": "CLM-1111111111111111",
            "claim_hash": "sha256:" + "1" * 64,
            "expected_catalog_generation_id": "sha256:" + "2" * 64,
            "expected_claim_effective_revision": "sha256:" + "3" * 64,
            "prior_structural_reason": "repeated_page_furniture",
            "actor": "expert:yyh",
            "reason": "verified source content",
            "request_idempotency_key": "http-structural-1",
            "allow_llm": False,
            "route": "stub",
            "verifier_max_calls": 0,
            "verifier_max_total_tokens": 0,
        }

    def test_claim_structural_override_real_http_forwards_budget_contract(self) -> None:
        expected = {
            "ok": True,
            "status": "rebuilt",
            "effective_fresh": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                return_value=expected,
            ) as confirm, _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected)
        self.assertEqual(confirm.call_args.kwargs["allow_llm"], False)
        self.assertEqual(confirm.call_args.kwargs["verifier_max_calls"], 0)
        self.assertEqual(confirm.call_args.kwargs["verifier_max_total_tokens"], 0)

    def test_claim_structural_override_real_http_routes_exclusion_confirmation(self) -> None:
        expected = {
            "ok": True,
            "status": "confirmed_excluded",
            "appended": True,
        }
        request = self._structural_override_payload()
        request.update({
            "decision": "confirm_exclusion",
            "prior_structural_reason": "untyped_colon_spec_cell",
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_exclusion",
                return_value=expected,
            ) as confirm_exclusion, patch(
                "claim_structural_overrides.confirm_structural_override",
            ) as promote, _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    request,
                    token=self.TOKEN,
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected)
        promote.assert_not_called()
        self.assertEqual(
            confirm_exclusion.call_args.kwargs["prior_structural_reason"],
            "untyped_colon_spec_cell",
        )
        self.assertEqual(
            confirm_exclusion.call_args.kwargs["expected_claim_effective_revision"],
            request["expected_claim_effective_revision"],
        )

    def test_claim_structural_override_real_http_forwards_paid_reconfirmation(self) -> None:
        expected = {"ok": True, "status": "rebuilt", "effective_fresh": True}
        request = self._structural_override_payload()
        request.update({
            "operation_id": "CSOP-1111111111111111",
            "reconfirm_paid_work": True,
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                return_value=expected,
            ) as confirm, _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    request,
                    token=self.TOKEN,
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected)
        self.assertEqual(
            confirm.call_args.kwargs["operation_id"],
            "CSOP-1111111111111111",
        )
        self.assertTrue(confirm.call_args.kwargs["reconfirm_paid_work"])

    def test_claim_structural_override_real_http_stale_is_409(self) -> None:
        from claim_structural_overrides import ClaimStructuralOverrideStale

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                side_effect=ClaimStructuralOverrideStale(
                    "claim effective revision changed"
                ),
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

        self.assertEqual(status, 409)
        self.assertTrue(payload["needs_reconfirmation"])
        self.assertFalse(payload["retryable"])

    def test_claim_structural_override_real_http_invalid_is_400(self) -> None:
        from claim_structural_overrides import ClaimStructuralOverrideError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                side_effect=ClaimStructuralOverrideError(
                    "structural reason is not runtime-overridable"
                ),
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

        self.assertEqual(status, 400)
        self.assertFalse(payload["retryable"])
        self.assertIn("not runtime-overridable", payload["error"])

    def test_claim_structural_override_torn_event_log_is_503_without_recovery(self) -> None:
        from claim_review_actions import ClaimReviewActionError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            events_path = root / claim_review_actions.CLAIM_REVIEW_EVENTS
            before = events_path.read_bytes() if events_path.is_file() else b""

            with patch(
                "claim_structural_overrides.confirm_structural_override",
                side_effect=ClaimReviewActionError(
                    "claim review event log has a torn tail"
                ),
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

            after = events_path.read_bytes() if events_path.is_file() else b""

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "claim_review_event_recovery_required")
        self.assertTrue(payload["retryable"])
        # The endpoint must never truncate or repair the event log itself; explicit
        # claim maintenance (repair=True) is the only thing that quarantines a torn tail.
        self.assertEqual(after, before)

    def test_claim_structural_override_artifact_failure_is_distinct_retryable_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                side_effect=claim_artifacts.ClaimArtifactError(
                    "effective snapshot is temporarily unavailable"
                ),
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "claim_artifact_recovery_required")
        self.assertTrue(payload["retryable"])
        self.assertIn("temporarily unavailable", payload["detail"])

    def test_claim_structural_override_torn_operation_log_is_503_without_recovery(self) -> None:
        import claim_structural_operations

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            operation_path = (
                root / claim_structural_operations.CLAIM_STRUCTURAL_OPERATIONS
            )
            torn = b'{"schema":"claim-structural-operation/v3"'
            operation_path.write_bytes(torn)

            with _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

            after = operation_path.read_bytes()

        self.assertEqual(status, 503)
        self.assertEqual(
            payload["error"],
            "claim_structural_operation_recovery_required",
        )
        self.assertIn("torn tail", payload["detail"])
        self.assertTrue(payload["retryable"])
        self.assertEqual(after, torn)

    def test_claim_structural_override_real_http_rebuild_pending_is_503(self) -> None:
        pending = {
            "ok": False,
            "status": "rebuild_pending",
            "effective_fresh": False,
            "error": "base rebuild failed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                return_value=pending,
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

        self.assertEqual(status, 503)
        self.assertEqual(payload, pending)

    def test_claim_structural_override_real_http_reconfirmation_required_is_409(self) -> None:
        pending = {
            "ok": False,
            "status": "needs_reconfirmation",
            "needs_reconfirmation": True,
            "effective_fresh": False,
            "error": "paid verifier outcome is incomplete",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "claim_structural_overrides.confirm_structural_override",
                return_value=pending,
            ), _claim_api(root, local_token=self.TOKEN) as base_url:
                status, payload = _http_post_json(
                    base_url,
                    "/claim-structural-overrides",
                    self._structural_override_payload(),
                    token=self.TOKEN,
                )

        self.assertEqual(status, 409)
        self.assertEqual(payload, pending)


class AiReviewActionsTests(unittest.TestCase):
    def _req(self) -> dict:
        return {"source_section": "3.1.7", "source_quote": "meter shall measure",
                "title": "计量器具定义", "module": "计量"}

    def test_ai_req_id_stable_and_content_based(self) -> None:
        a = ai_review_actions.ai_req_id(self._req())
        b = ai_review_actions.ai_req_id(dict(self._req()))  # 同内容 → 同 ID
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("AIR-"))
        other = ai_review_actions.ai_req_id({**self._req(), "source_quote": "different"})
        self.assertNotEqual(a, other)  # 内容变 → ID 变

    def test_apply_and_read_latest_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rid = ai_review_actions.ai_req_id(self._req())
            ai_review_actions.apply_ai_review_action(out, rid, "needs_discussion", reason="待议")
            ai_review_actions.apply_ai_review_action(out, rid, "accepted",
                                                     module_override="计量精度", reason="改归精度")
            states = ai_review_actions.read_ai_review_states(out)
            self.assertEqual(states[rid]["status"], "accepted")            # 最近覆盖
            self.assertEqual(states[rid]["module_override"], "计量精度")

    def test_invalid_status_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ai_review_actions.apply_ai_review_action(Path(tmp), "AIR-x", "bogus")

    def test_endpoint_rejects_ambiguous_empty_module_override(self) -> None:
        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.read_json_body = lambda: {
            "ai_req_id": "AIR-1", "status": "accepted", "module_override": "",
        }
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))

        handler.handle_ai_review_action()

        self.assertEqual(responses[0][0], 400)
        self.assertIn("must not be empty", responses[0][1]["error"])

    def test_endpoint_uses_explicit_clear_module_override_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.output_dir = Path(tmp)
            handler.read_json_body = lambda: {
                "ai_req_id": "AIR-1", "status": "accepted",
                "source_fingerprint": "source-current",
                "review_subject_fingerprint": "subject-current",
                "expected_target_fingerprint": "target-current",
                "expected_target_publication_revision": "publication-current",
                "expected_target_authority_write_revision": "revision-current",
                "clear_module_override": True,
            }
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))
            current = {
                "ai_req_id": "AIR-1", "source_fingerprint": "source-current",
                "review_subject_fingerprint": "subject-current",
                "target_fingerprint": "target-current",
                "target_publication_revision": "publication-current",
                "target_authority_write_revision": "revision-current",
                "review_state": {"module_override": "计量精度"},
            }
            state = {"ai_req_id": "AIR-1", "status": "accepted", "module_override": None}
            with patch("api_server.find_current_ai_requirement", return_value=current), patch(
                "api_server.apply_ai_review_action", return_value=state,
            ) as apply:
                handler.handle_ai_review_action()

        self.assertEqual(responses, [(200, state)])
        self.assertIsNone(apply.call_args.kwargs["module_override"])


class AiRequirementsEndpointTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        (out / "blocks.jsonl").write_text(
            json.dumps({"block_id": "BLK-2", "order": 2, "text": "B", "section_path": ["4"],
                        "page_number": 1, "type": "paragraph", "kb_matches": [1, 2, 3]}) + "\n" +
            json.dumps({"block_id": "BLK-1", "order": 1, "text": "A", "section_path": ["3"],
                        "page_number": 1, "type": "heading", "kb_matches": []}) + "\n",
            encoding="utf-8")
        doc = {"requirements": [
            {"id": "REQ-001", "title": "T1", "description": "d1", "module": "计量",
             "source_section": "4", "source_quote": "q1", "source_block_ids": ["BLK-2"],
             "acceptance_criteria": ["c1"], "labels": ["计量"]},
        ]}
        (out / "merged_spec_requirements.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_document_blocks_sorted_and_trimmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            result = api_server.build_document_blocks(out)
            self.assertEqual(result["count"], 2)
            self.assertEqual([b["block_id"] for b in result["blocks"]], ["BLK-1", "BLK-2"])  # 按 order
            self.assertNotIn("kb_matches", result["blocks"][0])  # 重负载字段被裁掉

    def test_document_blocks_normalize_embedded_pdf_bullet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            blocks_path = out / "blocks.jsonl"
            rows = [json.loads(line) for line in blocks_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["text"] = "\uf8e7 closed locations"
            blocks_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            result = api_server.build_document_blocks(out)

            by_id = {block["block_id"]: block for block in result["blocks"]}
            self.assertEqual(by_id["BLK-2"]["text"], "- closed locations")

    def test_document_blocks_mark_failed_extraction_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 1,
                "failed_section_ids": ["4"],
                "failed_section_block_ids": ["BLK-2"],
            }), encoding="utf-8")

            result = api_server.build_document_blocks(out)

            by_id = {block["block_id"]: block for block in result["blocks"]}
            self.assertFalse(by_id["BLK-1"]["extraction_failed"])
            self.assertTrue(by_id["BLK-2"]["extraction_failed"])
            self.assertEqual(result["failed_section_ids"], ["4"])

    def test_document_blocks_reject_structurally_invalid_quality_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            (out / "ai_extract_quality.json").write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                api_server.build_document_blocks(out)

    def test_ai_extraction_status_exposes_legacy_quality_metrics(self) -> None:
        # 防回归：账本页新旧并列卡的旧口径来自本端点的 quality 字段——此前该字段
        # 缺失时前端 mock 照样全绿（mock 与生产背离），必须以后端断言钉死。
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "coverage_pct": 82.5,
                "core_coverage_pct": 75.0,
            }), encoding="utf-8")

            status = api_server.build_ai_extraction_status(out)

            self.assertEqual(
                status["quality"],
                {"coverage_pct": 82.5, "core_coverage_pct": 75.0},
            )

    def test_ai_extraction_status_rejects_invalid_quality_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "coverage_pct": True,
                "core_coverage_pct": 75.0,
            }), encoding="utf-8")

            with self.assertRaises(ValueError):
                api_server.build_ai_extraction_status(out)

    def test_document_endpoint_wraps_structural_json_error_as_retryable_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            (out / "ai_extract_quality.json").write_text("[]", encoding="utf-8")
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.path = "/document"
            handler.headers = {}
            handler.allowed_origins = set()
            handler.local_token = ""
            handler.output_dir = out
            handler.package_root = out
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))

            handler.do_GET()

        self.assertEqual(responses[0][0], 503)
        self.assertTrue(responses[0][1]["retryable"])

    def test_document_payload_includes_cross_document_custom_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            bank_path = out / "bank.json"
            bank_path.write_text(json.dumps({
                "version": 1,
                "accepted": {},
                "rejected": {},
                "modules": {"通信安全": {"count": 2, "requirement_ids": ["A", "B"]}},
            }, ensure_ascii=False), encoding="utf-8")
            with patch.dict("os.environ", {"RATOMIZER_ADJUDICATION_BANK": str(bank_path)}):
                result = api_server.build_document_blocks(out)

        self.assertIn("通信安全", result["module_vocabulary"])

    def test_anchor_block_id_precise_to_quote_paragraph(self) -> None:
        text_by_block = {
            "BLK-1": "Some intro paragraph without the requirement.",
            "BLK-2": "The meter shall measure volume accurately.",
            "BLK-3": "Other unrelated text.",
        }
        # 精确落到引用句所在的那一小段
        req = {"source_quote": "the meter shall measure volume",
               "source_block_ids": ["BLK-1", "BLK-2", "BLK-3"]}
        self.assertEqual(api_server.anchor_block_id(req, text_by_block), "BLK-2")
        # 引用跨到下一块（尾部超出本段）→ 前缀兜底仍落本段
        req2 = {"source_quote": "The meter shall measure volume accurately and store 12 months",
                "source_block_ids": ["BLK-1", "BLK-2"]}
        self.assertEqual(api_server.anchor_block_id(req2, text_by_block), "BLK-2")
        # 无匹配 → 回退 source_block_ids 首块
        req3 = {"source_quote": "totally nonexistent", "source_block_ids": ["BLK-3", "BLK-1"]}
        self.assertEqual(api_server.anchor_block_id(req3, text_by_block), "BLK-3")
        # 无 quote/无 span → 空
        self.assertEqual(api_server.anchor_block_id({}, text_by_block), "")

    def test_quote_matched_block_ids_returns_full_quote_span(self) -> None:
        """证据区应覆盖原句实际跨越的全部块——多段引句只亮首块会丢后半段（test5 实证）。"""
        text_by_block = {
            "BLK-1": "The terminal box must be supplied with crosshead screws.",
            "BLK-2": "Condition upon delivery - screws must be firmly tightened.",
            "BLK-3": "Unrelated packaging text.",
        }
        req = {
            "source_quote": (
                "The terminal box must be supplied with crosshead screws.\n"
                "Condition upon delivery - screws must be firmly tightened."
            ),
            "source_block_ids": ["BLK-1", "BLK-2", "BLK-3"],
        }
        self.assertEqual(
            api_server.quote_matched_block_ids(req, text_by_block), ["BLK-1", "BLK-2"]
        )
        # 无匹配 → 空（调用方如实回退锚点单块）
        req_none = {"source_quote": "totally nonexistent", "source_block_ids": ["BLK-3"]}
        self.assertEqual(api_server.quote_matched_block_ids(req_none, text_by_block), [])

    def test_anchor_block_id_ignores_pdf_word_internal_spaces(self) -> None:
        text_by_block = {
            "BLK-1": "Unrelated introductory paragraph.",
            "BLK-2": (
                "Electricity meters must beable to communicate bidirectionally "
                "with the data a nd communication center."
            ),
        }
        req = {
            "source_quote": (
                "Electricity meters must be able to communicate bidirectionally "
                "with the data and communication center."
            ),
            "source_block_ids": ["BLK-1", "BLK-2"],
        }

        self.assertEqual(api_server.anchor_block_id(req, text_by_block), "BLK-2")

    def test_echo_block_ids_for_duplicated_text(self) -> None:
        """回声锚点(0715 电表招标实证):同一段产品描述在 Scope 与 3.1 各出现一次,
        条目锚在首次出现,第二次出现在批注视图显示"未覆盖"——用户误判整段没解析出。
        碎词拆点不同("G SM" vs "GSM"),匹配必须用全剥空白底座。"""
        long_desc = ("Static three-phase alternating current meter with GSM modem 4G/LTE "
                     "for indirect measurement of active and reactive consumption")
        blocks = [
            {"block_id": "BLK-1", "text": "1 Scope of validity"},
            {"block_id": "BLK-2",
             "text": "Static three-phase alternating current meter with G SM modem 4G/LTE "
                     "for i ndirect measurement of active a nd reactive consumption"},
            {"block_id": "BLK-3", "text": "3.1 Electrical requirements"},
            {"block_id": "BLK-4",   # 第二次出现:碎词拆点不同
             "text": "Static three-phase a lternating current meter with GSM modem 4G/LTE "
                     "for indirect measurement of a ctive and reactive consumption"},
            {"block_id": "BLK-5", "text": "Voltage 110000/100 V", "noise": False},
            {"block_id": "BLK-6", "text": long_desc, "noise": True},   # 噪声块不回声
        ]
        req = {"source_quote": long_desc,
               "source_block_ids": ["BLK-2"], "anchor_block_id": "BLK-2"}
        echoes = api_server.compute_echo_block_ids(req, blocks)
        self.assertEqual(echoes, ["BLK-4"])   # 命中重复段;跳过锚点自身/噪声块/无关块

    def test_echo_near_duplicate_with_wording_drift(self) -> None:
        """真实形态(0715 电表招标):原文两次出现本身有措辞微差("measurement of"↔
        "measuring"),LLM 引句尾部又意译——引句互含路失效,靠锚点原文近重复路
        (J≥0.8+数字守卫)兜住。"""
        occ1 = ("Static three-phase alternating current meter with GSM modem 4G/LTE for "
                "indirect measurement of load profiles Q1, Q2, Q3, Q4, S and measurement "
                "of quality profiles.")
        occ2 = ("Static three-phase a lternating current meter with GSM modem 4G/LTE for "
                "i ndirect measurement of load profiles Q1, Q2, Q3, Q4, S a nd measuring "
                "quality profiles")
        blocks = [{"block_id": "BLK-1", "text": occ1},
                  {"block_id": "BLK-2", "text": occ2},
                  {"block_id": "BLK-3", "text": "Voltage transfer 110000/100 V and current 100/1 A."}]
        req = {"source_quote": occ1.replace("measurement of quality", "measurement of the quality"),
               "source_block_ids": ["BLK-1"], "anchor_block_id": "BLK-1"}   # 引句非逐字
        self.assertEqual(api_server.compute_echo_block_ids(req, blocks), ["BLK-2"])

    def test_echo_number_guard_blocks_template_rows(self) -> None:
        # 同版式不同数值的模板句:数字多重集守卫拦截(不回声)
        a = "The register shall record values every 15 minutes with a capacity of 60 days."
        b = "The register shall record values every 30 minutes with a capacity of 90 days."
        blocks = [{"block_id": "BLK-1", "text": a}, {"block_id": "BLK-2", "text": b}]
        req = {"source_quote": a, "source_block_ids": ["BLK-1"], "anchor_block_id": "BLK-1"}
        self.assertEqual(api_server.compute_echo_block_ids(req, blocks), [])

    def test_echo_short_quote_never_matches(self) -> None:
        blocks = [{"block_id": "BLK-1", "text": "The meter shall work."},
                  {"block_id": "BLK-2", "text": "The meter shall work."}]
        req = {"source_quote": "The meter shall work.",   # 剥空白后 <30 字
               "source_block_ids": ["BLK-1"], "anchor_block_id": "BLK-1"}
        self.assertEqual(api_server.compute_echo_block_ids(req, blocks), [])

    def test_build_ai_requirements_carries_echo_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            self.assertIn("echo_block_ids", rows[0])      # 字段恒在(空列表也在,契约稳定)

    def test_view_prefers_raw_ai_requirements_over_merged(self) -> None:
        """merged 会剔除 rejected（裁决回流交付物），批注视图须读原始文件——被拒条目仍可见、可反悔。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)  # merged 里 1 条
            raw = [
                {"title": "T1", "description": "d1", "module": "计量", "source_section": "4",
                 "source_quote": "q1", "source_block_ids": ["BLK-2"], "labels": ["计量"]},
                {"title": "T2", "description": "d2", "module": "显示", "source_section": "5",
                 "source_quote": "q2", "source_block_ids": ["BLK-1"], "labels": ["显示"]},
            ]
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                for r in raw:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 2)  # 读 raw（2 条），而非 merged（1 条）

    def test_ai_requirements_carry_id_anchor_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 1)
            rid = rows[0]["ai_req_id"]
            self.assertTrue(rid.startswith("AIR-"))
            self.assertEqual(rows[0]["source_block_ids"], ["BLK-2"])      # 锚点保留
            self.assertEqual(rows[0]["module_effective"], "计量")
            self.assertEqual(rows[0]["status"], "draft")                  # 未裁决
            # 裁决（改模块）后再读，module_effective 走 override
            ai_review_actions.apply_ai_review_action(out, rid, "accepted", module_override="计量精度")
            rows2 = api_server.build_ai_requirements(out)
            self.assertEqual(rows2[0]["status"], "accepted")
            self.assertEqual(rows2[0]["module_effective"], "计量精度")

    def test_ai_requirements_use_ownership_override_as_effective_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            rid = rows[0]["ai_req_id"]
            with (out / "ai_review_states.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ai_req_id": rid,
                    "status": "accepted",
                    "module_override": None,
                    "ownership_override": "hardware",
                    "reason": "",
                    "actor": "tester",
                }, ensure_ascii=False) + "\n")

            rows2 = api_server.build_ai_requirements(out)

            self.assertEqual(rows2[0]["ownership_effective"], "hardware")

    def test_raw_ai_requirements_preserve_explicit_ai_req_id_for_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ai_req_id": "AI-1",
                    "title": "Clock",
                    "description": "The meter shall support Clock object daylight saving time.",
                    "source_section": "4",
                    "source_quote": "support Clock object daylight saving time",
                    "source_block_ids": ["BLK-2"],
                }, ensure_ascii=False) + "\n")
            with (out / "ai_review_states.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ai_req_id": "AI-1",
                    "status": "accepted",
                    "ownership_override": "hardware",
                }, ensure_ascii=False) + "\n")

            rows = api_server.build_ai_requirements(out)

            self.assertEqual(rows[0]["ai_req_id"], "AI-1")
            self.assertEqual(rows[0]["status"], "accepted")
            self.assertEqual(rows[0]["ownership_effective"], "hardware")


class ClarificationBatchEndpointTests(unittest.TestCase):
    def test_internal_checks_endpoint_wraps_structural_json_error_as_retryable_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "consistency_report.json").write_text("[]", encoding="utf-8")
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.path = "/clarification-internal-checks"
            handler.headers = {}
            handler.allowed_origins = set()
            handler.local_token = ""
            handler.output_dir = out
            handler.package_root = out
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))

            handler.do_GET()

        self.assertEqual(responses[0][0], 503)
        self.assertTrue(responses[0][1]["retryable"])

    def test_batch_endpoint_returns_fingerprint_validation_summary(self) -> None:
        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.output_dir = Path(".")
        handler.read_json_body = lambda: {
            "checks": [{"clarification_id": "CLR-1", "evidence_fingerprint": "FP-1"}],
            "action": "verified_ok",
            "actor": "reviewer",
        }
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))
        expected = {
            "requested": 1, "applied": 1, "stale": [], "missing": [],
            "ineligible": [], "duplicates": [], "by_signal": {"suspicion:引用": 1},
            "by_module": {"计量": 1}, "readiness": None, "written": [],
        }
        with patch("clarification_report.batch_apply_internal_checks", return_value=expected) as apply:
            handler.handle_clarification_check_batch()

        self.assertEqual(responses, [(200, expected)])
        apply.assert_called_once()

    def test_batch_endpoint_reports_extraction_conflict_as_retryable_409(self) -> None:
        from omission_actions import OmissionConflictError

        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.output_dir = Path(".")
        handler.read_json_body = lambda: {
            "checks": [{"clarification_id": "CLR-1", "evidence_fingerprint": "FP-1"}],
        }
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))

        with patch(
            "clarification_report.batch_apply_internal_checks",
            side_effect=OmissionConflictError("extraction is running"),
        ):
            handler.handle_clarification_check_batch()

        self.assertEqual(responses[0][0], 409)
        self.assertTrue(responses[0][1]["retryable"])
        self.assertTrue(responses[0][1]["needs_reconfirmation"])


class ConsistencyFlagsTests(unittest.TestCase):
    """一致性闭环：P1b critic 的报表标记挂到批注视图行上（此前只写不读）。"""

    def _seed(self, out: Path) -> None:
        (out / "blocks.jsonl").write_text("", encoding="utf-8")
        rows = [
            {"ai_req_id": "AI-1", "title": "能量寄存器", "description": "记录 1-0:1.8.0.255",
             "source_quote": "total active energy import shall be recorded", "module": "计量",
             "source_section": "4", "source_block_ids": ["B1"], "labels": ["计量"]},
            {"ai_req_id": "AI-2", "title": "重复章", "description": "restated elsewhere",
             "source_quote": "total active energy import shall be recorded", "module": "计量",
             "source_section": "7", "source_block_ids": ["B2"], "labels": ["计量"]},
            {"ai_req_id": "AI-3", "title": "无关", "description": "unrelated",
             "source_quote": "something completely different here", "module": "显示",
             "source_section": "5", "source_block_ids": ["B3"], "labels": ["显示"]},
        ]
        with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_rows_carry_duplicate_and_obis_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            report = {
                "summary": {},
                "duplicate_groups": [{"source_quote": "total active energy import shall be recorded",
                                       "members": ["REQ-001", "REQ-050"], "count": 2}],
                "obis_coreference": [{"obis": "1-0:1.8.0.255", "values_differ": True, "count": 2},
                                      {"obis": "0-0:96.1.0.255", "values_differ": False, "count": 3}],
            }
            (out / "consistency_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            rows = {r["ai_req_id"]: r for r in api_server.build_ai_requirements(out)}

        self.assertIn("跨章重复×2", rows["AI-1"].get("consistency_flags", []))
        self.assertIn("跨章重复×2", rows["AI-2"].get("consistency_flags", []))
        # AI-1 描述里含数值待核的 OBIS → 也带 OBIS 标记；values_differ=False 的码不标
        self.assertTrue(any("1-0:1.8.0.255" in f for f in rows["AI-1"]["consistency_flags"]))
        self.assertFalse(any("96.1.0" in f for f in rows["AI-1"]["consistency_flags"]))
        self.assertNotIn("consistency_flags", rows["AI-3"])   # 无关行零标记

    def test_missing_or_broken_report_yields_no_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)          # 无报表
            self.assertTrue(all("consistency_flags" not in r for r in rows))

            (out / "consistency_report.json").write_text("{broken", encoding="utf-8")
            rows = api_server.build_ai_requirements(out)          # 损坏报表 → 不抛、零标记
            self.assertTrue(all("consistency_flags" not in r for r in rows))

            (out / "consistency_report.json").write_text("[]", encoding="utf-8")
            rows = api_server.build_ai_requirements(out)          # 结构错误同样不可裸崩
            self.assertTrue(all("consistency_flags" not in r for r in rows))


class FunctionalMembershipProjectionTests(unittest.TestCase):
    def test_ai_requirements_include_synthesized_function_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "ai_requirements.jsonl").write_text(json.dumps({
                "ai_req_id": "AI-1", "title": "采集事件", "description": "采集重要事件。",
                "source_quote": "Collect significant events.", "source_block_ids": ["B-1"], "module": "事件",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B-1", "order": 1, "text": "Collect significant events."
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            (out / "functional_requirements.json").write_text(json.dumps({"items": [{
                "functional_requirement_id": "FREQ-1", "title": "重要事件管理",
                "objective": "实现重要事件管理。", "behaviors": ["采集重要事件。"],
                "source_ai_requirement_ids": ["AI-1"], "merge_method": "event_subject",
                "merge_confidence": 0.9, "conflict_flags": [],
            }]}, ensure_ascii=False), encoding="utf-8")

            row = api_server.build_ai_requirements(out)[0]

        self.assertEqual(row["functional_requirement_id"], "FREQ-1")
        self.assertEqual(row["functional_title"], "重要事件管理")
        self.assertEqual(row["functional_objective"], "实现重要事件管理。")
        self.assertEqual(row["functional_behaviors"], ["采集重要事件。"])


class ClaimStartupMaintenanceTests(unittest.TestCase):
    def test_fresh_effective_snapshot_short_circuits_without_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="startup-fresh-seed",
            )
            before = _file_bytes(root)

            with (
                patch(
                    "claim_review_actions.fold_effective_ledger",
                    side_effect=AssertionError("fresh startup invoked fold"),
                ),
                patch(
                    "ai_extract.refresh_claim_shadow",
                    side_effect=AssertionError("fresh startup invoked base refresh"),
                ),
                patch(
                    "claim_ledger.build_shadow_ledger",
                    side_effect=AssertionError("fresh startup invoked verifier"),
                ),
                patch(
                    "llm_client.chat_json",
                    side_effect=AssertionError("fresh startup invoked LLM"),
                ),
            ):
                result = api_server.run_claim_startup_maintenance(root)

            after = _file_bytes(root)

        self.assertTrue(result["ok"])
        self.assertTrue(result["publication_skipped"])
        self.assertEqual(result["reason"], "already_fresh")
        self.assertEqual(after, before)

    def test_startup_maintenance_gate_reads_hidden_state_for_package_v1(self) -> None:
        # B1 回归（2026-08-03 审查）：package_v1 下 claim_generation.meta.json 落在
        # .ratomizer/state/，裸路径闸门曾把 package_v1 目录的启动维护整体静默跳过。
        from result_package import initialize_result_package, resolve_analysis_root

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "standard.docx"
            source.write_bytes(b"docx-fixture")
            initialize_result_package(
                root, input_path=source, requested_stages=["atomize"],
            )
            analysis_root = resolve_analysis_root(root)
            _publish(analysis_root, _catalog())
            self.assertFalse((analysis_root / "claim_generation.meta.json").exists())
            self.assertTrue(
                (root / ".ratomizer" / "state" / "claim_generation.meta.json").is_file()
            )

            result = api_server.run_claim_startup_maintenance(analysis_root)

        self.assertTrue(result["ok"])
        self.assertNotEqual(result.get("reason"), "claim_generation_unavailable")


class RequirementsEndpointTests(unittest.TestCase):
    """2026-08-14 性能/健壮性：/requirements 先切片再富化 + 撕裂尾结构化 503。"""

    @staticmethod
    def _write_requirements(root: Path, count: int) -> list[dict]:
        rows = [
            {
                "requirement_id": f"R{i}",
                "requirement_type": "functional",
                "text": f"row {i}",
            }
            for i in range(count)
        ]
        (root / "atomic_requirements.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
        )
        return rows

    def test_enriches_only_the_sliced_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = self._write_requirements(root, 5)
            seen: list[int] = []

            def fake_enrich(reqs, out_dir):
                seen.append(len(reqs))
                return list(reqs)

            with _claim_api(root) as base_url:
                with patch.object(api_server, "enrich_requirements", fake_enrich):
                    status, payload = _http_json(base_url, "/requirements?limit=2")
                    status_typed, payload_typed = _http_json(
                        base_url, "/requirements?limit=2&type=functional",
                    )

        self.assertEqual((status, status_typed), (200, 200))
        self.assertEqual(payload, rows[:2])
        self.assertEqual(payload_typed, rows[:2])
        # 全量语料（5 行）不再逐行富化——富化只看到切片页
        self.assertEqual(seen, [2, 2])

    def test_torn_tail_maps_to_structured_retryable_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "atomic_requirements.jsonl").write_text(
                json.dumps({"requirement_id": "R0"}) + "\n" + '{"broken": ',
                encoding="utf-8",
            )

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/requirements")

        self.assertEqual(status, 503)
        self.assertTrue(payload["retryable"])
        self.assertIn("Expecting", payload["error"])


class UnitRoutingEndpointTests(unittest.TestCase):
    def test_unit_routing_unavailable_without_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _claim_api(Path(tmp)) as base_url:
                status, payload = _http_json(base_url, "/unit-routing")
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])

    def test_unit_routing_returns_shadow_summary(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_extraction_units import _corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocks, table_items, cell_items, dispositions = _corpus()
            for name, rows in (("blocks.jsonl", blocks),
                               ("table_items.jsonl", table_items),
                               ("table_cell_items.jsonl", cell_items),
                               ("table_cell_dispositions.jsonl", dispositions)):
                (root / name).write_text(
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")
            from extraction_units import plan_extraction_units

            plan_extraction_units(root)
            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/unit-routing")
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        routing = payload["routing"]
        self.assertTrue(routing["shadow_mode"])
        self.assertGreater(routing["unit_count"], 0)
        self.assertIn("counts_by_route", routing)


class ReviewStatesBoundaryTests(unittest.TestCase):
    def test_torn_tail_maps_to_structured_retryable_503(self) -> None:
        # 此前 read_jsonl 的撕裂尾 ValueError 直接掉出 do_GET：连接断、无 JSON 错误包。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "review_states.jsonl").write_text(
                json.dumps({"requirement_id": "R0", "status": "accepted"}) + "\n"
                + '{"broken": ',
                encoding="utf-8",
            )

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/review-states")

        self.assertEqual(status, 503)
        self.assertTrue(payload["retryable"])

    def test_filter_and_limit_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                {"requirement_id": f"R{i}", "status": "accepted" if i % 2 else "draft"}
                for i in range(4)
            ]
            (root / "review_states.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
            )

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/review-states?status=accepted")

        self.assertEqual(status, 200)
        self.assertEqual(payload, [rows[1], rows[3]])


class ReviewsBoundaryTests(unittest.TestCase):
    """/reviews 撕裂尾与 /review-states 同口径：结构化 retryable 503，不掐断连接。"""

    def test_torn_tail_maps_to_structured_retryable_503(self) -> None:
        # 此前 read_jsonl 的撕裂尾 ValueError 直接掉出 do_GET：连接断、无 JSON 错误包
        # （/review-states 已补齐边界，/reviews 是漏网的兄弟端点）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llm_review_results.jsonl").write_text(
                json.dumps({"ai_req_id": "AIR-1"}) + "\n" + '{"broken": ',
                encoding="utf-8",
            )

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/reviews")

        self.assertEqual(status, 503)
        self.assertTrue(payload["retryable"])
        self.assertIn("Expecting", payload["error"])

    def test_intact_rows_and_limit_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"ai_req_id": f"AIR-{i}"} for i in range(3)]
            (root / "llm_review_results.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
            )

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/reviews?limit=2")

        self.assertEqual(status, 200)
        self.assertEqual(payload, rows[:2])


class RecoveryPendingHeavyViewTests(unittest.TestCase):
    """两个重型视图的 recovery-pending 503 必须带机器码 effective_recovery_pending。

    /table-reviews 此前落进 ClaimArtifactError 兜底、/document/pdf 落进 ValueError
    兜底，都只回裸文案字符串（error=<消息>）——前端 api-client 按 error 码自动
    POST /claim-maintenance，恰好这两个最重的视图永远不触发自恢复。必须与
    claim 视图（ClaimLedgerHttpTests 的 pending journal 用例）同形。"""

    def _seed_pending(self, root: Path) -> None:
        catalog = _catalog()
        (root / "blocks.jsonl").write_text(json.dumps({
            "block_id": "B1", "order": 1, "type": "paragraph",
            "text": catalog["catalog"][0]["text"],
            "section_path": ["4 Functions"], "noise": False,
        }) + "\n", encoding="utf-8")
        _publish(root, catalog)
        claim_review_actions.fold_effective_ledger(
            root, actor_trigger="recovery-pending-heavy-view-test",
        )
        # 未完成的 effective 发布 WAL = 只读消费方必须 fail-closed 的恢复挂起态
        (root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).write_bytes(
            b'{"unfinished":true}',
        )

    def test_table_reviews_maps_recovery_pending_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_pending(root)
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/table-reviews")

            after = _file_bytes(root)

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "effective_recovery_pending")
        self.assertTrue(payload["retryable"])
        self.assertIn("claim effective recovery pending", payload["detail"])
        # GET 只读：恢复挂起不得被请求路径顺手执行（fail-closed 契约）
        self.assertEqual(after, before)

    def test_document_pdf_maps_recovery_pending_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_pending(root)
            before = _file_bytes(root)

            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/document/pdf")

            after = _file_bytes(root)

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "effective_recovery_pending")
        self.assertTrue(payload["retryable"])
        self.assertIn("claim effective recovery pending", payload["detail"])
        self.assertEqual(after, before)


class AiExtractionStatusMemoTests(unittest.TestCase):
    def setUp(self) -> None:
        api_server._reset_payload_memo()

    def tearDown(self) -> None:
        api_server._reset_payload_memo()

    def test_status_is_memoized_on_source_signature(self) -> None:
        # 抽取轮询（DocumentReview ~180ms）不再每次重算指纹/富化。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "ai_requirements.partial.json").write_text("{}", encoding="utf-8")
            calls: list[int] = []

            def builder(out_dir):
                calls.append(1)
                return {
                    "schema": "ai-requirements-partial/v1",
                    "run_id": "run-1",
                    "rows": [{"ai_req_id": "AIR-1"}],
                }

            with patch.object(
                api_server, "_build_ai_extraction_status_impl", builder,
            ):
                first = api_server.build_ai_extraction_status(root)
                # 命中返回独立副本：调用方原地改行不污染缓存
                first["rows"].append({"ai_req_id": "AIR-2"})
                second = api_server.build_ai_extraction_status(root)
            self.assertEqual(len(calls), 1)
            self.assertEqual(second["rows"], [{"ai_req_id": "AIR-1"}])

            # partial 落盘（行完成）→ 签名变化 → 重建
            (root / "ai_requirements.partial.json").write_text(
                '{"completed": 1}', encoding="utf-8",
            )
            with patch.object(
                api_server, "_build_ai_extraction_status_impl", builder,
            ):
                third = api_server.build_ai_extraction_status(root)
            self.assertEqual(len(calls), 2)
            self.assertEqual(third["run_id"], "run-1")

    def test_builder_errors_are_not_cached(self) -> None:
        from ai_extract import AI_REQUIREMENTS_PARTIAL

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            # 无 partial 文件 + 坏质量文件 → 构建期 ValueError 如实穿透（不缓存失败）
            (root / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B1"}) + "\n", encoding="utf-8",
            )
            (root / "ai_extract_quality.json").write_text(
                '{"coverage_pct": "not-a-number"}', encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                api_server.build_ai_extraction_status(root)
            self.assertFalse(
                (root / AI_REQUIREMENTS_PARTIAL).exists(),
                "failed builds must not write side files",
            )


class StartupMaintenanceOrderTests(unittest.TestCase):
    """2026-08-14：就绪信号先于启动维护；维护在守护线程跑且每进程恰一次。"""

    def setUp(self) -> None:
        api_server._reset_startup_maintenance_for_tests()

    def tearDown(self) -> None:
        api_server._reset_startup_maintenance_for_tests()

    @staticmethod
    def _run_main(tmp: str, events: list[str]) -> int:
        class FakeServer:
            def __init__(self, address, handler):
                events.append("server-bound")

            def serve_forever(self):
                events.append("serving")
                return None

        def slow_maintenance(out_dir):
            events.append("maintenance-start")
            time.sleep(0.05)
            events.append("maintenance-end")

        def fake_print(*args, **kwargs):
            events.append("ready-printed")
            return json.loads(str(args[0]))

        with patch.object(api_server, "ThreadingHTTPServer", FakeServer), \
                patch.object(api_server, "_claim_generation_present", lambda d: True), \
                patch.object(api_server, "run_claim_startup_maintenance", slow_maintenance), \
                patch.object(
                    api_server, "run_table_review_recompute_recovery",
                    lambda d: events.append("recompute"),
                ), \
                patch.object(desktop_tasks, "setup_run_logging", lambda out: None), \
                patch("builtins.print", fake_print):
            code = api_server.main(["--out", tmp])
            # 在补丁上下文内 join 维护线程（补丁还原后线程会调用真实维护函数）
            thread = api_server._STARTUP_MAINTENANCE_THREAD
            if thread is not None:
                thread.join(timeout=5)
            return code

    def test_readiness_printed_before_maintenance_and_runs_once(self) -> None:
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            ready = self._run_main(tmp, events)
            # 不复位闸门直接跑第二次 main（Electron 30s 杀进程重试场景）：
            # 维护每进程恰一次，重试不得重做。
            again = self._run_main(tmp, events)
            api_server._reset_startup_maintenance_for_tests()

        self.assertEqual((ready, again), (0, 0))
        self.assertLess(events.index("server-bound"), events.index("ready-printed"))
        self.assertLess(events.index("ready-printed"), events.index("maintenance-start"))
        self.assertEqual(events.count("maintenance-start"), 1)
        self.assertEqual(events.count("recompute"), 1)

    def test_maintenance_failure_is_logged_and_process_still_serves(self) -> None:
        events: list[str] = []

        class FakeServer:
            def __init__(self, address, handler):
                events.append("server-bound")

            def serve_forever(self):
                events.append("serving")
                return None

        def broken_maintenance(out_dir):
            raise RuntimeError("maintenance exploded")

        with tempfile.TemporaryDirectory() as tmp, \
                self.assertLogs("requirement_atomizer", level="WARNING") as logs:
            with patch.object(api_server, "ThreadingHTTPServer", FakeServer), \
                    patch.object(api_server, "_claim_generation_present", lambda d: True), \
                    patch.object(api_server, "run_claim_startup_maintenance", broken_maintenance), \
                    patch.object(
                        api_server, "run_table_review_recompute_recovery",
                        lambda d: events.append("recompute"),
                    ), \
                    patch.object(desktop_tasks, "setup_run_logging", lambda out: None), \
                    patch("builtins.print", lambda *a, **k: None):
                code = api_server.main(["--out", tmp])
                thread = api_server._STARTUP_MAINTENANCE_THREAD
                if thread is not None:
                    thread.join(timeout=5)
            api_server._reset_startup_maintenance_for_tests()

        self.assertEqual(code, 0)
        self.assertEqual(events.count("recompute"), 1)
        self.assertTrue(any("claim effective startup maintenance lagged" in line for line in logs.output))


class ClaimSnapshotCacheWiringTests(unittest.TestCase):
    """2026-08-14：/table-reviews 与 /document/pdf 复用 stat 签名快照缓存。"""

    def _seed(self, root: Path) -> None:
        catalog = _catalog()
        (root / "blocks.jsonl").write_text(json.dumps({
            "block_id": "B1", "order": 1, "type": "paragraph",
            "text": catalog["catalog"][0]["text"],
            "section_path": ["4 Functions"], "noise": False,
        }) + "\n", encoding="utf-8")
        _publish(root, catalog)
        claim_review_actions.fold_effective_ledger(
            root, actor_trigger="snapshot-cache-wiring-test",
        )

    def test_repeated_gets_load_snapshot_once_per_variant(self) -> None:
        original = claim_artifacts.load_committed_effective_snapshot_readonly
        calls: list[bool] = []

        def counting(root, **kwargs):
            calls.append(bool(kwargs.get("require_v2", True)))
            return original(root, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            with _claim_api(root) as base_url:
                with patch.object(
                    claim_artifacts,
                    "load_committed_effective_snapshot_readonly",
                    counting,
                ):
                    t1 = _http_json(base_url, "/table-reviews")
                    t2 = _http_json(base_url, "/table-reviews")
                    p1 = _http_json(base_url, "/document/pdf")
                    p2 = _http_json(base_url, "/document/pdf")

        self.assertEqual([status for status, _ in (t1, t2)], [200, 200])
        self.assertEqual([status for status, _ in (p1, p2)], [200, 200])
        # require_v2=False（表评审投影）与 require_v2=True（批注）各只读一次盘
        self.assertEqual(sorted(calls), [False, True])

    def test_snapshot_stat_change_invalidates_the_cache(self) -> None:
        import os

        from result_package import governed_artifact_path
        from table_claim_authority import load_table_claim_authority_projection

        original = claim_artifacts.load_committed_effective_snapshot_readonly
        calls: list[int] = []

        def counting(root, **kwargs):
            calls.append(1)
            return original(root, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            with patch.object(
                claim_artifacts,
                "load_committed_effective_snapshot_readonly",
                counting,
            ):
                first = load_table_claim_authority_projection(root)
                second = load_table_claim_authority_projection(root)
                # 任一输入文件 stat 变化（mtime）→ 签名失效 → 重读（内容未变则结果一致）
                ledger = governed_artifact_path(
                    root, "claim_effective_ledger.jsonl", category="state", for_write=False,
                )
                os.utime(ledger, None)
                third = load_table_claim_authority_projection(root)

        self.assertEqual(len(calls), 2)
        self.assertEqual(first, second)
        self.assertEqual(third, first)


class MemoPayloadCopyTests(unittest.TestCase):
    """2026-08-14：memo 命中副本 = pickle 往返（同保别名），不可 pickle 回退 deepcopy。"""

    def test_copy_preserves_internal_aliasing(self) -> None:
        shared = {"id": 1}
        payload = [shared, shared]
        copied = api_server._memo_payload_copy(payload)
        self.assertEqual(copied, payload)
        self.assertIsNot(copied[0], shared)
        self.assertIs(copied[0], copied[1])

    def test_copy_falls_back_to_deepcopy_for_non_picklable_values(self) -> None:
        class Custom:
            """可 deepcopy（走 __deepcopy__）但不可 pickle 的值。"""

            def __deepcopy__(self, memo):
                return Custom()

            def __reduce_ex__(self, protocol):
                raise TypeError("not picklable")

            def __eq__(self, other):
                return isinstance(other, Custom)

        original = Custom()
        payload = {"rows": [{"id": 1}], "obj": original}
        copied = api_server._memo_payload_copy(payload)
        self.assertEqual(copied["rows"], payload["rows"])
        self.assertIsNot(copied["rows"][0], payload["rows"][0])
        self.assertIsNot(copied["obj"], original)


class SourceSignatureIdentityHardeningTests(unittest.TestCase):
    """完整性封堵（2026-08-14）：memo 源签名 (mtime_ns, size) 可被「同尺寸原子替换
    （tmp + os.replace）+ os.utime 还原 mtime」伪造——复查者实测复现：源文件换内容
    后轮询仍吐缓存里的旧载荷。签名加入 (st_dev, st_ino) 文件标识：工具链写路径全部
    经 tmp+os.replace 原子替换（新文件标识）→ 必然重建；残余风险仅为蓄意的同尺寸
    原地覆写+还原 mtime（非工具链写路径）。"""

    def setUp(self) -> None:
        api_server._reset_payload_memo()

    def tearDown(self) -> None:
        api_server._reset_payload_memo()

    def test_atomic_replace_samesize_rebuilds_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            partial = root / "ai_requirements.partial.json"
            partial.write_bytes(b'{"completed": 1}')
            calls: list[int] = []

            def builder(out_dir):
                calls.append(1)
                return {
                    "schema": "ai-requirements-partial/v1",
                    "run_id": f"run-{len(calls)}",
                    "rows": [],
                }

            with patch.object(
                api_server, "_build_ai_extraction_status_impl", builder,
            ):
                first = api_server.build_ai_extraction_status(root)
                # 同尺寸原子替换 + 还原 mtime：旧 (mtime_ns, size) 签名被完全伪造
                before = partial.stat()
                tmp_file = root / "ai_requirements.partial.json.spoof.tmp"
                tmp_file.write_bytes(b'{"completed": 2}')
                os.replace(tmp_file, partial)
                os.utime(partial, ns=(before.st_atime_ns, before.st_mtime_ns))
                after = partial.stat()
                self.assertEqual(
                    (before.st_mtime_ns, before.st_size),
                    (after.st_mtime_ns, after.st_size),
                )
                second = api_server.build_ai_extraction_status(root)

            self.assertEqual(len(calls), 2, "same-size spoof must invalidate memo")
            self.assertEqual(first["run_id"], "run-1")
            self.assertEqual(second["run_id"], "run-2")


if __name__ == "__main__":
    unittest.main()

