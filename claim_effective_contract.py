"""Shared effective-revision/metrics contract for the claim effective ledger.

The fold (claim_review_actions.fold_effective_ledger), the publisher
(claim_artifacts.publish_effective_snapshot) and the read-only loader all
compute the document effective revision, per-claim effective revisions and
effective metrics through this single implementation.  Persisted values that
disagree with a recomputation are fail-closed, never trusted.
"""
from __future__ import annotations

from typing import Any

from claim_artifacts import ClaimArtifactError, hash_json
from claim_ledger import (
    CLAIM_EFFECTIVE_LEDGER_SCHEMA,
    CLAIM_EFFECTIVE_REDUCER_VERSION,
    CLAIM_QUEUE_VERSION,
    CLAIM_REVIEW_BRIDGE_VERSION,
    current_effective_versions,
    effective_review_adapter_versions,
)

CLAIM_REVISION_INPUTS_VERSION = "claim-effective-revision-inputs/v2"
CLAIM_AUTHORITY_PROJECTION_VERSION = "claim-effective-authority-projection/v1"
CLAIM_EFFECTIVE_STATE_VERSION = "claim-effective-state/v1"


_EFFECTIVE_STATE_FIELDS = (
    "resolution",
    "classification",
    "classification_status",
    "exclusion_kind",
    "semantic_negative",
    "invalid_reasons",
    "effective_facts",
    "last_relevant_event_seq",
)


def effective_state_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in _EFFECTIVE_STATE_FIELDS}


def compute_effective_state_hash(row: dict[str, Any]) -> str:
    return hash_json(CLAIM_EFFECTIVE_STATE_VERSION, effective_state_projection(row))


def compute_effective_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    eligible = [row for row in rows if row.get("exclusion_kind") != "structural"]
    covered = sum(row.get("resolution") == "covered" for row in rows)
    semantic = sum(row.get("exclusion_kind") == "semantic" for row in rows)
    structural = sum(row.get("exclusion_kind") == "structural" for row in rows)
    uncertain = sum(row.get("resolution") == "uncertain" for row in rows)

    def ratio(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
        }

    return {
        "catalog_total_count": total,
        "eligible_claim_count": len(eligible),
        "covered_count": covered,
        "semantic_excluded_count": semantic,
        "structural_excluded_count": structural,
        "uncertain_count": uncertain,
        "inventory_accounted_ratio": ratio(total, total),
        "verified_coverage_ratio": ratio(covered, len(eligible)),
        "verified_semantic_exclusion_ratio": ratio(semantic, len(eligible)),
        "verified_exclusion_ratio": ratio(structural + semantic, total),
        "eligible_resolution_ratio": ratio(covered + semantic, len(eligible)),
        "structural_exclusion_ratio": ratio(structural, total),
    }


def compute_document_effective_revision(
    *,
    base_generation_id: str,
    last_event_seq: int,
    event_prefix_sha256: str,
    target_set_hash: str,
    requirement_review_state_hash: str,
    authority_projection_hash: str,
) -> str:
    from claim_artifacts import (
        CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
        CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    )

    return hash_json(
        "claim-document-effective-revision/v2",
        {
            "base_generation_id": base_generation_id,
            "last_event_seq": last_event_seq,
            "event_prefix_sha256": event_prefix_sha256,
            "target_set_hash": target_set_hash,
            "requirement_review_state_hash": requirement_review_state_hash,
            "authority_projection_hash": authority_projection_hash,
            "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
            "effective_snapshot_version": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            "effective_artifact_version": (
                CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
            ),
            "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
            "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
            "queue_version": CLAIM_QUEUE_VERSION,
        },
    )


