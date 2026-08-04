from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import api_server
from atomize import build_table_artifacts
from output_writer import write_jsonl
from io_utils import read_jsonl
from requirement_kb import KnowledgeRepository
from result_package import governed_artifact_path, initialize_result_package, resolve_analysis_root
from table_dispositions import build_table_cell_dispositions
from table_review_state import (
    TableReviewConflict,
    apply_table_review_decision,
    build_table_review_payload,
    table_evidence_fingerprint,
)


KB = KnowledgeRepository.from_paths([])


def _seed(root: Path) -> tuple[Path, list[dict], list[dict]]:
    source = root / "source.docx"
    source.write_bytes(b"synthetic")
    initialize_result_package(root, input_path=source, requested_stages=["atomize"])
    analysis = resolve_analysis_root(root)
    block, items, cells = build_table_artifacts(
        [
            ["Configurable auxiliary output", ""],
            ["Mode", "Value"],
            ["Pulse", "Enabled"],
        ],
        table_id="TBL-000001",
        block_id="BLK-000001",
        order=1,
        table_title="Auxiliary output",
        section_path=["5 Requirements"],
        knowledge_bases=KB,
        merge_ranges=[],
    )
    dispositions = build_table_cell_dispositions([block], cells)
    write_jsonl(governed_artifact_path(analysis, "blocks.jsonl"), [block])
    write_jsonl(governed_artifact_path(analysis, "table_items.jsonl"), items)
    write_jsonl(governed_artifact_path(analysis, "table_cell_items.jsonl"), cells)
    write_jsonl(
        governed_artifact_path(analysis, "table_cell_dispositions.jsonl"),
        dispositions,
    )
    return analysis, cells, dispositions


class TableReviewStateTests(unittest.TestCase):
    def test_payload_exposes_summary_cells_and_evidence_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, cells, dispositions = _seed(Path(tmp))

            payload = build_table_review_payload(analysis)

            self.assertEqual(payload["schema"], "table-review-view/v1")
            self.assertEqual(len(payload["tables"]), 1)
            table = payload["tables"][0]
            self.assertEqual(table["table_id"], "TBL-000001")
            self.assertEqual(table["structure_review_status"], "pending")
            self.assertEqual(table["cell_count"], len(cells))
            self.assertEqual(
                table["evidence_fingerprint"],
                table_evidence_fingerprint("TBL-000001", dispositions),
            )

    def test_human_decision_updates_only_the_selected_table_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, _cells, dispositions = _seed(Path(tmp))
            fingerprint = table_evidence_fingerprint("TBL-000001", dispositions)
            review_cell = next(row for row in dispositions if row["disposition"] == "review")

            result = apply_table_review_decision(
                analysis,
                table_id="TBL-000001",
                expected_evidence_fingerprint=fingerprint,
                role_mapping={
                    review_cell["cell_id"]: {
                        "role": "row_header",
                        "disposition": "context",
                    }
                },
                actor="reviewer",
                reason="Confirmed as a row label",
            )

            self.assertEqual(result["structure_review_status"], "ready")
            self.assertEqual(result["recomputed_artifacts"], ["table_cell_dispositions.jsonl"])
            payload = build_table_review_payload(analysis)
            updated = next(
                cell for cell in payload["tables"][0]["cells"]
                if cell["cell_id"] == review_cell["cell_id"]
            )
            self.assertEqual(updated["decision_source"], "human")
            self.assertEqual(updated["role"], "row_header")
            self.assertEqual(updated["disposition"], "context")
            self.assertTrue(
                governed_artifact_path(
                    analysis, "table_review_states.jsonl", category="state"
                ).is_file()
            )

    def test_stale_evidence_fingerprint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, _cells, dispositions = _seed(Path(tmp))
            review_cell = next(row for row in dispositions if row["disposition"] == "review")

            with self.assertRaises(TableReviewConflict):
                apply_table_review_decision(
                    analysis,
                    table_id="TBL-000001",
                    expected_evidence_fingerprint="stale",
                    role_mapping={
                        review_cell["cell_id"]: {
                            "role": "row_header",
                            "disposition": "context",
                        }
                    },
                    actor="reviewer",
                    reason="stale",
                )

    def test_ready_decision_locally_regenerates_only_promoted_table_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, _cells, dispositions = _seed(Path(tmp))
            write_jsonl(analysis / "ai_requirements.jsonl", [])
            fingerprint = table_evidence_fingerprint("TBL-000001", dispositions)
            review_cell = next(row for row in dispositions if row["disposition"] == "review")

            result = apply_table_review_decision(
                analysis,
                table_id="TBL-000001",
                expected_evidence_fingerprint=fingerprint,
                role_mapping={
                    review_cell["cell_id"]: {
                        "role": "data",
                        "disposition": "target",
                    }
                },
                actor="reviewer",
                reason="Confirmed as a normative table target",
            )

            self.assertEqual(result["structure_review_status"], "ready")
            self.assertEqual(
                result["recomputed_artifacts"],
                [
                    "table_cell_dispositions.jsonl",
                    "ai_requirements.jsonl",
                    "ai_requirements.meta.json",
                ],
            )
            requirements = read_jsonl(analysis / "ai_requirements.jsonl")
            self.assertEqual(len(requirements), 1)
            self.assertEqual(requirements[0]["source_cell_ids"], [review_cell["cell_id"]])
            self.assertEqual(requirements[0]["source_mapping"], "table_review_deterministic")

    def test_api_get_and_post_use_table_review_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis, _cells, dispositions = _seed(Path(tmp))
            review_cell = next(row for row in dispositions if row["disposition"] == "review")

            get_handler = object.__new__(api_server.RequirementAPIHandler)
            get_handler.path = "/table-reviews"
            get_handler.headers = {}
            get_handler.allowed_origins = set()
            get_handler.local_token = ""
            get_handler.output_dir = analysis
            get_handler.package_root = Path(tmp)
            get_handler._refresh_analysis_root = lambda: None
            get_responses = []
            get_handler.send_json = lambda body, status=200: get_responses.append((status, body))
            get_handler.do_GET()

            self.assertEqual(get_responses[0][0], 200)
            self.assertEqual(get_responses[0][1]["tables"][0]["table_id"], "TBL-000001")

            post_handler = object.__new__(api_server.RequirementAPIHandler)
            post_handler.output_dir = analysis
            post_handler.read_json_body = lambda: {
                "table_id": "TBL-000001",
                "expected_evidence_fingerprint": table_evidence_fingerprint(
                    "TBL-000001", dispositions
                ),
                "role_mapping": {
                    review_cell["cell_id"]: {
                        "role": "row_header",
                        "disposition": "context",
                    }
                },
                "actor": "reviewer",
                "reason": "Confirmed",
            }
            post_responses = []
            post_handler.send_json = lambda body, status=200: post_responses.append((status, body))
            post_handler.handle_table_review_action()

            self.assertEqual(post_responses[0][0], 200)
            self.assertEqual(post_responses[0][1]["structure_review_status"], "ready")


if __name__ == "__main__":
    unittest.main()
