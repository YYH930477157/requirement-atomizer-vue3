from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_extract
from input_completeness import attach_input_completeness, read_ai_input_completeness


class InputCompletenessTests(unittest.TestCase):
    def _publish(
        self,
        root: Path,
        *,
        failed_sections: int = 0,
        failed_section_ids: list[str] | None = None,
        failed_section_block_ids: list[str] | None = None,
    ) -> None:
        (root / "blocks.jsonl").write_text(
            json.dumps({"block_id": "B1", "text": "The product shall work."}) + "\n",
            encoding="utf-8",
        )
        ai_extract.atomic_write_jsonl(
            root / ai_extract.AI_REQUIREMENTS,
            [{"ai_req_id": "AIR-1", "description": "The product shall work."}],
        )
        ai_extract.write_ai_requirements_metadata(
            root,
            failed_sections=failed_sections,
            failed_section_ids=failed_section_ids,
            failed_section_block_ids=failed_section_block_ids,
        )

    def test_complete_publication_is_bound_to_current_requirements_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._publish(root)

            result = read_ai_input_completeness(root)

            self.assertFalse(result["incomplete_inputs"])
            metadata = json.loads(
                (root / ai_extract.AI_REQUIREMENTS_META).read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["requirements_sha256"], result["requirements_sha256"])
            self.assertEqual(metadata["selected_snapshot"], "final")

    def test_failed_sections_propagate_from_one_deterministic_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._publish(
                root,
                failed_sections=1,
                failed_section_ids=["S2"],
                failed_section_block_ids=["B2"],
            )

            payload = attach_input_completeness({}, root)

            self.assertTrue(payload["incomplete_inputs"])
            self.assertEqual(payload["input_completeness"]["reasons"], ["failed_sections"])
            self.assertEqual(payload["input_completeness"]["failed_section_ids"], ["S2"])
            self.assertEqual(
                payload["input_completeness"]["failed_section_block_ids"], ["B2"]
            )

    def test_requirement_or_source_drift_is_not_propagated_as_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._publish(root)
            with (root / ai_extract.AI_REQUIREMENTS).open("ab") as handle:
                handle.write(b"{}\n")

            requirements_drift = read_ai_input_completeness(root)
            self.assertTrue(requirements_drift["incomplete_inputs"])
            self.assertIn("requirements_hash_mismatch", requirements_drift["reasons"])

            (root / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B2", "text": "Changed."}) + "\n",
                encoding="utf-8",
            )
            source_drift = read_ai_input_completeness(root)
            self.assertIn("source_input_mismatch", source_drift["reasons"])

    def test_missing_or_legacy_metadata_is_honestly_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blocks.jsonl").write_text("{}\n", encoding="utf-8")
            (root / ai_extract.AI_REQUIREMENTS).write_text("", encoding="utf-8")

            missing = read_ai_input_completeness(root)
            self.assertTrue(missing["incomplete_inputs"])
            self.assertIn("metadata_missing", missing["reasons"])

            (root / ai_extract.AI_REQUIREMENTS_META).write_text(
                json.dumps({"schema": "ai-requirements-final/v1"}),
                encoding="utf-8",
            )
            legacy = read_ai_input_completeness(root)
            self.assertIn("producer_lineage_mismatch", legacy["reasons"])
            self.assertIn("requirements_hash_missing", legacy["reasons"])