def build_claim_revision_inputs(
    *,
    base_claim_row_hash: str,
    ordered_relevant_event_hashes: list[str],
    linked_targets: list[dict[str, Any]],
    expert_overlay: dict[str, Any],
    effective_state: dict[str, Any],
) -> dict[str, Any]:
    """Persistable revision inputs for one effective row."""
    event_hashes = [str(value) for value in ordered_relevant_event_hashes]
    target_projection = list(linked_targets)
    overlay_projection = dict(expert_overlay)
    effective_state_hash = compute_effective_state_hash(effective_state)
    authority_projection_hash = hash_json(
        CLAIM_AUTHORITY_PROJECTION_VERSION,
        {
            "ordered_relevant_event_hashes": event_hashes,
            "linked_targets": target_projection,
            "expert_overlay": overlay_projection,
        },
    )
    return {
        "schema": CLAIM_REVISION_INPUTS_VERSION,
        "base_claim_row_hash": base_claim_row_hash,
        "ordered_relevant_event_hashes": event_hashes,
        "linked_targets": target_projection,
        "expert_overlay": overlay_projection,
        "authority_projection_hash": authority_projection_hash,
        "effective_state_hash": effective_state_hash,
        "versions": {
            "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
            "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
            "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
            "review_adapter_versions": effective_review_adapter_versions(),
        },
    }


def compute_claim_effective_revision(revision_inputs: dict[str, Any]) -> str:
    versions = dict(revision_inputs.get("versions") or {})
    return hash_json(
        "claim-effective-revision/v2",
        {
            "base_claim_row_hash": revision_inputs.get("base_claim_row_hash"),
            "ordered_relevant_event_hashes": list(
                revision_inputs.get("ordered_relevant_event_hashes") or []
            ),
            "linked_targets": list(revision_inputs.get("linked_targets") or []),
            "expert_overlay": dict(revision_inputs.get("expert_overlay") or {}),
            "authority_projection_hash": revision_inputs.get(
                "authority_projection_hash"
            ),
            "effective_state_hash": revision_inputs.get("effective_state_hash"),
            "effective_ledger_schema": versions.get("effective_ledger_schema"),
            "reducer_version": versions.get("reducer_version"),
            "bridge_version": versions.get("bridge_version"),
            "review_adapter_versions": versions.get("review_adapter_versions"),
        },
    )


def validate_effective_row_revision(row: dict[str, Any]) -> None:
    """Recompute one effective row's revision from its persisted inputs."""
    claim_id = str(row.get("claim_id") or "")
    revision_inputs = row.get("revision_inputs")
    if not isinstance(revision_inputs, dict):
        raise ClaimArtifactError(
            f"effective row {claim_id} is missing revision inputs"
        )
    if revision_inputs.get("schema") != CLAIM_REVISION_INPUTS_VERSION:
        raise ClaimArtifactError(
            f"effective row {claim_id} has stale revision inputs"
        )
    expected_versions = {
        "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
        "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
        "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
        "review_adapter_versions": effective_review_adapter_versions(),
    }
    if dict(revision_inputs.get("versions") or {}) != expected_versions:
        raise ClaimArtifactError(
            f"effective row {claim_id} has stale revision component versions"
        )
    if revision_inputs.get("base_claim_row_hash") != row.get("base_claim_row_hash"):
        raise ClaimArtifactError(
            f"effective row {claim_id} revision inputs disagree with its base row hash"
        )
    expected_projection_hash = hash_json(
        CLAIM_AUTHORITY_PROJECTION_VERSION,
        {
            "ordered_relevant_event_hashes": list(
                revision_inputs.get("ordered_relevant_event_hashes") or []
            ),
            "linked_targets": list(revision_inputs.get("linked_targets") or []),
            "expert_overlay": dict(revision_inputs.get("expert_overlay") or {}),
        },
    )
    if revision_inputs.get("authority_projection_hash") != expected_projection_hash:
        raise ClaimArtifactError(
            f"effective row {claim_id} authority projection does not recompute"
        )
    expected_state_hash = compute_effective_state_hash(row)
    if revision_inputs.get("effective_state_hash") != expected_state_hash:
        raise ClaimArtifactError(
            f"effective row {claim_id} state projection does not recompute"
        )
    expected = compute_claim_effective_revision(revision_inputs)
    if row.get("claim_effective_revision") != expected:
        raise ClaimArtifactError(
            f"effective row {claim_id} claim effective revision does not recompute"
        )


