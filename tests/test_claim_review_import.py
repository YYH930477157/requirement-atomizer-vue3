from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import claim_held_out
import claim_review_import


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "golden_sets" / "claim_ledger_v1"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
CLAIM_A = "CLM-" + "a" * 16


def _input_manifest() -> dict:
    return {
        "schema": "claim-shadow-acceptance-input/v3",
        "dataset_id": "review-import-test",
        "runs": [{
            "run_id": "run-1",
            "generation_run_id": "generation-1",
            "document_id": "document-1",
            "sequence": 1,
            "output_dir": "machine-local-output",
            "attempt_chain_id": HASH_A,
        }],
        "curation": {
            "human_review_status": "pending",
            "reviewed_by": "",
            "reviewed_at": "",
            "adjudications": [],
            "known_omissions": [{
                "run_id": "run-1",
                "claim_id": CLAIM_A,
                "claim_hash": HASH_A,
            }],
        },
    }


def _shadow_decision() -> dict:
    return {
        "run_id": "run-1",
        "claim_id": CLAIM_A,
        "claim_hash": HASH_A,
        "review_evidence_fingerprint": HASH_B,
        "ledger_resolution": "covered",
        "category": "semantic_positive",
        "verdict": "agree",
        "rationale": "",
    }


def _held_out_decision(item: dict) -> dict:
    return {
        "case_id": item["case_id"],
        "claim_id": item["claim_id"],
        "claim_hash": item["claim_hash"],
        "fixture_hash": item["fixture_hash"],
        "dimension_verdicts": {
            dimension: "agree"
            for dimension in claim_held_out.HELD_OUT_REVIEW_DIMENSIONS
        },
        "rationale": "The rebuilt claim and target preserve every reviewed dimension.",
    }


def _decisions(held_out_item: dict) -> dict:
    return {
        "schema": "claim-shadow-review-decisions/v3",
        "dataset_id": "review-import-test",
        "reviewed_by": "independent-reviewer",
        "reviewed_at": "2026-07-28T08:00:00Z",
        "shadow_adjudications": [_shadow_decision()],
        "golden_held_out": {
            "dataset_id": "claim_ledger_v1",
            "dataset_version": "claim-ledger-golden-v4",
            "adjudications": [_held_out_decision(held_out_item)],
        },
    }


def _packet(decisions: dict) -> dict:
    template = copy.deepcopy(decisions)
    template["reviewed_by"] = ""
    template["reviewed_at"] = ""
    for row in template["shadow_adjudications"]:
        row["verdict"] = ""
        row["rationale"] = ""
    for row in template["golden_held_out"]["adjudications"]:
        row["dimension_verdicts"] = {
            key: "" for key in row["dimension_verdicts"]
        }
        row["rationale"] = ""
    return {"decision_template": template}


class ClaimReviewImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.golden = self.root / "golden"
        shutil.copytree(GOLDEN_DIR, self.golden)
        manifest_path = self.golden / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["curation"].update({
            "human_review_status": "pending",
            "reviewed_by": "",
            "reviewed_at": "",
            "held_out_adjudications": [],
        })
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.held_out = claim_held_out.load_golden_held_out(self.golden)
        self.item = self.held_out["review_items"][0]
        self.input_path = self.root / "pending.json"
        self.decisions_path = self.root / "decisions.json"
        self.output_path = self.root / "reviewed.json"
        self.input_path.write_text(
            json.dumps(_input_manifest()),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        for root in claim_review_import._review_import_lock_roots(
            (self.golden / "manifest.json").resolve(),
            self.output_path.resolve(),
        ):
            shutil.rmtree(root, ignore_errors=True)
        self.tmp.cleanup()

    def _write_decisions(self, payload: dict | None = None) -> dict:
        value = copy.deepcopy(payload or _decisions(self.item))
        self.decisions_path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def _import(self, payload: dict | None = None) -> dict:
        decisions = self._write_decisions(payload)
        with patch(
            "claim_review_import.build_review_packet",
            return_value=_packet(decisions),
        ):
            return claim_review_import.import_review_decisions(
                self.input_path,
                self.decisions_path,
                self.output_path,
                self.golden / "manifest.json",
            )

    def test_import_writes_reviewed_input_and_authoritative_golden_manifest(self) -> None:
        result = self._import()

        reviewed = json.loads(self.output_path.read_text(encoding="utf-8"))
        manifest = json.loads(
            (self.golden / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(reviewed["curation"]["human_review_status"], "reviewed")
        self.assertEqual(len(reviewed["curation"]["adjudications"]), 1)
        self.assertEqual(manifest["curation"]["human_review_status"], "reviewed")
        self.assertEqual(len(manifest["curation"]["held_out_adjudications"]), 1)
        self.assertEqual(
            claim_held_out.summarize_held_out_review(
                claim_held_out.load_golden_held_out(self.golden)
            )["evidence_status"],
            "complete",
        )
        self.assertEqual(result["held_out_evidence_status"], "complete")

    def test_import_is_idempotent_for_the_same_existing_output(self) -> None:
        first = self._import()
        first_output = self.output_path.read_bytes()
        second = self._import()

        self.assertEqual(first_output, self.output_path.read_bytes())
        self.assertEqual(first["reviewed_by"], second["reviewed_by"])

    def test_import_accepts_a_bound_disagreement_but_reports_not_approved(self) -> None:
        decisions = _decisions(self.item)
        decisions["golden_held_out"]["adjudications"][0][
            "dimension_verdicts"
        ]["coverage"] = "disagree"
        decisions["golden_held_out"]["adjudications"][0][
            "rationale"
        ] = "Coverage does not preserve the expected obligation."
        result = self._import(decisions)
        self.assertEqual(result["held_out_evidence_status"], "not_approved")

    def test_load_rejects_review_time_without_timezone(self) -> None:
        decisions = self._write_decisions()
        decisions["reviewed_at"] = "2026-07-28T08:00:00"
        self.decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
        with self.assertRaisesRegex(claim_review_import.ReviewImportError, "timezone"):
            claim_review_import.load_review_decisions(self.decisions_path)

    def test_import_rejects_stale_shadow_binding_before_writes(self) -> None:
        decisions = _decisions(self.item)
        packet = _packet(decisions)
        decisions["shadow_adjudications"][0]["review_evidence_fingerprint"] = HASH_A
        self._write_decisions(decisions)
        with (
            patch("claim_review_import.build_review_packet", return_value=packet),
            self.assertRaisesRegex(claim_review_import.ReviewImportError, "stale"),
        ):
            claim_review_import.import_review_decisions(
                self.input_path,
                self.decisions_path,
                self.output_path,
                self.golden / "manifest.json",
            )
        self.assertFalse(self.output_path.exists())
        self.assertEqual(
            claim_held_out.load_golden_held_out(self.golden)["manifest"]["curation"][
                "human_review_status"
            ],
            "pending",
        )

    def test_import_rejects_disagreement_without_rationale(self) -> None:
        decisions = _decisions(self.item)
        decisions["shadow_adjudications"][0]["verdict"] = "disagree"
        with self.assertRaisesRegex(claim_review_import.ReviewImportError, "rationale"):
            self._import(decisions)

    def test_import_rejects_duplicate_shadow_adjudication(self) -> None:
        decisions = _decisions(self.item)
        decisions["shadow_adjudications"].append(
            copy.deepcopy(decisions["shadow_adjudications"][0])
        )
        packet = _packet(_decisions(self.item))
        self._write_decisions(decisions)
        with (
            patch("claim_review_import.build_review_packet", return_value=packet),
            self.assertRaisesRegex(claim_review_import.ReviewImportError, "duplicate"),
        ):
            claim_review_import.import_review_decisions(
                self.input_path,
                self.decisions_path,
                self.output_path,
                self.golden / "manifest.json",
            )

    def test_import_rejects_preparer_as_held_out_reviewer(self) -> None:
        decisions = _decisions(self.item)
        decisions["reviewed_by"] = self.held_out["manifest"]["curation"]["prepared_by"]
        with self.assertRaisesRegex(claim_review_import.ReviewImportError, "independent"):
            self._import(decisions)

    def test_import_does_not_overwrite_a_different_completed_output(self) -> None:
        self._import()
        first = self.output_path.read_bytes()
        decisions = _decisions(self.item)
        decisions["shadow_adjudications"][0]["verdict"] = "disagree"
        decisions["shadow_adjudications"][0]["rationale"] = "The target omits the role."
        with self.assertRaisesRegex(
            claim_review_import.ReviewImportError,
            "reviewed acceptance output.*different",
        ):
            self._import(decisions)
        self.assertEqual(first, self.output_path.read_bytes())

    def test_import_rejects_output_equal_to_decisions_before_writes(self) -> None:
        self._write_decisions()
        original = self.decisions_path.read_bytes()
        with self.assertRaisesRegex(claim_review_import.ReviewImportError, "decisions"):
            claim_review_import.import_review_decisions(
                self.input_path,
                self.decisions_path,
                self.decisions_path,
                self.golden / "manifest.json",
            )
        self.assertEqual(original, self.decisions_path.read_bytes())
        self.assertEqual(
            claim_held_out.load_golden_held_out(self.golden)["manifest"]["curation"][
                "human_review_status"
            ],
            "pending",
        )

    def test_import_rejects_output_inside_golden_corpus_before_writes(self) -> None:
        self._write_decisions()
        expected_path = self.golden / "expected.json"
        original = expected_path.read_bytes()
        with self.assertRaisesRegex(claim_review_import.ReviewImportError, "golden corpus"):
            claim_review_import.import_review_decisions(
                self.input_path,
                self.decisions_path,
                expected_path,
                self.golden / "manifest.json",
            )
        self.assertEqual(original, expected_path.read_bytes())

    def test_lock_roots_serialize_shared_manifest_or_shared_output(self) -> None:
        manifest_a = (self.golden / "manifest.json").resolve()
        manifest_b = (self.root / "other-golden" / "manifest.json").resolve()
        output_a = self.output_path.resolve()
        output_b = (self.root / "other-reviewed.json").resolve()

        same_manifest_a = set(claim_review_import._review_import_lock_roots(
            manifest_a, output_a
        ))
        same_manifest_b = set(claim_review_import._review_import_lock_roots(
            manifest_a, output_b
        ))
        same_output = set(claim_review_import._review_import_lock_roots(
            manifest_b, output_a
        ))
        self.assertIn(
            claim_review_import._review_import_lock_root(manifest_a),
            same_manifest_a & same_manifest_b,
        )
        self.assertIn(
            claim_review_import._review_import_lock_root(output_a),
            same_manifest_a & same_output,
        )

    def test_main_returns_machine_readable_input_error(self) -> None:
        stream = io.StringIO()
        with (
            patch(
                "claim_review_import.import_review_decisions",
                side_effect=claim_review_import.ReviewImportError("stale decisions"),
            ),
            redirect_stdout(stream),
        ):
            code = claim_review_import.main([
                "--input", str(self.input_path),
                "--decisions", str(self.decisions_path),
                "--output", str(self.output_path),
                "--golden-manifest", str(self.golden / "manifest.json"),
            ])
        payload = json.loads(stream.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "input_error")


if __name__ == "__main__":
    unittest.main()
