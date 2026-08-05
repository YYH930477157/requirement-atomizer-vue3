from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import claim_artifacts
import claim_catalog
import claim_review_actions
import claim_views
import ai_extract
from atomize import build_table_artifacts
from output_writer import write_jsonl
from requirement_kb import KnowledgeRepository
from table_dispositions import build_table_cell_dispositions
from table_claim_authority import (
    TABLE_CLAIM_AUTHORITY_VERSION,
    build_table_claim_authority_projection,
    project_table_dispositions,
)
from table_review_state import (
    apply_table_review_decision,
    build_table_review_payload,
)
from tests.test_claim_artifacts import _publish, _requirement, _shadow


KB = KnowledgeRepository.from_paths([])


def _artifacts(
    matrix: list[list[str]],
    *,
    parse_incomplete: bool = False,
) -> tuple[dict, list[dict], list[dict], list[dict]]:
    block, items, cells = build_table_artifacts(
        matrix,
        table_id="TBL-000001",
        block_id="BLK-000001",
        order=1,
        table_title="Synthetic table",
        section_path=["5 Requirements"],
        knowledge_bases=KB,
        merge_ranges=[],
        parse_incomplete=parse_incomplete,
        parse_incomplete_reason=(
            {"code": "row_width_conflict", "details": ["synthetic"]}
            if parse_incomplete
            else None
        ),
    )
    dispositions = build_table_cell_dispositions([block], cells)
    return block, items, cells, dispositions


def _candidate_cell_ids(build: dict) -> set[str]:
    return {
        str((row.get("locator") or {}).get("table_cell_id") or "")
        for row in build.get("catalog") or []
        if row.get("eligibility") == "excluded"
        and isinstance(row.get("exclusion"), dict)
    }


class ClaimCandidateCoverageTests(unittest.TestCase):
    def test_parse_incomplete_review_cells_have_exact_claim_candidates(self) -> None:
        block, items, cells, dispositions = _artifacts(
            [["Name", "Value"], ["Voltage", "230 V"]],
            parse_incomplete=True,
        )

        build = claim_catalog.build_claim_catalog(
            [block],
            items,
            table_cell_items=cells,
        )

        expected = {
            row["cell_id"] for row in dispositions if row["disposition"] == "review"
        }
        self.assertEqual(_candidate_cell_ids(build), expected)
        self.assertEqual(
            {
                row["exclusion"]["reason"]
                for row in build["catalog"]
                if row.get("eligibility") == "excluded"
            },
            {"parse_incomplete_table_cell"},
        )

    def test_normative_context_conflict_is_not_also_published_as_claim(self) -> None:
        block, items, cells, dispositions = _artifacts([
            ["Name", "Requirement"],
            ["Logger", "The meter shall log events."],
        ])
        normative = next(
            cell for cell in cells if "shall log events" in str(cell.get("text") or "")
        )
        normative["leaf_kind"] = "context"
        normative["structural_role"] = "header"
        plan = block["leaf_plan"]
        plan["cell_leaves"] = [
            cell_id for cell_id in plan.get("cell_leaves") or []
            if cell_id != normative["cell_id"]
        ]
        plan.setdefault("context_cells", []).append(normative["cell_id"])

        build = claim_catalog.build_claim_catalog(
            [block],
            items,
            table_cell_items=cells,
        )

        rows = [
            row for row in build["catalog"]
            if (row.get("locator") or {}).get("table_cell_id") == normative["cell_id"]
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["eligibility"], "excluded")
        self.assertEqual(
            rows[0]["exclusion"]["reason"], "normative_context_conflict"
        )


