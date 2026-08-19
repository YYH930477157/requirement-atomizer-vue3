"""§3.4 Claim 迁移到功能需求的机制测试（2026-08-15）。

- B 轨 target store 抽象：原子在场优先，直抽次之，两者皆无响亮失败；
- 直抽模式发布：generation 绑定 functional_requirements.json（FRE- 主键进 coverage）；
- 篡改检测：functional store 变化后 committed lineage 校验失败（fail-closed）；
- 直抽产物不守恒/执行不完整 → 不进 claim 绑定（functional_direct_basis 响亮 raise）;
- 队列执行在直抽模式诚实拒绝（原子级补丁不写错 store）。

纪律：单测禁止真实 LLM 调用（route=stub opt-in）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import desktop_tasks


def _write_min_corpus(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        '{"block_id":"B1","section_path":["4.1"],"text":"The meter shall log events."}\n',
        encoding="utf-8",
    )
    (out / "chunks.jsonl").write_text(
        '{"section_path":["4.1"],"heading":"4.1",'
        '"text":"The meter shall log events.","block_ids":["B1"]}\n',
        encoding="utf-8",
    )


def _write_direct_product(out: Path, *, conservation_ok: bool = True,
                          execution_status: str = "ok") -> None:
    payload = {
        "schema_version": 1,
        "producer": "functional-extract-v1",
        "route_requested": "stub",
        "route": "stub",
        "execution_status": execution_status,
        "fingerprint": "fp-claim-test",
        "items": [{
            "functional_requirement_id": "FRE-CLAIM1",
            "objective": "The meter shall log events",
            "behaviors": ["log events"],
            "title": "事件记录",
            "module": "计量",
            "source_quote": "The meter shall log events.",
            "source_section": "4.1",
            "source_block_ids": ["B1"],
            "merge_method": "functional_extract",
        }],
        "conservation": {
            "ok": conservation_ok,
            "missing_block_ids": [] if conservation_ok else ["B1"],
        },
    }
    (out / "functional_requirements.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ResolveTargetStoreTests(unittest.TestCase):
    def test_stale_atomic_file_does_not_hijack_functional_generation(self) -> None:
        """复审 P1：已提交 functional generation 的 store 权威 > 旧 ai_requirements 残留。"""
        from claim_review_actions import _resolve_b_target_store

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            _run_real_extraction(out)
            desktop_tasks._publish_functional_claim_shadow(
                out, route="openai_compatible")
            # 残留的旧原子产物（例如直抽切换前遗留）
            (out / "ai_requirements.jsonl").write_text(
                '{"ai_req_id":"AIR-STALE"}\n', encoding="utf-8")
            self.assertEqual(
                _resolve_b_target_store(out), "functional_requirements.json")

    def test_no_generation_meta_falls_back_to_file_presence(self) -> None:
        from claim_review_actions import _resolve_b_target_store

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "ai_requirements.jsonl").write_text(
                '{"ai_req_id":"AIR-1"}\n', encoding="utf-8")
            self.assertEqual(_resolve_b_target_store(out), "ai_requirements.jsonl")

    def test_atomic_store_preferred_when_present(self) -> None:
        from claim_ledger import resolve_b_track_target_store

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_direct_product(out)
            (out / "ai_requirements.jsonl").write_text(
                '{"ai_req_id":"AIR-1"}\n', encoding="utf-8")
            store, rows = resolve_b_track_target_store(out)
            self.assertEqual(store, "ai_requirements.jsonl")
            self.assertEqual(rows[0]["ai_req_id"], "AIR-1")

    def test_functional_store_used_when_no_atoms(self) -> None:
        from claim_ledger import resolve_b_track_target_store

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_direct_product(out)
            store, rows = resolve_b_track_target_store(out)
            self.assertEqual(store, "functional_requirements.json")
            self.assertEqual(rows[0]["functional_requirement_id"], "FRE-CLAIM1")

    def test_no_store_raises(self) -> None:
        from claim_ledger import resolve_b_track_target_store

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                resolve_b_track_target_store(Path(td))

    def test_unconserved_direct_product_refused(self) -> None:
        from claim_ledger import resolve_b_track_target_store
        import functional_extract as fe

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_direct_product(out, conservation_ok=False)
            with self.assertRaises(fe.FunctionalConservationError):
                resolve_b_track_target_store(out)

    def test_incomplete_direct_product_refused(self) -> None:
        from claim_ledger import resolve_b_track_target_store
        import functional_extract as fe

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_direct_product(out, execution_status="failed")
            with self.assertRaises(fe.FunctionalExtractionIncompleteError):
                resolve_b_track_target_store(out)


def _healthy_chat(system: str, user: str) -> dict:
    return {"items": [{
        "objective": "The meter shall log events",
        "behaviors": ["log events"],
        "source_quote": "The meter shall log events.",
        "source_block_ids": ["B1"],
    }]}


def _run_real_extraction(out: Path) -> None:
    """注入 chat 的真实直抽（executed=injected → 非草稿、execution ok）。"""
    import functional_extract as fe

    sections = [{
        "section_id": "4.1", "section_path": ["4.1"], "heading": "4.1",
        "text": "The meter shall log events.", "block_ids": ["B1"],
    }]
    result = fe.run_functional_extract(
        out, sections=sections, chat=_healthy_chat, route="openai_compatible")
    assert result["execution_status"] == "ok"
    assert not result["draft"]


class DirectModePublishTests(unittest.TestCase):
    def test_direct_publish_binds_functional_store(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            _run_real_extraction(out)
            shadow = desktop_tasks._publish_functional_claim_shadow(
                out, route="openai_compatible")
            self.assertEqual(shadow.get("store"), "functional_requirements.json")
            meta = json.loads(
                (out / "claim_generation.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["requirements_store"], "functional_requirements.json")
            from claim_artifacts import file_sha256
            self.assertEqual(
                meta["requirements_sha256"],
                file_sha256(out / "functional_requirements.json"))
            self.assertEqual(
                meta["requirements_producer_lineage"].get("producer"),
                "functional-extract-v1")
            # coverage targets 用 FRE 主键（source_ai_requirement_id 直通）
            coverage = [
                json.loads(line) for line in
                (out / "claim_coverage_groups.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            target_ids = {
                str(edge.get("target_requirement_id"))
                for group in coverage
                for edge in (group.get("edges") or [])
            }
            self.assertTrue(any(tid.startswith("FRE-") for tid in target_ids), target_ids)

    def test_tampered_functional_store_fails_lineage_verification(self) -> None:
        from claim_artifacts import ClaimArtifactError, load_committed_attempt_lineage

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            _run_real_extraction(out)
            desktop_tasks._publish_functional_claim_shadow(
                out, route="openai_compatible")
            # 首次校验通过（发布自洽）
            load_committed_attempt_lineage(out)
            # 篡改 functional store → 哈希失配，fail-closed
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            payload["items"][0]["objective"] = "tampered narrative"
            (out / "functional_requirements.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ClaimArtifactError):
                load_committed_attempt_lineage(out)

    def test_queue_execution_no_longer_refuses_in_direct_mode(self) -> None:
        """M2 §4.3：队列对直抽模式分流执行，不再整体拒绝。

        未带 allow_llm 的新尝试仍按通用纪律拒绝（付费执行必须显式授权）——
        功能级分流 E2E 见 tests/test_functional_claim_queue.py。
        """
        from claim_queue_execution import execute_claim_queue_proposal

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            _run_real_extraction(out)
            desktop_tasks._publish_functional_claim_shadow(
                out, route="openai_compatible")
            with self.assertRaises(ValueError) as ctx:
                execute_claim_queue_proposal(
                    out,
                    proposal_id="P1",
                    expected_claim_effective_revision="rev",
                    expected_ledger_state="state",
                    actor="tester",
                    allow_llm=False,
                    route="openai_compatible",
                    maximum_calls=0,
                    total_token_budget=0,
                    request_idempotency_key="k1",
                )
            self.assertIn("allow_llm=true", str(ctx.exception))


class DirectModeFullClosureE2ETests(unittest.TestCase):
    """复审 P1-4：直抽模式 full closure 端到端可达（专家路径，非 LLM 队列）。

    链路：真实直抽（注入 chat）→ claim 发布（functional store）→ 专家经指纹路径接受
    FRE 条目（/functional-review-actions 同款）→ 专家 claim 裁决闭合 uncertain →
    evaluate_full_closure ready=True 零缺口。队列执行（原子级 targeted reextract）
    在直抽模式仍诚实拒绝——LLM 重抽队列的功能级等价物是独立的后续设计。
    """

    def test_full_closure_ready_via_expert_paths(self) -> None:
        import os

        import functional_extract as fe

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
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
            self.assertFalse(result["draft"])
            desktop_tasks._publish_functional_claim_shadow(
                out, route="openai_compatible")

            # 专家接受 FRE 条目（带指纹——与 POST /functional-review-actions 同款；
            # 无指纹的 legacy 裁决会让 claim 边失效）
            from ai_review_actions import (
                apply_ai_review_action,
                review_anchor_fingerprint,
                review_subject_fingerprint,
                source_ai_requirement_id,
                source_fingerprint,
            )
            from requirements_analysis_rules import _read_functional_requirements_payload
            item = _read_functional_requirements_payload(out)["items"][0]
            apply_ai_review_action(
                out, source_ai_requirement_id(item), "accepted",
                level="functional", actor="expert",
                source_fingerprint_value=source_fingerprint(item),
                review_subject_fingerprint_value=review_subject_fingerprint(item),
                review_anchor_fingerprint_value=review_anchor_fingerprint(item),
            )

            # 专家 claim 裁决闭合 uncertain（coverage_group 证据 + CAS revision）
            from claim_review_actions import (
                apply_claim_adjudication,
                claim_coverage_group_hash,
            )
            groups = [
                json.loads(line) for line in
                (out / "claim_coverage_groups.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(groups[0].get("status"), "validated")
            ledger = [
                json.loads(line) for line in
                (out / "claim_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            row = ledger[0]
            effective = [
                json.loads(line) for line in
                (out / "claim_effective_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            eff_row = next(x for x in effective if x["claim_id"] == row["claim_id"])
            apply_claim_adjudication(
                out, claim_id=row["claim_id"], claim_hash=row["claim_hash"],
                adjudication="covered", reason="条款已被功能需求覆盖",
                evidence={
                    "kind": "coverage_group",
                    "coverage_group_id": groups[0]["coverage_group_id"],
                    "coverage_group_hash": claim_coverage_group_hash(groups[0]),
                },
                actor="expert",
                expected_claim_effective_revision=eff_row["claim_effective_revision"],
            )

            import unittest.mock
            with unittest.mock.patch.dict(
                    os.environ, {"RATOMIZER_CLAIM_LEDGER_MODE": "full"}):
                closure = desktop_tasks.evaluate_full_closure(out)
            self.assertTrue(closure["ready"], closure["gaps"])
            self.assertEqual(closure["gaps"], [])


class StubDraftNonPublishableTests(unittest.TestCase):
    """§3.5（复审 P1）：显式 stub 是草稿——claim 不绑定、closure 显式缺口、证据拒绝。"""

    def test_stub_task_marks_draft_and_skips_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            result = desktop_tasks.functional_extract_task(out, route="stub")
            self.assertTrue(result["draft"])
            self.assertEqual(
                result["claim_shadow"].get("skipped"), "draft_stub_product")
            self.assertFalse((out / "claim_generation.meta.json").exists())
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["draft"])

    def test_stub_draft_blocks_closure_and_evidence(self) -> None:
        from result_package import _functional_product_is_draft

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            desktop_tasks.functional_extract_task(out, route="stub")
            self.assertTrue(_functional_product_is_draft(out))
            closure = desktop_tasks.evaluate_full_closure(out)
            kinds = {g["kind"] for g in closure["gaps"]}
            self.assertFalse(closure["ready"])
            self.assertIn("functional_extract_draft", kinds)


class EmptyLedgerReadinessTests(unittest.TestCase):
    def test_empty_claim_generation_is_explicit_gap_not_silent_pass(self) -> None:
        """空账本 ≠ 已完成：无 claim generation 时 full closure 显式缺口。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            (out / "ai_requirements.jsonl").unlink(missing_ok=True)
            payload = desktop_tasks.evaluate_full_closure(out)
            self.assertFalse(payload["ready"])
            kinds = {g["kind"] for g in payload["gaps"]}
            self.assertIn("claim_document_not_ready", kinds)


if __name__ == "__main__":
    unittest.main()
