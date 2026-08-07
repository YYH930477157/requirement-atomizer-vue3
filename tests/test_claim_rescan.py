"""A4 claim 账本四视角复扫测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from claim_quality_rescan import run_claim_rescan, CLAIM_RESCAN_SWITCH


class ClaimRescanUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ.pop(CLAIM_RESCAN_SWITCH, None)

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop(CLAIM_RESCAN_SWITCH, None)

    def _write_functional(self, items: list[dict]) -> Path:
        out_dir = Path(self.tmpdir.name) / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "functional_requirements.json").write_text(
            json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "atomic_requirements.jsonl").write_text(
            json.dumps({"req_id": "R1"}) + "\n", encoding="utf-8"
        )
        return out_dir

    def test_default_off_returns_none(self):
        os.environ[CLAIM_RESCAN_SWITCH] = "0"
        out_dir = self._write_functional([])
        self.assertIsNone(run_claim_rescan(out_dir))

    def test_ownership_issue(self):
        os.environ[CLAIM_RESCAN_SWITCH] = "1"
        out_dir = self._write_functional([
            {"functional_requirement_id": "F1", "title": "Log events", "module": ""},
            {"functional_requirement_id": "F2", "title": "Alarm", "module": "未归属"},
        ])
        result = run_claim_rescan(out_dir)
        self.assertIsNotNone(result)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["perspectives"]["ownership"]["count"], 2)

    def test_numeric_issue(self):
        os.environ[CLAIM_RESCAN_SWITCH] = "1"
        out_dir = self._write_functional([
            {"functional_requirement_id": "F1", "title": "Timeout 30 s", "description": ""},
        ])
        result = run_claim_rescan(out_dir)
        self.assertEqual(result["perspectives"]["numeric"]["count"], 1)
        self.assertEqual(result["perspectives"]["numeric"]["issues"][0]["type"], "numeric_missing_threshold")

    def test_constraint_issue(self):
        os.environ[CLAIM_RESCAN_SWITCH] = "1"
        out_dir = self._write_functional([
            {"functional_requirement_id": "F1", "title": "Shall log", "acceptance_criteria": []},
        ])
        result = run_claim_rescan(out_dir)
        self.assertEqual(result["perspectives"]["constraint"]["count"], 1)

    def test_coverage_issue(self):
        os.environ[CLAIM_RESCAN_SWITCH] = "1"
        out_dir = self._write_functional([
            {"functional_requirement_id": "F1", "title": "Log", "source_ai_requirement_ids": []},
        ])
        result = run_claim_rescan(out_dir)
        self.assertEqual(result["perspectives"]["coverage"]["count"], 1)

    def test_no_issues(self):
        os.environ[CLAIM_RESCAN_SWITCH] = "1"
        out_dir = self._write_functional([
            {
                "functional_requirement_id": "F1",
                "title": "Log events",
                "module": "Metering",
                "description": "Log",
                "threshold_table": {"min": 1},
                "acceptance_criteria": ["A1"],
                "source_ai_requirement_ids": ["R1"],
            }
        ])
        result = run_claim_rescan(out_dir)
        self.assertEqual(result["total_issues"], 0)


if __name__ == "__main__":
    unittest.main()
