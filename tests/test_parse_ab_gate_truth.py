"""Tests for tools/parse_ab_gate.py --truth-set consumption (T1-2).

Self-proves the consumption chain: the committed gold_functional_v1 dir (empty real truth +
synthetic fixtures) reports pending_annotation with no fabricated numbers; a temp dir with a real
entry reports annotated; fixture entries are distinguished from real; and truth consumption never
changes the A/B degradation decision.
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

_GOLD = _REPO / "golden_sets" / "gold_functional_v1"


def _doc(document_id, tables):
    return {"schema": "ab-gate-document/v1", "document_id": document_id, "tables": tables}


def _clean_table():
    return {
        "table_id": "TBL-000001", "table_block_id": "BLK-000010", "family_id": "parameter_matrix",
        "matrix": [["Parameter", "Value"], ["Voltage", "230"]],
        "merge_ranges": [], "explicit_header_rows": [], "headers": ["Parameter", "Value"],
    }


class TruthSetLoadTests(unittest.TestCase):
    def test_committed_gold_dir_is_pending_annotation(self):
        """The real truth set is empty; only synthetic fixtures exist → pending, real=0."""
        section = gate.load_truth_set(_GOLD)
        self.assertEqual(section["truth_status"], "pending_annotation")
        self.assertEqual(section["counts"]["real"], 0)
        # fixtures are present and counted (self-proof chain)
        self.assertEqual(section["counts"]["fixture"], 3)
        # no fabricated recall/precision value
        self.assertIsNone(section["direct_extract_recall_precision"]["value"])
        self.assertEqual(section["direct_extract_recall_precision"]["status"], "pending_annotation")

    def test_fixture_entries_never_count_as_real(self):
        section = gate.load_truth_set(_GOLD)
        self.assertEqual(section["counts"]["real"], 0)
        self.assertGreater(section["counts"]["fixture"], 0)

    def test_real_entry_flips_to_annotated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "truth.jsonl").write_text(json.dumps({
                "entry_id": "R1", "doc_ref": "REAL-DOC", "annotation_status": "real",
                "annotator": "yyh", "objective": "real req",
                "source_anchor": {"section": "5.1", "coordinates": ["BLK-500"]},
            }, ensure_ascii=False), encoding="utf-8")
            section = gate.load_truth_set(root)
        self.assertEqual(section["truth_status"], "annotated")
        self.assertEqual(section["counts"]["real"], 1)
        self.assertEqual(section["truth_doc_refs"], ["REAL-DOC"])
        self.assertEqual(section["direct_extract_recall_precision"]["status"], "ready_to_compute")

    def test_missing_path_is_pending_not_crash(self):
        section = gate.load_truth_set(_REPO / "does-not-exist-truth-dir")
        self.assertTrue(section["missing_path"])
        self.assertEqual(section["truth_status"], "pending_annotation")
        self.assertEqual(section["counts"]["real"], 0)

    def test_classify_splits_real_and_fixture(self):
        raw = [
            {"entry_id": "R1", "annotation_status": "real"},
            {"entry_id": "F1", "annotation_status": "fixture"},
            {"entry_id": "R2"},  # default real
        ]
        real, fixture = gate._classify_truth_entries(raw)
        self.assertEqual({e["entry_id"] for e in real}, {"R1", "R2"})
        self.assertEqual([e["entry_id"] for e in fixture], ["F1"])


class TruthSetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        corpus = self.root / "corpus"
        corpus.mkdir()
        (corpus / "doc.tables.json").write_text(
            json.dumps(_doc("doc-1", [_clean_table()]), ensure_ascii=False), encoding="utf-8")
        self.corpus = corpus

    def _run(self, *extra):
        report = self.root / "report.json"
        rc = gate.main(["--corpus", str(self.corpus), "--report", str(report), *extra])
        rep = json.loads(report.read_text(encoding="utf-8"))
        return rc, rep

    def test_truth_set_flag_adds_truth_section_pending(self):
        rc, rep = self._run("--truth-set", str(_GOLD))
        self.assertEqual(rc, 0)
        self.assertEqual(rep["truth"]["truth_status"], "pending_annotation")
        self.assertEqual(rep["truth"]["counts"]["real"], 0)
        # decision is still pass (truth is a yardstick, not the thing under test)
        self.assertEqual(rep["decision"], "pass")

    def test_truth_set_with_real_entry_reports_annotated(self):
        truth_dir = self.root / "truth"
        truth_dir.mkdir()
        (truth_dir / "truth.jsonl").write_text(json.dumps({
            "entry_id": "R1", "doc_ref": "REAL-DOC", "annotation_status": "real",
            "annotator": "yyh", "objective": "real req",
            "source_anchor": {"section": "5.1", "coordinates": ["BLK-500"]},
        }, ensure_ascii=False), encoding="utf-8")
        rc, rep = self._run("--truth-set", str(truth_dir))
        self.assertEqual(rep["truth"]["truth_status"], "annotated")
        self.assertEqual(rep["truth"]["counts"]["real"], 1)

    def test_no_truth_set_flag_leaves_truth_null(self):
        rc, rep = self._run()
        self.assertIsNone(rep["truth"])
        self.assertEqual(rc, 0)

    def test_truth_does_not_flip_decision_on_clean_corpus(self):
        # truth consumption is orthogonal: clean corpus stays pass regardless of truth presence.
        rc1, _ = self._run()
        rc2, _ = self._run("--truth-set", str(_GOLD))
        self.assertEqual(rc1, rc2, 0)


if __name__ == "__main__":
    unittest.main()
