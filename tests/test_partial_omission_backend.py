from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ai_extract
import ai_review_actions
import api_server
import desktop_tasks
import omission_actions
from llm_client import LLMConnectionError


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_current_ai_requirements_metadata(out: Path) -> None:
    ai_extract.write_ai_requirements_metadata(
        out,
        input_fingerprint=ai_extract.extraction_input_fingerprint(out),
        run_id="base-run",
    )


class PartialSnapshotTests(unittest.TestCase):
    def test_extract_all_publishes_only_terminal_sections(self) -> None:
        sections = [
            {"section_id": "S1", "text": "cached", "block_ids": ["B1"]},
            {"section_id": "S2", "text": "fresh", "block_ids": ["B2"]},
        ]
        cached_fp = ai_extract.section_fingerprint(sections[0], "model")
        cached_row = {
            "title": "cached",
            "description": "cached requirement",
            "source_section": "S1",
            "source_quote": "cached",
            "source_block_ids": ["B1"],
        }
        fresh_row = {
            "title": "fresh",
            "description": "fresh requirement",
            "source_section": "S2",
            "source_quote": "fresh",
            "source_block_ids": ["B2"],
        }
        snapshots: list[dict] = []

        def capture(_path: Path, **payload):
            snapshots.append(copy.deepcopy(payload))
            return payload

        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache.jsonl"
            _write_jsonl(cache, [{"fingerprint": cached_fp, "requirements": [cached_row]}])
            with mock.patch.object(ai_extract, "write_partial_snapshot", side_effect=capture), \
                    mock.patch.object(ai_extract, "extract_section", return_value=[fresh_row]), \
                    mock.patch.object(ai_extract, "resolve_verify_enabled", return_value=False):
                rows = ai_extract.extract_all(
                    sections,
                    lambda _system, _user: {},
                    model="model",
                    cache_path=cache,
                    partial_path=Path(td) / "partial.json",
                    run_id="run-1",
                    concurrency=1,
                )

        self.assertEqual([snapshot["completed"] for snapshot in snapshots], [1, 2])
        self.assertEqual([row["title"] for row in snapshots[0]["rows"]], ["cached"])
        self.assertEqual([row["title"] for row in snapshots[1]["rows"]], ["cached", "fresh"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.get("extraction_fingerprint") for row in rows))

    def test_missing_partial_status_has_stable_empty_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(api_server.build_ai_extraction_status(Path(td)), {
                "schema": "ai-requirements-partial/v1",
                "run_id": None,
                "completed": 0,
                "total": 0,
                "complete": False,
                "failed": False,
                "rows": [],
            })

    def test_partial_status_projects_both_legacy_quality_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "requirements": 3,
                "coverage_pct": 82.5,
                "core_coverage_pct": 75.0,
            }), encoding="utf-8")

            status = api_server.build_ai_extraction_status(out)

        self.assertEqual(status["quality"], {
            "coverage_pct": 82.5,
            "core_coverage_pct": 75.0,
        })
        self.assertNotIn("requirements", status["quality"])

    def test_malformed_quality_makes_status_endpoint_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "ai_extract_quality.json").write_text("[]", encoding="utf-8")
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.path = "/ai-extraction-status"
            handler.headers = {}
            handler.allowed_origins = set()
            handler.local_token = ""
            handler.output_dir = out
            handler.package_root = out
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))

            handler.do_GET()

        self.assertEqual(responses[0][0], 503)
        self.assertTrue(responses[0][1]["retryable"])
        self.assertIn("must contain a JSON object", responses[0][1]["error"])

    def test_partial_status_does_not_project_stale_downstream_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            row = {
                "ai_req_id": "AI-1", "title": "Clock", "description": "Clock requirement",
                "module": "Clock", "source_section": "4", "source_quote": "Clock requirement",
                "source_block_ids": ["B1"],
            }
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Clock requirement"}])
            (out / "functional_requirements.json").write_text("{}", encoding="utf-8")
            (out / "engineering_analysis.json").write_text("{}", encoding="utf-8")
            ai_extract.write_partial_snapshot(
                out / ai_extract.AI_REQUIREMENTS_PARTIAL,
                run_id="run-new", completed=1, total=2, complete=False, rows=[row],
                input_fingerprint=ai_extract.extraction_input_fingerprint(out),
            )
            os.utime(out / "functional_requirements.json", ns=(1, 1))
            os.utime(out / "engineering_analysis.json", ns=(1, 1))
            with mock.patch.object(api_server, "_functional_membership", return_value={
                "AI-1": {"functional_requirement_id": "STALE-FREQ"},
            }) as membership, mock.patch.object(api_server, "_analysis_enrichment", return_value={
                "AI-1": {"analysis_id": "STALE-ANALYSIS"},
            }) as analysis:
                status = api_server.build_ai_extraction_status(out)

        self.assertEqual(status["rows"][0]["ai_req_id"], "AI-1")
        self.assertNotIn("functional_requirement_id", status["rows"][0])
        self.assertNotIn("analysis_id", status["rows"][0])
        membership.assert_not_called()
        analysis.assert_not_called()

    def test_partial_from_another_blocks_generation_is_not_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Old document"}])
            old_fingerprint = ai_extract.extraction_input_fingerprint(out)
            ai_extract.write_partial_snapshot(
                out / ai_extract.AI_REQUIREMENTS_PARTIAL,
                run_id="old-run", completed=1, total=1, complete=True,
                rows=[{"ai_req_id": "OLD", "title": "Old", "source_block_ids": ["B1"]}],
                input_fingerprint=old_fingerprint,
            )
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "ai_req_id": "OLD",
                "title": "Old",
                "source_section": "4",
                "source_quote": "Old document",
                "source_block_ids": ["B1"],
            }])
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "New document"}])

            status = api_server.build_ai_extraction_status(out)
            final_rows = api_server.build_ai_requirements(out)
            current = api_server.find_current_ai_requirement(out, "OLD")

        self.assertIsNone(status["run_id"])
        self.assertEqual(status["rows"], [])
        self.assertEqual(final_rows, [])
        self.assertIsNone(current)

    def test_final_metadata_rejects_old_document_without_partial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Old document"}])
            old_fingerprint = ai_extract.extraction_input_fingerprint(out)
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "ai_req_id": "OLD", "title": "Old", "source_quote": "Old document",
                "source_block_ids": ["B1"],
            }])
            ai_extract.write_ai_requirements_metadata(
                out, input_fingerprint=old_fingerprint, run_id="old-run"
            )
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "New document"}])

            rows = api_server.build_ai_requirements(out)

        self.assertEqual(rows, [])

    def test_failed_run_publishes_a_terminal_failure_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Document"}])

            def fail(root: Path, **_kwargs):
                ai_extract.write_partial_snapshot(
                    root / ai_extract.AI_REQUIREMENTS_PARTIAL,
                    run_id="failed-run", completed=1, total=3, complete=False,
                    rows=[], input_fingerprint=ai_extract.extraction_input_fingerprint(root),
                )
                raise RuntimeError("endpoint unavailable")

            with mock.patch.object(ai_extract, "_run_ai_extract_locked", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "endpoint unavailable"):
                    ai_extract.run_ai_extract(out, route="openai_compatible")
            partial = ai_extract.read_partial_snapshot(out / ai_extract.AI_REQUIREMENTS_PARTIAL)

        self.assertIsNotNone(partial)
        self.assertTrue(partial["failed"])
        self.assertFalse(partial["complete"])
        self.assertIn("endpoint unavailable", partial["error"])

    def test_preprocessing_failure_does_not_mutate_an_old_completed_generation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Document"}])
            current_input = ai_extract.extraction_input_fingerprint(out)
            ai_extract.write_partial_snapshot(
                out / ai_extract.AI_REQUIREMENTS_PARTIAL,
                run_id="old-complete", completed=1, total=1, complete=True,
                rows=[{"ai_req_id": "OLD", "title": "Old"}],
                input_fingerprint=current_input,
            )

            with mock.patch.object(
                ai_extract,
                "_run_ai_extract_locked",
                side_effect=RuntimeError("preprocessing failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "preprocessing failed"):
                    ai_extract.run_ai_extract(out, route="openai_compatible")
            partial = ai_extract.read_partial_snapshot(out / ai_extract.AI_REQUIREMENTS_PARTIAL)

        self.assertIsNotNone(partial)
        self.assertNotEqual(partial["run_id"], "old-complete")
        self.assertTrue(partial["failed"])
        self.assertEqual(partial["rows"], [])


class AdjudicationFingerprintTests(unittest.TestCase):
    def test_stale_persisted_fingerprint_cannot_hide_subject_drift(self) -> None:
        original = {
            "ai_req_id": "AI-1",
            "title": "Clock",
            "description": "The meter shall expose clock status.",
            "module": "Clock",
            "source_section": "4",
            "source_quote": "The meter shall expose clock status.",
            "source_block_ids": ["B1"],
        }
        ai_review_actions.ensure_requirement_identity(original, extraction_fingerprint="extract-1")
        state = {
            "ai_req_id": "AI-1",
            "status": "accepted",
            "source_fingerprint": original["source_fingerprint"],
            "review_subject_fingerprint": original["review_subject_fingerprint"],
        }
        changed = dict(original)
        changed["description"] = "The meter shall expose corrected clock status."

        self.assertTrue(ai_review_actions.review_state_needs_reconfirmation(changed, state))

    def test_mismatched_state_is_visible_but_draft_and_override_is_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            original = {
                "ai_req_id": "AI-1",
                "title": "Clock",
                "description": "The meter shall expose clock status.",
                "module": "Clock",
                "source_section": "4",
                "source_quote": "The meter shall expose clock status.",
                "source_block_ids": ["B1"],
            }
            ai_review_actions.ensure_requirement_identity(original, extraction_fingerprint="extract-1")
            ai_review_actions.apply_ai_review_action(
                out,
                "AI-1",
                "accepted",
                module_override="Security",
                source_fingerprint_value=original["source_fingerprint"],
                review_subject_fingerprint_value=original["review_subject_fingerprint"],
            )
            changed = dict(original)
            changed["description"] = "The meter shall expose corrected clock status."
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [changed])
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": changed["source_quote"]}])

            row = api_server.build_ai_requirements(out)[0]
            rebuilt = ai_extract.apply_ai_decisions(out, [changed])

        self.assertEqual(row["review_state"]["status"], "accepted")
        self.assertTrue(row["needs_reconfirmation"])
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["module_effective"], "Clock")
        self.assertEqual(len(rebuilt), 1)

    def test_unique_source_fingerprint_preserves_history_after_id_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            original = {
                "title": "Old title",
                "description": "The meter shall expose clock status.",
                "module": "Clock",
                "source_section": "4",
                "source_quote": "The meter shall expose clock status.",
                "source_block_ids": ["B1"],
            }
            ai_review_actions.ensure_requirement_identity(original, extraction_fingerprint="extract-1")
            old_id = original["ai_req_id"]
            ai_review_actions.apply_ai_review_action(
                out,
                old_id,
                "accepted",
                source_fingerprint_value=original["source_fingerprint"],
                review_subject_fingerprint_value=original["review_subject_fingerprint"],
            )
            changed = dict(original)
            changed.pop("ai_req_id")
            changed["title"] = "Corrected title"
            ai_review_actions.ensure_requirement_identity(changed, extraction_fingerprint="extract-2")
            self.assertNotEqual(changed["ai_req_id"], old_id)
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [changed])
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": changed["source_quote"]}])

            row = api_server.build_ai_requirements(out)[0]

        self.assertEqual(row["review_state"]["ai_req_id"], old_id)
        self.assertTrue(row["needs_reconfirmation"])
        self.assertEqual(row["status"], "draft")


