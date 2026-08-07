"""WS-B AI 裁决单元测试（B1-B4）。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import adjudicate as adjudicate_module
from adjudicate import (
    ADJUDICATION_SCHEMA,
    AUDIT_SCHEMA,
    RESULTS_FILENAME,
    AUDIT_FILENAME,
    AdjudicationRecord,
    HardBasis,
    adjudicate_all,
    adjudicate_item,
    auto_approve_enabled,
    auto_reject_enabled,
    calibration_state,
    hard_basis_check,
    overturn_adjudication,
    read_adjudication_results,
    read_adjudication_audit,
    semantic_vote,
)


class EnvFixtureMixin:
    """临时覆盖环境变量的测试辅助。"""

    def setUp(self) -> None:
        self._env_snapshot = dict(os.environ)

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key not in self._env_snapshot:
                del os.environ[key]
            else:
                os.environ[key] = self._env_snapshot[key]


class TestSwitches(EnvFixtureMixin, unittest.TestCase):
    def test_auto_approve_default_off(self) -> None:
        os.environ.pop("RATOMIZER_AUTO_ADJUDICATE_APPROVE", None)
        self.assertFalse(auto_approve_enabled())

    def test_auto_reject_default_off(self) -> None:
        os.environ.pop("RATOMIZER_AUTO_ADJUDICATE_REJECT", None)
        self.assertFalse(auto_reject_enabled())

    def test_approve_switch_respects_env(self) -> None:
        os.environ["RATOMIZER_AUTO_ADJUDICATE_APPROVE"] = "1"
        self.assertTrue(auto_approve_enabled())

    def test_reject_switch_respects_env(self) -> None:
        os.environ["RATOMIZER_AUTO_ADJUDICATE_REJECT"] = "1"
        self.assertTrue(auto_reject_enabled())


class TestHardBasis(unittest.TestCase):
    def _item(self, **overrides) -> dict:
        return {
            "functional_requirement_id": "FRE-0001",
            "objective": "实现计量功能",
            "source_quote": "The meter shall measure energy.",
            "source_section": "4.1",
            "source_block_ids": ["BLK-000001"],
            "rejected_codes": [],
            "numeric_drift_flag": False,
            "conflict_flags": [],
            **overrides,
        }

    def test_clean_item_ok(self) -> None:
        hard = hard_basis_check(self._item())
        self.assertTrue(hard.ok)
        self.assertEqual(hard.reject_reasons, [])

    def test_rejected_codes_veto(self) -> None:
        hard = hard_basis_check(self._item(rejected_codes=["0-0:96.1.0"]))
        self.assertFalse(hard.ok)
        self.assertTrue(any("漂移" in r for r in hard.reject_reasons))

    def test_unmatched_protected_code_veto(self) -> None:
        item = self._item(
            objective="实现计量功能",
            behaviors=["0-0:96.1.0"],
            source_quote="The meter shall measure energy.",
        )
        hard = hard_basis_check(item)
        self.assertFalse(hard.ok)
        self.assertTrue(any("无来源" in r for r in hard.reject_reasons))

    def test_numeric_drift_review(self) -> None:
        hard = hard_basis_check(self._item(numeric_drift_flag=True, numeric_drift_values=["999"]))
        self.assertTrue(hard.ok)
        self.assertTrue(any("数字漂移" in r for r in hard.review_reasons))

    def test_conflict_flags_review(self) -> None:
        hard = hard_basis_check(self._item(conflict_flags=["duplicate_title"]))
        self.assertTrue(hard.ok)
        self.assertTrue(any("冲突" in r for r in hard.review_reasons))

    def test_conservation_missing_veto(self) -> None:
        conservation = {
            "ok": False,
            "missing_block_ids": ["BLK-000001"],
            "duplicate_assignments": [],
            "extra_block_ids": [],
            "evidence_mismatches": [],
        }
        hard = hard_basis_check(self._item(), conservation=conservation)
        self.assertFalse(hard.ok)
        self.assertTrue(any("守恒缺失" in r for r in hard.reject_reasons))

    def test_conservation_duplicate_veto(self) -> None:
        conservation = {
            "ok": False,
            "missing_block_ids": [],
            "duplicate_assignments": ["BLK-000001"],
            "extra_block_ids": [],
            "evidence_mismatches": [],
        }
        hard = hard_basis_check(self._item(), conservation=conservation)
        self.assertFalse(hard.ok)
        self.assertTrue(any("守恒重复" in r for r in hard.reject_reasons))


class TestSemanticVote(unittest.TestCase):
    def test_injected_chat_returns_vote(self) -> None:
        item = {"objective": "x", "source_quote": "y"}
        chat = lambda _system, _user: {"vote": "accept", "reason": "ok"}
        vote, usage = semantic_vote(item, chat=chat)
        self.assertEqual(vote, "accept")
        self.assertTrue(usage["available"])

    def test_injected_chat_invalid_vote_becomes_none(self) -> None:
        item = {"objective": "x", "source_quote": "y"}
        chat = lambda _system, _user: {"vote": "maybe", "reason": "ok"}
        vote, usage = semantic_vote(item, chat=chat)
        self.assertIsNone(vote)
        self.assertTrue(usage["available"])

    def test_stub_route_unavailable(self) -> None:
        item = {"objective": "x", "source_quote": "y"}
        vote, usage = semantic_vote(item, route="stub")
        self.assertIsNone(vote)
        self.assertFalse(usage["available"])
        self.assertIn("unavailable", str(usage.get("error", "")).lower())


class TestCalibration(EnvFixtureMixin, unittest.TestCase):
    def test_pending_when_truth_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            truth = Path(tmp) / "truth.jsonl"
            truth.write_text("", encoding="utf-8")
            os.environ["RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET"] = str(truth)
            cal = calibration_state(tmp)
            self.assertEqual(cal.status, "pending_annotation")

    def test_calibrated_when_far_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            truth = Path(tmp) / "truth.jsonl"
            # 一条真值条目
            truth.write_text(json.dumps({
                "entry_id": "T1",
                "doc_ref": "doc",
                "source_anchor": {"section": "4.1", "coordinates": ["BLK-000001"]},
                "objective": "measure",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            # 产物完全覆盖真值
            products = Path(tmp) / "functional_requirements.json"
            products.write_text(json.dumps({
                "doc_ref": "doc",
                "items": [{
                    "functional_requirement_id": "FRE-0001",
                    "objective": "measure",
                    "source_section": "4.1",
                    "source_block_ids": ["BLK-000001"],
                }],
            }, ensure_ascii=False), encoding="utf-8")
            os.environ["RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET"] = str(truth)
            cal = calibration_state(tmp, products_path=products)
            self.assertEqual(cal.status, "calibrated")
            self.assertEqual(cal.far, 0.0)

    def test_insufficient_when_far_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            truth = Path(tmp) / "truth.jsonl"
            truth.write_text(json.dumps({
                "entry_id": "T1",
                "doc_ref": "doc",
                "source_anchor": {"section": "4.1", "coordinates": ["BLK-000001"]},
                "objective": "measure",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            # 产物空悬（precision 0）
            products = Path(tmp) / "functional_requirements.json"
            products.write_text(json.dumps({
                "doc_ref": "doc",
                "items": [{
                    "functional_requirement_id": "FRE-0001",
                    "objective": "measure",
                    "source_section": "4.2",
                    "source_block_ids": ["BLK-000002"],
                }],
            }, ensure_ascii=False), encoding="utf-8")
            os.environ["RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET"] = str(truth)
            cal = calibration_state(tmp, products_path=products)
            self.assertEqual(cal.status, "insufficient")
            self.assertEqual(cal.far, 1.0)


class TestAdjudicateItem(EnvFixtureMixin, unittest.TestCase):
    def _item(self, **overrides) -> dict:
        return {
            "functional_requirement_id": "FRE-0001",
            "objective": "实现计量功能",
            "source_quote": "The meter shall measure energy.",
            "source_section": "4.1",
            "source_block_ids": ["BLK-000001"],
            "rejected_codes": [],
            "numeric_drift_flag": False,
            "conflict_flags": [],
            **overrides,
        }

    def test_default_switch_all_off_goes_review(self) -> None:
        item = self._item()
        chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        self.assertEqual(record.decision, "review")
        self.assertEqual(record.semantic_vote, "accept")

    def test_hard_veto_overrides_semantic_accept(self) -> None:
        os.environ["RATOMIZER_AUTO_ADJUDICATE_APPROVE"] = "1"
        os.environ["RATOMIZER_AUTO_ADJUDICATE_REJECT"] = "1"
        item = self._item(rejected_codes=["0-0:96.1.0"])
        chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        self.assertEqual(record.decision, "reject")

    def test_approve_requires_calibration(self) -> None:
        os.environ["RATOMIZER_AUTO_ADJUDICATE_APPROVE"] = "1"
        item = self._item()
        chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        # 真值集为空 → pending_calibration → review
        self.assertEqual(record.decision, "review")
        self.assertEqual(record.calibration_status, "pending_annotation")

    def test_approve_with_calibration_and_clean_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            truth = Path(tmp) / "truth.jsonl"
            truth.write_text(json.dumps({
                "entry_id": "T1",
                "doc_ref": "doc",
                "source_anchor": {"section": "4.1", "coordinates": ["BLK-000001"]},
                "objective": "measure",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            products = Path(tmp) / "functional_requirements.json"
            products.write_text(json.dumps({
                "doc_ref": "doc",
                "items": [self._item()],
            }, ensure_ascii=False), encoding="utf-8")
            os.environ["RATOMIZER_AUTO_ADJUDICATE_APPROVE"] = "1"
            os.environ["RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET"] = str(truth)
            chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
            record = adjudicate_item(self._item(), out_dir=tmp, chat=chat)
            self.assertEqual(record.decision, "accept")

    def test_semantic_reject_does_not_auto_reject_without_hard_basis(self) -> None:
        # V4：自动拒绝仅限硬依据红灯；语义 reject 只转人工 review
        os.environ["RATOMIZER_AUTO_ADJUDICATE_REJECT"] = "1"
        item = self._item()
        chat = lambda _s, _u: {"vote": "reject", "reason": "bad"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        self.assertEqual(record.decision, "review")
        self.assertNotEqual(record.decision, "reject")

    def test_unavailable_llm_goes_review(self) -> None:
        item = self._item()
        record = adjudicate_item(item, out_dir=".", route="stub")
        self.assertEqual(record.decision, "review")
        self.assertFalse(record.semantic_usage["available"])

    def test_insufficient_evidence_short_quote_goes_review(self) -> None:
        # 来源引句过短 < FAITHFULNESS_MIN_SOURCE_CHARS，应标记 insufficient_evidence
        item = self._item(source_quote="shall")
        chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        self.assertEqual(record.decision, "review")
        self.assertEqual(record.low_score_category, "insufficient_evidence")
        self.assertFalse(record.customer_specific)

    def test_insufficient_evidence_missing_blocks_goes_review(self) -> None:
        item = self._item(source_block_ids=[])
        chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        self.assertEqual(record.decision, "review")
        self.assertEqual(record.low_score_category, "insufficient_evidence")

    def test_unfamiliar_but_faithful_accepted_and_tagged_when_approve_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            truth = Path(tmp) / "truth.jsonl"
            truth.write_text(json.dumps({
                "entry_id": "T1",
                "doc_ref": "doc",
                "source_anchor": {"section": "4.1", "coordinates": ["BLK-000001"]},
                "objective": "measure",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            products = Path(tmp) / "functional_requirements.json"
            products.write_text(json.dumps({
                "doc_ref": "doc",
                "items": [self._item(objective="unfamiliar capability X")],
            }, ensure_ascii=False), encoding="utf-8")
            os.environ["RATOMIZER_AUTO_ADJUDICATE_APPROVE"] = "1"
            os.environ["RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET"] = str(truth)
            os.environ["RATOMIZER_AUTO_ADJUDICATE_SAMPLE_RATE"] = "0"
            os.environ["RATOMIZER_AUTO_ADJUDICATE_REVIEW_RATE"] = "0"
            chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
            record = adjudicate_item(
                self._item(objective="unfamiliar capability X"),
                out_dir=tmp,
                chat=chat,
            )
            self.assertEqual(record.decision, "accept")
            self.assertEqual(record.low_score_category, "unfamiliar_but_faithful")
            self.assertTrue(record.customer_specific)

    def test_unfamiliar_but_faithful_goes_review_when_approve_disabled(self) -> None:
        item = self._item(objective="unfamiliar capability X")
        chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
        record = adjudicate_item(item, out_dir=".", chat=chat)
        self.assertEqual(record.decision, "review")
        self.assertEqual(record.low_score_category, "unfamiliar_but_faithful")
        self.assertTrue(record.customer_specific)


class TestAdjudicateAll(EnvFixtureMixin, unittest.TestCase):
    def _write_functional_requirements(self, out_dir: Path, items: list[dict]) -> None:
        payload = {
            "schema_version": 1,
            "items": items,
            "conservation": {"ok": True},
        }
        target = out_dir / "functional_requirements.json"
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_batch_writes_results_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {"functional_requirement_id": "FRE-0001", "objective": "a", "source_quote": "q", "source_block_ids": ["BLK-1"]},
                {"functional_requirement_id": "FRE-0002", "objective": "b", "source_quote": "q", "source_block_ids": ["BLK-2"], "rejected_codes": ["0-0:96.1.0"]},
            ]
            self._write_functional_requirements(out_dir, items)
            chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
            # 开启自动拒绝，让 total_auto > 0 从而生成 summary
            os.environ["RATOMIZER_AUTO_ADJUDICATE_REJECT"] = "1"
            summary = adjudicate_all(out_dir, items=items, chat=chat)
            self.assertEqual(summary["total"], 2)
            self.assertIn("review", summary["counts"])
            self.assertIn("reject", summary["counts"])
            results = read_adjudication_results(out_dir)
            self.assertEqual(len(results), 2)
            audit = read_adjudication_audit(out_dir)
            self.assertTrue(any(a.get("kind") == "summary" for a in audit))

    def test_overturn_appends_new_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {"functional_requirement_id": "FRE-0001", "objective": "a", "source_quote": "q", "source_block_ids": ["BLK-1"]},
            ]
            self._write_functional_requirements(out_dir, items)
            chat = lambda _s, _u: {"vote": "accept", "reason": "ok"}
            adjudicate_all(out_dir, items=items, chat=chat)
            overturn_adjudication(out_dir, "FRE-0001", new_decision="reject", actor="tester", reason="false positive")
            results = read_adjudication_results(out_dir)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["decision"], "reject")
            self.assertIn("人工推翻", results[0]["reason"])


class TestAPIIntegration(unittest.TestCase):
    """轻量端点冒烟：启动 api_server 并调用 adjudication 端点。"""

    def test_adjudication_endpoints_smoke(self) -> None:
        import threading
        import urllib.request

        from api_server import RequirementAPIHandler

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            # 写一份 functional_requirements.json
            payload = {
                "schema_version": 1,
                "items": [
                    {"functional_requirement_id": "FRE-0001", "objective": "a", "source_quote": "q", "source_block_ids": ["BLK-1"]},
                ],
                "conservation": {"ok": True},
            }
            (out_dir / "functional_requirements.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )

            RequirementAPIHandler.output_dir = out_dir
            RequirementAPIHandler.package_root = out_dir
            RequirementAPIHandler.allowed_origins = {"http://localhost:8770"}
            RequirementAPIHandler.local_token = "test-token"

            server = None
            try:
                from http.server import ThreadingHTTPServer
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequirementAPIHandler)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                base = f"http://127.0.0.1:{port}"
                headers = {
                    "X-Requirement-Atomizer-Token": "test-token",
                    "Origin": "http://localhost:8770",
                    "Content-Type": "application/json",
                }

                with urllib.request.urlopen(
                    urllib.request.Request(f"{base}/adjudication-summary", headers=headers, method="GET"),
                    timeout=5,
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(body["schema"], "adjudication-summary/v1")

                with urllib.request.urlopen(
                    urllib.request.Request(
                        f"{base}/adjudications/run",
                        data=json.dumps({"actor": "test"}).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    ),
                    timeout=5,
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(body["ok"])
                    self.assertEqual(body["total"], 1)

                with urllib.request.urlopen(
                    urllib.request.Request(f"{base}/adjudications", headers=headers, method="GET"),
                    timeout=5,
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(body["schema"], "adjudications/v1")
                    self.assertEqual(body["total"], 1)
            finally:
                if server is not None:
                    server.shutdown()


if __name__ == "__main__":
    unittest.main()