class ClaimAuthorityProjectionTests(unittest.TestCase):
    def test_projection_distinguishes_pending_excluded_promoted_and_inflight(self) -> None:
        generation = {
            "document_generation_id": "sha256:" + "1" * 64,
            "catalog_generation_id": "sha256:" + "2" * 64,
        }

        def candidate(index: int) -> dict:
            cell_id = f"TBL-000001-R000002-C{index:06d}"
            return {
                "claim_id": f"CLM-{index:016x}",
                "claim_hash": "sha256:" + str(index) * 64,
                "eligibility": "excluded",
                "locator": {"table_cell_id": cell_id},
                "exclusion": {
                    "reason": "ambiguous_table_structure",
                    "evidence": {"table_cell_id": cell_id},
                },
            }

        pending, excluded, promoted, inflight = [candidate(index) for index in range(1, 5)]
        promoted["eligibility"] = "claim"
        promoted["exclusion"] = None
        decisions = [{
            "claim_id": excluded["claim_id"],
            "claim_hash": excluded["claim_hash"],
            **generation,
            "decision_id": "CSCD-0000000000000002",
            "decision_hash": "sha256:" + "d" * 64,
            "decision": "confirm_exclusion",
            "original_exclusion": {
                "reason": "ambiguous_table_structure",
                "evidence": {
                    "table_cell_id": excluded["locator"]["table_cell_id"]
                },
            },
        }]
        overrides = [{
            "claim_id": promoted["claim_id"],
            "claim_hash": promoted["claim_hash"],
            "override_id": "CSO-0000000000000003",
            "override_hash": "sha256:" + "e" * 64,
            "original_exclusion": {
                "reason": "ambiguous_table_structure",
                "evidence": {
                    "table_cell_id": promoted["locator"]["table_cell_id"]
                },
            },
        }]
        pending_operations = {
            inflight["claim_id"]: {"operation_id": "CSOP-0000000000000004"}
        }

        projection = build_table_claim_authority_projection(
            catalog=[pending, excluded, promoted, inflight],
            generation_meta=generation,
            candidate_decisions=decisions,
            structural_overrides=overrides,
            pending_operations=pending_operations,
        )

        self.assertEqual(
            projection[pending["locator"]["table_cell_id"]]["status"],
            "pending_review",
        )
        self.assertEqual(
            projection[excluded["locator"]["table_cell_id"]]["status"],
            "confirmed_excluded",
        )
        self.assertEqual(
            projection[promoted["locator"]["table_cell_id"]]["status"],
            "promoted",
        )
        self.assertEqual(
            projection[inflight["locator"]["table_cell_id"]]["status"],
            "promotion_pending",
        )

    def test_claim_projection_replaces_only_review_dispositions(self) -> None:
        cell_id = "TBL-000001-R000002-C000002"
        cells = [{"cell_id": cell_id, "leaf_kind": "cell"}]
        dispositions = [{
            "cell_id": cell_id,
            "table_id": "TBL-000001",
            "disposition": "review",
            "confidence": "medium",
            "evidence": ["ambiguous_structure_cell"],
            "decision_source": "deterministic",
        }]
        projection = {
            cell_id: {
                "status": "promoted",
                "claim_id": "CLM-0000000000000001",
                "override_id": "CSO-0000000000000001",
            }
        }

        projected = project_table_dispositions(dispositions, cells, projection)

        self.assertEqual(projected[0]["disposition"], "target")
        self.assertEqual(projected[0]["decision_source"], "claim_authority")
        self.assertEqual(
            projected[0]["decision_version"], TABLE_CLAIM_AUTHORITY_VERSION
        )
        self.assertEqual(
            projected[0]["claim_authority"]["status"], "promoted"
        )

    def test_table_confirmation_updates_claim_pending_and_table_ready_together(self) -> None:
        block, items, cells, dispositions = _artifacts([
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "blocks.jsonl", [block])
            write_jsonl(root / "table_items.jsonl", items)
            write_jsonl(root / "table_cell_items.jsonl", cells)
            write_jsonl(root / "table_cell_dispositions.jsonl", dispositions)
            build = claim_catalog.build_catalog_from_directory(root)
            _publish(root, build, _shadow(build))
            claim_review_actions.fold_effective_ledger(
                root, actor_trigger="table-authority-e2e-seed"
            )
            before = claim_views.build_claim_view(root, "metrics")
            self.assertEqual(before["structural_review_pending_count"], 1)
            table = build_table_review_payload(root)["tables"][0]
            review_cell = next(
                cell for cell in table["cells"] if cell["disposition"] == "review"
            )

            result = apply_table_review_decision(
                root,
                table_id=table["table_id"],
                expected_evidence_fingerprint=table["evidence_fingerprint"],
                role_mapping={
                    review_cell["cell_id"]: {
                        "role": review_cell["role"],
                        "disposition": "excluded",
                    }
                },
                actor="expert:e2e",
                reason="Confirmed as structural context",
            )

            after_table = build_table_review_payload(root)["tables"][0]
            after_metrics = claim_views.build_claim_view(root, "metrics")
            self.assertEqual(result["structure_review_status"], "ready")
            self.assertEqual(after_table["structure_review_status"], "ready")
            self.assertEqual(after_metrics["structural_review_pending_count"], 0)
            projected = next(
                cell for cell in after_table["cells"]
                if cell["cell_id"] == review_cell["cell_id"]
            )
            self.assertEqual(projected["decision_source"], "claim_authority")
            self.assertEqual(projected["disposition"], "excluded")

    def test_table_promotion_rebuilds_claim_base_and_projects_promoted_cell(self) -> None:
        block, items, cells, dispositions = _artifacts([
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "blocks.jsonl", [block])
            write_jsonl(root / "table_items.jsonl", items)
            write_jsonl(root / "table_cell_items.jsonl", cells)
            write_jsonl(root / "table_cell_dispositions.jsonl", dispositions)
            build = claim_catalog.build_catalog_from_directory(root)
            write_jsonl(root / "ai_requirements.jsonl", [_requirement(build)])
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint=ai_extract.extraction_input_fingerprint(root),
            )
            claim_artifacts.publish_shadow_generation(
                root,
                build,
                _shadow(build),
                run_id="table-authority-promotion-seed",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            claim_review_actions.fold_effective_ledger(
                root, actor_trigger="table-authority-promotion-seed"
            )
            before_generation = build["meta"]["catalog_generation_id"]
            table = build_table_review_payload(root)["tables"][0]
            review_cell = next(
                cell for cell in table["cells"] if cell["disposition"] == "review"
            )

            def rebuild(root_dir: Path, **_kwargs) -> dict:
                rebuilt = claim_catalog.build_catalog_from_directory(root_dir)
                claim_artifacts.publish_shadow_generation(
                    root_dir,
                    rebuilt,
                    _shadow(rebuilt),
                    run_id="table-authority-promotion-rebuild",
                    requirements_sha256=claim_artifacts.file_sha256(
                        root_dir / "ai_requirements.jsonl"
                    ),
                )
                claim_review_actions.fold_effective_ledger(
                    root_dir,
                    actor_trigger="table-authority-promotion-rebuild",
                )
                return {"kind": "claim_shadow_refresh", "ledger_only": True}

            with patch("ai_extract.refresh_claim_shadow", side_effect=rebuild):
                result = apply_table_review_decision(
                    root,
                    table_id=table["table_id"],
                    expected_evidence_fingerprint=table["evidence_fingerprint"],
                    role_mapping={
                        review_cell["cell_id"]: {
                            "role": review_cell["role"],
                            "disposition": "target",
                        }
                    },
                    actor="expert:e2e",
                    reason="Confirmed as a requirement-bearing cell",
                )

            current = claim_artifacts.load_committed_effective_snapshot(root)
            after_table = build_table_review_payload(root)["tables"][0]
            after_metrics = claim_views.build_claim_view(root, "metrics")
            promoted = next(
                cell for cell in after_table["cells"]
                if cell["cell_id"] == review_cell["cell_id"]
            )
            self.assertEqual(result["structure_review_status"], "ready")
            self.assertNotEqual(
                current["generation_meta"]["catalog_generation_id"],
                before_generation,
            )
            self.assertEqual(after_metrics["structural_review_pending_count"], 0)
            self.assertEqual(promoted["decision_source"], "claim_authority")
            self.assertIn(promoted["disposition"], {"target", "composite"})


if __name__ == "__main__":
    unittest.main()