def compute_effective_authority_projection_hash(
    rows: list[dict[str, Any]],
) -> str:
    """Bind the ordered per-claim authority projections into snapshot meta."""
    return hash_json(
        "claim-effective-authority-projection-set/v1",
        [
            {
                "claim_id": str(row.get("claim_id") or ""),
                "authority_projection_hash": dict(
                    row.get("revision_inputs") or {}
                ).get("authority_projection_hash"),
                "effective_state_hash": dict(
                    row.get("revision_inputs") or {}
                ).get("effective_state_hash"),
                "claim_effective_revision": row.get("claim_effective_revision"),
            }
            for row in rows
        ],
    )


def validate_authoritative_effective_rows(
    persisted_rows: list[dict[str, Any]],
    authoritative_rows: list[dict[str, Any]],
) -> None:
    """Require the persisted projection to equal a pure authority reduction."""
    if len(persisted_rows) != len(authoritative_rows):
        raise ClaimArtifactError(
            "effective ledger differs from authoritative reduction: row count"
        )
    for persisted, authoritative in zip(
        persisted_rows, authoritative_rows, strict=True
    ):
        claim_id = str(persisted.get("claim_id") or "")
        if persisted != authoritative:
            differing = sorted({
                *persisted.keys(), *authoritative.keys()
            } - {
                key
                for key in {*persisted.keys(), *authoritative.keys()}
                if persisted.get(key) == authoritative.get(key)
            })
            raise ClaimArtifactError(
                "effective row differs from authoritative reduction"
                f" for {claim_id}: {', '.join(differing)}"
            )


def validate_effective_meta_consistency(
    effective_meta: dict[str, Any],
    effective_ledger: list[dict[str, Any]],
    *,
    authoritative_ledger: list[dict[str, Any]] | None = None,
) -> None:
    """Recompute document revision + metrics and compare item by item."""
    expected_components = {
        "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
        "review_adapter_versions": effective_review_adapter_versions(),
        "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
        "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
        "queue_version": CLAIM_QUEUE_VERSION,
    }
    for field, expected_value in expected_components.items():
        if effective_meta.get(field) != expected_value:
            raise ClaimArtifactError(
                f"effective meta has stale component version: {field}"
            )
    expected_versions = {
        **current_effective_versions(),
        "revision_inputs": CLAIM_REVISION_INPUTS_VERSION,
    }
    if dict(effective_meta.get("versions") or {}) != expected_versions:
        raise ClaimArtifactError("effective meta has a stale version vector")
    expected_revision = compute_document_effective_revision(
        base_generation_id=str(effective_meta.get("base_generation_id") or ""),
        last_event_seq=int(effective_meta.get("last_event_seq") or 0),
        event_prefix_sha256=str(effective_meta.get("event_prefix_sha256") or ""),
        target_set_hash=str(effective_meta.get("target_set_hash") or ""),
        requirement_review_state_hash=str(
            effective_meta.get("requirement_review_state_hash") or ""
        ),
        authority_projection_hash=str(
            effective_meta.get("authority_projection_hash") or ""
        ),
    )
    if effective_meta.get("document_effective_revision") != expected_revision:
        raise ClaimArtifactError(
            "effective document revision does not recompute from committed meta"
        )
    expected_metrics = compute_effective_metrics(list(effective_ledger))
    if effective_meta.get("effective_metrics") != expected_metrics:
        raise ClaimArtifactError(
            "effective metrics do not recompute from the committed ledger"
        )
    for row in effective_ledger:
        validate_effective_row_revision(row)
    expected_projection_hash = compute_effective_authority_projection_hash(
        effective_ledger
    )
    if effective_meta.get("authority_projection_hash") != expected_projection_hash:
        raise ClaimArtifactError(
            "effective authority projection does not recompute from the ledger"
        )
    if authoritative_ledger is not None:
        validate_authoritative_effective_rows(
            effective_ledger,
            authoritative_ledger,
        )
