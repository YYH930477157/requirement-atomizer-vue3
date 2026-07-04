"""裁决学习回路回归（确定性，零 LLM）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import review_insights


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _req(rid: str, module: str, title: str, description: str = "") -> dict:
    return {"ai_req_id": rid, "module": module, "title": title,
            "description": description or title, "source_quote": title, "labels": [module]}


class ReviewInsightsTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            _req("AI-1", "通信协议", "事件上报 A"),
            _req("AI-2", "通信协议", "事件上报 B"),
            _req("AI-3", "通信协议", "事件上报 C"),
            _req("AI-4", "计量", "计量芯片型号为 Att7022e", "计量芯片型号为 Att7022e。"),
            _req("AI-5", "显示", "显示轮显"),
        ])
        _write_jsonl(out / "ai_review_states.jsonl", [
            {"ai_req_id": "AI-1", "status": "accepted", "module_override": "事件记录"},
            {"ai_req_id": "AI-2", "status": "accepted", "module_override": "事件记录"},
            {"ai_req_id": "AI-3", "status": "accepted", "module_override": "事件记录"},
            # 规则会把"计量芯片"判 hardware，专家改判 co_design → 归属改判信号
            {"ai_req_id": "AI-4", "status": "accepted", "ownership_override": "co_design"},
            {"ai_req_id": "AI-5", "status": "rejected", "reason": "非产品需求"},
        ])

    def test_transitions_and_rejections_counted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            insights = review_insights.build_insights(out)

        self.assertEqual(insights["decided_states"], 5)
        self.assertEqual(insights["module_transitions"],
                         [{"from": "通信协议", "to": "事件记录", "count": 3}])
        self.assertEqual(insights["ownership_transitions"],
                         [{"from": "hardware", "to": "co_design", "count": 1}])
        self.assertEqual(insights["rejected_by_module"], {"显示": 1})

    def test_suggestion_emitted_at_threshold_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            insights = review_insights.build_insights(out)

        # 模块改判 3 次（=阈值）→ 出建议；归属改判 1 次（<阈值）→ 不出
        self.assertEqual(len(insights["suggestions"]), 1)
        self.assertIn("通信协议", insights["suggestions"][0])
        self.assertIn("事件记录", insights["suggestions"][0])
        self.assertIn("map_labels", insights["suggestions"][0])

    def test_write_insights_produces_json_and_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            review_insights.write_insights(out)

            data = json.loads((out / "review_insights.json").read_text(encoding="utf-8"))
            md = (out / "review_insights.md").read_text(encoding="utf-8")

        self.assertEqual(data["schema_version"], "review-insights/v1")
        self.assertIn("通信协议 → 事件记录：3 次", md)
        self.assertIn("建议", md)

    def test_empty_out_dir_yields_zero_report_not_crash(self) -> None:
        """无裁决/无需求：产零值报告不崩（新目录跑复盘是合法操作）。"""
        with tempfile.TemporaryDirectory() as td:
            insights = review_insights.write_insights(Path(td))
        self.assertEqual(insights["decided_states"], 0)
        self.assertEqual(insights["suggestions"], [])

    def test_stale_state_for_missing_requirement_skipped(self) -> None:
        """裁决指向已不存在的需求（重抽后 id 漂移）→ 跳过不计，不崩。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "ai_requirements.jsonl", [_req("AI-1", "计量", "t")])
            _write_jsonl(out / "ai_review_states.jsonl", [
                {"ai_req_id": "AI-GONE", "status": "accepted", "module_override": "事件记录"},
            ])
            insights = review_insights.build_insights(out)
        self.assertEqual(insights["decided_states"], 0)

    def test_rebuild_merged_spec_refreshes_insights(self) -> None:
        """裁决回流每次自动刷新复盘报告（学习回路挂载点）。"""
        import ai_extract

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "text": "The meter shall do A.", "requirement_like": True, "noise": False}])
            _write_jsonl(out / "ai_requirements.jsonl", [
                {"ai_req_id": "AI-1", "type": "functional", "priority": "P1", "module": "通信协议",
                 "title": "Do A", "description": "do A", "source_quote": "The meter shall do A.",
                 "source_section": "4", "labels": ["通信协议"]}])
            _write_jsonl(out / "ai_review_states.jsonl", [
                {"ai_req_id": "AI-1", "status": "accepted", "module_override": "事件记录"}])

            result = ai_extract.rebuild_merged_spec(out)

        self.assertIn("review_insights.json", result["written"])


if __name__ == "__main__":
    unittest.main()
