from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

import claim_acceptance
from claim_artifacts import ClaimArtifactError


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(
    run_id: str,
    sequence: int,
    *,
    route_mode: str = "llm",
    accounting_status: str = "complete",
    cost_status: str = "pass",
    cost_met: bool | None = True,
    verifier_calls: int = 10,
    verifier_tokens: int = 2000,
    independent_calls: int = 10,
    independent_tokens: int = 2000,
    operation_failures: int = 0,
    usage_complete: bool = True,
    baseline_lineage_match: bool = True,
    termination_reason: str = "stalled_open",
    budget_denied: bool = False,
    versions: dict[str, str] | None = None,
    target_generation_suffix: str = "",
    generation_run_id: str | None = None,
    attempt_chain_id: str | None = None,
    attempt_kind: str = "cold",
    attempt_status: str = "complete",
    attempt_count: int = 1,
    current_attempt_count: int | None = None,
    tail_attempt_id: str | None = None,
    tail_attempt_kind: str | None = None,
    tail_attempt_status: str | None = None,
    cumulative_calls: int | None = None,
    cumulative_failed_calls: int = 0,
    cumulative_operation_failures: int | None = None,
    cumulative_tokens: int | None = None,
    cumulative_usage_complete: bool | None = None,
    cumulative_reused_groups: int = 0,
    cumulative_candidate_groups: int = 20,
    reuse_generation_run_id: str | None = None,
) -> dict:
    claim_id = f"CLM-{sequence:016x}"
    claim_hash = "sha256:" + f"{sequence:064x}"
    component_versions = versions or {
        "ledger": "claim-ledger-v3",
        "prefilter": "claim-edge-prefilter-v3",
        "coverage_validator": "claim-coverage-validator-v6",
        "negative_validator": "claim-negative-validator-v3",
        "reducer": "claim-reducer-v2",
        "batch_policy": "claim-verifier-batch-v3-full-http-body",
        "cost_policy": "claim-cost-policy-v3-user-approved",
    }
    document_generation_id = "sha256:" + "d" * 64
    catalog_generation_id = "sha256:" + f"{sequence + 16:064x}"
    target_generation_id = "sha256:" + hashlib.sha256(
        f"target-{run_id}{target_generation_suffix}".encode("utf-8")
    ).hexdigest()
    requirements_sha256 = "sha256:" + f"{sequence + 32:064x}"
    chain_id = attempt_chain_id or "sha256:" + f"{sequence + 48:064x}"
    reused_ratio = (
        cumulative_reused_groups / cumulative_candidate_groups
        if cumulative_candidate_groups
        else None
    )
    snapshot = {
        "catalog": [{"claim_id": claim_id, "claim_hash": claim_hash}],
        "ledger": [{
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "resolution": "uncertain",
        }],
        "metrics": {
            "catalog_total_count": 220,
            "eligible_claim_count": 200,
            "covered_count": 120,
            "semantic_excluded_count": 10,
            "structural_excluded_count": 20,
            "uncertain_count": 70,
            "invalid_group_count": 0,
            "invalid_edge_count": 0,
            "verifier_call_count": verifier_calls,
            "verifier_failed_calls": 0,
            "verifier_operation_failure_count": operation_failures,
            "verifier_tokens": verifier_tokens,
            "independent_verifier_call_count": independent_calls,
            "independent_verifier_tokens": independent_tokens,
            "verifier_usage_complete": usage_complete,
            "no_ledger_baseline_lineage_match": baseline_lineage_match,
            "verifier_budget_policy_version": "llm-request-budget-v1",
            "verifier_budget_max_calls": 100,
            "verifier_budget_max_total_tokens": 100000,
            "verifier_budget_remaining_calls": max(0, 100 - verifier_calls),
            "verifier_budget_remaining_tokens": max(0, 100000 - verifier_tokens),
            "verifier_budget_denied": budget_denied,
            "verifier_budget_exhaustion_reason": (
                "call_budget_exhausted" if budget_denied else ""
            ),
            "no_ledger_baseline_call_count": 100,
            "no_ledger_baseline_tokens": 10000,
            "verifier_call_increase_ratio": {
                "numerator": 10,
                "denominator": 100,
                "value": 0.1,
            },
            "verifier_token_increase_ratio": {
                "numerator": verifier_tokens,
                "denominator": 10000,
                "value": verifier_tokens / 10000,
            },
            "verifier_cost_gate_status": cost_status,
            "phase0_cost_gate_met": cost_met,
            "verifier_cost_policy_version": "claim-cost-policy-v3-user-approved",
            "verifier_call_increase_limit": 0.25,
            "verifier_token_increase_limit": 0.65,
            "avg_verifier_calls_per_unit": {
                "numerator": 10,
                "denominator": 20,
                "value": 0.5,
            },
            "verifier_tokens_per_claim": {
                "numerator": verifier_tokens,
                "denominator": 200,
                "value": verifier_tokens / 200,
            },
            "prefilter_reject_rate": {
                "numerator": 30,
                "denominator": 100,
                "value": 0.3,
            },
            "deterministic_verbatim_ratio": {
                "numerator": 20,
                "denominator": 100,
                "value": 0.2,
            },
            "semantic_verifier_candidate_ratio": {
                "numerator": 70,
                "denominator": 200,
                "value": 0.35,
            },
            "sibling_claim_open_rate": {
                "numerator": 2,
                "denominator": 10,
                "value": 0.2,
            },
        },
        "catalog_meta": {
            "catalog_version": "claim-catalog-v4",
            "unit_packing_version": "claim-unit-packing-v1",
            "parser_provenance": {
                "source_alignment_version": "source-alignment-v6",
                "source_transformation_policy_version": "source-transform-policy-v4",
                "source_transformation_ruleset_version": "source-transform-rules-v4-pdf-word-repair-v4",
            },
        },
        "generation_meta": {
            "run_id": generation_run_id or run_id,
            "committed_at": f"2026-07-2{sequence}T10:00:00+00:00",
            "document_generation_id": document_generation_id,
            "catalog_generation_id": catalog_generation_id,
            "target_generation_id": target_generation_id,
            "requirements_sha256": requirements_sha256,
            "attempt_chain": {
                "schema": "claim-verifier-attempt-chain-binding/v2",
                "ledger_file": "claim_verifier_attempts.jsonl",
                "ledger_prefix_count": attempt_count,
                "ledger_prefix_sha256": "sha256:" + f"{sequence + 64:064x}",
                "chain_id": chain_id,
                "attempt_id": "sha256:" + f"{sequence + 80:064x}",
                "attempt_count": attempt_count,
                "attempt_kind": attempt_kind,
                "attempt_status": attempt_status,
                "source_locator": {
                    "attempt_request_id": f"attempt-request-{sequence}",
                    "requirements_request_id": f"requirements-request-{sequence}",
                    "catalog_generation_id": catalog_generation_id,
                    "document_generation_id": document_generation_id,
                    "target_generation_id": target_generation_id,
                    "requirements_sha256": requirements_sha256,
                    "reuse_generation_run_id": reuse_generation_run_id,
                    "reuse_attempt_id": (
                        "sha256:" + f"{sequence + 79:064x}"
                        if reuse_generation_run_id
                        else None
                    ),
                },
                "cumulative_metrics": {
                    "verifier_call_count": (
                        verifier_calls if cumulative_calls is None else cumulative_calls
                    ),
                    "verifier_failed_call_count": cumulative_failed_calls,
                    "verifier_operation_failure_count": (
                        operation_failures
                        if cumulative_operation_failures is None
                        else cumulative_operation_failures
                    ),
                    "verifier_tokens": (
                        verifier_tokens if cumulative_tokens is None else cumulative_tokens
                    ),
                    "verifier_usage_complete": (
                        usage_complete
                        if cumulative_usage_complete is None
                        else cumulative_usage_complete
                    ),
                    "semantic_validation_reused_group_count": cumulative_reused_groups,
                    "semantic_verifier_candidate_count": cumulative_candidate_groups,
                    "semantic_validation_reused_group_ratio": {
                        "numerator": cumulative_reused_groups,
                        "denominator": cumulative_candidate_groups,
                        "value": reused_ratio,
                    },
                },
            },
            "shadow_meta": {
                "scope": "full",
                "extraction_status": "success",
                "accounting_status": accounting_status,
                "resolution_status": "open",
                "termination_reason": termination_reason,
                "route_mode": route_mode,
                "semantic_verifier_enabled": route_mode == "llm",
                "verifier_runtime": {
                    "version": "claim-coverage-runtime-v10",
                    "cost_policy_version": "claim-cost-policy-v3-user-approved",
                    "fingerprint": f"sha256:runtime-{run_id}",
                },
                "versions": component_versions,
            },
        },
    }
    committed_attempt = snapshot["generation_meta"]["attempt_chain"]
    snapshot["attempt_cost_chain"] = {
        "schema": "claim-verifier-attempt-cost-chain/v1",
        "ledger_file": "claim_verifier_attempts.jsonl",
        "validated_full_ledger_count": (
            attempt_count
            if current_attempt_count is None
            else current_attempt_count
        ),
        "validated_full_ledger_sha256": "sha256:" + f"{sequence + 96:064x}",
        "chain_id": chain_id,
        "attempt_count": (
            attempt_count
            if current_attempt_count is None
            else current_attempt_count
        ),
        "tail_attempt_id": tail_attempt_id or committed_attempt["attempt_id"],
        "tail_attempt_kind": tail_attempt_kind or attempt_kind,
        "tail_attempt_status": tail_attempt_status or attempt_status,
        "cumulative_metrics": copy.deepcopy(committed_attempt["cumulative_metrics"]),
    }
    return snapshot


