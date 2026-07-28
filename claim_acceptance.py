"""Sanitized Phase 0 shadow acceptance evidence and transition gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator

from claim_artifacts import (
    CLAIM_VERIFIER_ATTEMPTS,
    CLAIM_VERIFIER_ATTEMPT_BINDING_SCHEMA,
    ClaimArtifactError,
    atomic_write_json,
    committed_shadow_versions_are_current,
    load_committed_shadow,
    paths_alias,
)
from claim_ledger import (
    CLAIM_COST_POLICY_VERSION,
    CLAIM_VERIFIER_CALL_INCREASE_LIMIT,
    CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT,
)
from claim_held_out import (
    HeldOutEvidenceError,
    invalid_held_out_summary,
    load_golden_held_out,
    summarize_held_out_review,
)


CLAIM_ACCEPTANCE_VERSION = "claim-shadow-acceptance-v9"
REPORT_SCHEMA_VERSION = "claim-shadow-acceptance-report/v7"
INPUT_SCHEMA_VERSION = "claim-shadow-acceptance-input/v3"
CLAIM_REVIEW_EVIDENCE_VERSION = "claim-review-evidence-v1"
NEGATIVE_AUDIT_POLICY_VERSION = "claim-negative-audit-v2"
NEGATIVE_AUDIT_SAMPLE_RATE = 0.10
ENVELOPE_SCHEMA_VERSION = "1.0"
MIN_CONSECUTIVE_RUNS = 3

ROOT = Path(__file__).resolve().parent
INPUT_SCHEMA = ROOT / "schemas" / "claim_shadow_acceptance_input.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "claim_shadow_acceptance_report.schema.json"

_INTEGER_METRICS = (
    "catalog_total_count",
    "failed_extraction_units",
    "eligible_claim_count",
    "covered_count",
    "semantic_excluded_count",
    "structural_excluded_count",
    "uncertain_count",
    "invalid_group_count",
    "invalid_edge_count",
    "verifier_call_count",
    "verifier_failed_calls",
    "verifier_operation_failure_count",
    "verifier_tokens",
    "independent_verifier_call_count",
    "independent_verifier_tokens",
    "verifier_budget_max_calls",
    "verifier_budget_max_total_tokens",
    "verifier_budget_remaining_calls",
    "verifier_budget_remaining_tokens",
    "no_ledger_baseline_call_count",
    "no_ledger_baseline_tokens",
)
_RATIO_METRICS = (
    "verifier_call_increase_ratio",
    "verifier_token_increase_ratio",
    "avg_verifier_calls_per_unit",
    "verifier_tokens_per_claim",
    "prefilter_reject_rate",
    "deterministic_verbatim_ratio",
    "semantic_verifier_candidate_ratio",
    "sibling_claim_open_rate",
)


class ClaimAcceptanceInputError(ValueError):
    """The local run manifest is missing or malformed."""


class _SnapshotIdentityMismatch(ValueError):
    """The committed generation does not match its manifest binding."""


def _blank_run(run_id: str, document_id: str, sequence: int, error_code: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "generation_run_id": None,
        "document_id": document_id,
        "sequence": sequence,
        "artifact_status": "invalid",
        "error_code": error_code,
        "committed_at": None,
        "document_generation_id": None,
        "catalog_generation_id": None,
        "target_generation_id": None,
        "component_versions_current": None,
        "component_versions": {},
        "scope": None,
        "extraction_status": None,
        "accounting_status": None,
        "resolution_status": None,
        "termination_reason": None,
        "route_mode": None,
        "semantic_verifier_enabled": None,
        "verifier_runtime_fingerprint": None,
        "attempt_chain": None,
        "metrics": _safe_metrics({}),
        "_claim_index": {},
    }


def _safe_ratio(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    ratio = value.get("value")
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int)
        or not isinstance(denominator, int)
    ):
        return None
    if ratio is not None and (
        isinstance(ratio, bool) or not isinstance(ratio, (int, float))
    ):
        return None
    return {
        "numerator": max(0, numerator),
        "denominator": max(0, denominator),
        "value": float(ratio) if ratio is not None else None,
    }


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        key: max(0, int(metrics.get(key) or 0))
        for key in _INTEGER_METRICS
    }
    for key in _RATIO_METRICS:
        ratio = _safe_ratio(metrics.get(key))
        if ratio is not None:
            result[key] = ratio
    status = str(metrics.get("verifier_cost_gate_status") or "insufficient_data")
    result["verifier_cost_gate_status"] = (
        status if status in {"pass", "fail", "not_run", "insufficient_data"}
        else "insufficient_data"
    )
    result["phase0_cost_gate_met"] = (
        metrics.get("phase0_cost_gate_met")
        if metrics.get("phase0_cost_gate_met") in {True, False}
        else None
    )
    result["verifier_usage_complete"] = metrics.get("verifier_usage_complete") is True
    result["no_ledger_baseline_lineage_match"] = (
        metrics.get("no_ledger_baseline_lineage_match") is True
    )
    result["verifier_budget_denied"] = metrics.get("verifier_budget_denied") is True
    result["verifier_budget_policy_version"] = str(
        metrics.get("verifier_budget_policy_version") or ""
    )
    result["verifier_budget_exhaustion_reason"] = str(
        metrics.get("verifier_budget_exhaustion_reason") or ""
    )
    result["verifier_cost_policy_version"] = str(
        metrics.get("verifier_cost_policy_version") or ""
    )
    for key in ("verifier_call_increase_limit", "verifier_token_increase_limit"):
        value = metrics.get(key)
        result[key] = (
            float(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else 0.0
        )
    return result


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _is_safe_id(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return False
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    return value[0].isalnum() and value.isascii() and all(
        character in allowed for character in value
    )


def _required_count(mapping: dict[str, Any], key: str, *, minimum: int = 0) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"invalid attempt-chain count: {key}")
    return value


def _strict_ratio(
    value: Any,
    *,
    expected_numerator: int,
    expected_denominator: int,
) -> dict[str, Any]:
    ratio = _safe_ratio(value)
    if (
        ratio is None
        or ratio["numerator"] != expected_numerator
        or ratio["denominator"] != expected_denominator
    ):
        raise ValueError("attempt-chain ratio does not match its counters")
    expected_value = (
        expected_numerator / expected_denominator if expected_denominator else None
    )
    actual_value = ratio["value"]
    if expected_value is None:
        if actual_value is not None:
            raise ValueError("zero-denominator attempt-chain ratio must be null")
    elif actual_value is None or abs(actual_value - expected_value) > 1e-12:
        raise ValueError("attempt-chain ratio value is inconsistent")
    return ratio


def _cost_ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _safe_source_generation(value: Any, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not _is_sha256(value):
        raise ValueError("attempt-chain source generation is invalid")
    return str(value)


def _summarize_attempt_chain(
    generation: dict[str, Any],
    final_metrics: dict[str, Any],
    cost_chain: dict[str, Any],
) -> dict[str, Any]:
    chain = generation.get("attempt_chain")
    if not isinstance(chain, dict):
        raise ValueError("attempt-chain binding is missing")
    if chain.get("schema") != CLAIM_VERIFIER_ATTEMPT_BINDING_SCHEMA:
        raise ValueError("attempt-chain binding version is invalid")
    if chain.get("ledger_file") != CLAIM_VERIFIER_ATTEMPTS:
        raise ValueError("attempt-chain ledger binding is invalid")

    chain_id = chain.get("chain_id")
    attempt_id = chain.get("attempt_id")
    prefix_sha256 = chain.get("ledger_prefix_sha256")
    if not all(_is_sha256(value) for value in (chain_id, attempt_id, prefix_sha256)):
        raise ValueError("attempt-chain identity is invalid")
    attempt_count = _required_count(chain, "attempt_count", minimum=1)
    prefix_count = _required_count(chain, "ledger_prefix_count", minimum=1)
    if prefix_count < attempt_count:
        raise ValueError("attempt-chain ledger prefix is incomplete")
    attempt_kind = chain.get("attempt_kind")
    if attempt_kind not in {"cold", "ledger_only"}:
        raise ValueError("attempt-chain kind is invalid")
    attempt_status = chain.get("attempt_status")
    if attempt_status not in {"complete", "incomplete", "failed"}:
        raise ValueError("attempt-chain status is invalid")
    committed_cumulative = chain.get("cumulative_metrics")
    if not isinstance(committed_cumulative, dict):
        raise ValueError("committed attempt-chain counters are missing")
    committed_calls = _required_count(committed_cumulative, "verifier_call_count")
    committed_failed_calls = _required_count(
        committed_cumulative,
        "verifier_failed_call_count",
    )
    committed_operation_failures = _required_count(
        committed_cumulative,
        "verifier_operation_failure_count",
    )
    committed_tokens = _required_count(committed_cumulative, "verifier_tokens")
    committed_reused = _required_count(
        committed_cumulative,
        "semantic_validation_reused_group_count",
    )
    committed_candidates = _required_count(
        committed_cumulative,
        "semantic_verifier_candidate_count",
    )
    if committed_reused > committed_candidates:
        raise ValueError("committed attempt-chain reused groups exceed candidates")
    _strict_ratio(
        committed_cumulative.get("semantic_validation_reused_group_ratio"),
        expected_numerator=committed_reused,
        expected_denominator=committed_candidates,
    )
    if not isinstance(committed_cumulative.get("verifier_usage_complete"), bool):
        raise ValueError("committed attempt-chain usage completeness is invalid")

    source = chain.get("source_locator")
    if not isinstance(source, dict):
        raise ValueError("attempt-chain evidence is incomplete")
    if any(
        not isinstance(source.get(key), str) or not source.get(key)
        for key in ("attempt_request_id", "requirements_request_id")
    ):
        raise ValueError("attempt-chain request lineage is incomplete")
    document_generation_id = _safe_source_generation(
        source.get("document_generation_id")
    )
    catalog_generation_id = _safe_source_generation(
        source.get("catalog_generation_id")
    )
    target_generation_id = _safe_source_generation(source.get("target_generation_id"))
    requirements_sha256 = _safe_source_generation(source.get("requirements_sha256"))
    if (
        document_generation_id != generation.get("document_generation_id")
        or catalog_generation_id != generation.get("catalog_generation_id")
        or target_generation_id != generation.get("target_generation_id")
        or requirements_sha256 != generation.get("requirements_sha256")
    ):
        raise ValueError("attempt-chain source lineage is stale")
    reuse_generation_run_id = source.get("reuse_generation_run_id")
    if reuse_generation_run_id is not None and not _is_safe_id(reuse_generation_run_id):
        raise ValueError("attempt-chain reuse generation run id is invalid")
    reuse_attempt_id = _safe_source_generation(
        source.get("reuse_attempt_id"),
        required=False,
    )
    if attempt_kind == "cold" and (
        reuse_generation_run_id is not None or reuse_attempt_id is not None
    ):
        raise ValueError("cold attempt cannot claim reused generation lineage")
    if attempt_kind == "ledger_only" and (
        reuse_generation_run_id is None or reuse_attempt_id is None
    ):
        raise ValueError("ledger-only attempt is missing reused generation lineage")

    if (
        not isinstance(cost_chain, dict)
        or cost_chain.get("schema") != "claim-verifier-attempt-cost-chain/v1"
        or cost_chain.get("ledger_file") != CLAIM_VERIFIER_ATTEMPTS
        or cost_chain.get("chain_id") != chain_id
    ):
        raise ValueError("full attempt-cost chain evidence is missing")
    validated_ledger_event_count = _required_count(
        cost_chain,
        "validated_full_ledger_count",
        minimum=1,
    )
    validated_ledger_sha256 = cost_chain.get("validated_full_ledger_sha256")
    if (
        validated_ledger_event_count < prefix_count
        or not _is_sha256(validated_ledger_sha256)
    ):
        raise ValueError("full attempt-cost ledger evidence is invalid")
    current_attempt_count = _required_count(
        cost_chain,
        "attempt_count",
        minimum=1,
    )
    if current_attempt_count < attempt_count:
        raise ValueError("full attempt-cost chain precedes the committed prefix")
    tail_attempt_id = _safe_source_generation(cost_chain.get("tail_attempt_id"))
    tail_attempt_kind = cost_chain.get("tail_attempt_kind")
    tail_attempt_status = cost_chain.get("tail_attempt_status")
    if tail_attempt_kind not in {"cold", "ledger_only"}:
        raise ValueError("full attempt-cost chain kind is invalid")
    if tail_attempt_status not in {"complete", "incomplete", "failed"}:
        raise ValueError("full attempt-cost chain status is invalid")
    cumulative = cost_chain.get("cumulative_metrics")
    if not isinstance(cumulative, dict):
        raise ValueError("full attempt-cost counters are missing")

    calls = _required_count(cumulative, "verifier_call_count")
    failed_calls = _required_count(cumulative, "verifier_failed_call_count")
    operation_failures = _required_count(
        cumulative,
        "verifier_operation_failure_count",
    )
    tokens = _required_count(cumulative, "verifier_tokens")
    reused_groups = _required_count(
        cumulative,
        "semantic_validation_reused_group_count",
    )
    candidate_groups = _required_count(
        cumulative,
        "semantic_verifier_candidate_count",
    )
    if reused_groups > candidate_groups:
        raise ValueError("attempt-chain reused group count exceeds candidates")
    usage_complete = cumulative.get("verifier_usage_complete")
    if not isinstance(usage_complete, bool):
        raise ValueError("attempt-chain usage completeness is invalid")
    reused_ratio = _strict_ratio(
        cumulative.get("semantic_validation_reused_group_ratio"),
        expected_numerator=reused_groups,
        expected_denominator=candidate_groups,
    )

    if (
        calls < max(committed_calls, int(final_metrics.get("verifier_call_count") or 0))
        or failed_calls < max(
            committed_failed_calls,
            int(final_metrics.get("verifier_failed_calls") or 0),
        )
        or operation_failures
        < max(
            committed_operation_failures,
            int(final_metrics.get("verifier_operation_failure_count") or 0),
        )
        or tokens < max(committed_tokens, int(final_metrics.get("verifier_tokens") or 0))
        or reused_groups < committed_reused
        or candidate_groups < committed_candidates
    ):
        raise ValueError("attempt-chain cumulative counters precede final counters")

    baseline_calls = int(final_metrics.get("no_ledger_baseline_call_count") or 0)
    baseline_tokens = int(final_metrics.get("no_ledger_baseline_tokens") or 0)
    return {
        "chain_id": str(chain_id),
        "attempt_id": str(tail_attempt_id),
        "attempt_count": current_attempt_count,
        "attempt_kind": str(tail_attempt_kind),
        "attempt_status": str(tail_attempt_status),
        "committed_attempt_id": str(attempt_id),
        "committed_attempt_kind": str(attempt_kind),
        "committed_attempt_status": str(attempt_status),
        "tail_is_committed": tail_attempt_id == attempt_id,
        "validated_ledger_event_count": validated_ledger_event_count,
        "cumulative_verifier_call_count": calls,
        "cumulative_verifier_failed_call_count": failed_calls,
        "cumulative_verifier_operation_failure_count": operation_failures,
        "cumulative_verifier_tokens": tokens,
        "cumulative_verifier_usage_complete": usage_complete,
        "cumulative_verifier_call_ratio": _cost_ratio(calls, baseline_calls),
        "cumulative_verifier_token_ratio": _cost_ratio(tokens, baseline_tokens),
        "reused_group_count": reused_groups,
        "candidate_group_count": candidate_groups,
        "reused_group_ratio": reused_ratio,
        "source_generations": {
            "document_generation_id": document_generation_id,
            "catalog_generation_id": catalog_generation_id,
            "target_generation_id": target_generation_id,
            "requirements_sha256": requirements_sha256,
            "reuse_generation_run_id": reuse_generation_run_id,
            "reuse_attempt_id": reuse_attempt_id,
        },
    }


def shadow_review_evidence_fingerprint(
    snapshot: dict[str, Any],
    claim_id: str,
    claim_hash: str,
) -> str:
    """Bind a human decision to the exact target, ledger row, and coverage evidence."""
    catalog = [
        row for row in (snapshot.get("catalog") or [])
        if isinstance(row, dict)
        and str(row.get("claim_id") or "") == claim_id
        and str(row.get("claim_hash") or "") == claim_hash
    ]
    ledger = [
        row for row in (snapshot.get("effective_ledger") or snapshot.get("ledger") or [])
        if isinstance(row, dict)
        and str(row.get("claim_id") or "") == claim_id
        and str(row.get("claim_hash") or "") == claim_hash
    ]
    if len(catalog) != 1 or len(ledger) != 1:
        raise ValueError("review claim identity is stale or ambiguous")
    groups = sorted(
        [
            row for row in (snapshot.get("groups") or [])
            if isinstance(row, dict) and str(row.get("claim_id") or "") == claim_id
        ],
        key=lambda row: str(row.get("coverage_group_id") or ""),
    )
    generation = dict(snapshot.get("generation_meta") or {})
    payload = {
        "version": CLAIM_REVIEW_EVIDENCE_VERSION,
        "document_generation_id": str(generation.get("document_generation_id") or ""),
        "catalog_generation_id": str(generation.get("catalog_generation_id") or ""),
        "target_generation_id": str(generation.get("target_generation_id") or ""),
        "target_review_authority_revision": str(
            generation.get("target_review_authority_revision") or ""
        ),
        "delivery_track": str(generation.get("delivery_track") or ""),
        "target_kind": str(generation.get("target_kind") or ""),
        "requirements_sha256": str(generation.get("requirements_sha256") or ""),
        "requirements_meta_sha256": str(
            generation.get("requirements_meta_sha256") or ""
        ),
        "claim": catalog[0],
        "ledger": ledger[0],
        "coverage_groups": groups,
    }
    digest = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def negative_audit_claim_refs(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Select a stable 10% audit sample from validated semantic negatives."""
    catalog_by_id = {
        str(row.get("claim_id") or ""): row
        for row in (snapshot.get("catalog") or [])
        if isinstance(row, dict) and str(row.get("claim_id") or "")
    }
    candidates: list[tuple[str, dict[str, str]]] = []
    for row in (snapshot.get("effective_ledger") or snapshot.get("ledger") or []):
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("claim_id") or "")
        claim = catalog_by_id.get(claim_id)
        claim_hash = str(row.get("claim_hash") or "")
        negative = row.get("semantic_negative")
        if (
            claim is None
            or row.get("resolution") != "excluded"
            or row.get("exclusion_kind") != "semantic"
            or not isinstance(negative, dict)
            or negative.get("status") != "validated"
            or str(claim.get("claim_hash") or "") != claim_hash
            or not claim_id
            or not claim_hash
        ):
            continue
        selection_key = hashlib.sha256(
            "\0".join((
                NEGATIVE_AUDIT_POLICY_VERSION,
                claim_id,
                claim_hash,
            )).encode("utf-8")
        ).hexdigest()
        candidates.append((selection_key, {
            "claim_id": claim_id,
            "claim_hash": claim_hash,
        }))
    if not candidates:
        return []
    sample_count = max(1, math.ceil(len(candidates) * NEGATIVE_AUDIT_SAMPLE_RATE))
    return [
        ref for _, ref in sorted(
            candidates,
            key=lambda item: (item[0], item[1]["claim_id"], item[1]["claim_hash"]),
        )[:sample_count]
    ]


