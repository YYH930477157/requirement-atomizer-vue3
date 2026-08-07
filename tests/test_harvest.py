"""WS-H 知识沉淀闭环单元测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import harvest as harvest_module
from harvest import (
    HARVEST_REPORT_FILE,
    PENDING_REQUIREMENTS_FILE,
    PENDING_SOLUTIONS_FILE,
    KB_CANDIDATES_FILE,
    DICTIONARY_CANDIDATES_FILE,
    CALIBRATION_REVIEW_FILE,
    harvest_assets,
    harvest_enabled,
    read_harvest_report,
)


class EnvFixtureMixin:
    """临时覆盖环境变量的测试辅助。"""

    def setUp(self) -> None:
        self._env_snapshot = dict(os.environ)

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key not in self._env_snapshot:
                del os.environ[key]
            else:
                os.environ[key] = self._env_snapshot[key]


class TestHarvestSwitch(EnvFixtureMixin, unittest.TestCase):
    def test_default_disabled(self) -> None:
        os.environ.pop("RATOMIZER_HARVEST", None)
        self.assertFalse(harvest_enabled())

    def test_enabled_by_env(self) -> None:
        os.environ["RATOMIZER_HARVEST"] = "1"
        self.assertTrue(harvest_enabled())


class TestHarvestAssets(EnvFixtureMixin, unittest.TestCase):
    def _write_functional_requirements(self, out_dir: Path, items: list[dict]) -> None:
        (out_dir / "functional_requirements.json").write_text(
            json.dumps({"schema_version": 1, "items": items, "conservation": {"ok": True}}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_verification_states(self, out_dir: Path, states: list[dict]) -> None:
        from result_package import governed_artifact_path

        path = governed_artifact_path(out_dir, "verification_states.jsonl", category="state", for_write=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in states:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_adjudication_results(self, out_dir: Path, records: list[dict]) -> None:
        from result_package import governed_artifact_path

        path = governed_artifact_path(out_dir, "adjudication_results.jsonl", category="state", for_write=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in records:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_empty_directory_returns_zero_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            report = harvest_assets(out_dir, actor="tester")
            self.assertEqual(report["total_functional_requirements"], 0)
            self.assertEqual(report["metrics"]["total_ingested"], 0)
            self.assertTrue(report["enabled"])

    def test_pending_requirements_and_solutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {
                    "functional_requirement_id": "FRE-0001",
                    "objective": "The meter shall support DLMS over TCP.",
                    "behaviors": ["Initiate application association"],
                    "source_quote": "The meter shall support DLMS over TCP.",
                    "source_block_ids": ["BLK-0001"],
                    "design_options": ["Use TCP wrapper"],
                    "ownership_reason": "通信协议归属",
                    "acceptance_criteria": ["Association succeeds"],
                },
            ]
            self._write_functional_requirements(out_dir, items)
            self._write_verification_states(out_dir, [
                {"requirement_id": "FRE-0001", "lifecycle_state": "confirmed", "schema": "verification-state/v1"},
            ])
            report = harvest_assets(out_dir, actor="tester")

            self.assertEqual(report["counts"]["pending_requirements"], 1)
            self.assertEqual(report["counts"]["pending_solutions"], 1)
            self.assertEqual(report["counts"]["kb_candidates"], 1)
            self.assertEqual(report["metrics"]["total_ingested"], 3)

            # 验证产物写入
            self.assertIn(PENDING_REQUIREMENTS_FILE, report["written"])
            self.assertIn(PENDING_SOLUTIONS_FILE, report["written"])
            self.assertIn(KB_CANDIDATES_FILE, report["written"])

    def test_confirmed_vs_draft_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {"functional_requirement_id": "FRE-0001", "objective": "confirmed item", "source_quote": "q", "source_block_ids": ["BLK-1"]},
                {"functional_requirement_id": "FRE-0002", "objective": "draft item", "source_quote": "q", "source_block_ids": ["BLK-2"]},
            ]
            self._write_functional_requirements(out_dir, items)
            self._write_verification_states(out_dir, [
                {"requirement_id": "FRE-0001", "lifecycle_state": "confirmed", "schema": "verification-state/v1"},
                {"requirement_id": "FRE-0002", "lifecycle_state": "draft", "schema": "verification-state/v1"},
            ])
            report = harvest_assets(out_dir, actor="tester")
            self.assertEqual(report["confirmed_count"], 1)
            self.assertEqual(report["counts"]["pending_requirements"], 2)

    def test_weak_word_dictionary_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {
                    "functional_requirement_id": "FRE-0001",
                    "objective": "The meter should respond within 适当 time.",
                    "source_quote": "respond within 适当 time",
                    "source_block_ids": ["BLK-1"],
                },
            ]
            self._write_functional_requirements(out_dir, items)
            report = harvest_assets(out_dir, actor="tester")
            self.assertGreaterEqual(report["counts"]["dictionary_candidates"], 1)
            self.assertIn(DICTIONARY_CANDIDATES_FILE, report["written"])

    def test_calibration_reviews_from_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {"functional_requirement_id": "FRE-0001", "objective": "x", "source_quote": "q", "source_block_ids": ["BLK-1"]},
            ]
            self._write_functional_requirements(out_dir, items)
            from result_package import governed_artifact_path

            audit_path = governed_artifact_path(out_dir, "adjudication_audit.jsonl", category="state", for_write=True)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({
                    "schema": "adjudication-audit/v1",
                    "kind": "potential_misjudgment",
                    "functional_requirement_id": "FRE-0001",
                    "decision": "accept",
                    "reason": "suspicious",
                }, ensure_ascii=False) + "\n")
            report = harvest_assets(out_dir, actor="tester")
            self.assertEqual(report["counts"]["calibration_reviews"], 1)
            self.assertIn(CALIBRATION_REVIEW_FILE, report["written"])

    def test_report_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {"functional_requirement_id": "FRE-0001", "objective": "x", "source_quote": "q", "source_block_ids": ["BLK-1"]},
            ]
            self._write_functional_requirements(out_dir, items)
            harvest_assets(out_dir, actor="tester")
            loaded = read_harvest_report(out_dir)
            self.assertEqual(loaded["schema"], "harvest-report/v1")
            self.assertTrue(loaded["enabled"])
            self.assertEqual(loaded["total_functional_requirements"], 1)

    def test_library_hit_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            library_path = Path(tmp) / "library.jsonl"
            library_path.write_text(json.dumps({
                "objective": "measure energy",
                "behaviors": ["accumulate"],
                "tokens": ["measure", "energy"],
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            os.environ["RATOMIZER_REQUIREMENT_LIBRARY"] = str(library_path)
            items = [
                {"functional_requirement_id": "FRE-0001", "objective": "measure energy", "source_quote": "q", "source_block_ids": ["BLK-1"]},
                {"functional_requirement_id": "FRE-0002", "objective": "unrelated thing", "source_quote": "q", "source_block_ids": ["BLK-2"]},
            ]
            self._write_functional_requirements(out_dir, items)
            report = harvest_assets(out_dir, actor="tester")
            self.assertEqual(report["metrics"]["kb_hit_count"], 1)
            self.assertEqual(report["metrics"]["next_project_library_hit_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
