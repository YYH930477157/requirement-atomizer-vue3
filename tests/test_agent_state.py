from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import omission_actions
from agent_state import AgentStateValidationError, load_analysis_state


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _seed(
    out_dir: Path,
    *,
    blocks: list[dict] | None = None,
    requirements: list[dict] | None = None,
    quality: dict | list | None = None,
    manifest: dict | None = None,
) -> None:
    _write_jsonl(out_dir / "blocks.jsonl", blocks or [])
    _write_jsonl(out_dir / "ai_requirements.jsonl", requirements or [])
    if quality is not None:
        (out_dir / "ai_extract_quality.json").write_text(
            json.dumps(quality, ensure_ascii=False), encoding="utf-8"
        )
    if manifest is not None:
        (out_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )


class AnalysisStateTests(unittest.TestCase):
    def test_aggregates_ready_state_and_manifest_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            text = "The meter shall record active energy."
            _seed(
                out,
                blocks=[{
                    "block_id": "B1",
                    "order": 1,
                    "text": text,
                    "requirement_like": True,
                    "noise": False,
                }],
                requirements=[{"ai_req_id": "AIR-1", "source_quote": text}],
                quality={"failed_sections": 0, "core_coverage_pct": 100.0},
                manifest={
                    "run_id": "run-state-1",
                    "stages": {"ai-extract": {"status": "ok"}},
                },
            )

            state = load_analysis_state(out)

        self.assertEqual(state.run_id, "run-state-1")
        self.assertEqual(state.requirement_count, 1)
        self.assertEqual(state.stage_statuses, {"ai-extract": "ok"})
        self.assertEqual(state.readiness["verdict"], "READY")
        self.assertEqual(state.state_digest()["ready_gate"], "pass")
        self.assertEqual(state.coverage_gap_block_ids, ())
        self.assertEqual(state.core_coverage_pct, 100.0)
        self.assertEqual(state.failed_stages, ())

    def test_computes_current_layered_coverage_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            covered = "The meter shall record active energy."
            missing = "The meter shall expose an event log."
            _seed(
                out,
                blocks=[
                    {"block_id": "B2", "order": 2, "text": missing,
                     "requirement_like": True, "noise": False},
                    {"block_id": "B1", "order": 1, "text": covered,
                     "requirement_like": True, "noise": False},
                ],
                requirements=[{"ai_req_id": "AIR-1", "source_quote": covered}],
                quality={"failed_sections": 0},
            )

            state = load_analysis_state(out)

        self.assertEqual(state.coverage_gap_block_ids, ("B2",))
        self.assertEqual(state.action_inputs["resample_section"], ["B2"])
        self.assertEqual(state.state_digest()["counts"]["coverage_gaps"], 1)

    def test_expert_non_requirement_is_not_a_coverage_gap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            text = "Product family background statement."
            _seed(
                out,
                blocks=[{"block_id": "B1", "order": 1, "text": text,
                         "requirement_like": True, "noise": False}],
                quality={"failed_sections": 0},
            )
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer"
            )

            state = load_analysis_state(out)

        self.assertEqual(state.coverage_gap_block_ids, ())
        self.assertEqual(state.coverage["excluded"]["block_ids"], ["B1"])

    def test_unresolved_hard_question_drives_readiness_and_action_input(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            text = "The meter shall report code 7."
            _seed(
                out,
                blocks=[{"block_id": "B1", "order": 1, "text": text,
                         "requirement_like": True, "noise": False}],
                requirements=[{
                    "ai_req_id": "AIR-1",
                    "title": "Code reporting",
                    "source_section": "4",
                    "source_quote": text,
                    "source_block_ids": ["B1"],
                    "suspicion_reasons": ["编码漂移"],
                }],
                quality={"failed_sections": 0},
            )

            state = load_analysis_state(out)

        self.assertEqual(state.open_question_count, 1)
        self.assertEqual(state.readiness["verdict"], "NEEDS WORK")
        self.assertEqual(len(state.action_inputs["ask_clarification"]), 1)
        self.assertEqual(state.state_digest()["ready_gate"], "blocked")

    def test_failed_section_blocks_are_resample_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(
                out,
                blocks=[
                    {"block_id": "B9", "order": 2, "text": "The meter shall log alarms.",
                     "requirement_like": True, "noise": False},
                    {"block_id": "B3", "order": 1, "text": "The meter shall log events.",
                     "requirement_like": True, "noise": False},
                ],
                quality={
                    "failed_sections": 1,
                    "failed_section_ids": ["SEC-1"],
                    "failed_section_block_ids": ["B9", "B3"],
                },
            )

            state = load_analysis_state(out)

        self.assertEqual(state.failed_sections, 1)
        self.assertEqual(state.failed_section_ids, ("SEC-1",))
        self.assertEqual(state.action_inputs["resample_section"], ["B3", "B9"])

    def test_structurally_invalid_quality_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, quality=[])

            with self.assertRaises(AgentStateValidationError):
                load_analysis_state(out)


if __name__ == "__main__":
    unittest.main()