class DownstreamInputCompletenessTests(unittest.TestCase):
    def _seed_publication(self, root: Path, *, mode: str) -> None:
        source = "The product shall support configurable outputs."
        (root / "blocks.jsonl").write_text(
            json.dumps({
                "block_id": "B1",
                "order": 1,
                "type": "paragraph",
                "text": source,
                "section_path": ["4 Functions"],
                "requirement_like": True,
                "noise": False,
            }) + "\n",
            encoding="utf-8",
        )
        ai_extract.atomic_write_jsonl(
            root / ai_extract.AI_REQUIREMENTS,
            [{
                "ai_req_id": "AIR-1",
                "type": "behavior",
                "title": "Configurable outputs",
                "description": source,
                "source_quote": source,
                "source_block_ids": ["B1"],
                "module": "I/O",
                "status": "draft",
            }],
        )
        ai_extract.write_ai_requirements_metadata(
            root,
            failed_sections=1 if mode == "partial" else 0,
            failed_section_ids=["S2"] if mode == "partial" else [],
            failed_section_block_ids=["B2"] if mode == "partial" else [],
        )
        if mode == "lineage_mismatch":
            metadata_path = root / ai_extract.AI_REQUIREMENTS_META
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["producer_lineage"] = {"version": "stale-test-lineage"}
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        ai_extract.atomic_write_jsonl(root / "atomic_requirements.jsonl", [])
        ai_extract.atomic_write_jsonl(root / "table_items.jsonl", [])

    def _assert_incomplete(self, payload: dict, expected_reason: str) -> None:
        self.assertTrue(payload["incomplete_inputs"])
        self.assertIn(expected_reason, payload["input_completeness"]["reasons"])

    def _exercise_consumers(self, root: Path, *, expected_reason: str) -> None:
        import clarification_report
        import engineering_composer
        import functional_synthesis
        import requirements_analysis
        import template_writer

        synthesis_result = functional_synthesis.run_functional_synthesis(
            root, route="stub"
        )
        synthesis_payload = json.loads(
            (root / functional_synthesis.FUNCTIONAL_REQUIREMENTS).read_text(
                encoding="utf-8"
            )
        )
        self._assert_incomplete(synthesis_result, expected_reason)
        self._assert_incomplete(synthesis_payload, expected_reason)

        with patch(
            "requirements_analysis.write_software_requirements_xlsx",
            side_effect=lambda _items, path: path,
        ):
            analysis_result = requirements_analysis.run_requirements_analysis(
                root, route="stub"
            )
        analysis_payload = json.loads(
            (root / "engineering_analysis.json").read_text(encoding="utf-8")
        )
        compliance_payload = json.loads(
            (root / "compliance_items.json").read_text(encoding="utf-8")
        )
        self._assert_incomplete(analysis_result, expected_reason)
        self._assert_incomplete(analysis_payload, expected_reason)
        self._assert_incomplete(compliance_payload, expected_reason)

        template_path = root / "controlled-template.xlsx"
        with patch(
            "template_writer.append_analysis_to_template",
            return_value={"appended_total": 0, "workbook": "controlled-output.xlsx"},
        ):
            writer_result = template_writer.run_writer(root, template_path)
        writer_payload = json.loads(
            (root / template_writer.WRITER_REPORT).read_text(encoding="utf-8")
        )
        self._assert_incomplete(writer_result, expected_reason)
        self._assert_incomplete(writer_payload, expected_reason)

        requirements = ai_extract.read_jsonl(root / ai_extract.AI_REQUIREMENTS)
        with (
            patch("ai_extract.load_or_build_deterministic", return_value=[]),
            patch(
                "ai_extract.build_skill_doc",
                return_value={"analysis": {"total_count": 1}, "requirements": []},
            ),
            patch(
                "meter_profile.infer_meter_profile",
                return_value={"meter_type": "multi", "target_standards": []},
            ),
        ):
            merged = ai_extract.build_merged_doc(
                root,
                requirements,
                source="controlled-fixture",
                extracted_at="2026-07-29T00:00:00",
            )
        self._assert_incomplete(merged, expected_reason)
        with patch("spec_excel.write_xlsx"):
            ai_extract._write_merged_outputs(root, merged)
        merged_payload = json.loads(
            (root / "merged_spec_requirements.json").read_text(encoding="utf-8")
        )
        consistency_payload = json.loads(
            (root / "consistency_report.json").read_text(encoding="utf-8")
        )
        self._assert_incomplete(merged_payload, expected_reason)
        self._assert_incomplete(consistency_payload, expected_reason)

        with patch("clarification_report.write_xlsx"):
            clarification = clarification_report.run_report(root)
        clarification_payload = json.loads(
            (root / clarification_report.REPORT_JSON).read_text(encoding="utf-8")
        )
        self._assert_incomplete(clarification, expected_reason)
        self._assert_incomplete(clarification_payload, expected_reason)

        complete_projection = {
            "schema": "ai-input-completeness/v1",
            "version": "ai-input-completeness-v1",
            "incomplete_inputs": False,
            "reasons": [],
        }
        with (
            patch("clarification_report.write_xlsx"),
            patch(
                "input_completeness.read_ai_input_completeness",
                return_value=complete_projection,
            ),
        ):
            complete_clarification = clarification_report.run_report(root)
        self.assertEqual(
            clarification["readiness"],
            complete_clarification["readiness"],
            "input completeness is informational and must not alter readiness",
        )

        with (
            patch("engineering_composer.build_object_model", return_value={"counts": {}}),
            patch("engineering_composer._load_default_kb_entry_index", return_value={}),
            patch("engineering_composer._compose_dlms_objects", return_value=[]),
            patch("engineering_composer._compose_requirement_functions", return_value=[]),
            patch("engineering_composer._link_functions_to_objects"),
        ):
            composer_model = engineering_composer.compose_engineering_requirements(root)
        self._assert_incomplete(composer_model, expected_reason)
        engineering_composer.write_engineering_requirements(root, composer_model)
        composer_payload = json.loads(
            (
                root
                / engineering_composer.OUTPUT_DIR
                / "engineering_requirements.json"
            ).read_text(encoding="utf-8")
        )
        self._assert_incomplete(composer_payload, expected_reason)

    def test_partial_publication_propagates_through_every_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_publication(root, mode="partial")

            self._exercise_consumers(root, expected_reason="failed_sections")

    def test_lineage_mismatch_propagates_through_every_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_publication(root, mode="lineage_mismatch")

            self._exercise_consumers(
                root,
                expected_reason="producer_lineage_mismatch",
            )


if __name__ == "__main__":
    unittest.main()