class OmissionActionTests(unittest.TestCase):
    def test_current_candidates_exclude_blocks_already_covered_by_a_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "order": 1, "text": "The meter shall log events.",
                 "requirement_like": True, "noise": False},
                {"block_id": "B2", "order": 2, "text": "The meter shall expose alarms.",
                 "requirement_like": True, "noise": False},
            ])
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "source_quote": "The meter shall log events.",
            }])

            candidates = omission_actions.current_omission_candidate_ids(out)

        self.assertEqual(candidates, {"B2"})

    def test_current_non_requirement_triage_is_removed_from_candidate_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            text = "Product family background statement."
            _write_jsonl(out / "blocks.jsonl", [{
                "block_id": "B1", "order": 1, "text": text,
                "requirement_like": True, "noise": False,
            }])
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [])
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )

            candidates = omission_actions.current_omission_candidate_ids(out)
            quality = ai_extract.refresh_ai_extract_quality(out, [])
            ai_extract._write_consistency_report(out, {"requirements": []})
            consistency = json.loads((out / "consistency_report.json").read_text(encoding="utf-8"))

        self.assertEqual(candidates, set())
        self.assertEqual(quality["core_requirement_like_blocks"], 0)
        self.assertEqual(quality["excluded_requirement_like_blocks"], 1)
        self.assertEqual(consistency["coverage"]["excluded"]["block_ids"], ["B1"])

    def test_current_candidates_include_failed_section_blocks(self) -> None:
        """Failed-section blocks stay candidates even when a leftover quote covers them."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "order": 1, "text": "The meter shall log events.",
                 "requirement_like": True, "noise": False},
                {"block_id": "B2", "order": 2, "text": "The meter shall expose alarms.",
                 "requirement_like": True, "noise": False},
            ])
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "source_quote": "The meter shall log events.",
            }])
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 1,
                "failed_section_ids": ["S1"],
                "failed_section_block_ids": ["B1"],
            }), encoding="utf-8")

            candidates = omission_actions.current_omission_candidate_ids(out)

        self.assertEqual(candidates, {"B1", "B2"})

    def test_current_candidates_drop_failed_blocks_absent_from_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{
                "block_id": "B1", "order": 1, "text": "The meter shall log events.",
                "requirement_like": True, "noise": False,
            }])
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [])
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 1,
                "failed_section_ids": ["S9"],
                "failed_section_block_ids": ["GHOST"],
            }), encoding="utf-8")

            candidates = omission_actions.current_omission_candidate_ids(out)

        self.assertEqual(candidates, {"B1"})

    def test_targeted_reextract_accepts_a_registered_failed_section_block(self) -> None:
        """A failed-section block queued by the agent stays extractable when covered."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            blocks = [{"block_id": "B1", "text": source_text, "requirement_like": True}]
            _write_jsonl(out / "blocks.jsonl", blocks)
            # The leftover row keeps B1 out of the recomputed uncovered set...
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "ai_req_id": "AI-1",
                "title": "Event logging",
                "description": "Old description",
                "module": "事件",
                "source_section": "4",
                "source_quote": source_text,
                "source_block_ids": ["B1"],
            }])
            # ...while the quality report still records the failed section.
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 1,
                "failed_section_ids": ["S1"],
                "failed_section_block_ids": ["B1"],
            }), encoding="utf-8")
            _write_current_ai_requirements_metadata(out)
            queued = omission_actions.apply_omission_action(
                out, block_id="B1", status="needs_extraction", actor="agent-loop",
            )
            self.assertEqual(omission_actions.current_omission_candidate_ids(out), {"B1"})
            section = {"section_id": "S1", "text": source_text, "block_ids": ["B1"]}
            config = mock.Mock(model="model-x")

            def critique(_section, existing, *_args, **_kwargs):
                existing[0]["description"] = "Guarded corrected description"
                return [], []

            with mock.patch.object(
                omission_actions,
                "_find_target_section",
                return_value=(blocks, section, [section]),
            ), mock.patch.object(
                ai_extract, "config_for_route", return_value=config,
            ), mock.patch.object(
                ai_extract, "build_doc_context", return_value="",
            ), mock.patch.object(
                ai_extract, "critique_section", side_effect=critique,
            ), mock.patch.object(
                ai_extract, "rebuild_merged_spec", return_value={"written": []},
            ), mock.patch(
                "llm_client.apply_min_tokens", side_effect=lambda value, _purpose: value,
            ):
                result = omission_actions.targeted_reextract(
                    out,
                    block_id="B1",
                    omission_id=queued["omission_id"],
                    expected_source_fingerprint=omission_actions.omission_source_fingerprint(
                        "B1", source_text
                    ),
                )

            effective = ai_extract.read_jsonl(out / ai_extract.AI_REQUIREMENTS)
            current = omission_actions.read_current_omission_states(out)

        self.assertEqual(result["requirements"], 1)
        self.assertEqual(effective[0]["description"], "Guarded corrected description")
        self.assertEqual(result["supplement"]["block_id"], "B1")
        self.assertEqual(current[queued["omission_id"]]["status"], "resolved")

    def test_targeted_reextract_rechecks_candidate_inside_operation_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{
                "block_id": "B1", "text": "The meter shall log events.",
            }])
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [])
            _write_current_ai_requirements_metadata(out)

            with mock.patch.object(
                omission_actions,
                "current_omission_candidate_ids",
                return_value=set(),
            ), self.assertRaises(omission_actions.OmissionConflictError):
                omission_actions.targeted_reextract(
                    out,
                    block_id="B1",
                    omission_id="OMI-B1",
                    route="openai_compatible",
                )

    def test_status_log_and_source_bound_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "The meter shall log events."}])

            state = omission_actions.apply_omission_action(
                out, block_id="B1", status="needs_extraction", actor="reviewer"
            )
            latest = omission_actions.read_omission_states(out)

            self.assertEqual(latest[state["omission_id"]]["status"], "needs_extraction")
            with self.assertRaises(ValueError):
                omission_actions.apply_omission_action(
                    out,
                    block_id="B1",
                    omission_id="OMI-wrong",
                    status="resolved",
                )

    def test_source_change_keeps_history_but_removes_state_from_current_projection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Old text"}])
            state = omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "New requirement text"}])

            history = omission_actions.read_omission_states(out)
            current = omission_actions.read_current_omission_states(out)

        self.assertIn(state["omission_id"], history)
        self.assertEqual(current, {})

    def test_targeted_reextract_updates_an_existing_row_with_guarded_preconditions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            blocks = [{"block_id": "B1", "text": source_text, "requirement_like": True}]
            _write_jsonl(out / "blocks.jsonl", blocks)
            original = {
                "ai_req_id": "AI-1",
                "title": "Event logging",
                "description": "Old description",
                "module": "事件",
                "source_section": "4",
                "source_quote": "An older adjacent event requirement.",
                "source_block_ids": ["B1"],
            }
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [original])
            _write_current_ai_requirements_metadata(out)
            section = {"section_id": "S1", "text": source_text, "block_ids": ["B1"]}
            config = mock.Mock(model="model-x")

            def critique(_section, existing, *_args, **_kwargs):
                existing[0]["description"] = "Guarded corrected description"
                return [], []

            with mock.patch.object(
                omission_actions,
                "_find_target_section",
                return_value=(blocks, section, [section]),
            ), mock.patch.object(
                ai_extract, "config_for_route", return_value=config,
            ), mock.patch.object(
                ai_extract, "build_doc_context", return_value="",
            ), mock.patch.object(
                ai_extract, "critique_section", side_effect=critique,
            ), mock.patch.object(
                ai_extract, "rebuild_merged_spec", return_value={"written": []},
            ), mock.patch(
                "llm_client.apply_min_tokens", side_effect=lambda value, _purpose: value,
            ):
                result = omission_actions.targeted_reextract(
                    out,
                    block_id="B1",
                    omission_id=omission_actions.make_omission_id("B1", source_text),
                    expected_source_fingerprint=omission_actions.omission_source_fingerprint(
                        "B1", source_text
                    ),
                )

            effective = ai_extract.read_jsonl(out / ai_extract.AI_REQUIREMENTS)

        self.assertEqual(result["requirements"], 1)
        self.assertEqual(effective[0]["description"], "Guarded corrected description")
        self.assertIn("source_fingerprint", result["supplement"]["preconditions"]["AI-1"])

    def test_targeted_patch_identity_changes_when_base_precondition_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            blocks = [{"block_id": "B1", "text": source_text, "requirement_like": True}]
            _write_jsonl(out / "blocks.jsonl", blocks)
            section = {"section_id": "S1", "text": source_text, "block_ids": ["B1"]}
            config = mock.Mock(model="model-x")

            def run_once(description: str) -> dict:
                _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                    "ai_req_id": "AI-1", "title": "Event logging", "description": description,
                    "module": "事件", "source_section": "4",
                    "source_quote": "An older adjacent event requirement.",
                    "source_block_ids": ["B1"],
                }])
                _write_current_ai_requirements_metadata(out)

                def critique(_section, existing, *_args, **_kwargs):
                    existing[0]["description"] = "Guarded corrected description"
                    return [], []

                with mock.patch.object(
                    omission_actions, "_find_target_section", return_value=(blocks, section, [section]),
                ), mock.patch.object(
                    ai_extract, "config_for_route", return_value=config,
                ), mock.patch.object(
                    ai_extract, "build_doc_context", return_value="",
                ), mock.patch.object(
                    ai_extract, "critique_section", side_effect=critique,
                ), mock.patch.object(
                    ai_extract, "rebuild_merged_spec", return_value={"written": []},
                ), mock.patch(
                    "llm_client.apply_min_tokens", side_effect=lambda value, _purpose: value,
                ):
                    return omission_actions.targeted_reextract(
                        out,
                        block_id="B1",
                        omission_id=omission_actions.make_omission_id("B1", source_text),
                        expected_source_fingerprint=omission_actions.omission_source_fingerprint(
                            "B1", source_text
                        ),
                    )

            first = run_once("Old description")
            second = run_once("Intermediate full-extraction description")
            patches = omission_actions.read_supplement_patches(out)
            effective = ai_extract.read_jsonl(out / ai_extract.AI_REQUIREMENTS)

        self.assertNotEqual(first["supplement"]["supplement_id"], second["supplement"]["supplement_id"])
        self.assertEqual(len(patches), 2)
        self.assertEqual(effective[0]["description"], "Guarded corrected description")

    def test_targeted_reextract_rejects_old_base_producer_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            _write_jsonl(out / "blocks.jsonl", [{
                "block_id": "B1", "text": source_text, "requirement_like": True,
            }])
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "ai_req_id": "AI-1",
                "title": "Event logging",
                "description": "Old description",
                "source_quote": source_text,
                "source_block_ids": ["B1"],
            }])
            _write_current_ai_requirements_metadata(out)
            metadata_path = out / ai_extract.AI_REQUIREMENTS_META
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["producer_lineage"]["extract_prompt_version"] = "ai-extract-v22"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            requirements_before = (out / ai_extract.AI_REQUIREMENTS).read_bytes()
            metadata_before = metadata_path.read_bytes()

            with mock.patch.object(
                omission_actions, "current_omission_candidate_ids",
            ) as candidates, mock.patch.object(
                ai_extract, "critique_section",
            ) as critique, self.assertRaisesRegex(
                omission_actions.OmissionConflictError, "older producer version",
            ):
                omission_actions.targeted_reextract(
                    out,
                    block_id="B1",
                    omission_id=omission_actions.make_omission_id("B1", source_text),
                    expected_source_fingerprint=omission_actions.omission_source_fingerprint(
                        "B1", source_text
                    ),
                )

            candidates.assert_not_called()
            critique.assert_not_called()
            self.assertEqual((out / ai_extract.AI_REQUIREMENTS).read_bytes(), requirements_before)
            self.assertEqual(metadata_path.read_bytes(), metadata_before)
            self.assertFalse((out / omission_actions.AI_SUPPLEMENTS).exists())

    def test_current_supplement_upserts_and_source_drift_invalidates_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": source_text}])
            model = "model-x"
            strategy = omission_actions.supplement_strategy_fingerprint(model)
            patch = {
                "strategy_version": omission_actions.AI_SUPPLEMENT_VERSION,
                "strategy_fingerprint": strategy,
                "model": model,
                "block_id": "B1",
                "source_fingerprint": omission_actions.omission_source_fingerprint("B1", source_text),
                "upserts": [{
                    "ai_req_id": "AI-SUP",
                    "title": "Event logging",
                    "description": source_text,
                    "source_section": "4",
                    "source_quote": source_text,
                    "source_block_ids": ["B1"],
                }],
                "preconditions": {"AI-SUP": {
                    "base_absent": True,
                    "source_blocks": {
                        "B1": omission_actions.omission_source_fingerprint("B1", source_text),
                    },
                }},
            }
            _write_jsonl(out / omission_actions.AI_SUPPLEMENTS, [patch])

            effective = omission_actions.apply_supplement_patches(out, [])
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Changed source."}])
            stale = omission_actions.apply_supplement_patches(out, [])

        self.assertEqual([row["ai_req_id"] for row in effective], ["AI-SUP"])
        self.assertEqual(stale, [])

    def test_stub_route_replays_supplements_instead_of_wiping_them(self) -> None:
        """回归：stub 路由曾把含专家补抽行的正式文件覆盖为空（补丁只在 LLM 分支重放）。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "section_path": ["4"], "text": source_text},
            ])
            model = "model-x"
            patch = {
                "strategy_version": omission_actions.AI_SUPPLEMENT_VERSION,
                "strategy_fingerprint": omission_actions.supplement_strategy_fingerprint(model),
                "model": model,
                "block_id": "B1",
                "source_fingerprint": omission_actions.omission_source_fingerprint("B1", source_text),
                "upserts": [{
                    "ai_req_id": "AI-SUP",
                    "title": "Event logging",
                    "description": source_text,
                    "source_section": "4",
                    "source_quote": source_text,
                    "source_block_ids": ["B1"],
                }],
                "preconditions": {"AI-SUP": {
                    "base_absent": True,
                    "source_blocks": {
                        "B1": omission_actions.omission_source_fingerprint("B1", source_text),
                    },
                }},
            }
            _write_jsonl(out / omission_actions.AI_SUPPLEMENTS, [patch])

            result = ai_extract.run_ai_extract(out, route="stub")
            rows = [json.loads(line)
                    for line in (out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            status = api_server.build_ai_extraction_status(out)

        self.assertEqual(result["route"], "stub")
        self.assertEqual([row["ai_req_id"] for row in rows], ["AI-SUP"])
        self.assertTrue(status["complete"])
        self.assertEqual([row["ai_req_id"] for row in status["rows"]], ["AI-SUP"])

    def test_base_absent_patch_does_not_duplicate_a_fresh_row_on_the_same_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source_text = "The meter shall log events."
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": source_text}])
            strategy = omission_actions.supplement_strategy_fingerprint("model-x")
            patched = {
                "ai_req_id": "AI-OLD", "title": "Old title", "description": "Old extraction",
                "source_section": "4", "source_quote": source_text, "source_block_ids": ["B1"],
            }
            patch = {
                "strategy_version": omission_actions.AI_SUPPLEMENT_VERSION,
                "strategy_fingerprint": strategy,
                "model": "model-x",
                "block_id": "B1",
                "source_fingerprint": omission_actions.omission_source_fingerprint("B1", source_text),
                "upserts": [patched],
                "preconditions": {"AI-OLD": {
                    "base_absent": True,
                    "source_blocks": {
                        "B1": omission_actions.omission_source_fingerprint("B1", source_text),
                    },
                }},
            }
            _write_jsonl(out / omission_actions.AI_SUPPLEMENTS, [patch])
            fresh = {
                "ai_req_id": "AI-NEW", "title": "Corrected title", "description": "Fresh extraction",
                "source_section": "4", "source_quote": "The meter shall record events.",
                "source_block_ids": ["B1"],
            }

            effective = omission_actions.apply_supplement_patches(out, [fresh])

        self.assertEqual(effective, [fresh])

    def test_quality_coverage_is_recomputed_after_targeted_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "text": "The meter shall log events.", "requirement_like": True},
                {"block_id": "B2", "text": "The meter shall expose alarms.", "requirement_like": True},
            ])
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 0, "coverage_pct": 50.0,
            }), encoding="utf-8")
            requirements = [
                {"source_quote": "The meter shall log events.", "labels": ["事件"]},
                {"source_quote": "The meter shall expose alarms.", "labels": ["事件"]},
            ]

            quality = ai_extract.refresh_ai_extract_quality(out, requirements)

        self.assertEqual(quality["covered_blocks"], 2)
        self.assertEqual(quality["coverage_pct"], 100.0)

    def test_quality_coverage_uses_reliable_whitespace_insensitive_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "order": 1,
                 "text": "The meter must beable to communicate a nd report alarms.",
                 "requirement_like": True, "noise": False},
                {"block_id": "B2", "order": 2,
                 "text": "The meter shall retain diagnostics.",
                 "requirement_like": True, "noise": False},
            ])
            requirements = [{
                "source_quote": "The meter must be able to communicate and report alarms.",
                "source_block_ids": ["B1", "B2"],
                "source_mapping": "section_fallback",
                "labels": ["通信"],
            }]

            quality = ai_extract.refresh_ai_extract_quality(out, requirements)

        self.assertEqual(quality["covered_blocks"], 1)
        self.assertEqual(quality["coverage_pct"], 50.0)

    def test_new_supplement_row_is_not_replayed_after_its_evidence_block_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            trigger = "Unchanged omission trigger"
            old_evidence = "The meter shall log old events."
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "text": trigger},
                {"block_id": "B2", "text": old_evidence},
            ])
            model = "model-x"
            strategy = omission_actions.supplement_strategy_fingerprint(model)
            patch = {
                "strategy_version": omission_actions.AI_SUPPLEMENT_VERSION,
                "strategy_fingerprint": strategy,
                "model": model,
                "block_id": "B1",
                "source_fingerprint": omission_actions.omission_source_fingerprint("B1", trigger),
                "upserts": [{
                    "ai_req_id": "AI-SUP",
                    "title": "Event logging",
                    "description": old_evidence,
                    "source_section": "4",
                    "source_quote": old_evidence,
                    "source_block_ids": ["B2"],
                }],
                "preconditions": {"AI-SUP": {
                    "base_absent": True,
                    "source_blocks": {
                        "B2": omission_actions.omission_source_fingerprint("B2", old_evidence),
                    },
                }},
            }
            _write_jsonl(out / omission_actions.AI_SUPPLEMENTS, [patch])
            self.assertEqual(len(omission_actions.apply_supplement_patches(out, [])), 1)

            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "text": trigger},
                {"block_id": "B2", "text": "The meter shall log corrected events."},
            ])
            stale = omission_actions.apply_supplement_patches(out, [])

        self.assertEqual(stale, [])

    def test_patch_cannot_overwrite_a_new_base_when_an_upsert_source_block_changed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            trigger = "Unchanged omission trigger"
            old_source = "Old source requirement"
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "text": trigger},
                {"block_id": "B2", "text": old_source},
            ])
            old = {
                "ai_req_id": "AI-1", "title": "Requirement", "description": "Old derived content",
                "source_section": "4", "source_quote": old_source, "source_block_ids": ["B2"],
            }
            changed_by_patch = {**old, "description": "Patched old content"}
            model = "model-x"
            strategy = omission_actions.supplement_strategy_fingerprint(model)
            patch = {
                "strategy_version": omission_actions.AI_SUPPLEMENT_VERSION,
                "strategy_fingerprint": strategy,
                "model": model,
                "block_id": "B1",
                "source_fingerprint": omission_actions.omission_source_fingerprint("B1", trigger),
                "upserts": [changed_by_patch],
                "preconditions": {"AI-1": {
                    "base_absent": False,
                    "source_fingerprint": ai_review_actions.source_fingerprint(old),
                    "review_subject_fingerprint": ai_review_actions.review_subject_fingerprint(old),
                    "source_blocks": {
                        "B2": omission_actions.omission_source_fingerprint("B2", old_source),
                    },
                }},
            }
            _write_jsonl(out / omission_actions.AI_SUPPLEMENTS, [patch])
            new_source = "New source requirement"
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "text": trigger},
                {"block_id": "B2", "text": new_source},
            ])
            new = {
                **old, "description": "New derived content", "source_quote": new_source,
            }

            effective = omission_actions.apply_supplement_patches(out, [new])

        self.assertEqual(effective[0]["description"], "New derived content")
        self.assertEqual(effective[0]["source_quote"], new_source)

    def test_full_and_targeted_extraction_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with omission_actions.extraction_operation_lock(out, operation="targeted"):
                with self.assertRaises(omission_actions.OmissionConflictError):
                    ai_extract.run_ai_extract(out, route="stub")

    def test_downstream_stage_and_targeted_extraction_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with omission_actions.extraction_operation_lock(out, operation="targeted"):
                with self.assertRaises(omission_actions.OmissionConflictError):
                    desktop_tasks.functional_synthesis_task(out, route="stub")

    def test_downstream_and_targeted_actions_reject_cross_document_final(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            old_text = "Old document requirement."
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": old_text}])
            old_fingerprint = ai_extract.extraction_input_fingerprint(out)
            _write_jsonl(out / ai_extract.AI_REQUIREMENTS, [{
                "ai_req_id": "AI-OLD", "title": "Old", "description": old_text,
                "source_quote": old_text, "source_block_ids": ["B1"],
            }])
            ai_extract.write_ai_requirements_metadata(
                out, input_fingerprint=old_fingerprint, run_id="old-run"
            )
            new_text = "New document shall expose alarms."
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": new_text}])

            with self.assertRaisesRegex(RuntimeError, "older parsed document"):
                desktop_tasks.functional_synthesis_task(out, route="stub")
            with self.assertRaisesRegex(
                omission_actions.OmissionConflictError, "older parsed document"
            ):
                omission_actions.targeted_reextract(
                    out,
                    block_id="B1",
                    omission_id=omission_actions.make_omission_id("B1", new_text),
                    expected_source_fingerprint=omission_actions.omission_source_fingerprint(
                        "B1", new_text
                    ),
                )

    def test_stale_manifest_is_not_a_concurrency_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "run_manifest.json").write_text(
                json.dumps({"stages": {"ai-extract": {"status": "running"}}}),
                encoding="utf-8",
            )
            self.assertTrue(omission_actions.extraction_in_progress(out))
            with omission_actions._targeted_operation_lock(out):
                pass

    def test_package_manifest_running_status_uses_governed_read_path(self) -> None:
        from result_package import initialize_result_package, package_artifact_path

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source = out / "standard.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(
                out, input_path=source, requested_stages=["ai-extract"],
            )
            package_artifact_path(out, "run_manifest", for_write=True).write_text(
                json.dumps({"stages": {"ai-extract": {"status": "running"}}}),
                encoding="utf-8",
            )

            self.assertTrue(omission_actions.extraction_in_progress(out))

    def test_package_progress_read_does_not_create_missing_directories(self) -> None:
        import shutil

        from result_package import initialize_result_package

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            source = out / "standard.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(
                out, input_path=source, requested_stages=["ai-extract"],
            )
            shutil.rmtree(out / ".ratomizer" / "stages")
            shutil.rmtree(out / ".ratomizer" / "pipeline")

            self.assertFalse(omission_actions.extraction_in_progress(out))
            self.assertFalse((out / ".ratomizer" / "stages").exists())
            self.assertFalse((out / ".ratomizer" / "pipeline").exists())

    def test_failed_partial_is_terminal_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "blocks.jsonl", [{"block_id": "B1", "text": "Document"}])
            ai_extract.write_partial_snapshot(
                out / ai_extract.AI_REQUIREMENTS_PARTIAL,
                run_id="failed-run", completed=1, total=2, complete=False,
                failed=True, error="endpoint unavailable", rows=[],
                input_fingerprint=ai_extract.extraction_input_fingerprint(out),
            )

            self.assertFalse(omission_actions.extraction_in_progress(out))

    def test_abandoned_operation_lock_is_reclaimed_by_pid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            lock_path = out / omission_actions._EXTRACTION_OPERATION_LOCK
            lock_path.write_text(json.dumps({"pid": 2_147_483_647}), encoding="utf-8")
            old = lock_path.stat().st_mtime - 10
            os.utime(lock_path, (old, old))

            with omission_actions.extraction_operation_lock(out, operation="targeted"):
                self.assertTrue(lock_path.exists())

            self.assertFalse(lock_path.exists())

    def test_supplement_hash_invalidates_functional_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            before = desktop_tasks.stage_input_fingerprint(out, "functional-synthesis", route="stub")
            _write_jsonl(out / omission_actions.AI_SUPPLEMENTS, [{"supplement_id": "SUP-1"}])
            after = desktop_tasks.stage_input_fingerprint(out, "functional-synthesis", route="stub")

        self.assertNotEqual(before, after)
        self.assertIn(omission_actions.AI_SUPPLEMENT_VERSION, desktop_tasks.stage_producer("ai-extract"))


class OmissionEndpointTests(unittest.TestCase):
    def _handler(self, out: Path, payload: dict) -> tuple[api_server.RequirementAPIHandler, list]:
        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.output_dir = out
        handler.read_json_body = lambda: payload
        responses: list = []
        handler.send_json = lambda body, status=200: responses.append((status, body))
        return handler, responses

    def test_reextract_maps_operation_conflict_to_409(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            handler, responses = self._handler(Path(td), {
                "block_id": "B1",
                "omission_id": "OMI-test",
                "source_fingerprint": "fingerprint",
            })
            with mock.patch.object(
                omission_actions,
                "targeted_reextract",
                side_effect=omission_actions.OmissionConflictError("busy"),
            ), mock.patch.object(
                omission_actions, "current_omission_candidate_ids", return_value={"B1"}
            ):
                handler.handle_omission_reextract()

        self.assertEqual(responses[0][0], 409)
        self.assertTrue(responses[0][1]["retryable"])
        self.assertTrue(responses[0][1]["needs_reconfirmation"])

    def test_reextract_maps_llm_failure_to_502(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            handler, responses = self._handler(Path(td), {
                "block_id": "B1",
                "omission_id": "OMI-test",
                "source_fingerprint": "fingerprint",
            })
            with mock.patch.object(
                omission_actions,
                "targeted_reextract",
                side_effect=LLMConnectionError("endpoint unavailable"),
            ), mock.patch.object(
                omission_actions, "current_omission_candidate_ids", return_value={"B1"}
            ):
                handler.handle_omission_reextract()

        self.assertEqual(responses[0][0], 502)
        self.assertTrue(responses[0][1]["retryable"])

    def test_omission_write_endpoints_require_identity_and_source_fingerprint(self) -> None:
        cases = (
            ("handle_omission_action", "apply_omission_action"),
            ("handle_omission_reextract", "targeted_reextract"),
        )
        for handler_name, implementation_name in cases:
            with self.subTest(endpoint=handler_name), tempfile.TemporaryDirectory() as td:
                handler, responses = self._handler(Path(td), {"block_id": "B1"})
                with mock.patch.object(omission_actions, implementation_name) as implementation:
                    getattr(handler, handler_name)()

                self.assertEqual(responses[0][0], 409)
                self.assertTrue(responses[0][1]["needs_reconfirmation"])
                implementation.assert_not_called()


class ClaimFocusEvidenceTests(unittest.TestCase):
    """P0-3 复审：上下文与可引用证据分离；矩阵 marker 三者同现才成立。"""

    @staticmethod
    def _section() -> dict:
        return {
            "section_id": "s1",
            "heading": "S",
            "text": (
                "The meter shall authenticate all clients. "
                "The meter shall log authentication failures."
            ),
            "block_ids": ["B1"],
            "source_blocks": [{
                "block_id": "B1",
                "text": (
                    "The meter shall authenticate all clients. "
                    "The meter shall log authentication failures."
                ),
            }],
        }

    def test_marker_cell_focus_builds_composite_fact(self) -> None:
        focus = {
            "kind": "table_cell",
            "table_cell_id": "TBL-000001-R000002-C000002",
            "table_title": "Optical communication interface capabilities",
            "header_path": ["Mode A"],
            "row_header_context": ["Feature=Encryption"],
            "text": "X",
        }
        evidence = omission_actions._claim_focus_evidence(Path("."), focus)
        roles = [entry["role"] for entry in evidence]
        self.assertEqual(roles.count("prompt_context"), 3)
        title_context = next(
            entry for entry in evidence
            if entry.get("context_kind") == "table_title"
        )
        self.assertEqual(
            title_context["text"], "Optical communication interface capabilities"
        )
        composite = next(
            entry for entry in evidence if entry["role"] == "composite_matrix_fact"
        )
        self.assertEqual(composite["subject"], "Feature=Encryption")
        self.assertEqual(composite["dimension"], "Mode A")
        self.assertEqual(composite["marker"], "X")

    def test_sentence_cell_focus_separates_context_from_evidence(self) -> None:
        focus = {
            "kind": "table_cell",
            "table_cell_id": "TBL-000001-R000002-C000002",
            "table_title": "Optical communication interface capabilities",
            "header_path": ["Behavior"],
            "row_header_context": ["Feature=Encryption"],
            "text": "The meter shall authenticate all clients.",
        }
        evidence = omission_actions._claim_focus_evidence(Path("."), focus)
        verbatim = [
            entry for entry in evidence if entry["role"] == "verbatim_evidence"
        ]
        context = [entry for entry in evidence if entry["role"] == "prompt_context"]
        self.assertEqual([entry["text"] for entry in verbatim],
                         ["The meter shall authenticate all clients."])
        self.assertTrue(context)
        self.assertFalse(
            any(entry["role"] == "composite_matrix_fact" for entry in evidence)
        )

    def test_table_title_is_prompt_context_but_never_quote_evidence(self) -> None:
        title = "Optical communication interface capabilities"
        evidence = [
            {
                "role": "prompt_context",
                "context_kind": "table_title",
                "text": title,
            },
            {
                "role": "composite_matrix_fact",
                "text": "X",
                "subject": "Interface=Data access",
                "dimension": "GET",
                "marker": "X",
            },
        ]
        prompts: list[str] = []

        def chat(_system: str, user: str) -> dict:
            prompts.append(user)
            return {"requirements": [], "supplements": []}

        ai_extract.critique_section(
            self._section(),
            [],
            chat,
            strict_focus=True,
            focus_evidence=evidence,
        )
        self.assertEqual(len(prompts), 1)
        self.assertIn(f"表标题：{title}", prompts[0])
        self.assertIn("消解证据中省略的产品/接口适用范围", prompts[0])
        self.assertIn("禁止作为 source_quote", prompts[0])

        title_as_quote = {
            "title": "Data access GET",
            "description": (
                f"{title}: Data access shall support GET using matrix marker X."
            ),
            "source_quote": title,
        }
        self.assertEqual(
            self._critique({"requirements": [title_as_quote]}, evidence), []
        )

    def _critique(self, payload: dict, evidence: list[dict]) -> list[dict]:
        chat = lambda system, user: payload  # noqa: E731
        extra, _supplements = ai_extract.critique_section(
            self._section(),
            [],
            chat,
            strict_focus=True,
            focus_evidence=evidence,
        )
        return extra

    def test_context_echo_does_not_pass_quote_gate(self) -> None:
        # P0-3 复现：模型回显定位上下文（Feature=Encryption）+ 编造描述——
        # v1 闸门放行，v2 拒收（上下文不是可引用证据）
        evidence = [
            {"role": "prompt_context", "text": "Feature=Encryption"},
            {"role": "verbatim_evidence",
             "text": "The meter shall authenticate all clients."},
        ]
        payload = {"requirements": [{
            "title": "加密特性",
            "description": "Feature=Encryption 应支持企业级密钥轮换与双向证书吊销。",
            "source_quote": "Feature=Encryption",
        }]}
        self.assertEqual(self._critique(payload, evidence), [])

    def test_verbatim_quote_passes_quote_gate(self) -> None:
        evidence = [
            {"role": "prompt_context", "text": "Feature=Encryption"},
            {"role": "verbatim_evidence",
             "text": "The meter shall authenticate all clients."},
        ]
        payload = {"requirements": [{
            "title": "客户端认证",
            "description": "The meter shall authenticate all clients.",
            "source_quote": "The meter shall authenticate all clients.",
        }]}
        self.assertEqual(len(self._critique(payload, evidence)), 1)

    def test_composite_matrix_fact_requires_subject_dimension_marker(self) -> None:
        composite = {
            "role": "composite_matrix_fact",
            "text": "X",
            "subject": "Feature=Encryption",
            "dimension": '"GET"',
            "marker": "X",
        }
        base = {
            "title": "Encryption shall support GET.",
            "description": "Encryption shall support GET (matrix marker X).",
            "source_quote": "X",
        }
        self.assertEqual(len(self._critique({"requirements": [base]}, [composite])), 1)
        # 缺维度 → 拒收（三者同现，不接受任一片段）
        missing_dimension = {**base, "description": "Encryption is supported (X).",
                             "title": "Encryption support X"}
        self.assertEqual(
            self._critique({"requirements": [missing_dimension]}, [composite]), []
        )
        # 单字符 marker 词边界：X509 不冒充 X（scope guard 无 quote 字段兜底）
        fake_marker_row = [{
            "source_block_ids": ["B1"],
            "description": "Encryption shall support GET via X509.",
        }]
        with self.assertRaises(omission_actions.OmissionNoResultError):
            omission_actions._claim_output_scope_guard(
                fake_marker_row,
                block_id="B1",
                section_block_ids={"B1"},
                focus_evidence=[composite],
            )

    def test_scope_guard_rejects_context_only_binding(self) -> None:
        evidence = [
            {"role": "prompt_context", "text": "Feature=Encryption"},
            {"role": "verbatim_evidence",
             "text": "The meter shall authenticate all clients."},
        ]
        context_only = [{
            "source_block_ids": ["B1"],
            "description": "Feature=Encryption 需要企业级密钥轮换。",
        }]
        with self.assertRaises(omission_actions.OmissionNoResultError):
            omission_actions._claim_output_scope_guard(
                context_only,
                block_id="B1",
                section_block_ids={"B1"},
                focus_evidence=evidence,
            )
        bound = [{
            "source_block_ids": ["B1"],
            "description": "The meter shall authenticate all clients.",
        }]
        omission_actions._claim_output_scope_guard(
            bound,
            block_id="B1",
            section_block_ids={"B1"},
            focus_evidence=evidence,
        )

    def test_scope_guard_composite_triple(self) -> None:
        composite = {
            "role": "composite_matrix_fact",
            "text": "X",
            "subject": "Feature=Encryption",
            "dimension": '"GET"',
            "marker": "X",
        }
        bound = [{
            "source_block_ids": ["B1"],
            "description": "Encryption shall support GET (X).",
        }]
        omission_actions._claim_output_scope_guard(
            bound,
            block_id="B1",
            section_block_ids={"B1"},
            focus_evidence=[composite],
        )
        missing_marker = [{
            "source_block_ids": ["B1"],
            "description": "Encryption shall support GET.",
        }]
        with self.assertRaises(omission_actions.OmissionNoResultError):
            omission_actions._claim_output_scope_guard(
                missing_marker,
                block_id="B1",
                section_block_ids={"B1"},
                focus_evidence=[composite],
            )


if __name__ == "__main__":
    unittest.main()
