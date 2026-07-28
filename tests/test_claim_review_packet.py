from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import claim_held_out
import claim_review_packet


def _snapshot(source_text: str = "Outputs can be assigned <safely>.") -> dict:
    claim_id = "CLM-0000000000000001"
    claim_hash = "sha256:" + "1" * 64
    return {
        "catalog": [{
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "text": source_text,
            "raw_text": source_text,
            "source_kind": "paragraph_sentence",
            "section_path": ["Synthetic section"],
            "locator": {"block_id": "B1", "start": 0, "end": len(source_text)},
            "region_evidence": {"page_number": 7},
        }],
        "ledger": [{
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "resolution": "covered",
            "classification": "normative",
            "classification_status": "validated",
            "exclusion_kind": None,
            "invalid_reasons": [],
            "semantic_negative": None,
        }],
        "effective_ledger": [{
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "resolution": "covered",
            "classification": "normative",
            "classification_status": "validated",
            "exclusion_kind": None,
            "invalid_reasons": [],
            "semantic_negative": None,
        }],
        "groups": [{
            "claim_id": claim_id,
            "coverage_group_id": "CGR-0000000000000001",
            "status": "validated",
            "validation_method": "independent_semantic",
            "prefilter": {"status": "not_applicable"},
            "validator_checks": {"subject": True},
            "validator_reason": "",
            "edges": [{
                "target_requirement_id": "AIR-1",
                "target_kind": "ai_requirement",
                "target_review_status": "unreviewed",
                "relation": "generated_from",
                "produced_evidence": [{
                    "field": "description",
                    "item_index": None,
                    "start": 0,
                    "end": 8,
                    "text": "输出可由用户程序分配。",
                }],
            }],
        }],
        "metrics": {
            "verifier_call_count": 7,
            "verifier_tokens": 35000,
            "coverage_group_count": 1,
        },
        "generation_meta": {
            "run_id": "generation-run-1",
            "attempt_chain": {
                "chain_id": "sha256:" + "2" * 64,
            },
        },
    }


def _manifest() -> dict:
    claim_hash = "sha256:" + "1" * 64
    return {
        "schema": "claim-shadow-acceptance-input/v3",
        "dataset_id": "review-packet-test",
        "runs": [{
            "run_id": "run-1",
            "generation_run_id": "generation-run-1",
            "document_id": "doc-1",
            "sequence": 1,
            "output_dir": "C:/customer/private/source",
            "attempt_chain_id": "sha256:" + "2" * 64,
        }],
        "curation": {
            "human_review_status": "pending",
            "reviewed_by": "",
            "reviewed_at": "",
            "adjudications": [],
            "known_omissions": [{
                "run_id": "run-1",
                "claim_id": "CLM-0000000000000001",
                "claim_hash": claim_hash,
            }],
        },
    }


def _pending_held_out() -> dict:
    dataset = claim_held_out.load_golden_held_out()
    dataset["manifest"]["curation"].update({
        "human_review_status": "pending",
        "reviewed_by": "",
        "reviewed_at": "",
        "held_out_adjudications": [],
    })
    return dataset


