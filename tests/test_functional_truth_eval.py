"""Tests for tools/functional_truth_eval.py (T1-3 直抽查全/查准 + T1-4 阈值网格扫描).

Self-proves the three forms (cover / miss / false-positive) on the committed synthetic fixtures,
the exit-code contract (0 达标 / 2 不达标 / 3 用法 / 4 环境), per-document non-averaging, the
pending_annotation honesty when only fixtures exist, and the sweep-thresholds matrix.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
for _p in (_REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import functional_truth_eval as feval  # noqa: E402

_FIX = _REPO / "golden_sets" / "gold_functional_v1" / "fixtures"
_TRUTH = _FIX / "synthetic_truth.jsonl"
_COVER = _FIX / "products_cover.json"
_MISS = _FIX / "products_miss.json"
_FALSEPOS = _FIX / "products_falsepos.json"


def _run(argv):
    """Run the CLI in-process, capture stdout JSON envelope, return (exit_code, envelope_or_None)."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = feval.main(argv)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 1
    envelope = None
    try:
        envelope = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        pass
    return code, envelope


class ThreeFormTests(unittest.TestCase):
    def test_cover_form_recall_precision_one(self):
        _, items = feval._load_products(_COVER)
        truth = feval._load_truth(_TRUTH)
        result = feval.evaluate_doc(truth, items)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["covered_truth_count"], 3)
        self.assertEqual(result["matched_product_count"], 3)
        self.assertEqual(result["uncovered_truth_ids"], [])
        self.assertEqual(result["floating_product_ids"], [])

    def test_miss_form_recall_third_precision_one(self):
        _, items = feval._load_products(_MISS)
        truth = feval._load_truth(_TRUTH)
        result = feval.evaluate_doc(truth, items)
        self.assertAlmostEqual(result["recall"], 1 / 3, places=4)
        self.assertEqual(result["precision"], 1.0)
        # the two missed truth entries are reported by id
        self.assertEqual(set(result["uncovered_truth_ids"]), {"SYN-B", "SYN-C"})

    def test_falsepos_form_recall_one_precision_three_quarters(self):
        _, items = feval._load_products(_FALSEPOS)
        truth = feval._load_truth(_TRUTH)
        result = feval.evaluate_doc(truth, items)
        self.assertEqual(result["recall"], 1.0)
        self.assertAlmostEqual(result["precision"], 3 / 4, places=4)
        self.assertEqual(result["floating_product_ids"], ["FP-X"])


class ExitCodeTests(unittest.TestCase):
    def test_default_thresholds_pass_on_cover(self):
        code, env = _run(["--products", str(_COVER), "--truth-set", str(_TRUTH)])
        self.assertEqual(code, 0)
        self.assertTrue(env["ok"])

    def test_recall_threshold_fails_exit_two_on_miss(self):
        code, env = _run(["--products", str(_MISS), "--truth-set", str(_TRUTH),
                          "--thresholds", "recall=0.5"])
        self.assertEqual(code, 2)
        self.assertFalse(env["ok"])

    def test_precision_threshold_fails_exit_two_on_falsepos(self):
        code, env = _run(["--products", str(_FALSEPOS), "--truth-set", str(_TRUTH),
                          "--thresholds", "precision=0.8"])
        self.assertEqual(code, 2)
        self.assertFalse(env["ok"])

    def test_bad_threshold_value_is_usage_exit_three(self):
        code, env = _run(["--products", str(_COVER), "--truth-set", str(_TRUTH),
                          "--thresholds", "recall=1.5"])
        self.assertEqual(code, 3)
        self.assertFalse(env["ok"])
        self.assertEqual(env["error"]["type"], "usage_error")

    def test_out_of_range_threshold_is_usage_exit_three(self):
        code, _ = _run(["--products", str(_COVER), "--truth-set", str(_TRUTH),
                        "--thresholds", "precision=-0.1"])
        self.assertEqual(code, 3)

    def test_missing_products_input_exit_three(self):
        code, env = _run(["--products", str(_REPO / "nonexistent.json"),
                          "--truth-set", str(_TRUTH)])
        self.assertEqual(code, 3)
        self.assertEqual(env["error"]["type"], "input_error")