def _curation(*run_ids: str, status: str = "reviewed") -> dict:
    adjudications = []
    known_omissions = []
    if status == "reviewed":
        for run_id in run_ids:
            sequence = int(run_id.rsplit("-", 1)[1])
            claim_ref = {
                "run_id": run_id,
                "claim_id": f"CLM-{sequence:016x}",
                "claim_hash": "sha256:" + f"{sequence:064x}",
            }
            adjudications.append({
                **claim_ref,
                "review_evidence_fingerprint": (
                    claim_acceptance.shadow_review_evidence_fingerprint(
                        _snapshot(run_id, sequence),
                        claim_ref["claim_id"],
                        claim_ref["claim_hash"],
                    )
                ),
                "ledger_resolution": "uncertain",
                "category": "uncertain",
                "verdict": "agree",
                "rationale": "",
            })
            known_omissions.append(claim_ref)
    return {
        "human_review_status": status,
        "reviewed_by": "independent-reviewer" if status == "reviewed" else "",
        "reviewed_at": "2026-07-26T12:00:00Z" if status == "reviewed" else "",
        "adjudications": adjudications,
        "known_omissions": known_omissions,
    }


def _held_out(evidence_status: str = "complete", **overrides) -> dict:
    summary = {
        "artifact_status": "valid",
        "error_code": None,
        "dataset_id": "claim_ledger_v1",
        "dataset_version": "claim-ledger-golden-v4",
        "human_review_status": (
            "reviewed" if evidence_status != "pending" else "pending"
        ),
        "evidence_status": evidence_status,
        "held_out_case_count": 1,
        "held_out_claim_count": 1,
        "reviewed_case_count": 1 if evidence_status != "pending" else 0,
        "reviewed_claim_count": 1 if evidence_status != "pending" else 0,
        "approved_claim_count": 1 if evidence_status == "complete" else 0,
        "stale_adjudication_count": 0,
        "duplicate_adjudication_count": 0,
        "missing_adjudication_count": 1 if evidence_status == "pending" else 0,
        "extra_adjudication_count": 0,
        "invalid_adjudication_count": 0,
        "disagreement_count": 1 if evidence_status == "not_approved" else 0,
        "followup_count": 0,
        "historical_review_count": 2,
        "historical_disagreement_count": 2,
        "baseline_revision_count": 2,
    }
    summary.update(overrides)
    return summary


