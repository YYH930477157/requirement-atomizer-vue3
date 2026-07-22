from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import omission_actions
from agent_state import load_analysis_state
from agent_tools import (
    ask_clarification,
    execute_action,
    recheck,
    resample_section,
    stop,
)


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


class AgentToolTests(unittest.TestCase):
    def test_zero_llm_resample_queues_without_calling_targeted_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            with mock.patch.object(omission_actions, "targeted_reextract") as targeted:
                result = resample_section(out, "B1")
            current = omission_actions.read_current_omission_states(out)

        self.assertEqual(result["status"], "skipped")
        self.assertIn("zero-LLM", result["summary"])
        targeted.assert_not_called()
        self.assertEqual(next(iter(current.values()))["status"], "needs_extraction")

    def test_explicit_llm_resample_delegates_to_existing_targeted_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            payload = {"schema": "omission-reextract/v1", "requirements": 2}
            with mock.patch.object(
                omission_actions, "targeted_reextract", return_value=payload
            ) as targeted:
                result = resample_section(out, "B1", allow_llm=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"], payload)
        self.assertEqual(targeted.call_args.kwargs["block_id"], "B1")
        self.assertTrue(targeted.call_args.kwargs["expected_source_fingerprint"])

    def test_resample_rejects_non_current_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            _write_jsonl(out / "ai_requirements.jsonl", [{
                "source_quote": "The meter shall log events."
            }])

            with self.assertRaises(ValueError):
                resample_section(out, "B1")

    def test_recheck_is_truthfully_skipped_in_phase1(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [])
            _write_jsonl(out / "ai_requirements.jsonl", [{
                "ai_req_id": "AIR-1",
                "source_quote": "The meter shall log events.",
                "suspicion_reasons": ["引用非逐字"],
            }])

            result = recheck(out, "AIR-1")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("standalone", result["summary"])

    def test_ask_clarification_reuses_report_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            report = {"questions": 3, "written": ["clarification_report.json"]}
            with mock.patch(
                "clarification_report.run_report", return_value=report
            ) as run_report:
                result = ask_clarification(out)

        self.assertEqual(result["status"], "ok")
        self.assertIn("3", result["summary"])
        run_report.assert_called_once_with(out.resolve())

    def test_dispatch_and_stop_return_trace_compatible_results(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed_gap(out)
            state = load_analysis_state(out)
            result = execute_action(out, "stop", state)
            direct = stop(state)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result, direct)
        self.assertEqual(set(result), {"status", "summary"})


if __name__ == "__main__":
    unittest.main()
