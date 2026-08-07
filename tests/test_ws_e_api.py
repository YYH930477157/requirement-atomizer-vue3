"""WS-E API 端点测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api_server
from tests.test_api_server import _claim_api, _http_json


class ClosureStatusEndpointTests(unittest.TestCase):
    def test_closure_status_returns_not_ready_for_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blocks.jsonl").write_text("[]\n", encoding="utf-8")
            (root / "ai_requirements.jsonl").write_text("[]\n", encoding="utf-8")
            with patch.dict("os.environ", {"RATOMIZER_CLAIM_LEDGER_MODE": "sampling"}, clear=False):
                with _claim_api(root) as base_url:
                    status, payload = _http_json(base_url, "/closure-status")
            self.assertEqual(status, 200)
            self.assertEqual(payload["schema"], "full-closure/v1")
            self.assertFalse(payload["ready"])
            self.assertEqual(payload["claim_mode"], "sampling")
            kinds = {g["kind"] for g in payload["gaps"]}
            self.assertIn("claim_mode_not_full", kinds)


class ChangesetReportEndpointTests(unittest.TestCase):
    def test_changeset_report_classifies_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old"
            new = Path(tmp) / "new"
            old.mkdir()
            new.mkdir()
            (old / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B1", "text": "alpha", "section_path": ["1"]}) + "\n" +
                json.dumps({"block_id": "B2", "text": "beta", "section_path": ["2"]}) + "\n",
                encoding="utf-8",
            )
            (new / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B1", "text": "alpha", "section_path": ["1"]}) + "\n" +
                json.dumps({"block_id": "B2", "text": "BETA-CHANGED", "section_path": ["2"]}) + "\n" +
                json.dumps({"block_id": "B3", "text": "new", "section_path": ["3"]}) + "\n",
                encoding="utf-8",
            )
            (old / "ai_requirements.jsonl").write_text(
                json.dumps({"ai_req_id": "R1", "source_block_ids": ["B1"]}) + "\n" +
                json.dumps({"ai_req_id": "R2", "source_block_ids": ["B2"]}) + "\n",
                encoding="utf-8",
            )
            (new / "ai_requirements.jsonl").write_text(
                json.dumps({"ai_req_id": "R1", "source_block_ids": ["B1"]}) + "\n" +
                json.dumps({"ai_req_id": "R2", "source_block_ids": ["B2"]}) + "\n" +
                json.dumps({"ai_req_id": "R3", "source_block_ids": ["B3"]}) + "\n",
                encoding="utf-8",
            )
            with _claim_api(old) as base_url:
                path = f"/changeset-report?old_out_dir={old.as_posix()}&new_out_dir={new.as_posix()}"
                status, payload = _http_json(base_url, path)
            self.assertEqual(status, 200)
            self.assertEqual(payload["schema"], "requirement-changeset/v1")
            self.assertEqual(payload["counts"]["added"], 1)
            self.assertEqual(payload["counts"]["obsolete"], 0)
            self.assertEqual(payload["counts"]["retained"], 2)
            self.assertEqual(payload["added"][0]["id"], "R3")
            r2 = next(r for r in payload["retained"] if r["id"] == "R2")
            self.assertEqual(r2["reason"], "source_changed")

    def test_changeset_report_requires_both_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blocks.jsonl").write_text("[]\n", encoding="utf-8")
            (root / "ai_requirements.jsonl").write_text("[]\n", encoding="utf-8")
            with _claim_api(root) as base_url:
                status, payload = _http_json(base_url, "/changeset-report")
            self.assertEqual(status, 400)
            self.assertIn("error", payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