class PendingAnnotationTests(unittest.TestCase):
    def test_only_fixture_truth_reports_pending(self):
        # The committed synthetic truth is all fixture → real count 0 → pending_annotation.
        code, env = _run(["--products", str(_COVER), "--truth-set", str(_TRUTH)])
        self.assertEqual(env["truth_status"], "pending_annotation")

    def test_empty_truth_file_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "truth.jsonl").write_text("", encoding="utf-8")
            products = {"doc_ref": "D", "items": [
                {"functional_requirement_id": "P1", "source_section": "1", "source_block_ids": ["B1"],
                 "objective": "x", "behaviors": [], "preconditions": [], "data_constraints": [],
                 "variants": [], "exceptions": [], "related_dlms_objects": []}]}
            ppath = Path(tmp) / "products.json"
            ppath.write_text(json.dumps(products), encoding="utf-8")
            code, env = _run(["--products", str(ppath), "--truth-set", str(Path(tmp) / "truth.jsonl")])
            self.assertEqual(env["truth_status"], "pending_annotation")
            # recall 0 (no truth), precision 0 (product floats) — honestly, not fabricated
            self.assertEqual(env["per_document"]["D"]["recall"], 0.0)


class PerDocumentNoAveragingTests(unittest.TestCase):
    def test_two_docs_reported_separately(self):
        truth = [
            {"entry_id": "T1", "doc_ref": "DOC-A", "annotation_status": "fixture", "objective": "a",
             "source_anchor": {"section": "1", "coordinates": ["B1"]}},
            {"entry_id": "T2", "doc_ref": "DOC-B", "annotation_status": "fixture", "objective": "b",
             "source_anchor": {"section": "1", "coordinates": ["B1"]}},
        ]
        products = {"doc_ref": "DOC-A", "items": [
            {"functional_requirement_id": "P1", "source_section": "1", "source_block_ids": ["B1"],
             "objective": "a", "behaviors": [], "preconditions": [], "data_constraints": [],
             "variants": [], "exceptions": [], "related_dlms_objects": []}]}
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "truth.jsonl"
            tpath.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in truth), encoding="utf-8")
            ppath = Path(tmp) / "products.json"
            ppath.write_text(json.dumps(products), encoding="utf-8")
            code, env = _run(["--products", str(ppath), "--truth-set", str(tpath),
                              "--report", str(Path(tmp) / "r.json")])
        self.assertIn("DOC-A", env["per_document"])
        self.assertIn("DOC-B", env["per_document"])
        # DOC-A: 1 truth covered, 1 product matched → recall 1.0 precision 1.0
        self.assertEqual(env["per_document"]["DOC-A"]["recall"], 1.0)
        # DOC-B: 1 truth, 0 products → recall 0.0 (honest miss, not averaged away)
        self.assertEqual(env["per_document"]["DOC-B"]["recall"], 0.0)


class SweepThresholdsTests(unittest.TestCase):
    def test_sweep_matrix_varies_and_optimal_cell_is_current_default(self):
        _, items = feval._load_products(_COVER)
        truth = feval._load_truth(_TRUTH)
        sweep = feval.sweep_thresholds(truth, items)
        # calibration signal is present (SYN-B carries expects_drilldown=true)
        self.assertEqual(sweep["truth_needs_drill_pos"], 1)
        self.assertEqual(sweep["truth_needs_drill_neg"], 2)
        self.assertEqual(sweep["truth_no_signal"], 0)
        self.assertEqual(sweep["uncalibrated_products"], 0)
        matrix = {(m["thresholds"]["multi_behavior"], m["thresholds"]["multi_condition"]): m
                  for m in sweep["matrix"]}
        # optimal cell (mb=2, mc=1) — matches functional_drilldown current default — perfect
        opt = matrix[(2, 1)]
        self.assertEqual(opt["drilled"], 1)
        self.assertEqual(opt["drill_recall"], 1.0)
        self.assertEqual(opt["drill_precision"], 1.0)
        # over-drill cell (mb=1) drills everything → precision drops
        over = matrix[(1, 1)]
        self.assertEqual(over["drilled"], 3)
        self.assertAlmostEqual(over["drill_precision"], 1 / 3, places=4)
        # under-drill cell (mb=3, mc=2) drills nothing → recall 0
        under = matrix[(3, 2)]
        self.assertEqual(under["drilled"], 0)
        self.assertEqual(under["drill_recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
