"""§3.3 统一功能级评审权威的机制测试（2026-08-15）。

- ai_review_states.jsonl 仍是唯一专家裁决存储（level=functional），不新增状态文件；
- POST /functional-review-actions：CAS 三元组（source/subject 指纹 + 产物指纹 +
  authority write revision）失配 → 409 needs_reconfirmation，不静默沿用旧裁决；
- GET /functional-requirements 投影 status/module/ownership 覆盖与 CAS 材料；
- requirements_analysis 对直抽条目的 rejected/override 投影生效（FRE 主键域打通）；
- clarification 投影 rejected_codes/numeric_drift；
- agent_state 直抽回退（无原子产物时"全部已裁决"检查有对象）；
- 批注视图直抽投影（FRE 卡片 + quote→block 锚点）。

纪律：单测禁止真实 LLM 调用。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import api_server
from ai_review_actions import read_ai_review_states, source_ai_requirement_id
from tests.test_api_server import _claim_api, _http_json, _http_post_json


def _write_direct_product(out: Path, *, items: list[dict] | None = None) -> dict:
    item = {
        "functional_requirement_id": "FRE-TEST1",
        "requirement_uid": "FR-0001",
        "objective": "记录事件",
        "behaviors": ["The meter shall log events."],
        "title": "事件记录",
        "module": "计量",
        "source_quote": "The meter shall log events.",
        "source_section": "4.1",
        "source_block_ids": ["B1"],
        "merge_method": "functional_extract",
    }
    payload = {
        "schema_version": 1,
        "producer": "functional-extract-v1",
        "route_requested": "stub",
        "route": "stub",
        "fingerprint": "fp-direct-v1",
        "items": items if items is not None else [item],
        "conservation": {"ok": True, "missing_block_ids": []},
    }
    (out / "functional_requirements.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _write_blocks(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        '{"block_id":"B1","section_path":["4.1"],"text":"The meter shall log events."}\n',
        encoding="utf-8",
    )


class FunctionalReviewEndpointTests(unittest.TestCase):
    def test_get_projects_review_state_and_cas_material(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            _write_direct_product(out)
            with _claim_api(out) as base:
                status, payload = _http_json(base, "/functional-requirements")
            self.assertEqual(status, 200)
            self.assertEqual(payload["total"], 1)
            row = payload["items"][0]
            self.assertEqual(row["level"], "functional")
            self.assertEqual(row["status"], "draft")
            self.assertTrue(row["source_fingerprint"])
            self.assertTrue(row["review_subject_fingerprint"])
            self.assertEqual(row["target_fingerprint"], "fp-direct-v1")
            self.assertTrue(row["target_authority_write_revision"])

    def test_post_accept_writes_level_functional_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            _write_direct_product(out)
            with _claim_api(out) as base:
                _, view = _http_json(base, "/functional-requirements")
            row = view["items"][0]
            rid = source_ai_requirement_id(row)
            with _claim_api(out, local_token="test-token") as base:
                status, resp = _http_post_json(base, "/functional-review-actions", token="test-token", payload={
                    "ai_req_id": rid,
                    "status": "accepted",
                    "module_override": "费控",
                    "ownership_override": "software",
                    "reason": "ok",
                    "source_fingerprint": row["source_fingerprint"],
                    "review_subject_fingerprint": row["review_subject_fingerprint"],
                    "expected_target_fingerprint": row["target_fingerprint"],
                    "expected_target_authority_write_revision":
                        row["target_authority_write_revision"],
                })
            self.assertEqual(status, 200)
            states = read_ai_review_states(out)
            self.assertIn(rid, states)
            self.assertEqual(states[rid]["status"], "accepted")
            self.assertEqual(states[rid]["level"], "functional")
            self.assertEqual(states[rid]["module_override"], "费控")
            self.assertEqual(states[rid]["ownership_override"], "software")
            # GET 投影随之更新
            with _claim_api(out) as base:
                _, view2 = _http_json(base, "/functional-requirements")
            row2 = view2["items"][0]
            self.assertEqual(row2["status"], "accepted")
            self.assertEqual(row2["module_effective"], "费控")
            self.assertEqual(row2["ownership_effective"], "software")

    def test_post_with_stale_fingerprints_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            _write_direct_product(out)
            with _claim_api(out) as base:
                _, view = _http_json(base, "/functional-requirements")
            row = view["items"][0]
            rid = source_ai_requirement_id(row)
            with _claim_api(out, local_token="test-token") as base:
                status, resp = _http_post_json(base, "/functional-review-actions", token="test-token", payload={
                    "ai_req_id": rid,
                    "status": "accepted",
                    "source_fingerprint": "stale-source",
                    "review_subject_fingerprint": row["review_subject_fingerprint"],
                    "expected_target_fingerprint": row["target_fingerprint"],
                    "expected_target_authority_write_revision":
                        row["target_authority_write_revision"],
                })
            self.assertEqual(status, 409)
            self.assertTrue(resp.get("needs_reconfirmation"))
            self.assertEqual(read_ai_review_states(out), {})

    def test_post_rejects_when_product_regenerated(self) -> None:
        """产物重生成（指纹变化）→ 旧 CAS 失配，状态不得静默沿用。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            payload = _write_direct_product(out)
            with _claim_api(out) as base:
                _, view = _http_json(base, "/functional-requirements")
            row = view["items"][0]
            rid = source_ai_requirement_id(row)
            # 产物重生成：指纹换新
            payload["fingerprint"] = "fp-direct-v2"
            (out / "functional_requirements.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with _claim_api(out, local_token="test-token") as base:
                status, resp = _http_post_json(base, "/functional-review-actions", token="test-token", payload={
                    "ai_req_id": rid,
                    "status": "accepted",
                    "source_fingerprint": row["source_fingerprint"],
                    "review_subject_fingerprint": row["review_subject_fingerprint"],
                    "expected_target_fingerprint": row["target_fingerprint"],
                    "expected_target_authority_write_revision":
                        row["target_authority_write_revision"],
                })
            self.assertEqual(status, 409)
            self.assertTrue(resp.get("needs_reconfirmation"))

    def test_post_unknown_requirement_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            _write_direct_product(out)
            with _claim_api(out, local_token="test-token") as base:
                status, resp = _http_post_json(base, "/functional-review-actions", token="test-token", payload={
                    "ai_req_id": "FRE-NOTEXIST",
                    "status": "accepted",
                    "source_fingerprint": "x",
                    "review_subject_fingerprint": "y",
                    "expected_target_fingerprint": "fp-direct-v1",
                    "expected_target_authority_write_revision": "z",
                })
            self.assertEqual(status, 409)


class AnalysisProjectionTests(unittest.TestCase):
    def test_rejected_functional_item_filtered_and_override_applied(self) -> None:
        import requirements_analysis
        from ai_review_actions import apply_ai_review_action

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            item2 = {
                "functional_requirement_id": "FRE-TEST2",
                "objective": "归档事件",
                "behaviors": ["The meter shall archive events."],
                "title": "事件归档",
                "module": "原始模块",
                "source_quote": "The meter shall archive events.",
                "source_section": "4.2",
                "source_block_ids": ["B2"],
                "merge_method": "functional_extract",
            }
            (out / "blocks.jsonl").write_text(
                '{"block_id":"B1","section_path":["4.1"],"text":"The meter shall log events."}\n'
                '{"block_id":"B2","section_path":["4.2"],"text":"The meter shall archive events."}\n',
                encoding="utf-8")
            _write_direct_product(out, items=[
                {
                    "functional_requirement_id": "FRE-TEST1",
                    "objective": "记录事件",
                    "behaviors": ["The meter shall log events."],
                    "title": "事件记录",
                    "module": "计量",
                    "source_quote": "The meter shall log events.",
                    "source_section": "4.1",
                    "source_block_ids": ["B1"],
                    "merge_method": "functional_extract",
                },
                item2,
            ])
            rid1 = source_ai_requirement_id({"functional_requirement_id": "FRE-TEST1"})
            rid2 = source_ai_requirement_id(item2)
            apply_ai_review_action(out, rid1, "rejected", reason="重复", level="functional")
            apply_ai_review_action(
                out, rid2, "accepted", module_override="费控", level="functional")
            result = requirements_analysis.run_requirements_analysis(out, route="stub")
            analysis = json.loads(
                (out / "engineering_analysis.json").read_text(encoding="utf-8"))
            modules = {it["module"] for it in analysis["items"]}
            # FRE-TEST1 被拒 → 不进分析；FRE-TEST2 模块覆盖生效
            self.assertEqual(result["analysis_count"], 1)
            self.assertEqual(modules, {"费控"})


class ClarificationGuardrailTests(unittest.TestCase):
    def test_rejected_codes_and_numeric_drift_projected(self) -> None:
        from clarification_report import BLOCKER_BLOCKING, collect_questions

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            item = {
                "functional_requirement_id": "FRE-DRIFT1",
                "objective": "记录事件",
                "behaviors": ["The meter shall log events."],
                "title": "事件记录",
                "module": "计量",
                "source_quote": "The meter shall log events.",
                "source_section": "4.1",
                "source_block_ids": ["B1"],
                "merge_method": "functional_extract",
                "rejected_codes": ["1.1.1"],
                "numeric_drift_flag": True,
                "numeric_drift_values": [999],
            }
            _write_direct_product(out, items=[item])
            entries = collect_questions(out)
            signals = {e["signal"] for e in entries}
            self.assertIn("functional:code_drift", signals)
            self.assertIn("functional:number_drift", signals)
            for entry in entries:
                if entry["signal"] in ("functional:code_drift", "functional:number_drift"):
                    self.assertEqual(entry["blocker_level"], BLOCKER_BLOCKING)


class CrossScriptReviewStateMachineTests(unittest.TestCase):
    """复审 P1-2（2026-08-16）：跨语种义务覆盖必须进入人工评审状态机。

    未确认 → BLOCKING 内部核对问题 → readiness NEEDS WORK → full closure 阻塞；
    专家 verified_ok 确认后自动解除（readiness 恢复 READY）。
    """

    def _seed(self, out: Path) -> None:
        _write_blocks(out)
        _write_direct_product(out, items=[{
            "functional_requirement_id": "FRE-CS1",
            "requirement_uid": "FR-0001",
            "objective": "记录事件",
            "behaviors": ["The meter shall log events."],
            "title": "事件记录",
            "module": "计量",
            "source_quote": "The meter shall log events.",
            "source_section": "4.1",
            "source_block_ids": ["B1"],
            "merge_method": "functional_extract",
        }])
        payload = json.loads(
            (out / "functional_requirements.json").read_text(encoding="utf-8"))
        payload["conservation"] = {
            "ok": True, "missing_block_ids": [],
            "checks": {"obligation_coverage": {
                "ok": True, "uncovered_obligations": [],
                "cross_script_review": [{
                    "section_id": "4.1", "unit_index": 0,
                    "functional_requirement_id": "FRE-CS1",
                }],
            }},
        }
        (out / "functional_requirements.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_blocks_readiness_until_expert_confirms(self) -> None:
        from clarification_check_states import apply_clarification_check_action
        from clarification_report import (
            collect_questions,
            readiness_verdict,
            unresolved_hard_questions,
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            entries = [
                e for e in collect_questions(out)
                if e["signal"] == "functional:cross_script_review"
            ]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["blocker_level"], "blocking")
            self.assertEqual(entries[0]["audience"], "内部核对")
            _unresolved, counts = unresolved_hard_questions(out)
            self.assertEqual(counts["blocking"], 1)
            pending = readiness_verdict(out, unresolved_blocking=counts["blocking"])
            self.assertEqual(pending["verdict"], "NEEDS WORK")

            apply_clarification_check_action(
                out, entries[0]["clarification_id"], "verified_ok",
                evidence_fingerprint=entries[0]["evidence_fingerprint"],
                blocker_level=entries[0]["blocker_level"],
                module=entries[0]["module"], signal=entries[0]["signal"],
                source_id=entries[0]["source_id"], actor="expert",
                note="跨语种覆盖已人工确认")
            # 复审 P1-2 二轮：确认绑定源义务文本哈希——义务文本变化后
            # clarification_id/evidence_fingerprint 换新，旧确认不得沿用。
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            changed = {
                "ok": True, "missing_block_ids": [],
                "checks": {"obligation_coverage": {
                    "ok": True, "uncovered_obligations": [],
                    "cross_script_review": [{
                        "section_id": "4.1", "unit_index": 0,
                        "functional_requirement_id": "FRE-CS1",
                        "source_text_hash": "sha256:changed-obligation",
                        "sentence": "The meter shall record events.",
                    }],
                }},
            }
            payload["conservation"] = changed
            (out / "functional_requirements.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            entries2 = [
                e for e in collect_questions(out)
                if e["signal"] == "functional:cross_script_review"
            ]
            self.assertEqual(len(entries2), 1)
            self.assertNotEqual(
                entries2[0]["clarification_id"], entries[0]["clarification_id"])
            self.assertNotEqual(
                entries2[0]["evidence_fingerprint"],
                entries[0]["evidence_fingerprint"])
            _unresolved3, counts3 = unresolved_hard_questions(out)
            self.assertEqual(counts3["blocking"], 1)  # 旧确认不再适用
            pending2 = readiness_verdict(
                out, unresolved_blocking=counts3["blocking"])
            self.assertEqual(pending2["verdict"], "NEEDS WORK")
            # 新 ID 重新确认 → 再次恢复 READY（换新身份后状态机照常工作）
            apply_clarification_check_action(
                out, entries2[0]["clarification_id"], "verified_ok",
                evidence_fingerprint=entries2[0]["evidence_fingerprint"],
                blocker_level=entries2[0]["blocker_level"],
                module=entries2[0]["module"], signal=entries2[0]["signal"],
                source_id=entries2[0]["source_id"], actor="expert",
                note="换新义务文本后重新确认")
            _unresolved4, counts4 = unresolved_hard_questions(out)
            self.assertEqual(counts4["blocking"], 0)
            confirmed = readiness_verdict(
                out, unresolved_blocking=counts4["blocking"])
            self.assertEqual(confirmed["verdict"], "READY")


class AgentStateDirectFallbackTests(unittest.TestCase):
    def test_load_analysis_state_with_direct_basis(self) -> None:
        from agent_state import load_analysis_state
        from ai_review_actions import apply_ai_review_action

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            _write_direct_product(out)
            state = load_analysis_state(out)
            self.assertEqual(len(state.requirements), 1)
            self.assertEqual(state.requirements[0]["status"], "draft")  # 空账本 ≠ 已完成
            self.assertEqual(state.requirements[0]["level"], "functional")
            rid = source_ai_requirement_id({"functional_requirement_id": "FRE-TEST1"})
            apply_ai_review_action(out, rid, "accepted", level="functional")
            state2 = load_analysis_state(out)
            self.assertEqual(state2.requirements[0]["status"], "accepted")

    def test_stale_fingerprinted_state_not_projected_as_accepted(self) -> None:
        """复审 P1：subject 指纹失配的陈旧裁决 → 投影回落 draft，不静默通过闭合门。"""
        from agent_state import load_analysis_state
        from ai_review_actions import apply_ai_review_action

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            item = {
                "functional_requirement_id": "FRE-STALE1",
                "objective": "记录事件 v2（内容已变）",
                "behaviors": ["The meter shall log events."],
                "title": "事件记录",
                "module": "计量",
                "source_quote": "The meter shall log events.",
                "source_section": "4.1",
                "source_block_ids": ["B1"],
                "merge_method": "functional_extract",
            }
            _write_direct_product(out, items=[item])
            rid = source_ai_requirement_id(item)
            # 裁决绑定在旧叙述指纹上（模拟产物重生成前的旧裁决）
            apply_ai_review_action(
                out, rid, "accepted", level="functional",
                source_fingerprint_value="sha256:old-source",
                review_subject_fingerprint_value="sha256:old-subject",
            )
            state = load_analysis_state(out)
            self.assertTrue(state.requirements[0]["needs_reconfirmation"])
            self.assertEqual(state.requirements[0]["status"], "draft")

    def test_load_analysis_state_still_fails_without_any_basis(self) -> None:
        from agent_state import AgentStateInputError, load_analysis_state

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "blocks.jsonl").write_text("[]\n", encoding="utf-8")
            with self.assertRaises(AgentStateInputError):
                load_analysis_state(out)


class AnnotationDirectProjectionTests(unittest.TestCase):
    def test_build_ai_requirements_from_direct_product(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out)
            _write_direct_product(out)
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["level"], "functional")
            self.assertEqual(row["anchor_block_id"], "B1")
            self.assertEqual(row["quote_block_ids"], ["B1"])
            self.assertEqual(row["status"], "draft")
            self.assertEqual(row.get("functional_requirement_id"), "FRE-TEST1")


if __name__ == "__main__":
    unittest.main()
