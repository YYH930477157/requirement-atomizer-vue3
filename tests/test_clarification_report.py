"""澄清问题清单 + 就绪判定回归（确定性零 LLM）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import clarification_report as cr


def seed(tmp: Path, *, reqs=None, analysis=None, consistency=None, quality=None) -> None:
    with (tmp / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
        for r in (reqs if reqs is not None else []):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if analysis is not None:
        (tmp / "engineering_analysis.json").write_text(
            json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    if consistency is not None:
        (tmp / "consistency_report.json").write_text(
            json.dumps(consistency, ensure_ascii=False), encoding="utf-8")
    if quality is not None:
        (tmp / "ai_extract_quality.json").write_text(
            json.dumps(quality, ensure_ascii=False), encoding="utf-8")


class CollectQuestionsTests(unittest.TestCase):
    def test_aggregates_all_signal_sources_with_categories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp,
                 reqs=[{"title": "泄漏率", "source_section": "7.13", "source_quote": "q1",
                        "suspicion_reasons": ["原文数值未带全", "验收不可测"]}],
                 analysis={"items": [{"source_section": "5.3", "source_quote": "q2",
                                      "source_requirement_ids": ["AIR-1"],
                                      "open_questions": ["升级包大小上限是多少？"],
                                      "assumptions": ["假定采用双区存储"]}]},
                 consistency={"obis_coreference": [{"code": "1-0:1.8.0", "values_differ": True}],
                              "duplicate_groups": [{"source_quote": "dup quote here"}]})
            entries = cr.collect_questions(tmp)

        cats = sorted(e["category"] for e in entries)
        self.assertEqual(cats.count(cr.CAT_MISSING), 2)       # 漏值 + open_question
        self.assertEqual(cats.count(cr.CAT_AMBIGUOUS), 1)     # 验收不可测
        self.assertEqual(cats.count(cr.CAT_ASSUMPTION), 1)
        self.assertEqual(cats.count(cr.CAT_CONFLICT), 2)      # OBIS 发散 + 重复组
        assumption = next(e for e in entries if e["category"] == cr.CAT_ASSUMPTION)
        self.assertIn("双区存储", assumption["question"])
        self.assertIn("请确认", assumption["question"])

    def test_absent_sources_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp, reqs=[{"title": "干净需求", "source_quote": "q"}])
            self.assertEqual(cr.collect_questions(tmp), [])


class ReadinessTests(unittest.TestCase):
    def test_ready_when_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp, reqs=[], quality={"failed_sections": 0, "coverage_pct": 80.0})
            v = cr.readiness_verdict(tmp, questions=5)
        self.assertEqual(v["verdict"], "READY")
        self.assertEqual(v["reasons"], [])

    def test_needs_work_reasons_accumulate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp, reqs=[], quality={"failed_sections": 2, "coverage_pct": 50.0})
            v = cr.readiness_verdict(tmp, questions=99)
        self.assertEqual(v["verdict"], "NEEDS WORK")
        self.assertEqual(len(v["reasons"]), 3)                 # 失败单元 + 覆盖率 + 待澄清


class TierTests(unittest.TestCase):
    """信号分级：硬信号（确定性检出）必答进就绪门；软信号（模型自报）留档不计门限。
    真实教训：v10 数据 303 条假设 + 277 条 open_questions 把清单膨胀到 612 条不可用。"""

    def test_soft_signals_do_not_trip_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp,
                 reqs=[{"title": "干净需求", "source_quote": "q"}],
                 analysis={"items": [{"source_section": "5", "source_requirement_ids": ["A"],
                                      "source_quote": "q",
                                      "open_questions": [f"软问题{i}" for i in range(20)],
                                      "assumptions": [f"假设{i}" for i in range(20)]}]},
                 quality={"failed_sections": 0, "coverage_pct": 80.0})
            report = cr.run_report(tmp)

        self.assertEqual(report["questions"], 0)                 # 必答 0
        self.assertEqual(report["soft_questions"], 40)
        self.assertEqual(report["questions_total"], 40)
        self.assertEqual(report["readiness"]["verdict"], "READY")   # 软信号不触发 NEEDS WORK

    def test_hard_signals_trip_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp,
                 reqs=[{"title": f"T{i}", "source_section": "4", "source_quote": "q",
                        "suspicion_reasons": ["原文数值未带全"]} for i in range(31)],
                 quality={"failed_sections": 0, "coverage_pct": 80.0})
            report = cr.run_report(tmp)
        self.assertEqual(report["questions"], 31)
        self.assertEqual(report["readiness"]["verdict"], "NEEDS WORK")

    def test_markdown_separates_tiers(self) -> None:
        entries = [cr._entry(cr.CAT_MISSING, "硬问题"),
                   cr._entry(cr.CAT_ASSUMPTION, "软问题", tier=cr.TIER_SOFT)]
        md = cr.render_markdown(entries, {"verdict": "READY", "reasons": []})
        self.assertIn("必答（1）", md)
        self.assertIn("参考（1）", md)
        self.assertLess(md.find("硬问题"), md.find("软问题"))   # 必答在前


class RunReportTests(unittest.TestCase):
    def test_end_to_end_writes_three_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp,
                 reqs=[{"title": "T", "source_section": "4.1", "source_quote": "=EVIL()",
                        "suspicion_reasons": ["原文数值未带全"]}],
                 quality={"failed_sections": 0, "coverage_pct": 80.0})
            report = cr.run_report(tmp)

            self.assertEqual(report["questions"], 1)
            self.assertEqual(report["readiness"]["verdict"], "READY")
            md = (tmp / cr.REPORT_MD).read_text(encoding="utf-8")
            self.assertIn("缺失", md)
            from openpyxl import load_workbook
            wb = load_workbook(tmp / cr.REPORT_XLSX)
            ws = wb["必答"]
            self.assertNotEqual(ws.cell(row=2, column=5).data_type, "f")   # 公式已中和
            self.assertIn("参考(模型自报)", wb.sheetnames)
            self.assertIn("就绪判定", wb.sheetnames)

    def test_missing_input_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                cr.run_report(Path(td))


if __name__ == "__main__":
    unittest.main()