def _snapshot_with_reuse_chain() -> dict:
    snapshot = _snapshot()
    snapshot["generation_meta"] = {
        "run_id": "generation-run-1",
        "attempt_chain": {
            "schema": "claim-verifier-attempt-chain-binding/v2",
            "chain_id": "sha256:" + "3" * 64,
            "attempt_id": "sha256:" + "4" * 64,
            "attempt_kind": "ledger_only",
            "attempt_status": "complete",
            "attempt_count": 2,
            "source_locator": {
                "attempt_request_id": "shadow-attempt-request-2",
                "requirements_request_id": "requirements-request-1",
                "document_generation_id": "sha256:" + "8" * 64,
                "catalog_generation_id": "sha256:" + "5" * 64,
                "target_generation_id": "sha256:" + "9" * 64,
                "requirements_sha256": "sha256:" + "6" * 64,
                "reuse_generation_run_id": "generation-run-1",
                "reuse_attempt_id": "sha256:" + "7" * 64,
                "source_generation_run_id": "generation-run-1",
                "source_attempt_id": "sha256:" + "7" * 64,
            },
            "cumulative_metrics": {
                "verifier_call_count": 21,
                "verifier_failed_call_count": 0,
                "verifier_operation_failure_count": 0,
                "verifier_tokens": 107121,
                "verifier_usage_complete": True,
                "semantic_validation_reused_group_count": 1,
                "semantic_verifier_candidate_count": 1,
                "semantic_validation_reused_group_ratio": {
                    "numerator": 1,
                    "denominator": 1,
                    "value": 1.0,
                },
            },
        },
    }
    snapshot["metrics"] = {
        "semantic_validation_reused_group_count": 1,
        "coverage_group_count": 1,
    }
    committed = snapshot["generation_meta"]["attempt_chain"]
    snapshot["attempt_cost_chain"] = {
        "schema": "claim-verifier-attempt-cost-chain/v1",
        "ledger_file": "claim_verifier_attempts.jsonl",
        "validated_full_ledger_count": 2,
        "validated_full_ledger_sha256": "sha256:" + "a" * 64,
        "chain_id": committed["chain_id"],
        "attempt_count": 2,
        "tail_attempt_id": committed["attempt_id"],
        "tail_attempt_kind": committed["attempt_kind"],
        "tail_attempt_status": committed["attempt_status"],
        "cumulative_metrics": dict(committed["cumulative_metrics"]),
    }
    snapshot["groups"][0].update({
        "validation_reused": True,
        "validation_source": {
            "request_id": "coverage-request-1",
            "generation_run_id": "generation-run-1",
        },
    })
    return snapshot


