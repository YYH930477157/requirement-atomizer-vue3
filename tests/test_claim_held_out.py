from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

import claim_held_out


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "golden_sets" / "claim_ledger_v1"


def _reviewed_dataset(*, verdict: str = "agree") -> dict:
    dataset = claim_held_out.load_golden_held_out()
    curation = dataset["manifest"]["curation"]
    dimension_value = "agree" if verdict == "agree" else verdict
    curation.update({
        "human_review_status": "reviewed",
        "reviewed_by": "independent-reviewer",
        "reviewed_at": "2026-07-27T12:00:00Z",
        "held_out_adjudications": [
            {
                "case_id": item["case_id"],
                "claim_id": item["claim_id"],
                "claim_hash": item["claim_hash"],
                "fixture_hash": item["fixture_hash"],
                "dimension_verdicts": {
                    dimension: dimension_value
                    for dimension in claim_held_out.HELD_OUT_REVIEW_DIMENSIONS
                },
                "rationale": (
                    "The seven review dimensions match the synthetic fixture."
                ),
            }
            for item in dataset["review_items"]
        ],
    })
    return dataset


class ClaimHeldOutTests(unittest.TestCase):
    def test_repository_manifest_has_a_consistent_review_state(self) -> None:
        schema = json.loads(
            claim_held_out.GOLDEN_MANIFEST_SCHEMA.read_text(encoding="utf-8")
        )
        dataset = claim_held_out.load_golden_held_out()
        Draft202012Validator(schema).validate(dataset["manifest"])

        summary = claim_held_out.summarize_held_out_review(dataset)
        self.assertEqual(summary["artifact_status"], "valid")
        self.assertEqual(summary["held_out_case_count"], 1)
        self.assertEqual(summary["held_out_claim_count"], 1)
        self.assertEqual(summary["historical_review_count"], 2)
        self.assertEqual(summary["historical_disagreement_count"], 2)
        self.assertEqual(summary["baseline_revision_count"], 2)

        review_status = dataset["manifest"]["curation"]["human_review_status"]
        if review_status == "pending":
            self.assertEqual(summary["evidence_status"], "pending")
            self.assertEqual(
                summary["missing_adjudication_count"],
                summary["held_out_claim_count"],
            )
        else:
            self.assertEqual(review_status, "reviewed")
            self.assertIn(summary["evidence_status"], {"complete", "not_approved"})
            self.assertEqual(summary["reviewed_claim_count"], 1)
            for field in (
                "missing_adjudication_count",
                "stale_adjudication_count",
                "duplicate_adjudication_count",
                "extra_adjudication_count",
                "invalid_adjudication_count",
            ):
                self.assertEqual(summary[field], 0)

    def test_complete_exact_review_is_accepted(self) -> None:
        dataset = _reviewed_dataset()
        summary = claim_held_out.summarize_held_out_review(dataset)
        self.assertEqual(summary["evidence_status"], "complete")
        self.assertEqual(summary["approved_claim_count"], 1)
        self.assertEqual(summary["reviewed_case_count"], 1)

    def test_stale_claim_or_fixture_hash_is_invalid(self) -> None:
        for field in ("claim_hash", "fixture_hash"):
            with self.subTest(field=field):
                dataset = _reviewed_dataset()
                dataset["manifest"]["curation"]["held_out_adjudications"][0][field] = (
                    "sha256:" + "f" * 64
                )
                summary = claim_held_out.summarize_held_out_review(dataset)
                self.assertEqual(summary["evidence_status"], "invalid")
                self.assertEqual(summary["stale_adjudication_count"], 1)
                self.assertEqual(summary["reviewed_claim_count"], 0)

    def test_missing_duplicate_and_extra_reviews_are_invalid(self) -> None:
        missing = _reviewed_dataset()
        missing["manifest"]["curation"]["held_out_adjudications"] = []
        self.assertEqual(
            claim_held_out.summarize_held_out_review(missing)["evidence_status"],
            "invalid",
        )

        duplicate = _reviewed_dataset()
        rows = duplicate["manifest"]["curation"]["held_out_adjudications"]
        rows.append(copy.deepcopy(rows[0]))
        summary = claim_held_out.summarize_held_out_review(duplicate)
        self.assertEqual(summary["evidence_status"], "invalid")
        self.assertEqual(summary["duplicate_adjudication_count"], 1)

        extra = _reviewed_dataset()
        row = copy.deepcopy(
            extra["manifest"]["curation"]["held_out_adjudications"][0]
        )
        row["case_id"] = "unknown-held-out"
        extra["manifest"]["curation"]["held_out_adjudications"].append(row)
        summary = claim_held_out.summarize_held_out_review(extra)
        self.assertEqual(summary["evidence_status"], "invalid")
        self.assertEqual(summary["extra_adjudication_count"], 1)

    def test_disagree_and_followup_are_not_approved(self) -> None:
        for verdict in ("disagree", "needs_followup", "not_reviewed"):
            with self.subTest(verdict=verdict):
                summary = claim_held_out.summarize_held_out_review(
                    _reviewed_dataset(verdict=verdict)
                )
                self.assertEqual(summary["evidence_status"], "not_approved")

    def test_dimension_verdicts_are_exact_and_overall_verdict_is_derived(self) -> None:
        disagree = _reviewed_dataset()
        row = disagree["manifest"]["curation"]["held_out_adjudications"][0]
        row["dimension_verdicts"]["target_obligation_subject"] = "disagree"
        summary = claim_held_out.summarize_held_out_review(disagree)
        self.assertEqual(summary["evidence_status"], "not_approved")
        self.assertEqual(summary["disagreement_count"], 1)

        missing = _reviewed_dataset()
        row = missing["manifest"]["curation"]["held_out_adjudications"][0]
        row["dimension_verdicts"].pop("coverage")
        summary = claim_held_out.summarize_held_out_review(missing)
        self.assertEqual(summary["evidence_status"], "invalid")
        self.assertEqual(summary["invalid_adjudication_count"], 1)

        extra = _reviewed_dataset()
        row = extra["manifest"]["curation"]["held_out_adjudications"][0]
        row["dimension_verdicts"]["unexpected"] = "agree"
        summary = claim_held_out.summarize_held_out_review(extra)
        self.assertEqual(summary["evidence_status"], "invalid")

    def test_v2_rejection_is_hash_bound_and_replayable_history(self) -> None:
        dataset = claim_held_out.load_golden_held_out()
        self.assertEqual(len(dataset["baseline_revisions"]), 2)
        revision = dataset["baseline_revisions"][0]
        record = revision["record"]
        replayed = revision["review_items"]

        self.assertEqual(record["dataset_version"], "claim-ledger-golden-v2")
        self.assertEqual(record["declaration"]["partition"], "held_out")
        self.assertFalse(record["declaration"]["tuning_eligible"])
        self.assertEqual(
            record["adjudication"]["reviewed_by"],
            "YYH",
        )
        self.assertEqual(
            record["adjudication"]["reviewed_at"],
            "2026-07-27T15:16:00.000Z",
        )
        self.assertEqual(record["adjudication"]["overall_verdict"], "disagree")
        self.assertEqual(
            record["adjudication"]["dimension_verdicts"],
            {
                dimension: (
                    "disagree"
                    if dimension == "target_obligation_subject"
                    else "not_reviewed"
                )
                for dimension in claim_held_out.HELD_OUT_REVIEW_DIMENSIONS
            },
        )
        self.assertEqual(replayed[0]["claim_id"], "CLM-8465d2904bfc03ad")
        self.assertEqual(
            replayed[0]["claim_hash"],
            "sha256:8465d2904bfc03ad4fb6f86b491905cfac7a5e0ea386d4e53cc5a065c58d3c80",
        )
        self.assertEqual(
            replayed[0]["fixture_hash"],
            "sha256:e777a181d4e1e7f893c7ffa458621ac9d49d8c9731d08e7a19bf2991975e2940",
        )

        current_declaration = next(
            row for row in dataset["manifest"]["cases"]
            if row["case_id"] == "programmable-equivalent-001"
        )
        self.assertEqual(current_declaration["partition"], "development")
        self.assertTrue(current_declaration["tuning_eligible"])

    def test_v3_rejection_is_hash_bound_and_replayable_history(self) -> None:
        dataset = claim_held_out.load_golden_held_out()
        revision = next(
            row for row in dataset["baseline_revisions"]
            if row["record"]["revision_id"]
            == "status-indication-mapping-001-v3-rejection"
        )
        record = revision["record"]
        replayed = revision["review_items"]

        self.assertEqual(record["dataset_version"], "claim-ledger-golden-v3")
        self.assertEqual(record["declaration"]["partition"], "held_out")
        self.assertFalse(record["declaration"]["tuning_eligible"])
        self.assertEqual(record["adjudication"]["reviewed_by"], "YYH")
        self.assertEqual(
            record["adjudication"]["reviewed_at"],
            "2026-07-28T12:18:00.000Z",
        )
        self.assertEqual(record["adjudication"]["overall_verdict"], "disagree")
        self.assertEqual(
            record["adjudication"]["dimension_verdicts"],
            {
                "claim_boundary": "disagree",
                "eligibility": "disagree",
                "resolution": "disagree",
                "coverage": "disagree",
                "target_obligation_subject": "agree",
                "target_modality": "disagree",
                "role_object_preservation": "disagree",
            },
        )
        self.assertEqual(
            record["adjudication"]["rationale"],
            "有点多了，这里体现接口输出可配置就好了，没必要往用户场景考虑",
        )
        self.assertEqual(replayed[0]["claim_id"], "CLM-24fc4484bbafac71")
        self.assertEqual(
            replayed[0]["claim_hash"],
            "sha256:24fc4484bbafac7115d8cecb5a4b9f7ac45ec4df3907f5b7ea4cbbd5f0b0fef7",
        )
        self.assertEqual(
            replayed[0]["fixture_hash"],
            "sha256:40c065202f1836388720e8739b0bb8e45276eefc791ca9f27715a028efa47a6a",
        )
        self.assertNotIn(
            "status-indication-mapping-001",
            {row["case_id"] for row in dataset["manifest"]["cases"]},
        )

    def test_replacement_held_out_binds_review_expectations(self) -> None:
        dataset = claim_held_out.load_golden_held_out()
        self.assertEqual(
            dataset["held_out_case_ids"],
            ["configurable-interface-capability-001"],
        )
        item = dataset["review_items"][0]
        self.assertEqual(item["claim_id"], "CLM-0eb57350dc55563e")
        self.assertEqual(
            item["claim_hash"],
            "sha256:0eb57350dc55563e80378ed761c8cc15ecb3bef34e070a676b022868d194fcb2",
        )
        self.assertEqual(
            item["fixture_hash"],
            "sha256:5a2dee40558e50a87734f98dd4e7cbf07b24dfd330da8f1098a0fd2fb6ce3bb3",
        )
        self.assertEqual(
            item["source_text"],
            "The auxiliary output interface shall be configurable.",
        )
        self.assertEqual(len(item["requirements"]), 1)
        self.assertEqual(
            item["requirements"][0]["description"],
            "该产品应支持配置辅助输出接口。",
        )
        self.assertEqual(
            item["requirements"][0]["source_quote"],
            "The auxiliary output interface shall be configurable.",
        )
        active_wording = "\n".join([
            item["source_text"],
            item["requirements"][0]["title"],
            item["requirements"][0]["description"],
            item["requirements"][0]["source_quote"],
        ]).casefold()
        for role_term in (
            "operator",
            "maintainer",
            "user",
            "操作人员",
            "维护人员",
            "用户",
        ):
            with self.subTest(role_term=role_term):
                self.assertNotIn(role_term, active_wording)
        self.assertEqual(item["expected"]["ledger"]["resolution"], "uncertain")
        self.assertEqual(item["actual"]["coverage"]["status"], "proposed")
        self.assertEqual(item["actual"]["coverage"]["prefilter_status"], "pass")
        self.assertEqual(
            item["review_expectations"]["target_obligation_subject"],
            "产品",
        )
        self.assertEqual(item["review_expectations"]["target_modality"], "应支持")
        preservation = item["review_expectations"]["role_object_preservation"]
        self.assertEqual(preservation["role"], "not_applicable")
        self.assertEqual(
            preservation["object"],
            {"source": "auxiliary output interface", "target": "辅助输出接口"},
        )
        self.assertEqual(
            preservation["capability"],
            {"source": "configurable", "target": "配置"},
        )

        programmable = next(
            row for row in dataset["inputs"]["cases"]
            if row["case_id"] == "programmable-equivalent-001"
        )
        self.assertEqual(
            programmable["requirements"][0]["description"],
            "该产品应支持操作人员配置指示通道。",
        )
        self.assertEqual(
            set(programmable["controlled_term_aliases"]),
            {"operator", "indicator channel"},
        )
        programmable_expected = next(
            row for row in dataset["expected"]["cases"]
            if row["case_id"] == "programmable-equivalent-001"
        )
        coverage = programmable_expected["claims"][0]["coverage"]
        self.assertEqual(coverage["status"], "proposed")
        self.assertEqual(coverage["prefilter_status"], "pass")
        self.assertEqual(
            programmable_expected["claims"][0]["ledger"]["resolution"],
            "uncertain",
        )

    def test_reviewer_must_be_independent_and_timestamped(self) -> None:
        for reviewed_by, reviewed_at in (
            ("Codex", "2026-07-27T12:00:00Z"),
            ("", "2026-07-27T12:00:00Z"),
            ("independent-reviewer", "2026-07-27T12:00:00"),
        ):
            with self.subTest(reviewed_by=reviewed_by, reviewed_at=reviewed_at):
                dataset = _reviewed_dataset()
                curation = dataset["manifest"]["curation"]
                curation["reviewed_by"] = reviewed_by
                curation["reviewed_at"] = reviewed_at
                self.assertEqual(
                    claim_held_out.summarize_held_out_review(dataset)["evidence_status"],
                    "invalid",
                )

    def test_corrupt_case_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            for name in ("manifest.json", "inputs.json", "expected.json"):
                (root / name).write_bytes((GOLDEN_DIR / name).read_bytes())
            (root / "history").mkdir()
            for source in (GOLDEN_DIR / "history").iterdir():
                (root / "history" / source.name).write_bytes(source.read_bytes())
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            held_out = next(
                row for row in manifest["cases"] if row["partition"] == "held_out"
            )
            held_out["tuning_eligible"] = True
            (root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(claim_held_out.HeldOutEvidenceError):
                claim_held_out.load_golden_held_out(root)

    def test_tampered_history_is_rejected_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            for name in ("manifest.json", "inputs.json", "expected.json"):
                (root / name).write_bytes((GOLDEN_DIR / name).read_bytes())
            (root / "history").mkdir()
            source = next((GOLDEN_DIR / "history").iterdir())
            target = root / "history" / source.name
            target.write_bytes(source.read_bytes() + b"\n")

            with self.assertRaisesRegex(
                claim_held_out.HeldOutEvidenceError,
                "history digest",
            ):
                claim_held_out.load_golden_held_out(root)

    def test_raw_hashed_history_uses_repository_stable_lf_bytes(self) -> None:
        manifest = json.loads(
            (GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        for reference in manifest["baseline_revisions"]:
            with self.subTest(path=reference["path"]):
                raw = (GOLDEN_DIR / reference["path"]).read_bytes()
                self.assertNotIn(b"\r\n", raw)

    def test_invalid_summary_includes_history_counters(self) -> None:
        summary = claim_held_out.invalid_held_out_summary("broken")
        self.assertEqual(summary["historical_review_count"], 0)
        self.assertEqual(summary["historical_disagreement_count"], 0)
        self.assertEqual(summary["baseline_revision_count"], 0)


if __name__ == "__main__":
    unittest.main()
