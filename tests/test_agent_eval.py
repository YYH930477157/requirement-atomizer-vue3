from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

import agent_eval


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "golden_sets" / "agent_eval_v1"


class AgentEvalDatasetTests(unittest.TestCase):
    def test_cases_are_schema_valid_and_meet_category_minimums(self) -> None:
        cases = agent_eval.load_cases(EVAL_DIR)
        counts = agent_eval.category_counts(cases)

        self.assertGreaterEqual(len(cases), 40)
        self.assertGreaterEqual(counts["classify"], 12)
        self.assertGreaterEqual(counts["grouping"], 8)
        self.assertGreaterEqual(counts["must_ask"], 10)
        self.assertGreaterEqual(counts["hallucination"], 10)
        self.assertEqual(len({case["case_id"] for case in cases}), len(cases))
        classify_verdicts = {
            case["expected"]["verdict"]
            for case in cases
            if case["category"] == "classify"
        }
        self.assertEqual(
            classify_verdicts,
            {"software", "hardware", "compliance", "non_requirement"},
        )
        grouping_docs = {
            case["source"]["doc_ref"]
            for case in cases
            if case["category"] == "grouping"
        }
        self.assertGreaterEqual(len(grouping_docs), 2)
        grouping_keys = Counter(
            case["expected"]["group_key"]
            for case in cases
            if case["category"] == "grouping"
        )
        self.assertTrue(grouping_keys)
        self.assertTrue(all(count >= 2 for count in grouping_keys.values()))

    def test_manifest_classification_baseline_matches_current_rules(self) -> None:
        cases = agent_eval.load_cases(EVAL_DIR)
        report = agent_eval.evaluate_cases(cases)
        manifest = json.loads((EVAL_DIR / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["case_count"], len(cases))
        self.assertEqual(manifest["category_counts"], agent_eval.category_counts(cases))
        self.assertEqual(manifest["classification_baseline"], report["classification"])
        self.assertEqual(manifest["grouping_baseline"], report["grouping"])
        self.assertEqual(manifest["must_ask_baseline"], report["must_ask"])
        self.assertEqual(manifest["hallucination_baseline"], report["hallucination"])
        self.assertEqual(manifest["curation"]["human_review_status"], "reviewed")
        self.assertEqual(
            manifest["curation"]["reviewed_case_ids"],
            [
                "classify-001",
                "classify-003",
                "classify-005",
                "classify-006",
                "must-ask-001",
                "classify-009",
                "classify-010",
                "classify-011",
                "classify-012",
                "grouping-005",
                "grouping-006",
                "grouping-007",
                "grouping-008",
                "must-ask-005",
                "must-ask-006",
                "must-ask-007",
                "must-ask-008",
                "must-ask-009",
                "must-ask-010",
                "hallucination-005",
                "hallucination-006",
                "hallucination-007",
                "hallucination-008",
                "hallucination-009",
                "hallucination-010",
            ],
        )

    def test_cli_writes_one_success_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied_eval_dir = Path(tmp) / "agent_eval_v1"
            shutil.copytree(EVAL_DIR, copied_eval_dir)
            before_manifest = json.loads(
                (copied_eval_dir / "manifest.json").read_text(encoding="utf-8")
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = agent_eval.main(["--eval-dir", str(copied_eval_dir)])
            after_manifest = json.loads(
                (copied_eval_dir / "manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "agent-eval")
        self.assertGreaterEqual(payload["summary"]["case_count"], 40)
        self.assertEqual(after_manifest["curation"], before_manifest["curation"])


class AgentEvalCliErrorTests(unittest.TestCase):
    def test_empty_directory_is_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = agent_eval.main(["--eval-dir", tmp])

        self.assertEqual(code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "input_error")

    def test_malformed_case_is_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "cases" / "classify"
            case_dir.mkdir(parents=True)
            (case_dir / "bad.json").write_text("{}\n", encoding="utf-8")
            (root / "manifest.json").write_text("{}\n", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = agent_eval.main(["--eval-dir", str(root)])

        self.assertEqual(code, 3)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "validation_error")


if __name__ == "__main__":
    unittest.main()