def summarize_snapshot(
    *,
    run_id: str,
    document_id: str,
    sequence: int,
    snapshot: dict[str, Any],
    component_versions_current: bool,
    expected_generation_run_id: str | None = None,
    expected_attempt_chain_id: str | None = None,
) -> dict[str, Any]:
    """Reduce a committed snapshot to path-free, wording-free acceptance evidence."""
    generation = dict(snapshot.get("generation_meta") or {})
    generation_run_id = str(generation.get("run_id") or "")
    if (
        expected_generation_run_id is not None
        and generation_run_id != expected_generation_run_id
    ):
        raise _SnapshotIdentityMismatch("generation run id does not match manifest")
    safe_metrics = _safe_metrics(dict(snapshot.get("metrics") or {}))
    attempt_chain = _summarize_attempt_chain(
        generation,
        safe_metrics,
        dict(snapshot.get("attempt_cost_chain") or {}),
    )
    if (
        expected_attempt_chain_id is not None
        and attempt_chain["chain_id"] != expected_attempt_chain_id
    ):
        raise _SnapshotIdentityMismatch("attempt chain id does not match manifest")
    shadow = dict(generation.get("shadow_meta") or {})
    runtime = dict(shadow.get("verifier_runtime") or {})
    catalog_by_id = {
        str(row.get("claim_id") or ""): row
        for row in (snapshot.get("catalog") or [])
        if isinstance(row, dict) and str(row.get("claim_id") or "")
    }
    negative_audit_ids = {
        (row["claim_id"], row["claim_hash"])
        for row in negative_audit_claim_refs(snapshot)
    }
    claim_index: dict[str, dict[str, Any]] = {}
    for row in (snapshot.get("effective_ledger") or snapshot.get("ledger") or []):
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("claim_id") or "")
        claim = catalog_by_id.get(claim_id, {})
        claim_hash = str(row.get("claim_hash") or claim.get("claim_hash") or "")
        resolution = str(row.get("resolution") or "")
        if claim_id and claim_hash and resolution:
            claim_index[f"{claim_id}\0{claim_hash}"] = {
                "claim_id": claim_id,
                "claim_hash": claim_hash,
                "resolution": resolution,
                "review_evidence_fingerprint": shadow_review_evidence_fingerprint(
                    snapshot,
                    claim_id,
                    claim_hash,
                ),
                "negative_audit_selected": (
                    claim_id,
                    claim_hash,
                ) in negative_audit_ids,
            }
    return {
        "run_id": run_id,
        "generation_run_id": generation_run_id,
        "document_id": document_id,
        "sequence": sequence,
        "artifact_status": "valid",
        "error_code": None,
        "committed_at": str(generation.get("committed_at") or "") or None,
        "document_generation_id": str(generation.get("document_generation_id") or "") or None,
        "catalog_generation_id": str(generation.get("catalog_generation_id") or "") or None,
        "target_generation_id": str(generation.get("target_generation_id") or "") or None,
        "component_versions_current": bool(component_versions_current),
        "component_versions": {
            str(key): str(value)
            for key, value in sorted(dict(shadow.get("versions") or {}).items())
        },
        "scope": str(shadow.get("scope") or "") or None,
        "extraction_status": str(shadow.get("extraction_status") or "") or None,
        "accounting_status": str(shadow.get("accounting_status") or "") or None,
        "resolution_status": str(shadow.get("resolution_status") or "") or None,
        "termination_reason": str(shadow.get("termination_reason") or "") or None,
        "route_mode": str(shadow.get("route_mode") or "") or None,
        "semantic_verifier_enabled": shadow.get("semantic_verifier_enabled") is True,
        "verifier_runtime_fingerprint": str(runtime.get("fingerprint") or "") or None,
        "attempt_chain": attempt_chain,
        "metrics": safe_metrics,
        "_claim_index": claim_index,
    }


