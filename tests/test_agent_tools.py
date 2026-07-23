from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import omission_actions
from agent_state import load_analysis_state
from agent_tools import (
    ask_clarification,
    execute_action,
    queue_all_gaps,
    recheck,
    resample_section,
    stop,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _seed_gap(out: Path) -> None:
    _write_jsonl(out / "blocks.jsonl", [{
        "block_id": "B1",
        "order": 1,
        "text": "The meter shall log events.",
        "requirement_like": True,
        "noise": False,
    }])
    _write_jsonl(out / "ai_requirements.jsonl", [])
    (out / "ai_extract_quality.json").write_text(
        json.dumps({"failed_sections": 0}), encoding="utf-8"
    )


def _seed_failed_section_covered(out: Path) -> None:
    """B1 已被需求引句覆盖（不再 uncovered），但被质量报告记为失败章节块。

    审计 P1-a 的现场形态：残存需求/跨章引句/denominator 规则使失败块不再出现在
    重算的 uncovered 集合里——候选口径并入失败章节块（H6）后，重算与快照两条
    路径都能登记它，登记后可经 targeted_reextract 真正补抽。
    """
    _write_jsonl(out / "blocks.jsonl", [{
        "block_id": "B1",
        "order": 1,
        "text": "The meter shall log events.",
        "requirement_like": True,
        "noise": False,
    }])
    _write_jsonl(out / "ai_requirements.jsonl", [{
        "ai_req_id": "AIR-1",
        "source_quote": "The meter shall log events.",
    }])
    (out / "ai_extract_quality.json").write_text(
        json.dumps({
            "failed_sections": 1,
            "failed_section_ids": ["S1"],
            "failed_section_block_ids": ["B1"],
        }),
        encoding="utf-8",
    )


class AgentToolTests(unittest.TestCase):
    def test_zero_llm_resample_queues_without_calling_targeted_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            with mock.patch.object(omission_actions, "targeted_reextract") as targeted:
                result = resample_section(out, "B1")
            current = omission_actions.read_current_omission_states(out)

        self.assertEqual(result["status"], "skipped")
        self.assertIn("zero-LLM", result["summary"])
        targeted.assert_not_called()
        self.assertEqual(next(iter(current.values()))["status"], "needs_extraction")

    def test_explicit_llm_resample_delegates_to_existing_targeted_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            payload = {"schema": "omission-reextract/v1", "requirements": 2}
            with mock.patch.object(
                omission_actions, "targeted_reextract", return_value=payload
            ) as targeted:
                result = resample_section(out, "B1", allow_llm=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"], payload)
        self.assertEqual(targeted.call_args.kwargs["block_id"], "B1")
        self.assertTrue(targeted.call_args.kwargs["expected_source_fingerprint"])

    def test_resample_rejects_non_current_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            _write_jsonl(out / "ai_requirements.jsonl", [{
                "source_quote": "The meter shall log events."
            }])

            with self.assertRaises(ValueError):
                resample_section(out, "B1")

    def test_resample_already_queued_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            first = resample_section(out, "B1")
            second = resample_section(out, "B1")
            rows = list(omission_actions.read_omission_states(out).values())

        self.assertEqual(first["status"], "skipped")
        self.assertEqual(second["status"], "skipped")
        self.assertIn("already queued", second["summary"])
        self.assertEqual(len(rows), 1)

    def test_queue_all_gaps_batches_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "order": 1, "text": "The meter shall log events.",
                 "requirement_like": True, "noise": False},
                {"block_id": "B2", "order": 2, "text": "The meter shall store profiles.",
                 "requirement_like": True, "noise": False},
                {"block_id": "B3", "order": 3, "text": "The meter shall report alarms.",
                 "requirement_like": True, "noise": False},
            ])

            first = queue_all_gaps(out)
            second = queue_all_gaps(out)
            rows = list(omission_actions.read_omission_states(out).values())

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["details"]["queued_block_ids"], ["B1", "B2", "B3"])
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["details"]["queued_block_ids"], [])
        self.assertEqual(len(rows), 3)

    def test_dispatch_routes_queue_all_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            state = load_analysis_state(out)
            result = execute_action(out, "queue_all_gaps", state)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["queued_block_ids"], ["B1"])

    def test_queue_all_gaps_recompute_queues_failed_section_block(self) -> None:
        """审计 H6 修复后：重算候选 = 未覆盖块 ∪ 失败章节块——不再 uncovered 的
        失败块经重算路径同样登记（修复前只有快照路径能登记，且登记后无法补抽）。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_failed_section_covered(out)

            recompute = queue_all_gaps(out)   # 新口径：失败块经重算也排得上队
            result = queue_all_gaps(out, block_ids=["B1"])
            rows = list(omission_actions.read_omission_states(out).values())

        self.assertEqual(recompute["status"], "ok")
        self.assertEqual(recompute["details"]["queued_block_ids"], ["B1"])
        # 已登记后快照路径幂等：不重复追加，如实记 skipped
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["details"]["queued_block_ids"], [])
        skipped = result["details"]["skipped_block_ids"]
        self.assertEqual([entry["block_id"] for entry in skipped], ["B1"])
        self.assertTrue(skipped[0]["reason"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["block_id"], "B1")
        self.assertEqual(rows[0]["status"], "needs_extraction")

    def test_queue_all_gaps_snapshot_revalidation_skips_with_reasons(self) -> None:
        """锁内重验证：不存在的块/已 pending 的块不登记，如实进 skipped_block_ids（带原因）。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "order": 1, "text": "The meter shall log events.",
                 "requirement_like": True, "noise": False},
                {"block_id": "B2", "order": 2, "text": "The meter shall store profiles.",
                 "requirement_like": True, "noise": False},
            ])
            _write_jsonl(out / "ai_requirements.jsonl", [])
            (out / "ai_extract_quality.json").write_text(
                json.dumps({"failed_sections": 0}), encoding="utf-8")
            omission_actions.apply_omission_action(
                out, block_id="B2", status="needs_extraction", reason="pre-queued")

            result = queue_all_gaps(out, block_ids=["B1", "B2", "GHOST", "B1"])
            rows = list(omission_actions.read_omission_states(out).values())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["queued_block_ids"], ["B1"])
        skipped = result["details"]["skipped_block_ids"]
        self.assertEqual([entry["block_id"] for entry in skipped], ["B2", "GHOST"])
        self.assertTrue(all(entry["reason"] for entry in skipped))
        self.assertIn("Queued 1", result["summary"])
        self.assertIn("Skipped 2", result["summary"])
        # B2 不重复追行（仍只有预先登记的一行）+ B1 一行
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(1 for row in rows if row["block_id"] == "B2"), 1)

    def test_queue_all_gaps_all_candidates_invalid_reports_skipped(self) -> None:
        """全部快照候选未过验证：不报错中断，status=skipped 且如实说明。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            result = queue_all_gaps(out, block_ids=["GHOST"])

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["details"]["queued_block_ids"], [])
        self.assertEqual(
            result["details"]["skipped_block_ids"],
            [{"block_id": "GHOST", "reason": "block 不存在于 blocks.jsonl"}],
        )
        self.assertIn("failed revalidation", result["summary"])

    def test_execute_action_feeds_state_snapshot_to_queue_all_gaps(self) -> None:
        """决策循环路径：execute_action 把 state.unqueued_gap_block_ids（缺口 ∪ 失败块）
        传给 queue_all_gaps——不再 uncovered 的失败块经调度照样登记。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_failed_section_covered(out)
            state = load_analysis_state(out)
            result = execute_action(out, "queue_all_gaps", state)

        self.assertEqual(state.unqueued_gap_block_ids, ("B1",))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["queued_block_ids"], ["B1"])

    def test_recheck_is_truthfully_skipped_in_phase1(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [])
            _write_jsonl(out / "ai_requirements.jsonl", [{
                "ai_req_id": "AIR-1",
                "source_quote": "The meter shall log events.",
                "suspicion_reasons": ["引用非逐字"],
            }])

            result = recheck(out, "AIR-1")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("standalone", result["summary"])

    def test_ask_clarification_reuses_report_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            report = {"questions": 3, "written": ["clarification_report.json"]}
            with mock.patch(
                "clarification_report.run_report", return_value=report
            ) as run_report:
                result = ask_clarification(out)

        self.assertEqual(result["status"], "ok")
        self.assertIn("3", result["summary"])
        run_report.assert_called_once_with(out.resolve())

    def test_dispatch_and_stop_return_trace_compatible_results(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            state = load_analysis_state(out)
            result = execute_action(out, "stop", state)
            direct = stop(state)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result, direct)
        self.assertEqual(set(result), {"status", "summary"})


if __name__ == "__main__":
    unittest.main()
