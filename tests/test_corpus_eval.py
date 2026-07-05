"""回归语料评估器回归：指标算得对，A/B 与防倒退才有裁判。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import corpus_eval


def seed(tmp: Path, reqs: list[dict], quality: dict | None = None) -> None:
    with (tmp / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
        for r in reqs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if quality is not None:
        (tmp / "ai_extract_quality.json").write_text(
            json.dumps(quality, ensure_ascii=False), encoding="utf-8")


class CorpusEvalTests(unittest.TestCase):
    def test_metrics_computed(self) -> None:
        reqs = [
            {"title": "A", "source_quote": "The AFD shall withstand the handling required during transport.",
             "sub_items": [{"label": "a", "text": "x"}], "threshold_table": {"rows": [[1]]}},
            # 引句为上一条前缀 → 重复对 1（真实 4.14 形态）
            {"title": "B", "source_quote": "The AFD shall withstand the handling required",
             "self_check_added": True, "suspicion_reasons": ["自检补充（初抽遗漏）"]},
            {"title": "C", "source_quote": "unrelated quote about the display readability test",
             "suspicion_reasons": ["原文数值未带全"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp, reqs, {"sections": 10, "failed_sections": 1, "coverage_pct": 75.0})
            m = corpus_eval.evaluate(tmp)
        self.assertEqual(m["requirements"], 3)
        self.assertEqual(m["self_check_added"], 1)
        self.assertEqual(m["duplicate_quote_pairs"], 1)
        self.assertEqual(m["values_left_behind"], 1)
        self.assertEqual(m["suspicious"], 2)
        self.assertEqual(m["with_sub_items"], 1)
        self.assertEqual(m["with_threshold_table"], 1)
        self.assertEqual(m["coverage_pct"], 75.0)
        self.assertEqual(m["failed_sections"], 1)

    def test_comparison_table_renders_all_labels(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed(tmp, [], {})
            m = corpus_eval.evaluate(tmp)
        table = corpus_eval.render_comparison({"旧": m, "新": m})
        self.assertIn("| 指标 | 旧 | 新 |", table)
        self.assertIn("重复对(引句互含)", table)


if __name__ == "__main__":
    unittest.main()
