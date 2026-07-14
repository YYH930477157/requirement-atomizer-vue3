"""批次一（0714 整体 review 落地）回归：

- E2 冻结归属注入：富化 prompt 携带上游冻结 ownership,模型只写不判;归属变化令缓存 key 变化。
- E1a 部分降级上屏：enrich_degraded>0 时 note 必须出现（此前只有全灭才提示）。
（S1 合批 / S2 自适应限流 / E1b 遗漏候选 的回归在各自实现后追加于此文件。）
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from requirements_analysis_agent import build_analysis_prompt, slim_vocabulary


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


class OwnershipInjectionPromptTests(unittest.TestCase):
    def test_prompt_instructs_frozen_ownership(self) -> None:
        prompt = build_analysis_prompt(
            [{"ai_req_id": "AI-1", "module": "时钟", "ownership": "software"}],
            slim_vocabulary({"modules": ["时钟"]}, "时钟"))
        user = prompt["user"]
        self.assertIn("冻结", user)
        self.assertIn("绝不改判", user)
        self.assertIn("给定归属", user)          # ownership_reason 字段说明改为解释给定归属
        self.assertIn('"ownership": "software"', user)   # 冻结值随需求 JSON 注入


class OwnershipInjectionEnrichTests(unittest.TestCase):
    SOURCE = {"ai_req_id": "AI-1", "module": "计量",
              "title": "数据存储",
              "description": "The meter shall store data.",
              "source_quote": "The meter shall store data."}
    VOCAB = {"modules": ["计量"], "submodules_by_module": {"计量": []}}

    def _item(self, ownership: str) -> dict:
        return {"analysis_id": "SRA-001", "ownership": ownership,
                "ownership_reason": "Matched software rule term: store",
                "ownership_source": "rule"}

    def test_prompt_req_carries_frozen_ownership(self) -> None:
        from requirements_analysis import _llm_enrich_item
        captured: list[str] = []

        def chat(system: str, user: str) -> dict:
            captured.append(user)
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。",
                               "ownership": "software"}]}

        ok, _ = _llm_enrich_item(self._item("software"), self.SOURCE, self.VOCAB,
                                 chat, {}, "m")
        self.assertTrue(ok)
        self.assertIn('"ownership": "software"', captured[0])

    def test_ownership_change_invalidates_cache_key(self) -> None:
        from requirements_analysis import _llm_enrich_item
        calls: list[str] = []
        cache: dict = {}

        def chat(system: str, user: str) -> dict:
            calls.append(user)
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。"}]}

        _llm_enrich_item(self._item("software"), self.SOURCE, self.VOCAB, chat, cache, "m")
        _llm_enrich_item(self._item("co_design"), self.SOURCE, self.VOCAB, chat, cache, "m")
        self.assertEqual(len(calls), 2)          # 归属不同 → key 不同 → 各自真调
        _llm_enrich_item(self._item("software"), self.SOURCE, self.VOCAB, chat, cache, "m")
        self.assertEqual(len(calls), 2)          # 归属相同 → 命中缓存零调用

    def test_echoed_frozen_ownership_reason_adopted(self) -> None:
        from requirements_analysis import _llm_enrich_item

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。",
                               "ownership": "software",
                               "ownership_reason": "存储与协议逻辑属软件职责"}]}

        item = self._item("software")
        ok, _ = _llm_enrich_item(item, self.SOURCE, self.VOCAB, chat, {}, "m")
        self.assertTrue(ok)
        self.assertEqual(item["ownership_reason"], "存储与协议逻辑属软件职责")
        self.assertEqual(item["ownership_reason_source"], "llm")


class PartialDegradeNoteTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            {"ai_req_id": "AI-1", "title": "数据存储", "module": "数据存储",
             "description": "The meter shall store data.",
             "source_quote": "The meter shall store data."},
            {"ai_req_id": "AI-2", "title": "时钟同步", "module": "时钟",
             "description": "The meter shall sync clock.",
             "source_quote": "The meter shall sync clock."},
        ])

    def test_partial_degrade_sets_note(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            if "store data" in user:
                return {"items": [{"software_requirement_text": "存储数据的软件逻辑。"}]}
            raise RuntimeError("boom")   # 第二条调用失败 → 单条降级

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enriched"], 1)
            self.assertEqual(result["enrich_degraded"], 1)
            self.assertIn("部分降级", result.get("note", ""))
            self.assertIn("1/2", result["note"])

    def test_full_success_has_no_note(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "对应软件逻辑成文。"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enrich_degraded"], 0)
            self.assertNotIn("note", result)


class CoverageGapClarificationTests(unittest.TestCase):
    """E1b：覆盖缺口的遗漏候选进澄清清单（独立档,不进就绪门,不混入模型自报）。"""

    def _seed(self, out: Path, consistency: dict) -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            {"ai_req_id": "AI-1", "title": "需求", "source_quote": "q"}])
        (out / "consistency_report.json").write_text(
            json.dumps(consistency, ensure_ascii=False), encoding="utf-8")

    def test_uncovered_samples_become_gap_entries(self) -> None:
        import clarification_report as cr
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out, {"coverage": {
                "measured": True, "uncovered_count": 2,
                "uncovered_samples": [
                    {"block_id": "BLK-1", "section": "4.5", "text": "The AFD shall close the valve."},
                    {"block_id": "BLK-2", "section": "", "text": "All meters shall meet this."},
                ]}})
            entries = cr.collect_questions(out)
        gap = [e for e in entries if e.get("tier") == cr.TIER_GAP]
        self.assertEqual(len(gap), 2)
        self.assertEqual(gap[0]["source_id"], "BLK-1")     # 溯源可回链批注视图
        self.assertEqual(gap[0]["section"], "4.5")
        self.assertIn("AFD shall close", gap[0]["quote"])
        self.assertTrue(all(e["audience"] == cr.AUDIENCE_INTERNAL for e in gap))

    def test_legacy_plain_string_samples_tolerated(self) -> None:
        import clarification_report as cr
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out, {"coverage": {"measured": True, "uncovered_count": 1,
                                          "uncovered_samples": ["Legacy uncovered text."]}})
            entries = cr.collect_questions(out)
        gap = [e for e in entries if e.get("tier") == cr.TIER_GAP]
        self.assertEqual(len(gap), 1)
        self.assertEqual(gap[0]["quote"], "Legacy uncovered text.")

    def test_gap_entries_do_not_trip_readiness_gate(self) -> None:
        import clarification_report as cr
        samples = [{"block_id": f"B{i}", "section": "", "text": f"Uncovered requirement {i}."}
                   for i in range(40)]   # 超过 READY_MAX_QUESTIONS=30
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out, {"coverage": {"measured": True, "uncovered_count": 40,
                                          "uncovered_samples": samples}})
            report = cr.run_report(out)
        self.assertEqual(report["questions"], 0)                 # 必答口径不含遗漏候选
        self.assertEqual(report["coverage_candidates"], 40)
        self.assertEqual(report["readiness"]["verdict"], "READY")

    def test_sample_cap_overflow_leaves_trace(self) -> None:
        import clarification_report as cr
        samples = [{"block_id": "B1", "section": "", "text": "Uncovered one."}]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out, {"coverage": {"measured": True, "uncovered_count": 113,
                                          "uncovered_samples": samples}})
            entries = cr.collect_questions(out)
        overflow = [e for e in entries if e["signal"] == "consistency:uncovered_overflow"]
        self.assertEqual(len(overflow), 1)
        self.assertIn("112", overflow[0]["question"])            # 无声截断禁令：超上限必留痕

    def test_gap_sheet_written_and_hard_sheets_unpolluted(self) -> None:
        import clarification_report as cr
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out, {"coverage": {"measured": True, "uncovered_count": 1,
                                          "uncovered_samples": [
                                              {"block_id": "B1", "section": "4.5",
                                               "text": "The AFD shall close the valve."}]}})
            cr.run_report(out)
            wb = load_workbook(out / cr.REPORT_XLSX, read_only=True)
            try:
                self.assertIn("遗漏候选(内部核对)", wb.sheetnames)
                gap_rows = list(wb["遗漏候选(内部核对)"].iter_rows(min_row=2, values_only=True))
                self.assertEqual(len(gap_rows), 1)
                self.assertIn("AFD shall close", str(gap_rows[0][4]))
                self.assertEqual(list(wb["必答-问客户"].iter_rows(min_row=2, values_only=True)), [])
            finally:
                wb.close()


class CoverageGapMarkdownTests(unittest.TestCase):
    def test_markdown_renders_gap_section(self) -> None:
        import clarification_report as cr
        entries = [
            cr._entry(cr.CAT_MISSING, "该段疑似含需求但未被覆盖", quote="The AFD shall act.",
                      source_id="B1", signal="consistency:uncovered",
                      tier=cr.TIER_GAP, audience=cr.AUDIENCE_INTERNAL),
        ]
        md = cr.render_markdown(entries, {"verdict": "READY", "reasons": [], "questions": 0})
        self.assertIn("遗漏候选（1）", md)
        self.assertIn("遗漏候选 1 条", md)
        self.assertIn("The AFD shall act.", md)


if __name__ == "__main__":
    unittest.main()