class ClaimReviewPacketTests(unittest.TestCase):
    def _packet(self, source_text: str = "Outputs can be assigned <safely>.") -> dict:
        with (
            patch("claim_review_packet.load_input_manifest", return_value=_manifest()),
            patch("claim_review_packet.load_committed_shadow", return_value=_snapshot(source_text)),
            patch("claim_review_packet.committed_shadow_versions_are_current", return_value=True),
            patch(
                "claim_review_packet.load_golden_held_out",
                return_value=_pending_held_out(),
            ),
        ):
            return claim_review_packet.build_review_packet("ignored.json")

    def test_packet_contains_review_evidence_without_local_paths(self) -> None:
        packet = self._packet()
        self.assertEqual(packet["schema"], "claim-shadow-review-packet/v5")
        self.assertEqual(
            packet["generator_version"],
            "claim-shadow-review-packet-v7",
        )
        self.assertTrue(packet["sensitive"])
        self.assertEqual(packet["storage_policy"], "machine_local_do_not_commit")
        self.assertEqual(len(packet["shadow_items"]), 1)
        self.assertEqual(len(packet["golden_held_out"]["items"]), 1)
        item = packet["shadow_items"][0]
        self.assertEqual(item["category"], "semantic_positive")
        self.assertEqual(item["review_purposes"], ["known_omission"])
        self.assertEqual(
            item["coverage_groups"][0]["edges"][0]["produced_evidence"][0]["text"],
            "输出可由用户程序分配。",
        )
        encoded = json.dumps(packet, ensure_ascii=False)
        self.assertNotIn("output_dir", encoded)
        self.assertNotIn("C:/customer", encoded)
        self.assertEqual(
            packet["decision_template"]["shadow_adjudications"][0]["verdict"],
            "",
        )
        self.assertRegex(
            packet["decision_template"]["shadow_adjudications"][0][
                "review_evidence_fingerprint"
            ],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            packet["golden_held_out"]["items"][0]["review_expectations"][
                "target_obligation_subject"
            ],
            "产品",
        )
        held_out = packet["decision_template"]["golden_held_out"]["adjudications"][0]
        self.assertEqual(
            set(held_out["dimension_verdicts"]),
            set(claim_review_packet.HELD_OUT_REVIEW_DIMENSIONS),
        )
        self.assertTrue(all(not value for value in held_out["dimension_verdicts"].values()))

    def test_packet_exposes_attempt_cost_and_coverage_reuse_provenance(self) -> None:
        snapshot = _snapshot_with_reuse_chain()
        manifest = _manifest()
        manifest["runs"][0]["attempt_chain_id"] = "sha256:" + "3" * 64
        with (
            patch("claim_review_packet.load_input_manifest", return_value=manifest),
            patch("claim_review_packet.load_committed_shadow", return_value=snapshot),
            patch("claim_review_packet.committed_shadow_versions_are_current", return_value=True),
            patch(
                "claim_review_packet.load_golden_held_out",
                return_value=_pending_held_out(),
            ),
        ):
            packet = claim_review_packet.build_review_packet("ignored.json")

        item = packet["shadow_items"][0]
        self.assertEqual(item["attempt_chain"], {
            "chain_id": "sha256:" + "3" * 64,
            "attempt_id": "sha256:" + "4" * 64,
            "committed_attempt_id": "sha256:" + "4" * 64,
            "tail_is_committed": True,
            "attempt_kind": "ledger_only",
            "attempt_status": "complete",
            "attempt_count": 2,
            "cumulative_verifier_call_count": 21,
            "cumulative_verifier_failed_call_count": 0,
            "cumulative_verifier_operation_failure_count": 0,
            "cumulative_verifier_tokens": 107121,
            "cumulative_verifier_usage_complete": True,
            "reused_group_count": 1,
            "reused_group_ratio": {
                "numerator": 1,
                "denominator": 1,
                "value": 1.0,
            },
            "source_locator": {
                "attempt_request_id": "shadow-attempt-request-2",
                "requirements_request_id": "requirements-request-1",
                "document_generation_id": "sha256:" + "8" * 64,
                "catalog_generation_id": "sha256:" + "5" * 64,
                "target_generation_id": "sha256:" + "9" * 64,
                "requirements_sha256": "sha256:" + "6" * 64,
                "reuse_generation_run_id": "generation-run-1",
                "reuse_attempt_id": "sha256:" + "7" * 64,
                "source_generation_run_id": "generation-run-1",
                "source_attempt_id": "sha256:" + "7" * 64,
            },
        })
        group = item["coverage_groups"][0]
        self.assertIs(group["validation_reused"], True)
        self.assertEqual(group["validation_source"], {
            "request_id": "coverage-request-1",
            "generation_locator": {
                "generation_run_id": "generation-run-1",
            },
        })
        rendered = claim_review_packet.render_review_html(packet)
        self.assertIn("Attempt kind", rendered)
        self.assertIn("ledger_only", rendered)
        self.assertIn("Cumulative verifier calls", rendered)
        self.assertIn("107121", rendered)
        self.assertIn("Reused coverage groups", rendered)
        self.assertIn("Reused group ratio", rendered)
        self.assertIn("1 / 1 (100.0%)", rendered)
        self.assertIn("coverage-request-1", rendered)
        self.assertIn("Source generation:", rendered)

    def test_packet_exposes_failed_tail_after_committed_prefix(self) -> None:
        snapshot = _snapshot_with_reuse_chain()
        cost_chain = snapshot["attempt_cost_chain"]
        cost_chain.update({
            "validated_full_ledger_count": 3,
            "attempt_count": 3,
            "tail_attempt_id": "sha256:" + "f" * 64,
            "tail_attempt_kind": "ledger_only",
            "tail_attempt_status": "failed",
        })
        cost_chain["cumulative_metrics"].update({
            "verifier_call_count": 22,
            "verifier_failed_call_count": 1,
            "verifier_operation_failure_count": 1,
            "verifier_tokens": 107132,
            "verifier_usage_complete": False,
        })
        manifest = _manifest()
        manifest["runs"][0]["attempt_chain_id"] = "sha256:" + "3" * 64
        with (
            patch("claim_review_packet.load_input_manifest", return_value=manifest),
            patch("claim_review_packet.load_committed_shadow", return_value=snapshot),
            patch("claim_review_packet.committed_shadow_versions_are_current", return_value=True),
            patch(
                "claim_review_packet.load_golden_held_out",
                return_value=_pending_held_out(),
            ),
        ):
            packet = claim_review_packet.build_review_packet("ignored.json")

        attempt = packet["shadow_items"][0]["attempt_chain"]
        self.assertEqual(attempt["attempt_status"], "failed")
        self.assertFalse(attempt["tail_is_committed"])
        self.assertEqual(attempt["cumulative_verifier_failed_call_count"], 1)
        self.assertEqual(attempt["cumulative_verifier_operation_failure_count"], 1)
        self.assertFalse(attempt["cumulative_verifier_usage_complete"])
        rendered = claim_review_packet.render_review_html(packet)
        self.assertIn("Cumulative operation failures", rendered)
        self.assertIn("Tail is committed", rendered)

    def test_packet_exposes_negative_reuse_provenance(self) -> None:
        snapshot = _snapshot_with_reuse_chain()
        manifest = _manifest()
        manifest["runs"][0]["attempt_chain_id"] = "sha256:" + "3" * 64
        negative = {
            "status": "validated",
            "validation_reused": True,
            "proposal": {
                "request_id": "negative-proposal-1",
                "reason": "definition",
                "rationale": "Product description, not a requirement.",
                "evidence": [{
                    "start": 0,
                    "end": 20,
                    "text": "Synthetic product description",
                }],
            },
            "validation": {
                "request_id": "negative-validation-1",
                "reason": "definition",
                "rationale": "The span contains no normative obligation.",
                "evidence": [{
                    "start": 0,
                    "end": 20,
                    "text": "Synthetic product description",
                }],
                "checks": {
                    "context_complete": True,
                    "no_normative_obligation": True,
                },
            },
            "validation_source": {
                "request_id": "negative-validation-1",
                "generation_run_id": "generation-run-1",
            },
        }
        for ledger in (snapshot["ledger"][0], snapshot["effective_ledger"][0]):
            ledger.update({
                "resolution": "excluded",
                "classification": "non_normative",
                "exclusion_kind": "semantic",
                "semantic_negative": negative,
            })
        snapshot["groups"] = []
        snapshot["metrics"].update({
            "semantic_validation_reused_group_count": 0,
            "coverage_group_count": 0,
        })
        with (
            patch("claim_review_packet.load_input_manifest", return_value=manifest),
            patch("claim_review_packet.load_committed_shadow", return_value=snapshot),
            patch("claim_review_packet.committed_shadow_versions_are_current", return_value=True),
            patch(
                "claim_review_packet.load_golden_held_out",
                return_value=_pending_held_out(),
            ),
        ):
            packet = claim_review_packet.build_review_packet("ignored.json")

        item = packet["shadow_items"][0]
        self.assertEqual(item["category"], "semantic_negative")
        self.assertEqual(
            item["review_purposes"],
            ["known_omission", "negative_audit"],
        )
        self.assertIs(item["semantic_negative"]["validation_reused"], True)
        self.assertEqual(
            item["semantic_negative"]["validation_source"]["request_id"],
            "negative-validation-1",
        )
        self.assertEqual(
            item["semantic_negative"]["validation_source"]["generation_locator"],
            {"generation_run_id": "generation-run-1"},
        )
        rendered = claim_review_packet.render_review_html(packet)
        self.assertIn("Semantic negative validation", rendered)
        self.assertIn("negative-validation-1", rendered)
        self.assertIn("Excluded as a semantic negative", rendered)
        self.assertIn("The span contains no normative obligation.", rendered)
        self.assertIn("Synthetic product description", rendered)
        self.assertIn("No target requirement is expected", rendered)
        self.assertIn("Validator checks", rendered)
        self.assertIn("no_normative_obligation", rendered)
        self.assertNotIn("No produced evidence.", rendered)
        self.assertIn("run-1 - Known omission / Negative audit", rendered)
        self.assertLess(
            rendered.index("The span contains no normative obligation."),
            rendered.index("Run provenance"),
        )

    def test_missing_attempt_and_reuse_fields_are_explicitly_unavailable(self) -> None:
        packet = self._packet()
        item = packet["shadow_items"][0]
        self.assertEqual(item["attempt_chain"], {
            "chain_id": "sha256:" + "2" * 64,
            "attempt_id": "unavailable",
            "committed_attempt_id": "unavailable",
            "tail_is_committed": "unavailable",
            "attempt_kind": "unavailable",
            "attempt_status": "unavailable",
            "attempt_count": "unavailable",
            "cumulative_verifier_call_count": "unavailable",
            "cumulative_verifier_failed_call_count": "unavailable",
            "cumulative_verifier_operation_failure_count": "unavailable",
            "cumulative_verifier_tokens": "unavailable",
            "cumulative_verifier_usage_complete": "unavailable",
            "reused_group_count": "unavailable",
            "reused_group_ratio": "unavailable",
            "source_locator": "unavailable",
        })
        group = item["coverage_groups"][0]
        self.assertEqual(group["validation_reused"], "unavailable")
        self.assertEqual(group["validation_source"], {
            "request_id": "unavailable",
            "generation_locator": "unavailable",
        })
        rendered = claim_review_packet.render_review_html(packet)
        self.assertIn("unavailable", rendered)

    def test_html_escapes_source_and_contains_offline_decision_controls(self) -> None:
        packet = self._packet("<script>alert('x')</script>")
        rendered = claim_review_packet.render_review_html(packet)
        self.assertNotIn("<script>alert('x')</script>", rendered)
        self.assertIn("&lt;script&gt;alert", rendered)
        self.assertIn("Export decisions", rendered)
        self.assertIn("data-kind=\"shadow\"", rendered)
        self.assertIn("data-kind=\"held-out\"", rendered)
        self.assertIn('data-frozen="false" data-held-out="false"', rendered)
        self.assertIn('data-frozen="true" data-held-out="true"', rendered)
        self.assertIn("not frozen", rendered)
        self.assertIn("not held-out", rendered)
        self.assertIn("badge-frozen", rendered)
        self.assertIn("badge-held-out", rendered)
        self.assertIn("Copy decisions JSON", rendered)
        self.assertIn("Product obligation subject", rendered)
        self.assertIn("Role and object preservation", rendered)
        self.assertIn('data-dimension="claim_boundary"', rendered)
        self.assertIn("Disagree and follow-up decisions need a rationale.", rendered)
        self.assertIn('id="export-result" hidden', rendered)
        self.assertIn('aria-live="polite"', rendered)
        self.assertIn("JSON.parse(JSON.stringify(template))", rendered)
        self.assertIn("JSON.stringify(output,null,2)+'\\n'", rendered)
        self.assertIn("setTimeout(()=>{URL.revokeObjectURL(url)", rendered)
        self.assertIn("run-1 - Known omission", rendered)
        self.assertIn("Run provenance", rendered)
        self.assertNotIn("https://", rendered)

    def test_same_run_positive_and_negative_cards_are_visibly_distinct(self) -> None:
        packet = self._packet()
        negative_item = json.loads(json.dumps(packet["shadow_items"][0]))
        negative_item.update({
            "claim_id": "CLM-0000000000000002",
            "claim_hash": "sha256:" + "2" * 64,
            "review_evidence_fingerprint": "sha256:" + "3" * 64,
            "category": "semantic_negative",
            "review_purposes": ["negative_audit"],
            "coverage_groups": [],
            "ledger": {
                "resolution": "excluded",
                "classification": "non_normative",
                "classification_status": "validated",
                "exclusion_kind": "semantic",
                "invalid_reasons": [],
            },
            "semantic_negative": {
                "status": "validated",
                "proposal": {
                    "reason": "definition",
                    "rationale": "A descriptive span.",
                    "evidence": [{"text": "Synthetic description"}],
                },
                "validation": {
                    "reason": "definition",
                    "rationale": "No normative obligation is present.",
                    "evidence": [{"text": "Synthetic description"}],
                    "checks": {"no_normative_obligation": True},
                },
                "validation_reused": False,
                "validation_source": {},
            },
        })
        packet["shadow_items"].append(negative_item)
        packet["decision_template"]["shadow_adjudications"].append({
            "run_id": "run-1",
            "claim_id": negative_item["claim_id"],
            "claim_hash": negative_item["claim_hash"],
            "review_evidence_fingerprint": negative_item[
                "review_evidence_fingerprint"
            ],
            "ledger_resolution": "excluded",
            "category": "semantic_negative",
            "verdict": "",
            "rationale": "",
        })

        rendered = claim_review_packet.render_review_html(packet)

        self.assertEqual(rendered.count("<h2>run-1 - Known omission</h2>"), 1)
        self.assertEqual(rendered.count("<h2>run-1 - Negative audit</h2>"), 1)
        self.assertIn('data-verdict="0"', rendered)
        self.assertIn('data-verdict="1"', rendered)
        self.assertIn("No normative obligation is present.", rendered)
        self.assertNotIn("No produced evidence.", rendered)

    def test_packet_files_are_written_atomically_and_parse(self) -> None:
        packet = self._packet()
        with tempfile.TemporaryDirectory() as raw_tmp:
            outputs = claim_review_packet.write_review_packet(packet, raw_tmp)
            persisted = json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))
            rendered = Path(outputs["html"]).read_text(encoding="utf-8")
        self.assertEqual(persisted["schema"], "claim-shadow-review-packet/v5")
        self.assertIn("Phase 0 Claim Review", rendered)

    def test_existing_shadow_decision_is_prefilled_without_promoting_held_out(self) -> None:
        manifest = _manifest()
        snapshot = _snapshot()
        fingerprint = claim_review_packet.shadow_review_evidence_fingerprint(
            snapshot,
            "CLM-0000000000000001",
            "sha256:" + "1" * 64,
        )
        manifest["curation"].update({
            "human_review_status": "reviewed",
            "reviewed_by": "synthetic-reviewer",
            "reviewed_at": "2026-01-01T00:00:00Z",
            "adjudications": [{
                "run_id": "run-1",
                "claim_id": "CLM-0000000000000001",
                "claim_hash": "sha256:" + "1" * 64,
                "review_evidence_fingerprint": fingerprint,
                "ledger_resolution": "covered",
                "category": "semantic_positive",
                "verdict": "disagree",
                "rationale": "Target lacks a product obligation subject.",
            }],
        })
        with (
            patch("claim_review_packet.load_input_manifest", return_value=manifest),
            patch("claim_review_packet.load_committed_shadow", return_value=snapshot),
            patch("claim_review_packet.committed_shadow_versions_are_current", return_value=True),
            patch(
                "claim_review_packet.load_golden_held_out",
                return_value=_pending_held_out(),
            ),
        ):
            packet = claim_review_packet.build_review_packet("ignored.json")
        self.assertEqual(
            packet["decision_template"]["reviewed_by"],
            "synthetic-reviewer",
        )
        self.assertEqual(
            packet["decision_template"]["shadow_adjudications"][0]["verdict"],
            "disagree",
        )
        self.assertEqual(
            packet["decision_template"]["shadow_adjudications"][0]["rationale"],
            "Target lacks a product obligation subject.",
        )
        rendered = claim_review_packet.render_review_html(packet)
        self.assertIn('<option value="disagree" selected>Disagree</option>', rendered)

    def test_stale_snapshot_cannot_generate_review_decisions(self) -> None:
        with (
            patch("claim_review_packet.load_input_manifest", return_value=_manifest()),
            patch("claim_review_packet.load_committed_shadow", return_value=_snapshot()),
            patch("claim_review_packet.committed_shadow_versions_are_current", return_value=False),
        ):
            with self.assertRaisesRegex(
                claim_review_packet.ReviewPacketError,
                "stale component versions",
            ):
                claim_review_packet.build_review_packet("ignored.json")

    def test_manifest_generation_identity_mismatch_is_rejected(self) -> None:
        manifest = _manifest()
        manifest["runs"][0]["generation_run_id"] = "another-generation"
        with (
            patch("claim_review_packet.load_input_manifest", return_value=manifest),
            patch(
                "claim_review_packet.load_committed_shadow",
                return_value=_snapshot(),
            ),
        ):
            with self.assertRaisesRegex(
                claim_review_packet.ReviewPacketError,
                "generation identity does not match manifest",
            ):
                claim_review_packet.build_review_packet("ignored.json")

    def test_manifest_attempt_chain_identity_mismatch_is_rejected(self) -> None:
        manifest = _manifest()
        manifest["runs"][0]["attempt_chain_id"] = "sha256:" + "f" * 64
        with (
            patch("claim_review_packet.load_input_manifest", return_value=manifest),
            patch(
                "claim_review_packet.load_committed_shadow",
                return_value=_snapshot(),
            ),
        ):
            with self.assertRaisesRegex(
                claim_review_packet.ReviewPacketError,
                "attempt chain does not match manifest",
            ):
                claim_review_packet.build_review_packet("ignored.json")

    def test_cli_success_emits_json_envelope(self) -> None:
        packet = self._packet()
        with tempfile.TemporaryDirectory() as raw_tmp:
            stdout = io.StringIO()
            with (
                patch("claim_review_packet.build_review_packet", return_value=packet),
                redirect_stdout(stdout),
            ):
                code = claim_review_packet.main([
                    "--input", "input.json",
                    "--output-dir", raw_tmp,
                ])
            envelope = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["shadow_item_count"], 1)
        self.assertEqual(envelope["held_out_item_count"], 1)

    def test_cli_rejects_hardlink_input_output_alias_without_writing(self) -> None:
        packet = self._packet()
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            input_path = root / "input.json"
            packet_path = root / claim_review_packet.PACKET_JSON_NAME
            original = b"do-not-overwrite"
            input_path.write_bytes(original)
            os.link(input_path, packet_path)
            stdout = io.StringIO()
            with (
                patch("claim_review_packet.build_review_packet", return_value=packet) as build,
                redirect_stdout(stdout),
            ):
                code = claim_review_packet.main([
                    "--input", str(input_path),
                    "--output-dir", str(root),
                ])

            self.assertEqual(code, 2)
            self.assertFalse(build.called)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertEqual(packet_path.read_bytes(), original)
            self.assertEqual(json.loads(stdout.getvalue())["error"]["type"], "input_error")

    def test_cli_output_failure_uses_exit_three(self) -> None:
        stdout = io.StringIO()
        with (
            patch("claim_review_packet.build_review_packet", return_value=self._packet()),
            patch("claim_review_packet.write_review_packet", side_effect=OSError("locked")),
            redirect_stdout(stdout),
        ):
            code = claim_review_packet.main([
                "--input", "input.json",
                "--output-dir", "packet",
            ])

        envelope = json.loads(stdout.getvalue())
        self.assertEqual(code, 3)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "output_error")


if __name__ == "__main__":
    unittest.main()
