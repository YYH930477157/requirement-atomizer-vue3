from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from requirement_candidates import build_full_coverage_audit, classify_semantic_units


class RequirementCandidateTests(unittest.TestCase):
    def test_contents_in_body_text_does_not_switch_to_informational(self) -> None:
        units = [{
            "semantic_unit_id": "SU-1",
            "section_path": ["3.12 Data interface"],
            "text": "The interface shall expose the contents of all registers.",
            "source_block_ids": ["B1"],
        }]
        result = classify_semantic_units(
            units,
            source_blocks=[{
                "block_id": "B1",
                "type": "paragraph",
                "text": units[0]["text"],
                "doc_region": "body",
            }],
        )
        row = result["units"][0]
        self.assertEqual(row["region_role"], "normative_body")
        self.assertEqual(row["category"], "requirement_candidate")

    def test_normative_sentence_in_informational_region_is_reviewable(self) -> None:
        units = [{
            "semantic_unit_id": "SU-1",
            "section_path": ["1 Introduction"],
            "text": "The meter must retain the audit record.",
            "source_block_ids": ["B1"],
        }]
        result = classify_semantic_units(units, source_blocks=[{
            "block_id": "B1",
            "type": "paragraph",
            "text": units[0]["text"],
        }])
        row = result["units"][0]
        self.assertEqual(row["region_role"], "informational")
        self.assertEqual(row["category"], "needs_review")
        self.assertEqual(row["reason"], "normative_language_in_informational_region")

    def test_coverage_audit_keeps_normative_informational_exclusion_visible(self) -> None:
        units = [{
            "semantic_unit_id": "SU-1",
            "section_path": ["1 Introduction"],
            "text": "The meter must retain the audit record.",
            "source_block_ids": ["B1"],
        }]
        # Simulate a downstream classifier regression so the audit itself is
        # tested independently of the current reviewable-category behavior.
        candidates = {
            "units": [{
                "semantic_unit_id": "SU-1",
                "category": "context",
                "region_role": "informational",
            }]
        }
        audit = build_full_coverage_audit(units, candidates)
        self.assertEqual(audit["suspicious_excluded_units"], 1)
        self.assertEqual(audit["suspicious"][0]["region_role"], "informational")

    def test_front_matter_role_does_not_persist_after_numbered_section_path(self) -> None:
        units = [
            {"semantic_unit_id": "SU-1", "section_path": ["Introduction"],
             "text": "Introduction", "source_block_ids": ["B1"]},
            {"semantic_unit_id": "SU-2", "section_path": ["Introduction"],
             "text": "This section contains contents and background.", "source_block_ids": ["B2"]},
            {"semantic_unit_id": "SU-3", "section_path": ["3.12 Data interface"],
             "text": "3.12 Data interface", "source_block_ids": ["B3"]},
            {"semantic_unit_id": "SU-4", "section_path": ["3.12 Data interface"],
             "text": "The meter must retain the interface configuration.", "source_block_ids": ["B4"]},
        ]
        result = classify_semantic_units(units, source_blocks=[
            {"block_id": "B1", "type": "heading", "text": "Introduction"},
            {"block_id": "B2", "type": "paragraph", "text": units[1]["text"]},
            {"block_id": "B3", "type": "heading", "text": "3.12 Data interface"},
            {"block_id": "B4", "type": "paragraph", "text": units[3]["text"]},
        ])
        row = result["units"][-1]
        self.assertEqual(row["region_role"], "normative_body")
        self.assertEqual(row["category"], "requirement_candidate")

    def test_audit_suspicion_is_promoted_into_functional_scope(self) -> None:
        # Keep the fixture at the legacy root layout used by direct CLI calls;
        # governed_artifact_path resolves to this location without a marker.
        from functional_extract import run_functional_extract

        def clause(section_id: str, block_id: str, text: str) -> dict:
            return {"section_id": section_id, "section_path": [section_id],
                    "block_ids": [block_id], "text": text}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirement_candidates.json").write_text(json.dumps({
                "units": [{"category": "requirement_candidate", "source_block_ids": ["B1"]}],
            }), encoding="utf-8")
            (root / "requirement_coverage_audit.json").write_text(json.dumps({
                "suspicious": [{"source_block_ids": ["B2"], "reason": "constraint"}],
            }), encoding="utf-8")
            result = run_functional_extract(
                root,
                sections=[
                    clause("7.1", "B1", "The meter shall log events."),
                    clause("7.2", "B2", "Accuracy 0.5 percent."),
                    clause("7.3", "B3", "Background context."),
                ],
                route="stub",
            )
        self.assertEqual(result["candidate_filter"]["status"], "applied")
        self.assertEqual(result["candidate_filter"]["audit_promoted_block_count"], 1)
        self.assertEqual(result["candidate_filter"]["selected_section_count"], 2)


if __name__ == "__main__":
    unittest.main()
