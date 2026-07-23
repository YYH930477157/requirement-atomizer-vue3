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

    def test_cli_rejects_out_of_range_budgets_before_running(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "src"
            out.mkdir()
            _seed_gap(out)
            bad_flags = (
                ["--max-tokens", "-1"],
                ["--max-iterations", "0"],
                ["--max-iterations", str(agent_compare.MAX_ITERATIONS + 1)],
            )
            for flags in bad_flags:
                with self.subTest(flags=flags):
                    stdout = StringIO()
                    # 无 key 场景也必须预校验命中（此前 --max-tokens -1 静默 exit 0）
                    with mock.patch("agent_compare._llm_config_or_none", return_value=None):
                        with redirect_stdout(stdout):
                            code = agent_compare.main(["--out-dir", str(out), *flags])
                    self.assertEqual(code, 2)
                    payload = json.loads(stdout.getvalue())
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["error"]["type"], "input_error")
            # 预校验拒绝时不得产生任何循环副作用
            self.assertFalse((out / "decide_trace.jsonl").exists())
            self.assertFalse((out / "agent_loop_summary.json").exists())

    def test_trace_details_accompany_actions_for_both_sides(self) -> None:
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

        for side in ("rule", "llm"):
            section = report[side]
            trace = section["trace"]
            self.assertEqual([entry["action"] for entry in trace], section["actions"])
            self.assertEqual(
                [entry["iteration"] for entry in trace],
                list(range(1, len(trace) + 1)),
            )
            for entry in trace:
                self.assertIn(entry["decider"], ("rule", "llm"))
                self.assertTrue(entry["reason"])
                self.assertEqual(entry["result"]["status"], "ok")
                self.assertTrue(entry["result"]["summary"])
        self.assertEqual(report["rule"]["trace"][0]["action"], "queue_all_gaps")
        self.assertEqual(report["rule"]["trace"][0]["decider"], "rule")
        self.assertIn("Failed extraction sections", report["rule"]["trace"][0]["reason"])
        self.assertEqual(report["llm"]["trace"][0]["decider"], "llm")
        self.assertEqual(report["llm"]["trace"][0]["reason"], "same as rule")


if __name__ == "__main__":
    unittest.main()
