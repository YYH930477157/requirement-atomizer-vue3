"""V3 WS-A A3：整篇对账 reconcile（规则筛疑 + LLM 裁定两段）测试。

纪律：单测禁止真实 LLM 调用——LLM 路径经注入 chat 回调或走 rules_only。
验收面：规则筛疑命中夹具已知冲突；硬依据（编码零漂移回指）失败一票否决 LLM 通过票；
LLM 裁定 rationale 幻觉编码硬拦；LLM 不可用 → provenance 如实 rules_only；
reconcile_report.json 封闭 schema 校验；quality_report 摘要接线（原子写）。
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import merged_consistency
import reconcile


def _req(req_id: str, quote: str, section: str, block_ids: list[str], text: str = "") -> dict:
    return {
        "id": req_id,
        "title": text or quote[:40],
        "description": text,
        "source_quote": quote,
        "source_section": section,
        "source_block_ids": block_ids,
        "source_mapping": "exact",
    }


def _block(block_id: str, text: str, *, requirement_like: bool = False, order: int = 0) -> dict:
    return {
        "block_id": block_id,
        "text": text,
        "order": order,
        "type": "paragraph",
        "section_path": ["4", "4.1"],
        "requirement_like": requirement_like,
        "doc_region": "body",
    }


def _fixture():
    """已知冲突夹具：跨章重复 ×1、OBIS 数值分歧 ×1、覆盖缺口 ×1。"""
    blocks = [
        _block("B1", "The meter shall store the daily load profile.", order=1),
        _block("B2", "The meter shall store the daily load profile.", order=2),
        _block("B3", "Register 1-1:32.7.0 has 24 entries.", order=3),
        _block("B4", "Register 1-1:32.7.0 has 96 entries.", order=4),
        _block("B5", "The meter shall sign every response.", requirement_like=True, order=5),
    ]
    requirements = [
        _req("R1", "The meter shall store the daily load profile.", "4.1", ["B1"]),
        _req("R2", "The meter shall store the daily load profile.", "7.2", ["B2"]),
        _req("R3", "Register 1-1:32.7.0 has 24 entries.", "4.1", ["B3"]),
        _req("R4", "Register 1-1:32.7.0 has 96 entries.", "4.2", ["B4"]),
    ]
    return requirements, blocks


class SwitchTests(unittest.TestCase):
    def test_default_off(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_RECONCILE", None)
            self.assertFalse(reconcile.reconcile_enabled())
            self.assertFalse(reconcile.reconcile_enabled("0"))

    def test_on(self) -> None:
        self.assertTrue(reconcile.reconcile_enabled("1"))


class RuleScreenTests(unittest.TestCase):
    def test_screen_hits_known_fixture_conflicts(self) -> None:
        """规则筛疑必须命中夹具里的三类已知冲突（确定性，零 LLM）。"""
        requirements, blocks = _fixture()
        req_like = merged_consistency.coverage_denominator_blocks(blocks)
        suspects = merged_consistency.screen_reconcile_suspects(
            requirements, req_like, source_blocks=blocks,
        )
        kinds = {s["kind"] for s in suspects}
        self.assertIn("cross_section_duplicate", kinds)
        self.assertIn("obis_value_divergence", kinds)
        self.assertIn("coverage_gap", kinds)
        # 疑似集带确定性证据（编码/引句/块溯源），供 LLM 裁定层只读
        dup = next(s for s in suspects if s["kind"] == "cross_section_duplicate")
        self.assertEqual(sorted(dup["members"]), ["R1", "R2"])
        obis = next(s for s in suspects if s["kind"] == "obis_value_divergence")
        self.assertIn("1-1:32.7.0", obis["evidence"]["codes"])

    def test_screen_does_not_change_analyze_consistency_output(self) -> None:
        """既有 analyze_consistency 输出形状零变化（新旧消费方不受影响）。"""
        requirements, blocks = _fixture()
        req_like = merged_consistency.coverage_denominator_blocks(blocks)
        report = merged_consistency.analyze_consistency(
            requirements, req_like, source_blocks=blocks,
        )
        self.assertEqual(set(report), {
            "producer_version", "requirements", "duplicate_groups",
            "obis_coreference", "coverage", "summary",
        })


class ReconcileAdjudicationTests(unittest.TestCase):
    def _run(self, tmp: str, requirements, blocks, chat=None, route="stub"):
        return reconcile.run_reconcile(
            tmp, requirements=requirements, blocks=blocks, chat=chat, route=route,
        )

    def test_llm_only_votes_on_suspect_set(self) -> None:
        """LLM 只对规则筛出的疑似集裁定（不自由扫描）。"""
        requirements, blocks = _fixture()

        def chat(system: str, user: str) -> dict:
            payload = json.loads(user[user.index("{"):])
            suspect_ids = [s["suspect_id"] for s in payload["suspects"]]
            self.assertEqual(len(suspect_ids), 3, "疑似集恰好三条")
            return {"votes": [
                {"suspect_id": sid, "verdict": "confirmed_issue", "rationale": "语义冲突成立"}
                for sid in suspect_ids
            ]}

        with TemporaryDirectory() as tmp:
            result = self._run(tmp, requirements, blocks, chat=chat, route="openai_compatible")
            self.assertEqual(result["mode"], "rules_plus_llm")
            artifact = json.loads(
                (Path(tmp) / reconcile.RECONCILE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["summary"]["llm_confirmed"], 3)
            # 封闭 schema 校验
            import jsonschema
            schema = json.loads(
                (Path(reconcile.__file__).parent / "schemas" / "reconcile_report.schema.json")
                .read_text(encoding="utf-8")
            )
            jsonschema.validate(artifact, schema)

    def test_hard_evidence_vetoes_llm_pass(self) -> None:
        """硬依据失败一票否决：LLM 判 not_an_issue，但成员编码无法逐字回指来源 → hard_veto。"""
        # R5/R6 引句含 OBIS 9-9:99.9.9，但任何来源块都没有该编码 → 编码零漂移硬失败
        blocks = [_block("B1", "The meter shall store the profile.", order=1)]
        requirements = [
            _req("R5", "Profile OBIS 9-9:99.9.9 shall be stored.", "4.1", ["B1"]),
            _req("R6", "Profile OBIS 9-9:99.9.9 shall be stored.", "7.1", ["B1"]),
        ]

        def chat(system: str, user: str) -> dict:
            payload = json.loads(user[user.index("{"):])
            return {"votes": [
                {"suspect_id": s["suspect_id"], "verdict": "not_an_issue", "rationale": "语义等价"}
                for s in payload["suspects"]
            ]}

        with TemporaryDirectory() as tmp:
            result = self._run(tmp, requirements, blocks, chat=chat, route="openai_compatible")
            artifact = json.loads(
                (Path(tmp) / reconcile.RECONCILE_FILENAME).read_text(encoding="utf-8")
            )
            vetoed = [a for a in artifact["adjudications"] if a["final"] == "hard_veto"]
            self.assertTrue(vetoed, "硬依据失败必须否决 LLM 的 not_an_issue 票")
            for row in vetoed:
                self.assertEqual(row["llm_vote"], "not_an_issue")
                self.assertEqual(row["hard_evidence"], "fail")

    def test_hallucinated_code_in_llm_rationale_hard_blocked(self) -> None:
        """LLM 裁定 rationale 里臆造来源没有的编码 → 硬拦：票判 invalid，编码剔除留痕。"""
        requirements, blocks = _fixture()

        def chat(system: str, user: str) -> dict:
            payload = json.loads(user[user.index("{"):])
            votes = []
            for s in payload["suspects"]:
                votes.append({
                    "suspect_id": s["suspect_id"],
                    "verdict": "not_an_issue",
                    "rationale": "两者都引用 OBIS 0-0:10.0.0，语义一致",  # 来源无此编码
                })
            return {"votes": votes}

        with TemporaryDirectory() as tmp:
            result = self._run(tmp, requirements, blocks, chat=chat, route="openai_compatible")
            artifact = json.loads(
                (Path(tmp) / reconcile.RECONCILE_FILENAME).read_text(encoding="utf-8")
            )
            for row in artifact["adjudications"]:
                self.assertEqual(row["llm_vote"], "invalid_llm_code_drift")
                self.assertTrue(any("0-0:10.0.0" in c for c in row["rejected_codes"]))
                self.assertNotIn("0-0:10.0.0", row["llm_rationale"])
                self.assertNotEqual(row["final"], "llm_cleared",
                                    "幻觉票不得形成 cleared 结论")

    def test_llm_unavailable_rules_only(self) -> None:
        requirements, blocks = _fixture()
        with TemporaryDirectory() as tmp:
            result = self._run(tmp, requirements, blocks, route="stub")
            self.assertEqual(result["mode"], "rules_only")
            artifact = json.loads(
                (Path(tmp) / reconcile.RECONCILE_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["provenance_mode"], "rules_only")
            self.assertEqual(artifact["summary"]["suspects"], 3)
            for row in artifact["adjudications"]:
                self.assertIsNone(row["llm_vote"])
                self.assertEqual(row["final"], "rules_only_suspect")

    def test_budget_exhausted_falls_back_rules_only(self) -> None:
        import llm_client
        requirements, blocks = _fixture()

        def chat(system: str, user: str) -> dict:
            raise llm_client.LLMBudgetExceeded("exhausted")

        with TemporaryDirectory() as tmp:
            result = self._run(tmp, requirements, blocks, chat=chat, route="openai_compatible")
            self.assertEqual(result["mode"], "rules_only")
            self.assertEqual(result.get("llm_unavailable_reason"), "budget_exhausted")


class QualityReportAttachTests(unittest.TestCase):
    def test_summary_merges_into_quality_report_atomically(self) -> None:
        requirements, blocks = _fixture()
        with TemporaryDirectory() as tmp:
            quality = {"quality_report_version": "1.0", "counts": {"x": 1}}
            (Path(tmp) / "quality_report.json").write_text(
                json.dumps(quality, ensure_ascii=False), encoding="utf-8"
            )
            result = reconcile.run_reconcile(
                tmp, requirements=requirements, blocks=blocks, route="stub",
            )
            merged = json.loads(
                (Path(tmp) / "quality_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(merged["counts"], {"x": 1}, "既有字段零改动")
            self.assertIn("reconcile", merged)
            self.assertEqual(merged["reconcile"]["suspects"], 3)
            self.assertEqual(merged["reconcile"]["report_file"], reconcile.RECONCILE_FILENAME)
            self.assertEqual(result["quality_report_attached"], True)

    def test_missing_quality_report_no_crash(self) -> None:
        requirements, blocks = _fixture()
        with TemporaryDirectory() as tmp:
            result = reconcile.run_reconcile(
                tmp, requirements=requirements, blocks=blocks, route="stub",
            )
            self.assertEqual(result["quality_report_attached"], False)
            self.assertTrue((Path(tmp) / reconcile.RECONCILE_FILENAME).is_file())


if __name__ == "__main__":
    unittest.main()