class ClaimAcceptanceTests(unittest.TestCase):
    def _record(self, run_id: str, sequence: int, **kwargs) -> dict:
        return claim_acceptance.summarize_snapshot(
            run_id=run_id,
            document_id="historical-doc-1",
            sequence=sequence,
            snapshot=_snapshot(run_id, sequence, **kwargs),
            component_versions_current=True,
        )

    def test_three_real_reviewed_runs_are_eligible_for_user_decision(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["phase1_entry_recommendation"], "eligible_for_user_decision")
        self.assertTrue(all(gate["status"] == "pass" for gate in report["gates"].values()))
        self.assertEqual(report["totals"]["run_count"], 3)
        self.assertEqual(report["totals"]["eligible_claim_count"], 600)
        self.assertEqual(
            report["golden_held_out_summary"]["historical_review_count"],
            2,
        )
        self.assertEqual(
            report["golden_held_out_summary"]["historical_disagreement_count"],
            2,
        )
        self.assertEqual(
            report["golden_held_out_summary"]["baseline_revision_count"],
            2,
        )
        self.assertEqual(report["curation_summary"]["reviewed_claim_count"], 3)
        self.assertEqual(report["curation_summary"]["known_omission_passed"], 3)
        self.assertEqual(report["curation_summary"]["verifier_disagreement_count"], 0)
        self.assertEqual(report["runs"][0]["attempt_chain"]["attempt_kind"], "cold")
        self.assertEqual(report["runs"][0]["attempt_chain"]["attempt_count"], 1)
        self.assertEqual(
            report["runs"][0]["attempt_chain"]["cumulative_verifier_call_count"],
            10,
        )
        self.assertEqual(report["totals"]["cumulative_verifier_call_count"], 30)
        self.assertEqual(report["totals"]["reused_group_count"], 0)

    def test_negative_audit_selection_is_stable_and_samples_ten_percent(self) -> None:
        ledger = []
        catalog = []
        for index in range(25):
            claim_id = f"CLM-{index + 100:016x}"
            claim_hash = "sha256:" + f"{index + 100:064x}"
            catalog.append({"claim_id": claim_id, "claim_hash": claim_hash})
            ledger.append({
                "claim_id": claim_id,
                "claim_hash": claim_hash,
                "claim_effective_revision": "sha256:" + f"{index + 200:064x}",
                "resolution": "excluded",
                "exclusion_kind": "semantic",
                "semantic_negative": {"status": "validated"},
            })
        ledger.append({
            "claim_id": "CLM-ffffffffffffffff",
            "claim_hash": "sha256:" + "f" * 64,
            "claim_effective_revision": "sha256:" + "e" * 64,
            "resolution": "uncertain",
            "exclusion_kind": None,
            "semantic_negative": {"status": "invalid"},
        })
        snapshot = {"catalog": catalog, "effective_ledger": ledger}

        first = claim_acceptance.negative_audit_claim_refs(snapshot)
        second = claim_acceptance.negative_audit_claim_refs(copy.deepcopy(snapshot))
        revised = copy.deepcopy(snapshot)
        for index, row in enumerate(revised["effective_ledger"]):
            row["claim_effective_revision"] = "sha256:" + f"{index + 900:064x}"
        after_target_revision = claim_acceptance.negative_audit_claim_refs(revised)

        self.assertEqual(first, second)
        self.assertEqual(first, after_target_revision)
        self.assertEqual(len(first), 3)
        self.assertTrue(all(row["claim_id"] != "CLM-ffffffffffffffff" for row in first))

    def test_negative_audit_requires_selected_reviews_and_reports_disagreement(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        audit_claim = {
            "claim_id": "CLM-00000000000000aa",
            "claim_hash": "sha256:" + "a" * 64,
            "resolution": "excluded",
            "review_evidence_fingerprint": "sha256:" + "b" * 64,
            "negative_audit_selected": True,
        }
        records[0]["_claim_index"][
            f"{audit_claim['claim_id']}\0{audit_claim['claim_hash']}"
        ] = audit_claim
        curation = _curation("run-1", "run-2", "run-3")

        pending = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1", records, curation, _held_out(),
        )

        self.assertEqual(pending["status"], "blocked")
        self.assertEqual(pending["gates"]["negative_audit"], {
            "status": "blocked",
            "reason": "negative_audit_review_pending",
        })

        curation["adjudications"].append({
            "run_id": "run-1",
            "claim_id": audit_claim["claim_id"],
            "claim_hash": audit_claim["claim_hash"],
            "review_evidence_fingerprint": audit_claim["review_evidence_fingerprint"],
            "ledger_resolution": "excluded",
            "category": "semantic_negative",
            "verdict": "disagree",
            "rationale": "The sampled negative contains a normative obligation.",
        })
        reviewed = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1", records, curation, _held_out(),
        )

        self.assertEqual(reviewed["gates"]["negative_audit"]["status"], "pass")
        self.assertEqual(reviewed["curation_summary"]["negative_audit_sample_count"], 1)
        self.assertEqual(reviewed["curation_summary"]["negative_audit_reviewed_count"], 1)
        self.assertEqual(reviewed["curation_summary"]["audit_disagreement_rate"], {
            "numerator": 1,
            "denominator": 1,
            "value": 1.0,
        })

    def test_failed_extraction_units_are_sanitized_and_block_acceptance(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        records[0]["metrics"]["failed_extraction_units"] = 2

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["gates"]["extraction_success"], {
            "status": "fail",
            "reason": "failed_extraction_units_present",
        })
        self.assertEqual(report["totals"]["failed_extraction_units"], 2)

    def test_shadow_adjudication_is_stale_when_target_generation_changes(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                target_generation_suffix="-changed" if index == 2 else "",
            )
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["gates"]["human_adjudication"]["reason"],
                         "human_adjudication_invalid")
        self.assertEqual(report["curation_summary"]["stale_adjudication_count"], 1)

    def test_shadow_disagreement_requires_rationale(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        curation = _curation("run-1", "run-2", "run-3")
        curation["adjudications"][1]["verdict"] = "disagree"
        curation["adjudications"][1]["rationale"] = ""

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1", records, curation, _held_out(),
        )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["curation_summary"]["missing_rationale_count"], 1)

    def test_stub_cost_and_pending_human_evidence_are_blocked(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                route_mode="stub",
                cost_status="not_run",
                cost_met=None,
            )
            for index in range(1, 4)
        ]

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation(status="pending"),
            _held_out(),
        )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["real_semantic_verifier"]["status"], "blocked")
        self.assertEqual(report["gates"]["verifier_cost"]["status"], "blocked")
        self.assertEqual(report["gates"]["human_adjudication"]["status"], "blocked")
        self.assertNotIn("pass", report["phase1_entry_recommendation"])

    def test_enabled_but_zero_independent_calls_is_blocked(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                verifier_calls=0,
                independent_calls=0,
            )
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["real_semantic_verifier"]["status"], "blocked")

    def test_incomplete_verifier_usage_is_blocked(self) -> None:
        records = [
            self._record(f"run-{index}", index, usage_complete=False)
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["real_semantic_verifier"]["status"], "blocked")

    def test_zero_token_verifier_calls_are_blocked_even_if_declared_complete(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                verifier_tokens=0,
                independent_tokens=0,
                usage_complete=True,
            )
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["gates"]["real_semantic_verifier"]["status"],
            "blocked",
        )

    def test_successful_provider_call_with_invalid_verifier_envelope_is_blocked(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                operation_failures=1,
                attempt_status="failed",
            )
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["real_semantic_verifier"], {
            "status": "blocked",
            "reason": "real_semantic_verifier_not_run",
        })
        self.assertEqual(report["gates"]["verifier_cost"], {
            "status": "pass",
            "reason": "verifier_cost_within_limits",
        })

    def test_warm_success_charges_and_discloses_cold_operation_failures(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                verifier_calls=3,
                verifier_tokens=1000,
                operation_failures=0,
                attempt_kind="ledger_only",
                attempt_count=2,
                cumulative_calls=13,
                cumulative_operation_failures=2,
                cumulative_tokens=3000,
                cumulative_reused_groups=15,
                reuse_generation_run_id=f"cold-run-{index}",
            )
            for index in range(1, 4)
        ]

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["gates"]["real_semantic_verifier"]["status"], "pass")
        self.assertEqual(report["gates"]["verifier_cost"], {
            "status": "pass",
            "reason": "verifier_cost_within_limits",
        })
        self.assertEqual(
            report["runs"][0]["attempt_chain"][
                "cumulative_verifier_operation_failure_count"
            ],
            2,
        )
        self.assertEqual(
            report["totals"]["cumulative_verifier_operation_failure_count"],
            6,
        )
        self.assertEqual(report["totals"]["reused_group_count"], 45)
        self.assertEqual(
            report["runs"][0]["attempt_chain"]["source_generations"][
                "reuse_generation_run_id"
            ],
            "cold-run-1",
        )

    def test_cumulative_cost_exceeding_limit_fails_even_when_final_attempt_passes(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                verifier_calls=3,
                verifier_tokens=1000,
                attempt_kind="ledger_only",
                attempt_count=2,
                cumulative_calls=26,
                cumulative_tokens=5100,
                cumulative_reused_groups=10,
                reuse_generation_run_id=f"cold-run-{index}",
            )
            for index in range(1, 4)
        ]

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["gates"]["real_semantic_verifier"]["status"], "pass")
        self.assertEqual(report["gates"]["verifier_cost"], {
            "status": "fail",
            "reason": "verifier_cost_limit_exceeded",
        })
        self.assertEqual(
            report["runs"][0]["attempt_chain"]["cumulative_verifier_call_ratio"][
                "value"
            ],
            0.26,
        )

    def test_cumulative_token_cost_limit_is_inclusive_at_sixty_five_percent(self) -> None:
        for cumulative_tokens, expected_status in ((6500, "pass"), (6501, "fail")):
            with self.subTest(cumulative_tokens=cumulative_tokens):
                records = [
                    self._record(
                        f"run-{index}",
                        index,
                        cumulative_calls=20,
                        cumulative_tokens=cumulative_tokens,
                    )
                    for index in range(1, 4)
                ]
                report = claim_acceptance.evaluate_phase0_evidence(
                    "historical-shadow-v1",
                    records,
                    _curation("run-1", "run-2", "run-3"),
                    _held_out(),
                )

                self.assertEqual(
                    report["gates"]["verifier_cost"]["status"],
                    expected_status,
                )

    def test_failed_tail_after_committed_prefix_blocks_and_is_charged(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                attempt_count=1,
                current_attempt_count=2,
                tail_attempt_id="sha256:" + f"{index + 128:064x}",
                tail_attempt_kind="ledger_only",
                tail_attempt_status="failed",
                cumulative_calls=26,
                cumulative_failed_calls=1,
                cumulative_operation_failures=1,
                cumulative_tokens=5100,
            )
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(
            report["gates"]["real_semantic_verifier"]["status"],
            "blocked",
        )
        self.assertEqual(report["gates"]["verifier_cost"], {
            "status": "fail",
            "reason": "verifier_cost_limit_exceeded",
        })
        attempt = report["runs"][0]["attempt_chain"]
        self.assertEqual(attempt["attempt_status"], "failed")
        self.assertFalse(attempt["tail_is_committed"])
        self.assertEqual(attempt["attempt_count"], 2)
        self.assertEqual(attempt["cumulative_verifier_call_count"], 26)

    def test_three_labels_cannot_disguise_the_same_attempt_chain(self) -> None:
        chain_id = "sha256:" + "a" * 64
        records = [
            self._record(f"run-{index}", index, attempt_chain_id=chain_id)
            for index in range(1, 4)
        ]

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["gates"]["consecutive_runs"], {
            "status": "fail",
            "reason": "consecutive_attempt_chain_identity_reused",
        })

    def test_mismatched_baseline_lineage_is_blocked(self) -> None:
        records = [
            self._record(f"run-{index}", index, baseline_lineage_match=False)
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["baseline_lineage"], {
            "status": "blocked",
            "reason": "baseline_lineage_mismatch",
        })

    def test_budget_exhaustion_blocks_even_when_cost_ratio_passes(self) -> None:
        records = [
            self._record(
                f"run-{index}",
                index,
                termination_reason="budget_exhausted",
                budget_denied=True,
            )
            for index in range(1, 4)
        ]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["verifier_budget"], {
            "status": "blocked",
            "reason": "verifier_budget_exhausted",
        })

    def test_incomplete_accounting_is_a_failed_gate(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        records[1] = self._record("run-2", 2, accounting_status="incomplete")

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["gates"]["source_accounting"]["status"], "fail")
        self.assertIn("source_accounting_incomplete", report["blocking_reasons"])

    def test_mixed_component_versions_fail_consistency_gate(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        mixed = dict(records[2]["component_versions"])
        mixed["reducer"] = "claim-reducer-future"
        records[2]["component_versions"] = mixed

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )

        self.assertEqual(report["gates"]["component_version_consistency"]["status"], "fail")

    def test_reviewed_label_cannot_promote_stale_claim_adjudication(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        curation = _curation("run-1", "run-2", "run-3")
        stale_hash = "sha256:" + "f" * 64
        curation["adjudications"][0]["claim_hash"] = stale_hash
        curation["known_omissions"][0]["claim_hash"] = stale_hash

        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            curation,
            _held_out(),
        )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["gates"]["human_adjudication"]["status"], "fail")
        self.assertEqual(report["gates"]["known_omissions"]["status"], "fail")
        self.assertEqual(report["curation_summary"]["reviewed_claim_count"], 2)
        self.assertEqual(report["curation_summary"]["known_omission_passed"], 2)

    def test_invalid_artifact_error_never_echoes_source_path(self) -> None:
        secret_path = Path("C:/customer/secret-document/test11")
        with patch(
            "claim_acceptance.load_committed_shadow",
            side_effect=ClaimArtifactError(f"missing artifact: {secret_path}"),
        ):
            record = claim_acceptance.collect_run(
                run_id="run-1",
                generation_run_id="run-1",
                document_id="historical-doc-1",
                sequence=1,
                output_dir=secret_path,
                attempt_chain_id="sha256:" + "1" * 64,
            )

        encoded = json.dumps(record)
        self.assertEqual(record["artifact_status"], "invalid")
        self.assertEqual(record["error_code"], "snapshot_invalid")
        self.assertNotIn("customer", encoded)
        self.assertNotIn("test11", encoded)

    def test_collect_run_rejects_manifest_generation_run_identity_mismatch(self) -> None:
        snapshot = _snapshot("review-label", 1, generation_run_id="actual-run")
        with (
            patch("claim_acceptance.load_committed_shadow", return_value=snapshot),
            patch("claim_acceptance.committed_shadow_versions_are_current", return_value=True),
        ):
            record = claim_acceptance.collect_run(
                run_id="manifest-run",
                generation_run_id="wrong-generation-run",
                document_id="historical-doc-1",
                sequence=1,
                output_dir="ignored",
                attempt_chain_id=snapshot["generation_meta"]["attempt_chain"]["chain_id"],
            )

        self.assertEqual(record["artifact_status"], "invalid")
        self.assertEqual(record["error_code"], "snapshot_identity_mismatch")

    def test_collect_run_keeps_review_label_separate_from_bound_generation_id(self) -> None:
        snapshot = _snapshot("review-label", 1, generation_run_id="actual-run")
        with (
            patch("claim_acceptance.load_committed_shadow", return_value=snapshot),
            patch("claim_acceptance.committed_shadow_versions_are_current", return_value=True),
        ):
            record = claim_acceptance.collect_run(
                run_id="review-label",
                generation_run_id="actual-run",
                document_id="historical-doc-1",
                sequence=1,
                output_dir="ignored",
                attempt_chain_id=snapshot["generation_meta"]["attempt_chain"]["chain_id"],
            )

        self.assertEqual(record["artifact_status"], "valid")
        self.assertEqual(record["run_id"], "review-label")
        self.assertEqual(record["generation_run_id"], "actual-run")

    def test_collect_run_rejects_manifest_attempt_chain_identity_mismatch(self) -> None:
        snapshot = _snapshot("run-1", 1)
        with (
            patch("claim_acceptance.load_committed_shadow", return_value=snapshot),
            patch("claim_acceptance.committed_shadow_versions_are_current", return_value=True),
        ):
            record = claim_acceptance.collect_run(
                run_id="run-1",
                generation_run_id="run-1",
                document_id="historical-doc-1",
                sequence=1,
                output_dir="ignored",
                attempt_chain_id="sha256:" + "f" * 64,
            )

        self.assertEqual(record["artifact_status"], "invalid")
        self.assertEqual(record["error_code"], "snapshot_identity_mismatch")

    def test_collect_run_rejects_missing_attempt_chain_evidence(self) -> None:
        snapshot = _snapshot("run-1", 1)
        del snapshot["generation_meta"]["attempt_chain"]
        with (
            patch("claim_acceptance.load_committed_shadow", return_value=snapshot),
            patch("claim_acceptance.committed_shadow_versions_are_current", return_value=True),
        ):
            record = claim_acceptance.collect_run(
                run_id="run-1",
                generation_run_id="run-1",
                document_id="historical-doc-1",
                sequence=1,
                output_dir="ignored",
                attempt_chain_id="sha256:" + "1" * 64,
            )

        self.assertEqual(record["artifact_status"], "invalid")
        self.assertEqual(record["error_code"], "snapshot_invalid")

    def test_collect_run_rejects_missing_full_attempt_cost_chain(self) -> None:
        snapshot = _snapshot("run-1", 1)
        del snapshot["attempt_cost_chain"]
        with (
            patch("claim_acceptance.load_committed_shadow", return_value=snapshot),
            patch("claim_acceptance.committed_shadow_versions_are_current", return_value=True),
        ):
            record = claim_acceptance.collect_run(
                run_id="run-1",
                generation_run_id="run-1",
                document_id="historical-doc-1",
                sequence=1,
                output_dir="ignored",
                attempt_chain_id=snapshot["generation_meta"]["attempt_chain"]["chain_id"],
            )

        self.assertEqual(record["artifact_status"], "invalid")
        self.assertEqual(record["error_code"], "snapshot_invalid")

    def test_collect_run_rejects_inconsistent_cumulative_reuse_ratio(self) -> None:
        snapshot = _snapshot("run-1", 1)
        snapshot["generation_meta"]["attempt_chain"]["cumulative_metrics"][
            "semantic_validation_reused_group_ratio"
        ]["value"] = 0.5
        with (
            patch("claim_acceptance.load_committed_shadow", return_value=snapshot),
            patch("claim_acceptance.committed_shadow_versions_are_current", return_value=True),
        ):
            record = claim_acceptance.collect_run(
                run_id="run-1",
                generation_run_id="run-1",
                document_id="historical-doc-1",
                sequence=1,
                output_dir="ignored",
                attempt_chain_id=snapshot["generation_meta"]["attempt_chain"]["chain_id"],
            )

        self.assertEqual(record["artifact_status"], "invalid")
        self.assertEqual(record["error_code"], "snapshot_invalid")

    def test_report_is_schema_valid_and_contains_no_output_paths(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(),
        )
        schema = json.loads(
            (ROOT / "schemas" / "claim_shadow_acceptance_report.schema.json").read_text(
                encoding="utf-8"
            )
        )

        Draft202012Validator(schema).validate(report)
        encoded = json.dumps(report)
        self.assertNotIn("output_dir", encoded)
        self.assertNotIn("source_text", encoded)
        self.assertNotIn("reviewed_by", encoded)
        self.assertNotIn("fixture_hash", encoded)
        self.assertNotIn("ledger_file", encoded)

    def test_pending_golden_held_out_blocks_phase0_exit(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out("pending"),
        )
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"]["golden_held_out_adjudication"], {
            "status": "blocked",
            "reason": "golden_held_out_adjudication_pending",
        })

    def test_invalid_or_unapproved_golden_held_out_fails_closed(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        for evidence_status, reason in (
            ("invalid", "golden_held_out_adjudication_invalid"),
            ("not_approved", "golden_held_out_adjudication_not_approved"),
        ):
            with self.subTest(evidence_status=evidence_status):
                report = claim_acceptance.evaluate_phase0_evidence(
                    "historical-shadow-v1",
                    records,
                    _curation("run-1", "run-2", "run-3"),
                    _held_out(evidence_status),
                )
                self.assertEqual(report["status"], "fail")
                self.assertEqual(
                    report["gates"]["golden_held_out_adjudication"]["reason"],
                    reason,
                )

    def test_invalid_golden_artifact_fails_closed(self) -> None:
        records = [self._record(f"run-{index}", index) for index in range(1, 4)]
        report = claim_acceptance.evaluate_phase0_evidence(
            "historical-shadow-v1",
            records,
            _curation("run-1", "run-2", "run-3"),
            _held_out(
                "invalid",
                artifact_status="invalid",
                error_code="golden_held_out_artifact_invalid",
            ),
        )
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["gates"]["golden_held_out_adjudication"], {
            "status": "fail",
            "reason": "golden_held_out_artifact_invalid",
        })

    def test_cli_gate_failure_uses_exit_three_and_sanitized_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            marker = "customer-secret-test11"
            manifest = {
                "schema": "claim-shadow-acceptance-input/v3",
                "dataset_id": "historical-shadow-v1",
                "runs": [
                    {
                        "run_id": f"run-{index}",
                        "generation_run_id": f"generation-run-{index}",
                        "document_id": "historical-doc-1",
                        "sequence": index,
                        "output_dir": str(root / marker / str(index)),
                        "attempt_chain_id": "sha256:" + f"{index:064x}",
                    }
                    for index in range(1, 4)
                ],
                "curation": _curation(status="pending"),
            }
            input_path = root / "input.json"
            output_path = root / "report.json"
            input_path.write_text(json.dumps(manifest), encoding="utf-8")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                code = claim_acceptance.main(
                    ["--input", str(input_path), "--output", str(output_path)]
                )

            envelope = json.loads(stdout.getvalue())
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 3)
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["error"]["type"], "acceptance_gate_not_met")
            self.assertEqual(persisted["status"], "fail")
            self.assertNotIn(marker, stdout.getvalue())
            self.assertNotIn(marker, output_path.read_text(encoding="utf-8"))

    def test_cli_rejects_hardlink_output_alias_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            input_path = root / "input.json"
            output_path = root / "report.json"
            original = b"do-not-overwrite"
            input_path.write_bytes(original)
            os.link(input_path, output_path)
            stdout = io.StringIO()

            with (
                patch("claim_acceptance.run_acceptance") as run_acceptance,
                redirect_stdout(stdout),
            ):
                code = claim_acceptance.main([
                    "--input", str(input_path),
                    "--output", str(output_path),
                ])

            self.assertEqual(code, 2)
            self.assertFalse(run_acceptance.called)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(json.loads(stdout.getvalue())["error"]["type"], "input_error")

    def test_cli_output_failure_uses_exit_three(self) -> None:
        stdout = io.StringIO()
        with (
            patch("claim_acceptance.run_acceptance", return_value={"status": "pass"}),
            patch("claim_acceptance.atomic_write_json", side_effect=OSError("locked")),
            redirect_stdout(stdout),
        ):
            code = claim_acceptance.main([
                "--input", "input.json",
                "--output", "report.json",
            ])

        envelope = json.loads(stdout.getvalue())
        self.assertEqual(code, 3)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "output_error")


if __name__ == "__main__":
    unittest.main()