def collect_run(
    *,
    run_id: str,
    generation_run_id: str,
    document_id: str,
    sequence: int,
    output_dir: Path | str,
    attempt_chain_id: str,
) -> dict[str, Any]:
    """Load one immutable snapshot without copying paths or exception text into evidence."""
    try:
        snapshot = load_committed_shadow(output_dir)
        versions_current = committed_shadow_versions_are_current(
            snapshot,
            require_environment_match=False,
        )
        return summarize_snapshot(
            run_id=run_id,
            document_id=document_id,
            sequence=sequence,
            snapshot=snapshot,
            component_versions_current=versions_current,
            expected_generation_run_id=generation_run_id,
            expected_attempt_chain_id=attempt_chain_id,
        )
    except _SnapshotIdentityMismatch:
        return _blank_run(run_id, document_id, sequence, "snapshot_identity_mismatch")
    except (ClaimArtifactError, OSError, UnicodeError, ValueError, TypeError):
        return _blank_run(run_id, document_id, sequence, "snapshot_invalid")
    except Exception:  # pragma: no cover - defensive privacy boundary
        return _blank_run(run_id, document_id, sequence, "snapshot_unexpected_error")


def collect_golden_held_out() -> dict[str, Any]:
    """Load repository-owned held-out evidence without exposing paths or wording."""
    try:
        return summarize_held_out_review(load_golden_held_out())
    except (HeldOutEvidenceError, OSError, UnicodeError, ValueError, TypeError):
        return invalid_held_out_summary("golden_held_out_artifact_invalid")
    except Exception:  # pragma: no cover - defensive privacy boundary
        return invalid_held_out_summary("golden_held_out_unexpected_error")


