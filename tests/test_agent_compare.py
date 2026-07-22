from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_compare


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _seed_gap(out: Path) -> None:
    _write_jsonl(out / "blocks.jsonl", [{
        "block_id": "B1",
        "order": 1,
        "text": "The meter shall log events.",
        "requirement_like": True,
        "noise": False,
    }])
    _write_jsonl(out / "ai_requirements.jsonl", [])
    (out / "ai_extract_quality.json").write_text(
        json.dumps({"failed_sections": 0}), encoding="utf-8"
    )


class AgentCompareTests(unittest.TestCase):
    def test_rule_side_runs_and_source_dir_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "src"
            out.mkdir()
            _seed_gap(out)

            report = agent_compare.run_comparison(out, llm_config=None)

            self.assertTrue(Path(out / "blocks.jsonl").exists())
            self.assertFalse((out / "decide_trace.jsonl").exists())
            self.assertFalse((out / "agent_loop_summary.json").exists())

        self.assertEqual(report["llm_ran"], False)
        self.assertEqual(report["llm"], None)
        self.assertEqual(report["agreement"], None)
        self.assertIn("llm_unavailable", report["llm_error"])
        self.assertGreaterEqual(report["rule"]["iterations"], 1)
        self.assertIn("queue_all_gaps", report["rule"]["actions"])

    def test_llm_side_runs_with_mocked_decider_and_agreement_is_computed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "src"
            out.mkdir()
            _seed_gap(out)
            meta = {"usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                    "usage_complete": True}

            with mock.patch(
                "agent_loop.llm_decide",
                return_value=("queue_all_gaps", "same as rule", meta),
            ):
                report = agent_compare.run_comparison(out, llm_config=object())

        self.assertTrue(report["llm_ran"])
        self.assertEqual(report["llm"]["tokens_used"], 10)
        self.assertEqual(report["llm"]["decider_usage"]["llm"], 1)
        self.assertEqual(report["rule"]["actions"], report["llm"]["actions"])
        self.assertTrue(report["agreement"]["sequence_identical"])
        self.assertEqual(report["agreement"]["position_agreement"], 1.0)

    def test_missing_directory_is_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(agent_compare.AgentCompareInputError):
                agent_compare.run_comparison(Path(td) / "missing")

    def test_cli_envelope_marks_llm_not_run(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "src"
            out.mkdir()
            _seed_gap(out)
            stdout = StringIO()
            with mock.patch("agent_compare._llm_config_or_none", return_value=None):
                with redirect_stdout(stdout):
                    code = agent_compare.main(["--out-dir", str(out)])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["llm_ran"])


if __name__ == "__main__":
    unittest.main()
