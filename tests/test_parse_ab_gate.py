"""Tests for tools/parse_ab_gate.py (WS1 wk8 新旧解析路径 A/B 门禁).

Exercises the gate in-process against synthetic ``ab-gate-document/v1`` fixtures:
clean signed hypothesis → pass; protected-encoding drift attempt → fail (HARD);
no hypothesis → designed fallback identical to old path; corpus_eval three
metrics compared when two minimal atomize outputs are supplied, with degradation
driving exit 2.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
for _p in (_REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import parse_ab_gate as gate  # noqa: E402
from output_writer import write_jsonl  # noqa: E402

DUAL_TRACK_SWITCH = "RATOMIZER_TABLE_DUAL_TRACK"


def _doc(document_id, tables):
    return {"schema": "ab-gate-document/v1", "document_id": document_id, "tables": tables}


def _clean_table():
    hypothesis = {
        "schema": "table-structure-hypothesis/v1", "header_level_count": 1,
        "cells": [
            {"coordinate": [1, 1], "role": "header", "confidence": "high"},
            {"coordinate": [1, 2], "role": "header", "confidence": "high"},
            {"coordinate": [1, 3], "role": "header", "confidence": "high"},
            {"coordinate": [2, 1], "role": "data", "confidence": "high"},
            {"coordinate": [2, 2], "role": "data", "confidence": "high"},
            {"coordinate": [2, 3], "role": "data", "confidence": "high"},
            {"coordinate": [3, 1], "role": "data", "confidence": "high"},
            {"coordinate": [3, 2], "role": "data", "confidence": "high"},
            {"coordinate": [3, 3], "role": "data", "confidence": "high"},
        ],
        "semantic_merges": [],
    }
    return {
        "table_id": "TBL-000001", "table_block_id": "BLK-000010",
        "family_id": "parameter_matrix",
        "matrix": [["Parameter", "Value", "Unit"],
                   ["Voltage", "230", "V"],
                   ["Frequency", "50", "Hz"]],
        "merge_ranges": [], "explicit_header_rows": [],
        "headers": ["Parameter", "Value", "Unit"],
        "hypothesis": hypothesis,
    }


def _drift_table():
    # Semantic merge of "0-0:41." + "0.0.255" creates an OBIS code → drift attempt.
    hypothesis = {
        "schema": "table-structure-hypothesis/v1", "header_level_count": 0,
        "cells": [{"coordinate": [1, 1], "role": "data", "confidence": "high"},
                  {"coordinate": [1, 2], "role": "data", "confidence": "high"}],
        "semantic_merges": [{"coordinates": [[1, 1], [1, 2]]}],
    }
    return {
        "table_id": "TBL-000002", "table_block_id": "BLK-000020",
        "family_id": "obis_object",
        "matrix": [["0-0:41.", "0.0.255"]],
        "merge_ranges": [], "explicit_header_rows": [],
        "headers": ["LN", "Value"], "hypothesis": hypothesis,
    }


class ParseABGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Ensure the dual-track switch is not left on by a test.
        self._saved = __import__("os").environ.pop(DUAL_TRACK_SWITCH, None)

    def tearDown(self):
        env = __import__("os").environ
        if self._saved is not None:
            env[DUAL_TRACK_SWITCH] = self._saved
        else:
            env.pop(DUAL_TRACK_SWITCH, None)

    def _write_corpus(self, name, docs):
        corpus = self.root / name
        corpus.mkdir(parents=True, exist_ok=True)
        for i, doc in enumerate(docs):
            (corpus / f"{doc['document_id']}.tables.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return corpus

    def test_clean_signed_hypothesis_passes(self):
        corpus = self._write_corpus("clean", [_doc("doc-clean", [_clean_table()])])
        report = self.root / "r.json"
        rc = gate.main(["--corpus", str(corpus), "--report", str(report)])
        self.assertEqual(rc, 0)
        rep = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(rep["decision"], "pass")
        self.assertEqual(rep["summary"]["signed"], 1)
        self.assertEqual(rep["summary"]["protected_encoding_drift_total"], 0)
        # Signed structure is hypothesis-derived; data rows = [2,3].
        t = rep["documents"][0]["tables"][0]
        self.assertTrue(t["signed"])
        self.assertEqual(t["data_rows"]["new"], [2, 3])
        # corpus_eval honestly pending in fixture mode.
        self.assertEqual(rep["corpus_eval"]["status"], "pending")

    def test_protected_encoding_drift_attempt_fails_hard(self):
        corpus = self._write_corpus("drift", [_doc("doc-drift", [_drift_table()])])
        report = self.root / "r.json"
        rc = gate.main(["--corpus", str(corpus), "--report", str(report)])
        self.assertEqual(rc, 2)
        rep = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(rep["decision"], "fail")
        self.assertTrue(rep["red_lights"]["protected_encoding_drift"])
        self.assertEqual(rep["summary"]["protected_encoding_drift_total"], 1)
        self.assertIn("doc-drift/TBL-000002", rep["summary"]["drift_tables"])

    def test_no_hypothesis_falls_back_identical_to_old(self):
        table = _clean_table()
        table["hypothesis"] = None  # caller ran no proposer → designed fallback
        corpus = self._write_corpus("nofb", [_doc("doc-nofb", [table])])
        report = self.root / "r.json"
        rc = gate.main(["--corpus", str(corpus), "--report", str(report)])
        self.assertEqual(rc, 0)
        rep = json.loads(report.read_text(encoding="utf-8"))
        t = rep["documents"][0]["tables"][0]
        self.assertEqual(t["new_mode"], "fallback_no_hypothesis")
        self.assertEqual(t["data_rows"]["old"], t["data_rows"]["new"])

    def test_corpus_eval_degradation_drives_exit_2(self):
        # Two minimal atomize outputs: NEW has lower coverage than OLD → degraded.
        old_root = self.root / "out_old"
        new_root = self.root / "out_new"
        old_root.mkdir(); new_root.mkdir()
        # corpus_eval reads ai_requirements.jsonl + ai_extract_quality.json.
        write_jsonl(old_root / "ai_requirements.jsonl", [{"id": "r1"}])
        write_jsonl(new_root / "ai_requirements.jsonl", [{"id": "r1"}])
        (old_root / "ai_extract_quality.json").write_text(json.dumps({"coverage_pct": 80.0}), encoding="utf-8")
        (new_root / "ai_extract_quality.json").write_text(json.dumps({"coverage_pct": 70.0}), encoding="utf-8")
        corpus = self._write_corpus("ce", [_doc("doc-clean", [_clean_table()])])
        report = self.root / "r.json"
        rc = gate.main(["--corpus", str(corpus),
                        "--corpus-eval-roots", str(old_root), str(new_root),
                        "--report", str(report)])
        self.assertEqual(rc, 2)
        rep = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(rep["decision"], "fail")
        cov = next(m for m in rep["corpus_eval"]["metrics"] if m["metric"] == "coverage_pct")
        self.assertEqual(cov["status"], "degraded")
        self.assertIn("coverage_pct", rep["corpus_eval"]["degraded_metrics"])

    def test_corpus_eval_no_degradation_passes(self):
        old_root = self.root / "out_old"
        new_root = self.root / "out_new"
        old_root.mkdir(); new_root.mkdir()
        write_jsonl(old_root / "ai_requirements.jsonl", [{"id": "r1"}])
        write_jsonl(new_root / "ai_requirements.jsonl", [{"id": "r1"}])
        # Equal coverage + equal self_check_ratio + equal values_left_behind → no degradation.
        quality = {"coverage_pct": 80.0}
        (old_root / "ai_extract_quality.json").write_text(json.dumps(quality), encoding="utf-8")
        (new_root / "ai_extract_quality.json").write_text(json.dumps(quality), encoding="utf-8")
        corpus = self._write_corpus("ce2", [_doc("doc-clean", [_clean_table()])])
        report = self.root / "r.json"
        rc = gate.main(["--corpus", str(corpus),
                        "--corpus-eval-roots", str(old_root), str(new_root),
                        "--report", str(report)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