def _gate(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _sum_metric(records: list[dict[str, Any]], key: str) -> int:
    return sum(int(record.get("metrics", {}).get(key) or 0) for record in records)


def _sum_attempt_metric(records: list[dict[str, Any]], key: str) -> int:
    return sum(int(record.get("attempt_chain", {}).get(key) or 0) for record in records)


def evaluate_phase0_evidence(
    dataset_id: str,
    records: list[dict[str, Any]],
    curation: dict[str, Any],
    golden_held_out: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate Phase 0 exit evidence without authorizing the Phase 1 transition."""
    ordered = sorted(records, key=lambda row: (int(row.get("sequence") or 0), row["run_id"]))
    valid = [row for row in ordered if row.get("artifact_status") == "valid"]
    run_ids = {str(row.get("run_id") or "") for row in ordered}
    records_by_run = {str(row.get("run_id") or ""): row for row in ordered}

    gates: dict[str, dict[str, str]] = {}
    gates["artifact_integrity"] = _gate(
        "pass" if len(valid) == len(ordered) else "fail",
        "artifacts_valid" if len(valid) == len(ordered) else "artifact_integrity_failure",
    )

    sequences = [int(row.get("sequence") or 0) for row in ordered]
    timestamps = [_timestamp(row.get("committed_at")) for row in ordered]
    enough_runs = len(ordered) >= MIN_CONSECUTIVE_RUNS
    contiguous = sequences == list(range(1, len(ordered) + 1))
    chronological = (
        len(valid) == len(ordered)
        and all(value is not None for value in timestamps)
        and all(timestamps[index] < timestamps[index + 1] for index in range(len(timestamps) - 1))
    )
    chain_ids = [
        str(row.get("attempt_chain", {}).get("chain_id") or "")
        for row in valid
    ]
    distinct_chains = (
        len(valid) == len(ordered)
        and all(chain_ids)
        and len(set(chain_ids)) == len(chain_ids)
    )
    if not enough_runs:
        gates["consecutive_runs"] = _gate("blocked", "consecutive_runs_missing")
    elif not contiguous or not chronological:
        gates["consecutive_runs"] = _gate("fail", "consecutive_run_order_invalid")
    elif not distinct_chains:
        gates["consecutive_runs"] = _gate(
            "fail",
            "consecutive_attempt_chain_identity_reused",
        )
    else:
        gates["consecutive_runs"] = _gate("pass", "consecutive_runs_present")

    if valid and all(row.get("component_versions_current") is True for row in valid):
        gates["current_component_versions"] = _gate("pass", "component_versions_current")
    else:
        gates["current_component_versions"] = _gate("fail", "stale_component_version")

    version_sets = {
        json.dumps(row.get("component_versions") or {}, sort_keys=True, separators=(",", ":"))
        for row in valid
    }
    gates["component_version_consistency"] = _gate(
        "pass" if valid and len(version_sets) == 1 else "fail",
        "component_versions_consistent"
        if valid and len(version_sets) == 1
        else "component_versions_mixed",
    )
    gates["full_scope"] = _gate(
        "pass" if valid and all(row.get("scope") == "full" for row in valid) else "fail",
        "full_scope" if valid and all(row.get("scope") == "full" for row in valid)
        else "non_full_scope_present",
    )
    extraction_status_success = bool(valid) and all(
        row.get("extraction_status") == "success" for row in valid
    )
    failed_extraction_units = _sum_metric(valid, "failed_extraction_units")
    if failed_extraction_units:
        gates["extraction_success"] = _gate(
            "fail", "failed_extraction_units_present"
        )
    elif extraction_status_success:
        gates["extraction_success"] = _gate("pass", "extraction_success")
    else:
        gates["extraction_success"] = _gate("fail", "extraction_not_successful")
    gates["source_accounting"] = _gate(
        "pass"
        if valid and all(row.get("accounting_status") == "complete" for row in valid)
        else "fail",
        "source_accounting_complete"
        if valid and all(row.get("accounting_status") == "complete" for row in valid)
        else "source_accounting_incomplete",
    )

    real_verifier = valid and all(
        row.get("route_mode") == "llm"
        and row.get("semantic_verifier_enabled") is True
        and int(row.get("metrics", {}).get("verifier_call_count") or 0) > 0
        and int(row.get("metrics", {}).get("verifier_tokens") or 0) > 0
        and int(row.get("metrics", {}).get("independent_verifier_call_count") or 0) > 0
        and int(row.get("metrics", {}).get("independent_verifier_tokens") or 0) > 0
        and row.get("metrics", {}).get("verifier_usage_complete") is True
        and int(row.get("metrics", {}).get("verifier_operation_failure_count") or 0) == 0
        and row.get("attempt_chain", {}).get("tail_is_committed") is True
        and row.get("attempt_chain", {}).get("attempt_status") == "complete"
        for row in valid
    )
    gates["real_semantic_verifier"] = _gate(
        "pass" if real_verifier else "blocked",
        "real_semantic_verifier_ran" if real_verifier else "real_semantic_verifier_not_run",
    )
    budget_authorized = valid and all(
        row.get("metrics", {}).get("verifier_budget_policy_version")
        == "llm-request-budget-v1"
        and int(row.get("metrics", {}).get("verifier_budget_max_calls") or 0) > 0
        and int(row.get("metrics", {}).get("verifier_budget_max_total_tokens") or 0) > 0
        for row in valid
    )
    budget_exhausted = any(
        row.get("termination_reason") == "budget_exhausted"
        or row.get("metrics", {}).get("verifier_budget_denied") is True
        for row in valid
    )
    if budget_exhausted:
        gates["verifier_budget"] = _gate("blocked", "verifier_budget_exhausted")
    elif not budget_authorized:
        gates["verifier_budget"] = _gate("blocked", "verifier_budget_not_authorized")
    else:
        gates["verifier_budget"] = _gate("pass", "verifier_budget_within_limits")
    baseline_lineage_current = valid and all(
        row.get("metrics", {}).get("no_ledger_baseline_lineage_match") is True
        for row in valid
    )
    gates["baseline_lineage"] = _gate(
        "pass" if baseline_lineage_current else "blocked",
        "baseline_lineage_current"
        if baseline_lineage_current
        else "baseline_lineage_mismatch",
    )
    cost_policy_current = bool(valid) and all(
        str(row.get("metrics", {}).get("verifier_cost_policy_version") or "")
        == CLAIM_COST_POLICY_VERSION
        and row.get("metrics", {}).get("verifier_call_increase_limit")
        == CLAIM_VERIFIER_CALL_INCREASE_LIMIT
        and row.get("metrics", {}).get("verifier_token_increase_limit")
        == CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT
        for row in valid
    )
    cumulative_cost_evidence_complete = bool(valid) and all(
        row.get("route_mode") == "llm"
        and row.get("semantic_verifier_enabled") is True
        and row.get("attempt_chain", {}).get("cumulative_verifier_usage_complete") is True
        and int(
            row.get("attempt_chain", {}).get("cumulative_verifier_call_count") or 0
        ) > 0
        and int(
            row.get("attempt_chain", {}).get("cumulative_verifier_tokens") or 0
        ) > 0
        and int(row.get("metrics", {}).get("no_ledger_baseline_call_count") or 0) > 0
        and int(row.get("metrics", {}).get("no_ledger_baseline_tokens") or 0) > 0
        and row.get("metrics", {}).get("no_ledger_baseline_lineage_match") is True
        for row in valid
    )
    cumulative_operation_failures = _sum_attempt_metric(
        valid,
        "cumulative_verifier_operation_failure_count",
    )
    cumulative_cost_within_limits = cumulative_cost_evidence_complete and all(
        float(
            row.get("attempt_chain", {})
            .get("cumulative_verifier_call_ratio", {})
            .get("value")
        ) <= CLAIM_VERIFIER_CALL_INCREASE_LIMIT
        and float(
            row.get("attempt_chain", {})
            .get("cumulative_verifier_token_ratio", {})
            .get("value")
        ) <= CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT
        for row in valid
    )
    if not cost_policy_current:
        gates["verifier_cost"] = _gate("blocked", "verifier_cost_policy_mismatch")
    elif not cumulative_cost_evidence_complete:
        gates["verifier_cost"] = _gate("blocked", "verifier_cost_evidence_missing")
    elif cumulative_cost_within_limits:
        gates["verifier_cost"] = _gate("pass", "verifier_cost_within_limits")
    else:
        gates["verifier_cost"] = _gate("fail", "verifier_cost_limit_exceeded")

    held_out_status = str(golden_held_out.get("evidence_status") or "invalid")
    if golden_held_out.get("artifact_status") != "valid":
        gates["golden_held_out_adjudication"] = _gate(
            "fail", "golden_held_out_artifact_invalid"
        )
    elif held_out_status == "pending":
        gates["golden_held_out_adjudication"] = _gate(
            "blocked", "golden_held_out_adjudication_pending"
        )
    elif held_out_status == "invalid":
        gates["golden_held_out_adjudication"] = _gate(
            "fail", "golden_held_out_adjudication_invalid"
        )
    elif held_out_status == "not_approved":
        gates["golden_held_out_adjudication"] = _gate(
            "fail", "golden_held_out_adjudication_not_approved"
        )
    elif held_out_status == "complete":
        gates["golden_held_out_adjudication"] = _gate(
            "pass", "golden_held_out_adjudication_complete"
        )
    else:
        gates["golden_held_out_adjudication"] = _gate(
            "fail", "golden_held_out_adjudication_invalid"
        )

    def current_claim(item: dict[str, Any]) -> dict[str, str] | None:
        record = records_by_run.get(str(item.get("run_id") or ""))
        if not record or record.get("artifact_status") != "valid":
            return None
        key = f"{item.get('claim_id') or ''}\0{item.get('claim_hash') or ''}"
        current = dict(record.get("_claim_index") or {}).get(key)
        return dict(current) if isinstance(current, dict) else None

    def current_resolution(item: dict[str, Any]) -> str | None:
        current = current_claim(item)
        return str(current.get("resolution") or "") if current is not None else None

    adjudications = [dict(row) for row in (curation.get("adjudications") or [])]
    reviewed_ids: set[str] = set()
    stale_adjudications = 0
    followup_adjudications = 0
    verifier_disagreements = 0
    duplicate_adjudications = 0
    missing_rationales = 0
    valid_adjudications = 0
    valid_adjudications_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
    seen_adjudications: set[tuple[str, str, str]] = set()
    for item in adjudications:
        identity = (
            str(item.get("run_id") or ""),
            str(item.get("claim_id") or ""),
            str(item.get("claim_hash") or ""),
        )
        if identity in seen_adjudications:
            duplicate_adjudications += 1
            continue
        seen_adjudications.add(identity)
        current = current_claim(item)
        resolution = str(current.get("resolution") or "") if current is not None else None
        category = str(item.get("category") or "")
        category_matches = (
            (category == "semantic_positive" and resolution == "covered")
            or (category in {"semantic_negative", "structural_exclusion"}
                and resolution == "excluded")
            or (category == "uncertain" and resolution == "uncertain")
        )
        if (
            resolution is None
            or resolution != str(item.get("ledger_resolution") or "")
            or not category_matches
            or str(item.get("review_evidence_fingerprint") or "")
            != str((current or {}).get("review_evidence_fingerprint") or "")
        ):
            stale_adjudications += 1
            continue
        valid_adjudications += 1
        valid_adjudications_by_identity[identity] = item
        reviewed_ids.add(str(item.get("run_id") or ""))
        verdict = str(item.get("verdict") or "")
        rationale_missing = verdict != "agree" and not str(
            item.get("rationale") or ""
        ).strip()
        if rationale_missing:
            missing_rationales += 1
        if verdict == "needs_followup":
            followup_adjudications += 1
        elif verdict == "disagree":
            verifier_disagreements += 1
    human_status = str(curation.get("human_review_status") or "pending")
    if human_status != "reviewed":
        gates["human_adjudication"] = _gate("blocked", "human_adjudication_pending")
    elif (
        not bool(str(curation.get("reviewed_by") or "").strip())
        or _timestamp(curation.get("reviewed_at")) is None
        or not adjudications
        or run_ids != reviewed_ids
        or stale_adjudications
        or duplicate_adjudications
        or missing_rationales
        or followup_adjudications
    ):
        gates["human_adjudication"] = _gate("fail", "human_adjudication_invalid")
    else:
        gates["human_adjudication"] = _gate("pass", "human_adjudication_complete")

    negative_audit_identities = {
        (
            str(record.get("run_id") or ""),
            str(claim.get("claim_id") or ""),
            str(claim.get("claim_hash") or ""),
        )
        for record in valid
        for claim in dict(record.get("_claim_index") or {}).values()
        if isinstance(claim, dict) and claim.get("negative_audit_selected") is True
    }
    reviewed_negative_audit = {
        identity: valid_adjudications_by_identity[identity]
        for identity in negative_audit_identities
        if identity in valid_adjudications_by_identity
        and str(valid_adjudications_by_identity[identity].get("category") or "")
        == "semantic_negative"
        and not (
            str(valid_adjudications_by_identity[identity].get("verdict") or "")
            != "agree"
            and not str(
                valid_adjudications_by_identity[identity].get("rationale") or ""
            ).strip()
        )
    }
    audit_disagreements = sum(
        str(item.get("verdict") or "") == "disagree"
        for item in reviewed_negative_audit.values()
    )
    if not negative_audit_identities:
        gates["negative_audit"] = _gate("pass", "negative_audit_not_applicable")
    elif len(reviewed_negative_audit) != len(negative_audit_identities):
        gates["negative_audit"] = _gate("blocked", "negative_audit_review_pending")
    else:
        gates["negative_audit"] = _gate("pass", "negative_audit_review_complete")

    known_omissions = [dict(row) for row in (curation.get("known_omissions") or [])]
    omission_total = len(known_omissions)
    omission_passed = sum(
        current_resolution(item) in {"covered", "uncertain"}
        for item in known_omissions
    )
    if omission_total <= 0:
        gates["known_omissions"] = _gate("blocked", "known_omission_evidence_missing")
    elif omission_passed != omission_total:
        gates["known_omissions"] = _gate("fail", "known_omission_not_conserved")
    else:
        gates["known_omissions"] = _gate("pass", "known_omissions_conserved")

    gate_statuses = {gate["status"] for gate in gates.values()}
    status = "fail" if "fail" in gate_statuses else "blocked" if "blocked" in gate_statuses else "pass"
    blocking_reasons = sorted({
        gate["reason"] for gate in gates.values() if gate["status"] != "pass"
    })
    cumulative_calls = _sum_attempt_metric(valid, "cumulative_verifier_call_count")
    cumulative_tokens = _sum_attempt_metric(valid, "cumulative_verifier_tokens")
    reused_groups = _sum_attempt_metric(valid, "reused_group_count")
    candidate_groups = _sum_attempt_metric(valid, "candidate_group_count")
    return {
        "schema": REPORT_SCHEMA_VERSION,
        "runner_version": CLAIM_ACCEPTANCE_VERSION,
        "dataset_id": dataset_id,
        "status": status,
        "phase1_entry_recommendation": (
            "eligible_for_user_decision" if status == "pass" else "not_eligible"
        ),
        "gates": gates,
        "totals": {
            "run_count": len(ordered),
            "valid_run_count": len(valid),
            "document_count": len({str(row.get("document_id") or "") for row in valid}),
            "catalog_total_count": _sum_metric(valid, "catalog_total_count"),
            "failed_extraction_units": failed_extraction_units,
            "eligible_claim_count": _sum_metric(valid, "eligible_claim_count"),
            "covered_count": _sum_metric(valid, "covered_count"),
            "uncertain_count": _sum_metric(valid, "uncertain_count"),
            "verifier_call_count": cumulative_calls,
            "verifier_tokens": cumulative_tokens,
            "final_verifier_call_count": _sum_metric(valid, "verifier_call_count"),
            "final_verifier_tokens": _sum_metric(valid, "verifier_tokens"),
            "cumulative_verifier_call_count": cumulative_calls,
            "cumulative_verifier_failed_call_count": _sum_attempt_metric(
                valid,
                "cumulative_verifier_failed_call_count",
            ),
            "cumulative_verifier_operation_failure_count": cumulative_operation_failures,
            "cumulative_verifier_tokens": cumulative_tokens,
            "reused_group_count": reused_groups,
            "candidate_group_count": candidate_groups,
            "reused_group_ratio": _cost_ratio(reused_groups, candidate_groups),
            "independent_verifier_call_count": _sum_metric(
                valid, "independent_verifier_call_count"
            ),
            "independent_verifier_tokens": _sum_metric(
                valid, "independent_verifier_tokens"
            ),
        },
        "curation_summary": {
            "human_review_status": (
                "reviewed" if curation.get("human_review_status") == "reviewed" else "pending"
            ),
            "reviewed_run_count": len(reviewed_ids),
            "reviewed_claim_count": valid_adjudications - missing_rationales,
            "stale_adjudication_count": stale_adjudications,
            "duplicate_adjudication_count": duplicate_adjudications,
            "missing_rationale_count": missing_rationales,
            "known_omission_total": omission_total,
            "known_omission_passed": omission_passed,
            "verifier_disagreement_count": verifier_disagreements,
            "negative_audit_policy_version": NEGATIVE_AUDIT_POLICY_VERSION,
            "negative_audit_sample_count": len(negative_audit_identities),
            "negative_audit_reviewed_count": len(reviewed_negative_audit),
            "audit_disagreement_rate": _cost_ratio(
                audit_disagreements,
                len(reviewed_negative_audit),
            ),
        },
        "golden_held_out_summary": dict(golden_held_out),
        "runs": [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in ordered
        ],
        "blocking_reasons": blocking_reasons,
    }


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_input_manifest(path: Path | str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimAcceptanceInputError("acceptance input is missing or invalid JSON") from exc
    errors = sorted(
        Draft202012Validator(_load_schema(INPUT_SCHEMA)).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        location = ".".join(str(value) for value in errors[0].absolute_path) or "$"
        raise ClaimAcceptanceInputError(f"acceptance input schema violation at {location}")
    run_ids = [str(row["run_id"]) for row in payload["runs"]]
    generation_run_ids = [str(row["generation_run_id"]) for row in payload["runs"]]
    sequences = [int(row["sequence"]) for row in payload["runs"]]
    if len(set(run_ids)) != len(run_ids):
        raise ClaimAcceptanceInputError("acceptance input has duplicate run_id")
    if len(set(generation_run_ids)) != len(generation_run_ids):
        raise ClaimAcceptanceInputError(
            "acceptance input has duplicate generation_run_id"
        )
    if len(set(sequences)) != len(sequences):
        raise ClaimAcceptanceInputError("acceptance input has duplicate sequence")
    curation = payload["curation"]
    for field in ("adjudications", "known_omissions"):
        identities = [
            (str(row["run_id"]), str(row["claim_id"]), str(row["claim_hash"]))
            for row in curation[field]
        ]
        if len(set(identities)) != len(identities):
            raise ClaimAcceptanceInputError(f"acceptance input has duplicate {field}")
    return payload


def run_acceptance(input_path: Path | str) -> dict[str, Any]:
    manifest = load_input_manifest(input_path)
    records = [
        collect_run(
            run_id=str(row["run_id"]),
            generation_run_id=str(row["generation_run_id"]),
            document_id=str(row["document_id"]),
            sequence=int(row["sequence"]),
            output_dir=Path(str(row["output_dir"])),
            attempt_chain_id=str(row["attempt_chain_id"]),
        )
        for row in manifest["runs"]
    ]
    report = evaluate_phase0_evidence(
        str(manifest["dataset_id"]),
        records,
        dict(manifest["curation"]),
        collect_golden_held_out(),
    )
    Draft202012Validator(_load_schema(REPORT_SCHEMA)).validate(report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate sanitized Phase 0 claim shadow transition evidence."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.output is not None and paths_alias(args.input, args.output):
            raise ClaimAcceptanceInputError(
                "acceptance report output must differ from acceptance input"
            )
        report = run_acceptance(args.input)
        if args.output is not None:
            atomic_write_json(args.output, report)
        if report["status"] == "pass":
            envelope = {
                "tool": "requirement-atomizer",
                "schema_version": ENVELOPE_SCHEMA_VERSION,
                "command": "claim-shadow-acceptance",
                "ok": True,
                "report": report,
            }
            code = 0
        else:
            envelope = {
                "tool": "requirement-atomizer",
                "schema_version": ENVELOPE_SCHEMA_VERSION,
                "command": "claim-shadow-acceptance",
                "ok": False,
                "error": {
                    "type": "acceptance_gate_not_met",
                    "message": "Phase 0 evidence does not permit a Phase 1 entry decision.",
                },
                "report": report,
            }
            code = 3
    except ClaimAcceptanceInputError as exc:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-acceptance",
            "ok": False,
            "error": {"type": "input_error", "message": str(exc)},
        }
        code = 2
    except OSError:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-acceptance",
            "ok": False,
            "error": {
                "type": "output_error",
                "message": "The acceptance report could not be written.",
            },
        }
        code = 3
    except Exception:  # pragma: no cover - final CLI privacy boundary
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-acceptance",
            "ok": False,
            "error": {
                "type": "unexpected_error",
                "message": "Claim shadow acceptance failed unexpectedly.",
            },
        }
        code = 1
    print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
