from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BASELINE = Path(__file__).resolve().parents[1] / "golden_sets" / "requirements_analysis_semantic_v1.json"


class SemanticQualityBaselineTests(unittest.TestCase):
    def test_baseline_has_at_least_thirty_executable_cases(self) -> None:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(payload["cases"]), 30)
        self.assertTrue(all(case.get("requirements") for case in payload["cases"]))
        self.assertTrue(all(case.get("expected") for case in payload["cases"]))

    def test_all_semantic_quality_cases_pass(self) -> None:
        from semantic_quality import evaluate_baseline

        report = evaluate_baseline(BASELINE)

        self.assertEqual(report["failed_cases"], 0, report["failures"])
        self.assertEqual(report["critical_violations"], 0, report["failures"])
        self.assertGreater(report["merged_cases"], 0)
        self.assertGreater(report["split_cases"], 0)

    def test_legacy_corpus_has_safe_nonzero_reduction(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "L-PV1", "title": "PV1点对多点协议配置文件要求", "module": "通信协议",
             "description": "支持PV1点对多点协议配置。"},
            {"ai_req_id": "L-PV2", "title": "PV2点对多点协议配置文件要求", "module": "通信协议",
             "description": "支持PV2点对多点协议配置。"},
            {"ai_req_id": "L-M1", "title": "计量事件日志定义", "module": "事件记录",
             "description": "定义计量事件日志。"},
            {"ai_req_id": "L-M2", "title": "计量事件日志访问权限", "module": "事件记录",
             "description": "定义计量事件日志访问权限。"},
            {"ai_req_id": "L-G1", "title": "通用事件日志定义", "module": "事件记录",
             "description": "定义通用事件日志。"},
            {"ai_req_id": "L-NR", "title": "不可更换电池MGW的电池寿命要求", "module": "环境可靠性"},
            {"ai_req_id": "L-R", "title": "可更换电池MGW的电池寿命要求", "module": "环境可靠性"},
            {"ai_req_id": "L-O", "title": "累计有功电能对象", "module": "DLMS对象",
             "description": "提供OBIS 1-0:1.8.0.255对象。"},
        ]

        items = build_function_catalog(rows)
        assigned = [rid for item in items for rid in item["source_ai_requirement_ids"]]
        rendered = json.dumps(items, ensure_ascii=False)

        self.assertLess(len(items), len(rows))
        self.assertCountEqual(assigned, [row["ai_req_id"] for row in rows])
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertIn("1-0:1.8.0.255", rendered)
        battery_groups = [item for item in items if any(rid in {"L-NR", "L-R"} for rid in item["source_ai_requirement_ids"])]
        self.assertEqual(len(battery_groups), 2)

    def test_module_cli_prints_report_and_returns_success(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "semantic_quality", "--baseline", str(BASELINE)],
            cwd=BASELINE.parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["failed_cases"], 0)
        self.assertEqual(report["total_cases"], 32)
    @unittest.skipUnless(
        __import__("os").environ.get("RATOMIZER_HISTORICAL_SAMPLE"),
        "真实历史样本为外置客户数据(RATOMIZER_HISTORICAL_SAMPLE 未设置)——本门跳过")
    def test_historical_test18_sample_preserves_known_merge_and_split_decisions(self) -> None:
        import os

        from functional_catalog import build_function_catalog

        fixture = Path(os.environ["RATOMIZER_HISTORICAL_SAMPLE"]).expanduser()
        rows = json.loads(fixture.read_text(encoding="utf-8"))["rows"]
        items = build_function_catalog(rows)
        groups = [set(item["source_ai_requirement_ids"]) for item in items]
        by_source = {
            source_id: item
            for item in items for source_id in item["source_ai_requirement_ids"]
        }

        self.assertEqual(len(items), 8)
        self.assertIn({"AIR-ee0ae469c177", "AIR-e395f118c4ae"}, groups)
        self.assertIn({"AIR-3951515976df", "AIR-2fa24b25867e", "AIR-49faeb877290"}, groups)
        self.assertIn({"AIR-b6744a02ac7e", "AIR-1fa0621376ee"}, groups)
        self.assertNotEqual(
            by_source["AIR-56ccdfac8886"]["functional_requirement_id"],
            by_source["AIR-396cd39da293"]["functional_requirement_id"],
        )
        pm_item = by_source["AIR-ee0ae469c177"]
        self.assertEqual([variant["name"] for variant in pm_item["variants"]], ["PM1", "PM2"])
        assigned = [source_id for item in items for source_id in item["source_ai_requirement_ids"]]
        self.assertCountEqual(assigned, [row["ai_req_id"] for row in rows])
        self.assertEqual(len(assigned), len(set(assigned)))
    def test_release_report_includes_historical_corpus_gate(self) -> None:
        import os

        from semantic_quality import evaluate_baseline

        report = evaluate_baseline(BASELINE)

        historical = report["historical_corpus"]
        if not os.environ.get("RATOMIZER_HISTORICAL_SAMPLE"):
            # 外置样本缺席:门如实上报不可用,不计违规也不装作跑过(0715 客户数据出仓)
            self.assertFalse(historical["available"])
            self.assertEqual(historical["critical_violations"], 0)
            return
        self.assertTrue(historical["available"])
        self.assertEqual(historical["source_requirements"], 12)
        self.assertEqual(historical["functional_requirements"], 8)
        self.assertEqual(historical["critical_violations"], 0)
        self.assertTrue(historical["assigned_exactly_once"])
        self.assertTrue(historical["known_groups_preserved"])
        self.assertTrue(historical["opposed_battery_requirements_split"])
    def test_report_can_be_written_for_release_audit(self) -> None:
        from semantic_quality import write_report

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "semantic_quality_report.json"
            report = write_report(BASELINE, target)

            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["passed_cases"], report["passed_cases"])


if __name__ == "__main__":
    unittest.main()
