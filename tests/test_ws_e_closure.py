"""WS-E 首次全量闭合 + 增量变更集测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_tasks as dt


class EvaluateFullClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._mode_env = os.environ.pop("RATOMIZER_CLAIM_LEDGER_MODE", None)
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "blocks.jsonl").write_text("[]\n", encoding="utf-8")
        (self.tmp / "ai_requirements.jsonl").write_text("[]\n", encoding="utf-8")

    def tearDown(self) -> None:
        if self._mode_env is not None:
            os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = self._mode_env
        else:
            os.environ.pop("RATOMIZER_CLAIM_LEDGER_MODE", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_minimal_state(self, ready: bool = False) -> None:
        # ai_extract_quality.json 让 clarification_report.readiness_verdict 有输入
        (self.tmp / "ai_extract_quality.json").write_text(
            '{"coverage_pct": 80.0, "failed_sections": 0, "failed_section_ids": [], "failed_section_block_ids": []}',
            encoding="utf-8",
        )
        # 空 clarification 报告
        (self.tmp / "clarification_report.json").write_text(
            '{"entries": [], "readiness": {"verdict": "READY"}}',
            encoding="utf-8",
        )
        (self.tmp / "clarification_questions.xlsx").write_bytes(b"")

    def test_sampling_mode_blocks_ready(self) -> None:
        os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = "sampling"
        self._write_minimal_state()
        with patch("agent_state.load_analysis_state") as mock_state, \
                patch("claim_views.build_claim_view") as mock_view:
            from agent_state import AnalysisState
            mock_state.return_value = AnalysisState(
                out_dir=self.tmp,
                run_id="r1",
                manifest={},
                stage_statuses={},
                requirements=tuple(),
                quality={},
                coverage={},
                coverage_gaps=tuple(),
                open_questions=tuple(),
                readiness={"verdict": "READY", "reasons": []},
                failed_sections=0,
                failed_section_ids=tuple(),
                failed_section_block_ids=tuple(),
                pending_extraction_block_ids=tuple(),
            )
            mock_view.return_value = {
                "document_ready": True,
                "effective_fresh": True,
                "effective_metrics": {"uncertain_count": 0},
                "structural_review_pending_count": 0,
                "health": {},
            }
            result = dt.evaluate_full_closure(self.tmp)
        self.assertEqual(result["schema"], "full-closure/v1")
        self.assertFalse(result["ready"])
        self.assertEqual(result["claim_mode"], "sampling")
        kinds = {g["kind"] for g in result["gaps"]}
        self.assertIn("claim_mode_not_full", kinds)

    def test_unreviewed_requirements_block_ready(self) -> None:
        os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = "full"
        self._write_minimal_state()
        with patch("agent_state.load_analysis_state") as mock_state, \
                patch("claim_views.build_claim_view") as mock_view:
            from agent_state import AnalysisState
            mock_state.return_value = AnalysisState(
                out_dir=self.tmp,
                run_id="r1",
                manifest={},
                stage_statuses={},
                requirements=tuple([
                    {"ai_req_id": "R1", "status": "draft", "source_block_ids": ["B1"]},
                ]),
                quality={},
                coverage={},
                coverage_gaps=tuple(),
                open_questions=tuple(),
                readiness={"verdict": "NEEDS WORK", "reasons": ["unreviewed requirements"]},
                failed_sections=0,
                failed_section_ids=tuple(),
                failed_section_block_ids=tuple(),
                pending_extraction_block_ids=tuple(),
            )
            mock_view.return_value = {
                "document_ready": True,
                "effective_fresh": True,
                "effective_metrics": {"uncertain_count": 0},
                "structural_review_pending_count": 0,
                "health": {},
            }
            result = dt.evaluate_full_closure(self.tmp)
        self.assertFalse(result["ready"])
        self.assertEqual(result["claim_mode"], "full")
        kinds = {g["kind"] for g in result["gaps"]}
        self.assertIn("unreviewed_requirements", kinds)

    def test_all_confirmed_returns_ready_true(self) -> None:
        os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = "full"
        self._write_minimal_state()
        with patch("agent_state.load_analysis_state") as mock_state, \
                patch("claim_views.build_claim_view") as mock_view:
            from agent_state import AnalysisState
            mock_state.return_value = AnalysisState(
                out_dir=self.tmp,
                run_id="r1",
                manifest={},
                stage_statuses={},
                requirements=tuple([
                    {"ai_req_id": "R1", "status": "accepted", "source_block_ids": ["B1"]},
                ]),
                quality={},
                coverage={},
                coverage_gaps=tuple(),
                open_questions=tuple(),
                readiness={"verdict": "READY", "reasons": []},
                failed_sections=0,
                failed_section_ids=tuple(),
                failed_section_block_ids=tuple(),
                pending_extraction_block_ids=tuple(),
            )
            mock_view.return_value = {
                "document_ready": True,
                "effective_fresh": True,
                "effective_metrics": {"uncertain_count": 0},
                "structural_review_pending_count": 0,
                "health": {},
            }
            result = dt.evaluate_full_closure(self.tmp)
        self.assertTrue(result["ready"])
        self.assertEqual(result["gaps"], [])

    def test_conservation_open_blocks_ready(self) -> None:
        """A-5：守恒未闭合必须显式入 gaps 并阻断 READY（注释承诺落地）。

        E1 门注释承诺"守恒未闭合 → 不 READY"，但原实现只检查 claim 模式 / claim ready /
        分析 readiness / 全部已裁决，从未直接消费 functional_extract 守恒状态——守恒未闭合
        时仍可能判 ready=True（靠间接覆盖，缺口清单不含 conservation_open）。
        """
        os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = "full"
        self._write_minimal_state()
        # functional_requirements.json 守恒未闭合（missing 一块）
        (self.tmp / "functional_requirements.json").write_text(
            json.dumps({
                "items": [{"functional_requirement_id": "FRE-0001", "source_block_ids": ["B1"]}],
                "conservation": {"ok": False, "missing_block_ids": ["B9"]},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        with patch("agent_state.load_analysis_state") as mock_state, \
                patch("claim_views.build_claim_view") as mock_view:
            from agent_state import AnalysisState
            mock_state.return_value = AnalysisState(
                out_dir=self.tmp,
                run_id="r1",
                manifest={},
                stage_statuses={},
                requirements=tuple([
                    {"ai_req_id": "R1", "status": "accepted", "source_block_ids": ["B1"]},
                ]),
                quality={},
                coverage={},
                coverage_gaps=tuple(),
                open_questions=tuple(),
                readiness={"verdict": "READY", "reasons": []},
                failed_sections=0,
                failed_section_ids=tuple(),
                failed_section_block_ids=tuple(),
                pending_extraction_block_ids=tuple(),
            )
            mock_view.return_value = {
                "document_ready": True,
                "effective_fresh": True,
                "effective_metrics": {"uncertain_count": 0},
                "structural_review_pending_count": 0,
                "health": {},
            }
            result = dt.evaluate_full_closure(self.tmp)
        self.assertFalse(result["ready"], "守恒未闭合必须阻断 READY")
        kinds = {g["kind"] for g in result["gaps"]}
        self.assertIn("conservation_open", kinds, "缺口清单必须含 conservation_open")

    def test_conservation_ok_does_not_block_ready(self) -> None:
        """守恒闭合时不产生 conservation_open 缺口（回归守卫）。"""
        os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = "full"
        self._write_minimal_state()
        (self.tmp / "functional_requirements.json").write_text(
            json.dumps({"items": [], "conservation": {"ok": True}}, ensure_ascii=False),
            encoding="utf-8",
        )
        with patch("agent_state.load_analysis_state") as mock_state, \
                patch("claim_views.build_claim_view") as mock_view:
            from agent_state import AnalysisState
            mock_state.return_value = AnalysisState(
                out_dir=self.tmp,
                run_id="r1",
                manifest={},
                stage_statuses={},
                requirements=tuple(),
                quality={},
                coverage={},
                coverage_gaps=tuple(),
                open_questions=tuple(),
                readiness={"verdict": "READY", "reasons": []},
                failed_sections=0,
                failed_section_ids=tuple(),
                failed_section_block_ids=tuple(),
                pending_extraction_block_ids=tuple(),
            )
            mock_view.return_value = {
                "document_ready": True,
                "effective_fresh": True,
                "effective_metrics": {"uncertain_count": 0},
                "structural_review_pending_count": 0,
                "health": {},
            }
            result = dt.evaluate_full_closure(self.tmp)
        kinds = {g["kind"] for g in result["gaps"]}
        self.assertNotIn("conservation_open", kinds)


class BuildRequirementChangesetTests(unittest.TestCase):
    def _req(self, rid: str, block_ids: list[str]) -> dict:
        return {"ai_req_id": rid, "source_block_ids": block_ids}

    def _chunk(self, block_id: str, text: str) -> dict:
        return {
            "section_id": block_id,
            "section_path": ["1", block_id],
            "heading": block_id,
            "text": text,
            "block_ids": [block_id],
        }

    def test_single_chapter_change_flags_retained_source_changed(self) -> None:
        old = [
            self._chunk("B1", "alpha"),
            self._chunk("B2", "beta"),
            self._chunk("B3", "gamma"),
        ]
        new = [
            self._chunk("B1", "alpha"),
            self._chunk("B2", "BETA-CHANGED"),
            self._chunk("B3", "gamma"),
        ]
        old_reqs = [self._req("R1", ["B1"]), self._req("R2", ["B2"]), self._req("R3", ["B3"])]
        new_reqs = list(old_reqs)
        report = dt.build_requirement_changeset(old_reqs, new_reqs, old, new)
        self.assertEqual(report["schema"], "requirement-changeset/v1")
        self.assertEqual(report["counts"]["added"], 0)
        self.assertEqual(report["counts"]["obsolete"], 0)
        self.assertEqual(report["counts"]["retained"], 3)
        r2 = next(r for r in report["retained"] if r["id"] == "R2")
        self.assertEqual(r2["reason"], "source_changed")
        self.assertEqual(r2["changed_source_blocks"], ["B2"])

    def test_added_requirement_detected(self) -> None:
        old = [self._chunk("B1", "alpha")]
        new = [self._chunk("B1", "alpha"), self._chunk("B2", "new")]
        old_reqs = [self._req("R1", ["B1"])]
        new_reqs = [self._req("R1", ["B1"]), self._req("R2", ["B2"])]
        report = dt.build_requirement_changeset(old_reqs, new_reqs, old, new)
        self.assertEqual(report["counts"]["added"], 1)
        self.assertEqual(report["added"][0]["id"], "R2")
        self.assertEqual(report["counts"]["obsolete"], 0)

    def test_obsolete_requirement_detected(self) -> None:
        old = [self._chunk("B1", "alpha"), self._chunk("B2", "beta")]
        new = [self._chunk("B1", "alpha")]
        old_reqs = [self._req("R1", ["B1"]), self._req("R2", ["B2"])]
        new_reqs = [self._req("R1", ["B1"])]
        report = dt.build_requirement_changeset(old_reqs, new_reqs, old, new)
        self.assertEqual(report["counts"]["obsolete"], 1)
        self.assertEqual(report["obsolete"][0]["id"], "R2")
        self.assertEqual(report["counts"]["added"], 0)

    def test_no_change_empty_changeset(self) -> None:
        old = [self._chunk("B1", "alpha")]
        new = [self._chunk("B1", "alpha")]
        reqs = [self._req("R1", ["B1"])]
        report = dt.build_requirement_changeset(reqs, reqs, old, new)
        self.assertEqual(report["counts"], {"added": 0, "obsolete": 0, "retained": 1})
        self.assertEqual(report["retained"][0]["reason"], "unchanged")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
