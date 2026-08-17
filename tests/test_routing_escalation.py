"""M5 局部升级接线（方案 §9.3/§19，2026-08-17）：routing gap → 既有 claim 队列。

矩阵（全部离线：chat/executor 注入，禁止真实 LLM）：
① 守恒失败产品 → 块级 targeted_reextract 缺口（gaps_from_functional_product）；
② 可执行缺口匹配 pending proposal → 走 execute_claim_queue_proposal 真实机械
   （E2E：functional_targeted_reextract 条款族重抽 + WAL + fold，未受影响 FRE 稳定）；
③ 无匹配 proposal → no_matching_proposal，绝不伪造 claim 锚；
④ expert_review/needs_work 缺口永不自动执行；
⑤ 同一 proposal 只执行一次（多缺口共享时消费后移除）；
⑥ 队列异常分类如实落账（CAS 冲突/可重试/失败）；
⑦ 幂等键稳定（gap-{gap_id}-{salt}）——重放走队列自身幂等。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ai_extract
import claim_queue_execution as execution
import claim_reextract_attempts
import desktop_tasks
import functional_extract as fe
from llm_client import LLMClientConfig
from routing_escalation import (
    OUTCOME_EXECUTED,
    OUTCOME_NO_MATCH,
    ROUTING_ESCALATIONS_FILENAME,
    actionable_gaps,
    escalate_gaps,
    gap_block_ids,
    load_routing_escalations,
)
from routing_gaps import build_gap, gaps_from_functional_product

B1_TEXT = "The meter shall log events."
B2_TEXT = "The controller shall forward alarms to the management platform."
WEAK_B2_OBJECTIVE = "Alarms from the controller shall reach the management platform."


def _sections() -> list[dict]:
    return [
        {"section_id": "4.1", "section_path": ["4.1"], "heading": "4.1",
         "text": B1_TEXT, "block_ids": ["B1"]},
        {"section_id": "4.2", "section_path": ["4.2"], "heading": "4.2",
         "text": B2_TEXT, "block_ids": ["B2"]},
    ]


def _write_corpus(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        '{"block_id":"B1","section_path":["4.1"],"text":"'
        + B1_TEXT.replace('"', '\\"') + '"}\n'
        '{"block_id":"B2","section_path":["4.2"],"text":"'
        + B2_TEXT.replace('"', '\\"') + '"}\n',
        encoding="utf-8")
    (out / "chunks.jsonl").write_text(
        '{"section_path":["4.1"],"heading":"4.1","text":"'
        + B1_TEXT.replace('"', '\\"') + '","block_ids":["B1"]}\n'
        '{"section_path":["4.2"],"heading":"4.2","text":"'
        + B2_TEXT.replace('"', '\\"') + '","block_ids":["B2"]}\n',
        encoding="utf-8")


def _chat_v1(system: str, user: str) -> dict:
    return {"items": [
        {"objective": B1_TEXT, "behaviors": ["log events"],
         "source_quote": B1_TEXT, "source_block_ids": ["B1"]},
        {"objective": WEAK_B2_OBJECTIVE, "behaviors": ["deliver alarms"],
         "source_quote": B2_TEXT, "source_block_ids": ["B2"]},
    ]}


def _chat_v2_with_meta(calls: list[str] | None = None):
    def chat(_config, system, user, *, request_budget=None):
        if calls is not None:
            calls.append(user)
        return {"items": [{
            "objective": B2_TEXT, "behaviors": ["forward alarms"],
            "source_quote": B2_TEXT, "source_block_ids": ["B2"],
        }]}, {}
    return chat


def _seed_direct_mode(root: Path) -> dict:
    _write_corpus(root)
    result = fe.run_functional_extract(
        root, sections=_sections(), chat=_chat_v1, route="openai_compatible")
    assert result["execution_status"] == "ok", result
    desktop_tasks._publish_functional_claim_shadow(root, route="openai_compatible")
    from claim_artifacts import load_committed_effective_snapshot

    snapshot = load_committed_effective_snapshot(root)
    proposals = [dict(row) for row in snapshot.get("queue_proposals") or []]
    assert proposals, "seed must leave an uncertain claim with a queue proposal"
    return proposals[0]


def _config() -> LLMClientConfig:
    return LLMClientConfig(base_url="https://example.invalid/v1", model="deepseek-chat",
                           max_tokens=128, max_retries=0)


def _read_product(root: Path) -> dict:
    return json.loads((root / "functional_requirements.json").read_text(encoding="utf-8"))


class GapBuilderTests(unittest.TestCase):
    def test_failed_product_yields_block_anchored_gaps(self) -> None:
        product = {
            "execution_status": "failed",
            "conservation": {"ok": False, "checks": {
                "evidence_presence": {"ok": False, "evidence_mismatches": [
                    {"functional_requirement_id": "FRE-1", "reason": "quote_matches_no_block",
                     "declared_block_ids": ["BLK-000219"], "quote_hit_block_ids": []}]},
                "duplicates": {"ok": False, "groups": [
                    {"section_id": "2 20", "functional_requirement_ids": ["FRE-2", "FRE-3"],
                     "block_ids": ["BLK-000690", "BLK-000692"]}]},
                "obligation_coverage": {"ok": True, "uncovered_obligations": [
                    {"sentence_index": 3, "unit_index": 0, "sentence": "shall do X"}]},
            }},
        }
        gaps = gaps_from_functional_product(product, product_fingerprint="sha256:abc")
        by_action = {}
        for gap in gaps:
            by_action.setdefault(gap["recommended_action"], []).append(gap)
        # 块锚失败 → targeted_reextract；无锚义务/执行失败 → needs_work
        self.assertEqual(len(by_action["targeted_reextract"]), 2)
        self.assertEqual(len(by_action["needs_work"]), 2)
        self.assertTrue(all(g["blocking"] for g in gaps))
        self.assertEqual(by_action["targeted_reextract"][0]["block_ids"], ["BLK-000219"])
        self.assertEqual(by_action["targeted_reextract"][1]["block_ids"],
                         ["BLK-000690", "BLK-000692"])
        self.assertEqual(by_action["targeted_reextract"][0]["source_hash"], "sha256:abc")
        # 健康/空产品零缺口
        self.assertEqual(gaps_from_functional_product({"execution_status": "ok"}), [])
        self.assertEqual(gaps_from_functional_product(None), [])


class EscalationUnitTests(unittest.TestCase):
    def test_actionable_filter_and_block_resolution(self) -> None:
        targeted = build_gap(unit_id="U1", gate="g", reason="r",
                             recommended_action="targeted_reextract",
                             extra={"block_ids": ["B2"]})
        expert = build_gap(unit_id="U2", gate="g", reason="r",
                           recommended_action="expert_review")
        self.assertEqual(actionable_gaps([targeted, expert]), [targeted])
        units = {"U2": {"unit_id": "U2", "source_block_ids": ["B9"]}}
        self.assertEqual(gap_block_ids(targeted, units), {"B2"})
        self.assertEqual(gap_block_ids(expert, units), {"B9"})
        self.assertEqual(gap_block_ids(expert, None), set())

    def test_escalation_executes_matching_proposal_once(self) -> None:
        calls: list[dict] = []

        def fake_executor(root, **kwargs):
            calls.append(kwargs)
            return {"lifecycle": "executed", "resolution": "covered",
                    "attempt_id": "ATT-1", "schema": "claim-queue-execution/v1"}

        gap_b2 = build_gap(unit_id="", gate="obligation_conservation", reason="dups",
                           recommended_action="targeted_reextract",
                           extra={"block_ids": ["B2"]})
        gap_b2_again = build_gap(unit_id="", gate="obligation_conservation", reason="dups2",
                                 recommended_action="targeted_secondary_route",
                                 extra={"block_ids": ["B2"]})
        gap_b1 = build_gap(unit_id="", gate="obligation_conservation", reason="x",
                           recommended_action="targeted_reextract",
                           extra={"block_ids": ["B1"]})
        expert = build_gap(unit_id="U", gate="routing_review_pending", reason="y",
                           recommended_action="expert_review")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_direct_mode(root)
            report = escalate_gaps(root, [gap_b2, gap_b2_again, gap_b1, expert],
                                   executor=fake_executor)
            self.assertEqual(len(calls), 1)  # 同 proposal 只执行一次；B1 无匹配
            self.assertEqual(calls[0]["request_idempotency_key"],
                             f"gap-{gap_b2['gap_id']}-1")
            self.assertEqual(report["counts_by_outcome"],
                             {OUTCOME_EXECUTED: 1, OUTCOME_NO_MATCH: 2})
            self.assertEqual(report["skipped_gap_ids"], [expert["gap_id"]])
            rows = load_routing_escalations(root)
            self.assertEqual(len(rows), 3)
            self.assertTrue((root / ROUTING_ESCALATIONS_FILENAME).is_file())

    def test_escalation_classifies_queue_errors(self) -> None:
        from claim_queue_execution import (
            ClaimQueueExecutionConflict,
            ClaimQueueExecutionUnavailable,
        )

        def boom(exc):
            def executor(root, **kwargs):
                raise exc
            return executor

        gap = build_gap(unit_id="", gate="g", reason="r",
                        recommended_action="targeted_reextract",
                        extra={"block_ids": ["B2"]})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_direct_mode(root)
            report = escalate_gaps(root, [gap], executor=boom(
                ClaimQueueExecutionConflict("stale")))
            self.assertEqual(report["counts_by_outcome"], {"cas_conflict": 1})
            self.assertFalse(report["outcomes"][0]["retryable"])
            report = escalate_gaps(root, [gap], executor=boom(
                ClaimQueueExecutionUnavailable("503")), idempotency_salt="2")
            self.assertEqual(report["counts_by_outcome"], {"retryable_error": 1})
            self.assertTrue(report["outcomes"][0]["retryable"])


class EscalationE2ETests(unittest.TestCase):
    """真实执行器全链：gap → execute_claim_queue_proposal → 条款族重抽/fold。"""

    def test_gap_driven_queue_reextract_closes_claim_and_keeps_b1_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            before = _read_product(root)
            self.assertEqual(len(before["items"]), 2)
            affected_before = next(item for item in before["items"]
                                   if "B2" in (item.get("source_block_ids") or []))
            self.assertNotEqual(affected_before.get("objective"), B2_TEXT)

            # 缺口形态来自守恒失败（此处按 gaps_from_functional_product 的块锚形态构造）
            gap = build_gap(unit_id="", gate="obligation_conservation",
                            reason="duplicate group @ 4.2",
                            recommended_action="targeted_reextract",
                            extra={"block_ids": ["B2"]})
            calls: list[str] = []
            config = _config()
            with mock.patch.object(ai_extract, "config_for_route", return_value=config), \
                    mock.patch.object(execution, "apply_min_tokens",
                                      side_effect=lambda value, _purpose: value):
                report = escalate_gaps(
                    root, [gap], chat_with_meta=_chat_v2_with_meta(calls),
                    route_config=config)

            outcome = report["outcomes"][0]
            self.assertEqual(outcome["outcome"], OUTCOME_EXECUTED)
            self.assertEqual(outcome["proposal_id"], proposal["proposal_id"])
            self.assertEqual(outcome["resolution"], "covered")
            # 只重抽受影响条款族（4.2），未把 4.1 拖进 prompt
            self.assertEqual(len(calls), 1, calls)
            self.assertNotIn(B1_TEXT, calls[0])
            # 幂等键稳定且绑定 gap
            self.assertEqual(outcome["attempt_key"], f"gap-{gap['gap_id']}-1")

            # 产品健康 + B2 换强叙述 + B1 指纹稳定
            after = _read_product(root)
            self.assertEqual(after["execution_status"], "ok")
            self.assertTrue(after["conservation"].get("ok"))
            affected_after = next(item for item in after["items"]
                                  if item.get("requirement_uid")
                                  == affected_before.get("requirement_uid"))
            self.assertEqual(affected_after.get("objective"), B2_TEXT)
            kept_before = next(item for item in before["items"]
                               if "B1" in (item.get("source_block_ids") or []))
            kept_after = next(item for item in after["items"]
                              if item.get("functional_requirement_id")
                              == kept_before.get("functional_requirement_id"))
            self.assertEqual(kept_after, kept_before)

            # 队列既有 WAL 机械被复用（事件序列在案）
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            kinds = [row["event_kind"] for row in rows]
            self.assertIn("reextract_succeeded", kinds)
            # 审计行落 governed 产物
            self.assertEqual(load_routing_escalations(root)[0]["gap_id"], gap["gap_id"])


if __name__ == "__main__":
    unittest.main()
