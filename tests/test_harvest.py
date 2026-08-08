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


class TestHarvestIdempotency(EnvFixtureMixin, unittest.TestCase):
    """A-3：台账写入加锁 + 幂等去重（重跑/并发不污染台账）。"""

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

    def _ledger_count(self, out_dir: Path, filename: str) -> int:
        from result_package import governed_artifact_path

        path = governed_artifact_path(out_dir, filename, category="state", for_write=False)
        if not path.is_file():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def test_rerun_harvest_produces_no_duplicate_entries(self) -> None:
        """简报判据：连续两次 harvest，台账条目数不变（幂等去重）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [
                {
                    "functional_requirement_id": "FRE-0001",
                    "objective": "The meter shall support DLMS.",
                    "behaviors": ["associate"],
                    "source_quote": "The meter shall support DLMS.",
                    "source_block_ids": ["BLK-1"],
                    "design_options": ["TCP wrapper"],
                    "ownership_reason": "通信协议",
                    "acceptance_criteria": ["ok"],
                },
                {
                    "functional_requirement_id": "FRE-0002",
                    "objective": "The meter shall respond within 适当 time.",
                    "source_quote": "respond within 适当 time",
                    "source_block_ids": ["BLK-2"],
                },
            ]
            self._write_functional_requirements(out_dir, items)
            self._write_verification_states(out_dir, [
                {"requirement_id": "FRE-0001", "lifecycle_state": "confirmed", "schema": "verification-state/v1"},
                {"requirement_id": "FRE-0002", "lifecycle_state": "draft", "schema": "verification-state/v1"},
            ])
            harvest_assets(out_dir, actor="tester")
            targets = [PENDING_REQUIREMENTS_FILE, PENDING_SOLUTIONS_FILE,
                       KB_CANDIDATES_FILE, DICTIONARY_CANDIDATES_FILE]
            first = {f: self._ledger_count(out_dir, f) for f in targets}
            self.assertGreater(first[PENDING_REQUIREMENTS_FILE], 0, "前置：首跑应写入台账")

            # 第二次 harvest（内容未变）——不得产生重复条目
            harvest_assets(out_dir, actor="tester")
            second = {f: self._ledger_count(out_dir, f) for f in targets}
            self.assertEqual(first, second, f"重跑产生重复台账条目：{first} vs {second}")

            # 逐文件无重复 document_id+asset_kind+asset_id 键
            from result_package import governed_artifact_path
            for filename in targets:
                path = governed_artifact_path(out_dir, filename, category="state", for_write=False)
                if not path.is_file():
                    continue
                keys = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    keys.append((row.get("document_id"), row.get("asset_kind"), row.get("asset_id")))
                self.assertEqual(len(keys), len(set(keys)), f"{filename} 存在重复幂等键")

    def test_ledger_entries_carry_idempotency_components(self) -> None:
        """台账条目携带 document_id + asset_kind + asset_id 幂等键。"""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            items = [{
                "functional_requirement_id": "FRE-0001",
                "objective": "The meter shall support DLMS.",
                "source_quote": "The meter shall support DLMS.",
                "source_block_ids": ["BLK-1"],
                "design_options": ["TCP wrapper"],
            }]
            self._write_functional_requirements(out_dir, items)
            harvest_assets(out_dir, actor="tester")
            from result_package import governed_artifact_path

            path = governed_artifact_path(out_dir, PENDING_REQUIREMENTS_FILE, category="state", for_write=False)
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue(row.get("document_id"), "document_id 缺失")
            self.assertEqual(row.get("asset_kind"), "pending_requirement")
            self.assertEqual(row.get("asset_id"), "FRE-0001")

    def test_harvest_uses_process_lock(self) -> None:
        """写路径套 process_file_lock——harvest.lock 落盘（锁文件留在磁盘是既有模式）。"""
        from result_package import governed_artifact_path

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self._write_functional_requirements(out_dir, [{
                "functional_requirement_id": "FRE-0001",
                "objective": "x", "source_quote": "q", "source_block_ids": ["BLK-1"],
            }])
            harvest_assets(out_dir, actor="tester")
            lock_path = governed_artifact_path(out_dir, "harvest.lock", category="state", for_write=False)
            self.assertTrue(lock_path.is_file(), "harvest 未使用 process_file_lock（无 harvest.lock）")

    def test_concurrent_harvests_do_not_lose_or_corrupt(self) -> None:
        """并发两个 harvest：锁 + 幂等去重保证最终台账无丢失、无损坏、计数=单跑。"""
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self._write_functional_requirements(out_dir, [{
                "functional_requirement_id": "FRE-0001",
                "objective": "The meter shall support DLMS.",
                "source_quote": "The meter shall support DLMS.",
                "source_block_ids": ["BLK-1"],
                "design_options": ["TCP wrapper"],
            }])
            errors: list[BaseException] = []

            def _run() -> None:
                try:
                    harvest_assets(out_dir, actor="tester")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=_run) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [], f"并发 harvest 异常：{errors}")
            count = self._ledger_count(out_dir, PENDING_REQUIREMENTS_FILE)
            self.assertEqual(count, 1, f"并发后台账应恰为 1 条（幂等），实为 {count}")


if __name__ == "__main__":
    unittest.main()
