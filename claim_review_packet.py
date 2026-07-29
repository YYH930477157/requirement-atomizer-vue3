"""Generate a machine-local, offline Phase 0 claim adjudication packet."""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from claim_acceptance import (
    ClaimAcceptanceInputError,
    load_input_manifest,
    negative_audit_claim_refs,
    shadow_review_evidence_fingerprint,
)
from claim_artifacts import (
    ClaimArtifactError,
    atomic_write_json,
    atomic_write_text,
    committed_shadow_versions_are_current,
    load_committed_shadow,
    paths_alias,
)
from claim_held_out import (
    HELD_OUT_REVIEW_DIMENSIONS,
    HeldOutEvidenceError,
    load_golden_held_out,
)


REVIEW_PACKET_VERSION = "claim-shadow-review-packet-v7"
REVIEW_PACKET_SCHEMA = "claim-shadow-review-packet/v5"
REVIEW_DECISIONS_SCHEMA = "claim-shadow-review-decisions/v3"
ENVELOPE_SCHEMA_VERSION = "1.0"
PACKET_JSON_NAME = "claim-shadow-review-packet.json"
PACKET_HTML_NAME = "claim-shadow-review-packet.html"
UNAVAILABLE = "unavailable"


class ReviewPacketError(ValueError):
    """Review evidence cannot be assembled from the committed snapshots."""


def _category(ledger: dict[str, Any]) -> str:
    resolution = str(ledger.get("resolution") or "")
    if resolution == "covered":
        return "semantic_positive"
    if resolution == "excluded":
        return (
            "structural_exclusion"
            if ledger.get("exclusion_kind") == "structural"
            else "semantic_negative"
        )
    return "uncertain"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_value(
    sources: Sequence[dict[str, Any]],
    names: Sequence[str],
    *,
    kind: str,
) -> Any:
    for source in sources:
        for name in names:
            if name not in source:
                continue
            value = source[name]
            if kind == "text" and isinstance(value, str) and value:
                return value
            if (
                kind == "count"
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            ):
                return value
            if kind == "ratio" and isinstance(value, dict):
                numerator = value.get("numerator")
                denominator = value.get("denominator")
                ratio = value.get("value")
                if (
                    isinstance(numerator, int)
                    and not isinstance(numerator, bool)
                    and numerator >= 0
                    and isinstance(denominator, int)
                    and not isinstance(denominator, bool)
                    and denominator >= 0
                    and (ratio is None or (
                        isinstance(ratio, (int, float))
                        and not isinstance(ratio, bool)
                    ))
                ):
                    return {
                        "numerator": numerator,
                        "denominator": denominator,
                        "value": ratio,
                    }
    return UNAVAILABLE


def _attempt_chain_for_packet(snapshot: dict[str, Any]) -> dict[str, Any]:
    generation_meta = _mapping(snapshot.get("generation_meta"))
    committed_chain = _mapping(generation_meta.get("attempt_chain"))
    cost_chain = _mapping(snapshot.get("attempt_cost_chain"))
    shadow_meta = _mapping(generation_meta.get("shadow_meta"))
    snapshot_meta = _mapping(snapshot.get("meta"))
    metrics = _mapping(snapshot.get("metrics"))
    chains = [
        candidate
        for candidate in (
            cost_chain,
            committed_chain,
            _mapping(shadow_meta.get("attempt_chain")),
            _mapping(snapshot_meta.get("attempt_chain")),
            _mapping(metrics.get("attempt_chain")),
            _mapping(snapshot.get("attempt_chain")),
        )
        if candidate
    ]
    current_sources = [
        value
        for chain in chains
        for value in (
            _mapping(chain.get("current")),
            _mapping(chain.get("current_attempt")),
        )
        if value
    ]
    cumulative_sources = [
        value
        for chain in chains
        for value in (
            _mapping(chain.get("cumulative_metrics")),
            _mapping(chain.get("cumulative")),
        )
        if value
    ]
    cumulative_verifier_sources = [
        _mapping(value.get("verifier"))
        for value in cumulative_sources
        if _mapping(value.get("verifier"))
    ]
    reuse_sources = [
        value
        for chain in chains
        for value in (
            _mapping(chain.get("reuse")),
            _mapping(chain.get("cumulative_metrics")),
            _mapping(chain.get("cumulative")),
        )
        if value
    ]

    general_sources = [
        *chains,
        *current_sources,
        generation_meta,
        shadow_meta,
        snapshot_meta,
        metrics,
    ]
    explicit_cumulative_sources = [*chains, generation_meta, shadow_meta, snapshot_meta, metrics]
    reused_group_count = _first_value(
        reuse_sources,
        (
            "reused_group_count",
            "reused_coverage_group_count",
            "coverage_validation_reused_group_count",
            "semantic_validation_reused_group_count",
        ),
        kind="count",
    )
    reused_group_ratio = _first_value(
        reuse_sources,
        (
            "reused_group_ratio",
            "reused_coverage_group_ratio",
            "coverage_validation_reused_group_ratio",
            "semantic_validation_reused_group_ratio",
        ),
        kind="ratio",
    )

    cumulative_verifier_call_count = _first_value(
        explicit_cumulative_sources,
        (
            "cumulative_verifier_call_count",
            "cumulative_verifier_calls",
            "verifier_call_count_cumulative",
        ),
        kind="count",
    )
    if cumulative_verifier_call_count == UNAVAILABLE:
        cumulative_verifier_call_count = _first_value(
            [*cumulative_verifier_sources, *cumulative_sources],
            ("verifier_call_count", "calls"),
            kind="count",
        )
    cumulative_verifier_tokens = _first_value(
        explicit_cumulative_sources,
        (
            "cumulative_verifier_tokens",
            "verifier_tokens_cumulative",
        ),
        kind="count",
    )
    if cumulative_verifier_tokens == UNAVAILABLE:
        cumulative_verifier_tokens = _first_value(
            [*cumulative_verifier_sources, *cumulative_sources],
            ("verifier_tokens", "tokens"),
            kind="count",
        )
    cumulative_verifier_failed_call_count = _first_value(
        [*cumulative_verifier_sources, *cumulative_sources],
        ("verifier_failed_call_count", "failed_calls"),
        kind="count",
    )
    cumulative_verifier_operation_failure_count = _first_value(
        [*cumulative_verifier_sources, *cumulative_sources],
        ("verifier_operation_failure_count", "operation_failures"),
        kind="count",
    )
    cumulative_usage_complete: bool | str = UNAVAILABLE
    for source in [*cumulative_verifier_sources, *cumulative_sources]:
        value = source.get("verifier_usage_complete")
        if isinstance(value, bool):
            cumulative_usage_complete = value
            break

    current_attempt_id = _first_value(
        [cost_chain, *general_sources],
        ("tail_attempt_id", "attempt_id"),
        kind="text",
    )
    committed_attempt_id = _first_value(
        [committed_chain],
        ("attempt_id",),
        kind="text",
    )
    tail_is_committed: bool | str = UNAVAILABLE
    if current_attempt_id != UNAVAILABLE and committed_attempt_id != UNAVAILABLE:
        tail_is_committed = current_attempt_id == committed_attempt_id

    source_locator: dict[str, Any] | str = UNAVAILABLE
    for chain in chains:
        candidate = chain.get("source_locator")
        if isinstance(candidate, dict) and candidate:
            source_locator = dict(candidate)
            break

    return {
        "chain_id": _first_value(
            general_sources,
            ("attempt_chain_id", "chain_id"),
            kind="text",
        ),
        "attempt_id": current_attempt_id,
        "committed_attempt_id": committed_attempt_id,
        "tail_is_committed": tail_is_committed,
        "attempt_kind": _first_value(
            [cost_chain, *general_sources],
            ("tail_attempt_kind", "attempt_kind", "kind"),
            kind="text",
        ),
        "attempt_status": _first_value(
            [cost_chain, *general_sources],
            ("tail_attempt_status", "attempt_status", "status"),
            kind="text",
        ),
        "attempt_count": _first_value(
            general_sources,
            ("attempt_count", "count"),
            kind="count",
        ),
        "cumulative_verifier_call_count": cumulative_verifier_call_count,
        "cumulative_verifier_failed_call_count": (
            cumulative_verifier_failed_call_count
        ),
        "cumulative_verifier_operation_failure_count": (
            cumulative_verifier_operation_failure_count
        ),
        "cumulative_verifier_tokens": cumulative_verifier_tokens,
        "cumulative_verifier_usage_complete": cumulative_usage_complete,
        "reused_group_count": reused_group_count,
        "reused_group_ratio": reused_group_ratio,
        "source_locator": source_locator,
    }


def _generation_locator(value: Any) -> dict[str, Any] | str:
    if isinstance(value, dict) and value:
        return dict(value)
    if isinstance(value, str) and value:
        return {"generation_id": value}
    return UNAVAILABLE


def _validation_source_for_packet(
    record: dict[str, Any],
    *,
    negative: bool = False,
) -> dict[str, Any]:
    source = _mapping(record.get("validation_source"))
    provenance = _mapping(record.get("validation_provenance"))
    request_sources = [source, provenance, record]
    if negative:
        request_sources.extend((
            _mapping(record.get("validation")),
            _mapping(record.get("proposal")),
        ))
    request_id = _first_value(
        request_sources,
        (
            "request_id",
            "source_request_id",
            "validation_source_request_id",
            "validator_request_id",
        ),
        kind="text",
    )

    locator: dict[str, Any] | str = UNAVAILABLE
    for holder in (source, provenance, record):
        for name in (
            "generation_locator",
            "source_generation_locator",
            "validation_source_generation_locator",
            "generation_run_id",
            "source_generation_id",
            "validation_source_generation_id",
        ):
            if name in holder:
                locator = (
                    {"generation_run_id": holder[name]}
                    if name == "generation_run_id"
                    and isinstance(holder[name], str)
                    and holder[name]
                    else _generation_locator(holder[name])
                )
                if locator != UNAVAILABLE:
                    break
        if locator != UNAVAILABLE:
            break
    return {
        "request_id": request_id,
        "generation_locator": locator,
    }


def _group_for_packet(
    group: dict[str, Any],
) -> dict[str, Any]:
    validation_reused = group.get("validation_reused")
    return {
        "coverage_group_id": str(group.get("coverage_group_id") or ""),
        "status": str(group.get("status") or ""),
        "validation_method": str(group.get("validation_method") or ""),
        "validation_reused": (
            validation_reused if isinstance(validation_reused, bool) else UNAVAILABLE
        ),
        "validation_source": _validation_source_for_packet(group),
        "prefilter_status": str(dict(group.get("prefilter") or {}).get("status") or ""),
        "validator_checks": dict(group.get("validator_checks") or {}),
        "validator_reason": str(group.get("validator_reason") or ""),
        "edges": [{
            "target_requirement_id": str(edge.get("target_requirement_id") or ""),
            "target_kind": str(edge.get("target_kind") or ""),
            "target_review_status": str(edge.get("target_review_status") or ""),
            "relation": str(edge.get("relation") or ""),
            "produced_evidence": [{
                "field": str(evidence.get("field") or ""),
                "item_index": evidence.get("item_index"),
                "start": evidence.get("start"),
                "end": evidence.get("end"),
                "text": str(evidence.get("text") or ""),
            } for evidence in (edge.get("produced_evidence") or [])],
        } for edge in (group.get("edges") or [])],
    }


def _select_claim_refs(
    run: dict[str, Any],
    snapshot: dict[str, Any],
    known_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}

    def add(ref: dict[str, Any], purpose: str) -> None:
        claim_id = str(ref.get("claim_id") or "")
        claim_hash = str(ref.get("claim_hash") or "")
        key = (claim_id, claim_hash)
        item = selected.setdefault(key, {
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "review_purposes": [],
        })
        if purpose not in item["review_purposes"]:
            item["review_purposes"].append(purpose)

    for row in known_refs:
        add(row, "known_omission")
    for row in negative_audit_claim_refs(snapshot):
        add(row, "negative_audit")
    if selected:
        return list(selected.values())

    ledger = list(snapshot.get("effective_ledger") or snapshot.get("ledger") or [])
    groups_by_claim: dict[str, list[dict[str, Any]]] = {}
    for group in snapshot.get("groups") or []:
        groups_by_claim.setdefault(str(group.get("claim_id") or ""), []).append(group)
    ordered = sorted(
        ledger,
        key=lambda row: (
            0 if any(
                group.get("validation_method") == "independent_semantic"
                for group in groups_by_claim.get(str(row.get("claim_id") or ""), [])
            ) else 1,
            0 if row.get("resolution") == "covered" else 1,
            str(row.get("claim_id") or ""),
        ),
    )
    if not ordered:
        raise ReviewPacketError(f"run {run.get('run_id')} has no reviewable claims")
    row = ordered[0]
    return [{
        "claim_id": str(row.get("claim_id") or ""),
        "claim_hash": str(row.get("claim_hash") or ""),
        "review_purposes": ["representative_review"],
    }]


def _shadow_item(
    *,
    run: dict[str, Any],
    snapshot: dict[str, Any],
    claim_ref: dict[str, Any],
) -> dict[str, Any]:
    claim_id = claim_ref["claim_id"]
    catalog_by_id = {
        str(row.get("claim_id") or ""): row
        for row in (snapshot.get("catalog") or [])
    }
    ledger_by_id = {
        str(row.get("claim_id") or ""): row
        for row in (snapshot.get("effective_ledger") or snapshot.get("ledger") or [])
    }
    claim = catalog_by_id.get(claim_id)
    ledger = ledger_by_id.get(claim_id)
    if (
        claim is None
        or ledger is None
        or str(claim.get("claim_hash") or "") != claim_ref["claim_hash"]
        or str(ledger.get("claim_hash") or "") != claim_ref["claim_hash"]
    ):
        raise ReviewPacketError("review claim identity is stale or missing")
    attempt_chain = _attempt_chain_for_packet(snapshot)
    groups = [
        _group_for_packet(group)
        for group in (snapshot.get("groups") or [])
        if str(group.get("claim_id") or "") == claim_id
    ]
    region = dict(claim.get("region_evidence") or {})
    semantic_negative = ledger.get("semantic_negative")
    if isinstance(semantic_negative, dict):
        semantic_negative = dict(semantic_negative)
        reused = semantic_negative.get("validation_reused")
        semantic_negative["validation_reused"] = (
            reused if isinstance(reused, bool) else UNAVAILABLE
        )
        semantic_negative["validation_source"] = _validation_source_for_packet(
            semantic_negative,
            negative=True,
        )
    return {
        "run_id": str(run.get("run_id") or ""),
        "document_id": str(run.get("document_id") or ""),
        "claim_id": claim_id,
        "claim_hash": claim_ref["claim_hash"],
        "review_purposes": list(claim_ref.get("review_purposes") or []),
        "review_evidence_fingerprint": shadow_review_evidence_fingerprint(
            snapshot,
            claim_id,
            claim_ref["claim_hash"],
        ),
        "source": {
            "text": str(claim.get("text") or ""),
            "raw_text": str(claim.get("raw_text") or ""),
            "source_kind": str(claim.get("source_kind") or ""),
            "section_path": list(claim.get("section_path") or []),
            "page_number": region.get("page_number"),
            "locator": dict(claim.get("locator") or {}),
        },
        "ledger": {
            "resolution": str(ledger.get("resolution") or ""),
            "classification": str(ledger.get("classification") or ""),
            "classification_status": str(ledger.get("classification_status") or ""),
            "exclusion_kind": ledger.get("exclusion_kind"),
            "invalid_reasons": list(ledger.get("invalid_reasons") or []),
        },
        "category": _category(ledger),
        "attempt_chain": attempt_chain,
        "coverage_groups": groups,
        "semantic_negative": semantic_negative,
    }


def build_review_packet(input_path: Path | str) -> dict[str, Any]:
    """Build sensitive review evidence without persisting it in the repository."""
    manifest = load_input_manifest(input_path)
    known_by_run: dict[str, list[dict[str, Any]]] = {}
    for row in manifest["curation"]["known_omissions"]:
        known_by_run.setdefault(str(row["run_id"]), []).append(dict(row))

    shadow_items: list[dict[str, Any]] = []
    for run in sorted(manifest["runs"], key=lambda row: int(row["sequence"])):
        snapshot = load_committed_shadow(Path(str(run["output_dir"])))
        generation = dict(snapshot.get("generation_meta") or {})
        attempt_chain = dict(generation.get("attempt_chain") or {})
        if str(generation.get("run_id") or "") != str(
            run.get("generation_run_id") or ""
        ):
            raise ReviewPacketError(
                f"run {run.get('run_id')} generation identity does not match manifest"
            )
        if str(attempt_chain.get("chain_id") or "") != str(
            run.get("attempt_chain_id") or ""
        ):
            raise ReviewPacketError(
                f"run {run.get('run_id')} attempt chain does not match manifest"
            )
        if not committed_shadow_versions_are_current(
            snapshot,
            require_environment_match=False,
        ):
            raise ReviewPacketError(
                f"run {run.get('run_id')} has stale component versions"
            )
        refs = _select_claim_refs(
            dict(run),
            snapshot,
            known_by_run.get(str(run["run_id"]), []),
        )
        shadow_items.extend(
            _shadow_item(run=dict(run), snapshot=snapshot, claim_ref=ref)
            for ref in refs
        )

    held_out = load_golden_held_out()
    declarations = {
        str(row.get("case_id") or ""): row
        for row in held_out["manifest"]["cases"]
    }
    held_out_items = []
    for item in held_out["review_items"]:
        held_out_items.append({
            "case_id": item["case_id"],
            "scenario": str(declarations[item["case_id"]].get("scenario") or ""),
            "claim_id": item["claim_id"],
            "claim_hash": item["claim_hash"],
            "fixture_hash": item["fixture_hash"],
            "source": {
                "text": item["source_text"],
                "raw_text": item["raw_text"],
                "section_path": item["section_path"],
                "locator": item["locator"],
            },
            "requirements": item["requirements"],
            "review_expectations": item["review_expectations"],
            "expected": item["expected"],
            "actual": item["actual"],
        })

    shadow_review_by_identity = {
        (
            str(row.get("run_id") or ""),
            str(row.get("claim_id") or ""),
            str(row.get("claim_hash") or ""),
            str(row.get("review_evidence_fingerprint") or ""),
            str(row.get("ledger_resolution") or ""),
            str(row.get("category") or ""),
        ): row
        for row in (manifest["curation"].get("adjudications") or [])
        if isinstance(row, dict)
    }
    held_out_curation = dict(held_out["manifest"].get("curation") or {})
    held_out_review_by_identity = {
        (
            str(row.get("case_id") or ""),
            str(row.get("claim_id") or ""),
            str(row.get("claim_hash") or ""),
            str(row.get("fixture_hash") or ""),
        ): row
        for row in (held_out_curation.get("held_out_adjudications") or [])
        if isinstance(row, dict)
    }

    shadow_adjudications = []
    for item in shadow_items:
        existing = shadow_review_by_identity.get((
            item["run_id"],
            item["claim_id"],
            item["claim_hash"],
            item["review_evidence_fingerprint"],
            item["ledger"]["resolution"],
            item["category"],
        ))
        verdict = str((existing or {}).get("verdict") or "")
        shadow_adjudications.append({
            "run_id": item["run_id"],
            "claim_id": item["claim_id"],
            "claim_hash": item["claim_hash"],
            "review_evidence_fingerprint": item["review_evidence_fingerprint"],
            "ledger_resolution": item["ledger"]["resolution"],
            "category": item["category"],
            "verdict": verdict if verdict in {"agree", "disagree", "needs_followup"} else "",
            "rationale": str((existing or {}).get("rationale") or ""),
        })

    held_out_adjudications = []
    for item in held_out_items:
        existing = held_out_review_by_identity.get((
            item["case_id"],
            item["claim_id"],
            item["claim_hash"],
            item["fixture_hash"],
        ))
        existing_dimensions = dict((existing or {}).get("dimension_verdicts") or {})
        held_out_adjudications.append({
            "case_id": item["case_id"],
            "claim_id": item["claim_id"],
            "claim_hash": item["claim_hash"],
            "fixture_hash": item["fixture_hash"],
            "dimension_verdicts": {
                dimension: (
                    str(existing_dimensions.get(dimension) or "")
                    if str(existing_dimensions.get(dimension) or "")
                    in {"agree", "disagree", "needs_followup", "not_reviewed"}
                    else ""
                )
                for dimension in HELD_OUT_REVIEW_DIMENSIONS
            },
            "rationale": str((existing or {}).get("rationale") or ""),
        })

    decision_template = {
        "schema": REVIEW_DECISIONS_SCHEMA,
        "dataset_id": str(manifest["dataset_id"]),
        "reviewed_by": str(manifest["curation"].get("reviewed_by") or ""),
        "reviewed_at": "",
        "shadow_adjudications": shadow_adjudications,
        "golden_held_out": {
            "dataset_id": str(held_out["manifest"]["dataset_id"]),
            "dataset_version": str(held_out["manifest"]["version"]),
            "adjudications": held_out_adjudications,
        },
    }
    return {
        "schema": REVIEW_PACKET_SCHEMA,
        "generator_version": REVIEW_PACKET_VERSION,
        "dataset_id": str(manifest["dataset_id"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sensitive": True,
        "storage_policy": "machine_local_do_not_commit",
        "shadow_items": shadow_items,
        "golden_held_out": {
            "dataset_id": str(held_out["manifest"]["dataset_id"]),
            "dataset_version": str(held_out["manifest"]["version"]),
            "items": held_out_items,
        },
        "decision_template": decision_template,
    }


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _integrity_block(*values: tuple[str, Any]) -> str:
    rows = "".join(
        f"<div><dt>{_e(label)}</dt><dd><code>{_e(value)}</code></dd></div>"
        for label, value in values
    )
    return f"<details class=\"integrity\"><summary>Integrity</summary><dl>{rows}</dl></details>"


def _verdict_options(selected: str) -> str:
    options = [("", "Select"), ("agree", "Agree"), ("disagree", "Disagree"),
               ("needs_followup", "Needs follow-up")]
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{label}</option>'
        for value, label in options
    )


def _shadow_verdict_control(index: int, decision: dict[str, Any]) -> str:
    return (
        f'<div class="decision"><label>Verdict<select data-verdict="{index}" required>'
        f'{_verdict_options(str(decision.get("verdict") or ""))}</select></label>'
        f'<label>Rationale<textarea data-rationale="{index}" rows="3">'
        f'{_e(decision.get("rationale") or "")}</textarea></label></div>'
    )


_DIMENSION_LABELS = {
    "claim_boundary": "Claim boundary",
    "eligibility": "Eligibility",
    "resolution": "Ledger resolution",
    "coverage": "Coverage state",
    "target_obligation_subject": "Product obligation subject",
    "target_modality": "Normative modality",
    "role_object_preservation": "Role and object preservation",
}


def _held_out_dimension_controls(index: int, decision: dict[str, Any]) -> str:
    selected = dict(decision.get("dimension_verdicts") or {})
    rows = "".join(
        '<label><span>' + _e(_DIMENSION_LABELS.get(dimension, dimension)) + '</span>'
        f'<select data-dimension="{_e(dimension)}" required>'
        + _verdict_options(str(selected.get(dimension) or ""))
        + '<option value="not_reviewed"'
        + (' selected' if selected.get(dimension) == "not_reviewed" else "")
        + '>Not reviewed</option></select></label>'
        for dimension in HELD_OUT_REVIEW_DIMENSIONS
    )
    return (
        f'<div class="dimension-review" data-dimension-review="{index}">{rows}</div>'
        f'<div class="decision decision-rationale"><label>Rationale'
        f'<textarea data-rationale="{index}" required rows="3">'
        f'{_e(decision.get("rationale") or "")}</textarea></label></div>'
    )


def _display_reused(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return UNAVAILABLE


def _display_locator(value: Any) -> str:
    if isinstance(value, dict) and value:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value) if isinstance(value, str) and value else UNAVAILABLE


def _display_ratio(value: Any) -> str:
    if not isinstance(value, dict):
        return UNAVAILABLE
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    ratio = value.get("value")
    if ratio is None:
        return f"{numerator} / {denominator}"
    return f"{numerator} / {denominator} ({float(ratio):.1%})"


def _attempt_chain_html(attempt: dict[str, Any]) -> str:
    rows = (
        ("Attempt kind", attempt["attempt_kind"]),
        ("Attempt status", attempt["attempt_status"]),
        ("Tail is committed", attempt["tail_is_committed"]),
        ("Attempt count", attempt["attempt_count"]),
        ("Cumulative verifier calls", attempt["cumulative_verifier_call_count"]),
        ("Cumulative failed calls", attempt["cumulative_verifier_failed_call_count"]),
        (
            "Cumulative operation failures",
            attempt["cumulative_verifier_operation_failure_count"],
        ),
        ("Cumulative verifier tokens", attempt["cumulative_verifier_tokens"]),
        ("Cumulative usage complete", attempt["cumulative_verifier_usage_complete"]),
        ("Reused coverage groups", attempt["reused_group_count"]),
        (
            "Reused group ratio",
            _display_ratio(attempt["reused_group_ratio"]),
        ),
        ("Source locator", _display_locator(attempt["source_locator"])),
        ("Attempt chain", attempt["chain_id"]),
        ("Attempt ID", attempt["attempt_id"]),
    )
    values = "".join(
        f"<div><dt>{_e(label)}</dt><dd><code>{_e(value)}</code></dd></div>"
        for label, value in rows
    )
    return (
        '<details class="attempt-chain"><summary>Run provenance</summary>'
        f'<dl>{values}</dl></details>'
    )


def _negative_evidence_html(label: str, evidence: Any) -> str:
    if not isinstance(evidence, list):
        return ""
    rows = "".join(
        f'<li><blockquote lang="en">{_e(row.get("text") or "")}</blockquote></li>'
        for row in evidence
        if isinstance(row, dict) and str(row.get("text") or "").strip()
    )
    if not rows:
        return ""
    return (
        f'<div class="negative-evidence"><strong>{_e(label)}</strong>'
        f'<ul>{rows}</ul></div>'
    )


def _negative_checks_html(checks: Any) -> str:
    if not isinstance(checks, dict) or not checks:
        return ""
    rows = "".join(
        f'<li><code>{_e(key)}</code>: {_e(value)}</li>'
        for key, value in sorted(checks.items())
    )
    return f'<div class="negative-checks"><strong>Validator checks</strong><ul>{rows}</ul></div>'


def _semantic_negative_html(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    proposal = _mapping(record.get("proposal"))
    validation = _mapping(record.get("validation"))
    source = _mapping(record.get("validation_source"))
    return (
        '<section class="negative-review">'
        '<h3>Excluded as a semantic negative</h3>'
        '<p>No target requirement is expected because the system classified this source span '
        'as non-normative.</p>'
        '<dl>'
        f'<div><dt>Proposal reason</dt><dd>{_e(proposal.get("reason") or UNAVAILABLE)}</dd></div>'
        f'<div><dt>Proposal rationale</dt><dd>{_e(proposal.get("rationale") or UNAVAILABLE)}</dd></div>'
        f'<div><dt>Validator reason</dt><dd>{_e(validation.get("reason") or UNAVAILABLE)}</dd></div>'
        f'<div><dt>Validator rationale</dt><dd>{_e(validation.get("rationale") or UNAVAILABLE)}</dd></div>'
        '</dl>'
        f'{_negative_evidence_html("Proposal evidence", proposal.get("evidence"))}'
        f'{_negative_evidence_html("Validator evidence", validation.get("evidence"))}'
        f'{_negative_checks_html(validation.get("checks"))}'
        '</section>'
        '<details class="validation-record">'
        '<summary>Semantic negative validation provenance</summary><dl>'
        f'<div><dt>Status</dt><dd>{_e(record.get("status") or UNAVAILABLE)}</dd></div>'
        f'<div><dt>Validation reused</dt><dd>{_e(_display_reused(record.get("validation_reused")))}</dd></div>'
        f'<div><dt>Source request</dt><dd><code>{_e(source.get("request_id") or UNAVAILABLE)}</code></dd></div>'
        f'<div><dt>Source generation</dt><dd><code>{_e(_display_locator(source.get("generation_locator")))}</code></dd></div>'
        '</dl></details>'
    )


def _shadow_html(
    item: dict[str, Any],
    index: int,
    decision: dict[str, Any],
) -> str:
    source = item["source"]
    ledger = item["ledger"]
    purpose_labels = {
        "known_omission": "Known omission",
        "negative_audit": "Negative audit",
    }
    review_purpose = " / ".join(
        purpose_labels.get(str(value), str(value).replace("_", " ").title())
        for value in item.get("review_purposes") or []
    ) or "Shadow evidence"
    evidence_rows: list[str] = []
    group_headers: list[str] = []
    for group in item["coverage_groups"]:
        validation_source = _mapping(group.get("validation_source"))
        group_headers.append(
            f'<div class="group-meta"><code>{_e(group["coverage_group_id"])}</code>'
            f'<span>{_e(group["validation_method"])}</span>'
            f'<span>{_e(group["status"])}</span>'
            f'<span>Validation reused: {_e(_display_reused(group.get("validation_reused")))}</span>'
            f'<span>Source request: <code>{_e(validation_source.get("request_id") or UNAVAILABLE)}</code></span>'
            f'<span>Source generation: <code>{_e(_display_locator(validation_source.get("generation_locator")))}</code></span>'
            '</div>'
        )
        for edge in group["edges"]:
            for evidence in edge["produced_evidence"]:
                item_index = "" if evidence["item_index"] is None else f'[{evidence["item_index"]}]'
                evidence_rows.append(
                    f'<tr><td><code>{_e(edge["target_requirement_id"])}</code></td>'
                    f'<td>{_e(evidence["field"])}{_e(item_index)}</td>'
                    f'<td lang="zh-CN">{_e(evidence["text"])}</td></tr>'
                )
    negative = _semantic_negative_html(item.get("semantic_negative"))
    evidence_table = (
        '<table><thead><tr><th>Target</th><th>Field</th><th>Produced evidence</th></tr></thead>'
        f'<tbody>{"".join(evidence_rows)}</tbody></table>'
        if evidence_rows else ("" if negative else '<p class="empty">No produced evidence.</p>')
    )
    raw = ""
    if source["raw_text"] and source["raw_text"] != source["text"]:
        raw = f'<details><summary>Raw parser text</summary><pre>{_e(source["raw_text"])}</pre></details>'
    section = " / ".join(str(value) for value in source["section_path"])
    return (
        f'<article class="review-item" data-kind="shadow" data-frozen="false" '
        f'data-held-out="false" data-index="{index}">'
        f'<header><div><span class="kind">{_e(review_purpose)}</span>'
        f'<h2>{_e(item["run_id"])} - {_e(review_purpose)}</h2><p>{_e(section)}</p></div>'
        '<div class="badges"><span class="badge badge-shadow">shadow</span>'
        '<span class="badge badge-neutral">not frozen</span>'
        '<span class="badge badge-neutral">not held-out</span>'
        f'<span class="badge badge-neutral">{_e(item["category"].replace("_", " "))}</span>'
        f'<span class="status status-{_e(ledger["resolution"])}">{_e(ledger["resolution"])}</span>'
        '</div></header>'
        f'<blockquote lang="en">{_e(source["text"])}</blockquote>{raw}'
        + f'{"".join(group_headers)}{evidence_table}{negative}'
        + _attempt_chain_html(item["attempt_chain"])
        + _integrity_block(
            ("Claim", item["claim_id"]),
            ("Claim hash", item["claim_hash"]),
            ("Review evidence", item["review_evidence_fingerprint"]),
            ("Category", item["category"]),
            ("Review purposes", ", ".join(item.get("review_purposes") or [])),
            ("Page", source["page_number"]),
        )
        + _shadow_verdict_control(index, decision)
        + '</article>'
    )


def _held_out_html(
    item: dict[str, Any],
    index: int,
    decision: dict[str, Any],
) -> str:
    requirements = "".join(
        f'<li><strong>{_e(row.get("title"))}</strong><p lang="zh-CN">{_e(row.get("description"))}</p></li>'
        for row in item["requirements"]
    )
    expected = json.dumps(item["expected"], ensure_ascii=False, indent=2)
    review_expectations = json.dumps(
        item.get("review_expectations") or {},
        ensure_ascii=False,
        indent=2,
    )
    return (
        f'<article class="review-item" data-kind="held-out" data-frozen="true" '
        f'data-held-out="true" data-index="{index}">'
        '<header><div><span class="kind">Frozen held-out regression case</span>'
        f'<h2>{_e(item["case_id"])}</h2><p>{_e(item["scenario"])}</p></div>'
        '<div class="badges"><span class="badge badge-frozen">frozen</span>'
        '<span class="badge badge-held-out">held-out</span>'
        '<span class="status status-synthetic">synthetic</span></div></header>'
        f'<blockquote lang="en">{_e(item["source"]["text"])}</blockquote>'
        f'<ul class="requirements">{requirements}</ul>'
        f'<details open><summary>Target formulation expectations</summary><pre>{_e(review_expectations)}</pre></details>'
        f'<details open><summary>Expected claim projection</summary><pre>{_e(expected)}</pre></details>'
        + _integrity_block(
            ("Claim", item["claim_id"]),
            ("Claim hash", item["claim_hash"]),
            ("Fixture hash", item["fixture_hash"]),
        )
        + _held_out_dimension_controls(index, decision)
        + '</article>'
    )


_STYLE = """
:root{color-scheme:light;--ink:#20242a;--muted:#626b75;--line:#d8dde3;--paper:#fff;--wash:#f4f6f7;--green:#1d6b4f;--amber:#9a6200;--red:#a33a35;--blue:#245f8f}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:0}
main{max-width:1180px;margin:0 auto;padding:28px 24px 96px}.top{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end;border-bottom:2px solid var(--ink);padding-bottom:18px}
h1{font-size:28px;line-height:1.15;margin:5px 0 6px}h2{font-size:18px;margin:3px 0}.eyebrow,.kind{font-size:12px;text-transform:uppercase;color:var(--muted);font-weight:700}.sensitive{color:var(--red);font-weight:700}
.reviewer{display:grid;grid-template-columns:minmax(220px,1fr) minmax(220px,1fr);gap:12px;margin:22px 0 34px}.reviewer label,.decision label{display:grid;gap:6px;font-weight:650}
input,select,textarea,button{font:inherit;letter-spacing:0}input,select,textarea{width:100%;border:1px solid #aeb6bf;border-radius:4px;background:#fff;padding:9px 10px;color:var(--ink)}textarea{resize:vertical;min-height:82px}
.section-title{display:flex;justify-content:space-between;align-items:end;gap:18px;margin:34px 0 12px}.section-title h2{font-size:21px}.section-title p{margin:1px 0 0;color:var(--muted)}.count{color:var(--muted);white-space:nowrap}
.review-item{background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:6px;padding:20px;margin:0 0 16px;box-shadow:0 1px 2px rgba(25,32,40,.05)}
.review-item[data-kind="held-out"]{border-left-color:var(--green)}.review-item header{display:flex;justify-content:space-between;gap:20px;align-items:start}.review-item header p{margin:0;color:var(--muted)}
.badges{display:flex;justify-content:flex-end;gap:6px;flex-wrap:wrap}.badge,.status{border:1px solid currentColor;border-radius:4px;padding:3px 7px;font-size:12px;font-weight:700;text-transform:uppercase}.badge-shadow{color:var(--blue)}.badge-neutral{color:var(--muted)}.badge-frozen{color:var(--green)}.badge-held-out{color:var(--amber)}.status-covered{color:var(--green)}.status-uncertain{color:var(--amber)}.status-excluded{color:var(--red)}.status-synthetic{color:var(--blue)}
blockquote{margin:18px 0;padding:14px 16px;border-left:3px solid #7c8792;background:#f7f8f9;font-size:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f7f8;border:1px solid var(--line);padding:12px;border-radius:4px;font-size:12px}
table{width:100%;border-collapse:collapse;margin:14px 0}th,td{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px 8px}th{background:#f1f3f5;font-size:12px}td:last-child{overflow-wrap:anywhere}
.attempt-chain{border-block:1px solid var(--line);margin:16px 0;padding:12px 0}.attempt-chain dl,.validation-record dl{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:6px 18px;margin:10px 0 0}.attempt-chain dl div,.validation-record dl div{display:grid;grid-template-columns:minmax(150px,1fr) minmax(110px,1fr);gap:8px}.attempt-chain dt,.validation-record dt{color:var(--muted)}.attempt-chain dd,.validation-record dd{margin:0;overflow-wrap:anywhere}
.group-meta{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:16px;color:var(--muted)}.group-meta span{border-left:1px solid var(--line);padding-left:10px}.validation-record{border-block:1px solid var(--line);padding:10px 0}.decision{display:grid;grid-template-columns:minmax(180px,240px) 1fr;gap:14px;border-top:1px solid var(--line);margin-top:18px;padding-top:18px}
.negative-review{border-block:1px solid var(--line);margin:14px 0;padding:12px 0}.negative-review h3{font-size:16px;margin:0 0 4px}.negative-review>p{margin:0 0 10px;color:var(--muted)}.negative-review dl{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:8px 18px;margin:0}.negative-review dl div{display:grid;grid-template-columns:minmax(130px,170px) 1fr;gap:8px}.negative-review dt{color:var(--muted)}.negative-review dd{margin:0}.negative-evidence,.negative-checks{margin-top:12px}.negative-evidence ul,.negative-checks ul{margin:6px 0 0;padding-left:22px}.negative-evidence blockquote{font-size:14px;margin:6px 0;padding:8px 12px}
.dimension-review{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:12px 16px;border-top:1px solid var(--line);margin-top:18px;padding-top:18px}.dimension-review label{display:grid;grid-template-columns:minmax(160px,1fr) minmax(150px,190px);align-items:center;gap:10px;font-weight:650}.decision-rationale{grid-template-columns:1fr}
details{margin:12px 0}summary{cursor:pointer;font-weight:650}.integrity dl{display:grid;gap:4px}.integrity dl div{display:grid;grid-template-columns:110px 1fr;gap:8px}.integrity dt{color:var(--muted)}.integrity dd{margin:0;overflow-wrap:anywhere}.requirements{padding-left:22px}.requirements p{margin:3px 0 10px}.empty{color:var(--muted)}
.export-result{border-top:2px solid var(--ink);margin-top:36px;padding-top:20px}.export-result[hidden]{display:none}.export-result h2{font-size:21px}.export-result p{color:var(--muted)}.export-result textarea{font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;min-height:220px}.export-actions{display:flex;justify-content:flex-end;margin-top:10px}.export-actions button{border:0;border-radius:4px;background:var(--blue);color:#fff;padding:9px 14px;font-weight:700;cursor:pointer}
.actionbar{position:fixed;left:0;right:0;bottom:0;background:rgba(255,255,255,.97);border-top:1px solid var(--line);padding:12px 24px;display:flex;justify-content:flex-end;align-items:center;gap:14px}.actionbar output{color:var(--red);font-weight:650}.actionbar button{border:0;border-radius:4px;background:var(--ink);color:#fff;padding:10px 16px;font-weight:700;cursor:pointer}.actionbar button:hover{background:#000}
@media(max-width:720px){main{padding:18px 12px 100px}.top,.reviewer,.decision,.dimension-review,.attempt-chain dl,.validation-record dl,.negative-review dl{grid-template-columns:1fr}.dimension-review label,.attempt-chain dl div,.validation-record dl div,.negative-review dl div{grid-template-columns:1fr}.section-title{align-items:start}.review-item{padding:15px}.review-item header{align-items:flex-start;flex-direction:column}.badges{justify-content:flex-start}table{display:block;overflow-x:auto}.actionbar{justify-content:stretch}.actionbar button{margin-left:auto}}
"""


_SCRIPT = """
const button=document.getElementById('export');
const message=document.getElementById('message');
const exportResult=document.getElementById('export-result');
const exportJson=document.getElementById('export-json');
const copyButton=document.getElementById('copy-export');
button.addEventListener('click',()=>{
  message.textContent='';
  try{
    const reviewedBy=document.getElementById('reviewed-by').value.trim();
    const reviewedAt=document.getElementById('reviewed-at').value;
    if(!reviewedBy||!reviewedAt){message.textContent='Reviewer and review time are required.';return;}
    const reviewedDate=new Date(reviewedAt);
    if(Number.isNaN(reviewedDate.getTime())){message.textContent='Review time is invalid.';return;}
    const output=JSON.parse(JSON.stringify(template));
    output.reviewed_by=reviewedBy;
    output.reviewed_at=reviewedDate.toISOString();
    const controls=[...document.querySelectorAll('.review-item')];
    for(const node of controls){
      const index=Number(node.dataset.index);
      const rationale=node.querySelector('[data-rationale]').value.trim();
      const target=node.dataset.kind==='shadow'?output.shadow_adjudications[index]:output.golden_held_out.adjudications[index];
      if(node.dataset.kind==='shadow'){
        const verdict=node.querySelector('[data-verdict]').value;
        if(!verdict){message.textContent='Every shadow item needs a verdict.';node.scrollIntoView({behavior:'smooth'});return;}
        if(verdict!=='agree'&&!rationale){message.textContent='Disagree and follow-up decisions need a rationale.';node.scrollIntoView({behavior:'smooth'});return;}
        target.verdict=verdict;
      }else{
        const dimensions=[...node.querySelectorAll('[data-dimension]')];
        for(const control of dimensions){
          if(!control.value){message.textContent='Every held-out dimension needs a verdict.';control.focus();return;}
          target.dimension_verdicts[control.dataset.dimension]=control.value;
        }
        if(!rationale){message.textContent='Held-out rationale is required.';node.scrollIntoView({behavior:'smooth'});return;}
      }
      target.rationale=rationale;
    }
    const serialized=JSON.stringify(output,null,2)+'\\n';
    exportJson.value=serialized;
    exportResult.hidden=false;
    const blob=new Blob([serialized],{type:'application/json'});
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');
    link.href=url;link.download='claim-shadow-review-decisions.json';link.hidden=true;
    document.body.appendChild(link);link.click();
    setTimeout(()=>{URL.revokeObjectURL(url);link.remove();},1500);
    message.textContent='Decisions are ready. If no file appears, use Copy decisions JSON.';
    exportResult.scrollIntoView({behavior:'smooth',block:'center'});
  }catch(error){
    console.error('Decision export failed',error);
    message.textContent='Export failed. Your form entries are still on this page.';
  }
});
copyButton.addEventListener('click',async()=>{
  const value=exportJson.value;
  if(!value){message.textContent='Prepare the decisions before copying.';return;}
  try{
    await navigator.clipboard.writeText(value);
    message.textContent='Decisions JSON copied.';
  }catch(error){
    exportJson.focus();exportJson.select();
    const copied=document.execCommand('copy');
    message.textContent=copied?'Decisions JSON copied.':'JSON selected. Press Ctrl+C to copy it.';
  }
});
"""


def render_review_html(packet: dict[str, Any]) -> str:
    decisions = packet["decision_template"]
    shadow = "".join(
        _shadow_html(item, index, decisions["shadow_adjudications"][index])
        for index, item in enumerate(packet["shadow_items"])
    )
    held_out_items = packet["golden_held_out"]["items"]
    held_out = "".join(
        _held_out_html(
            item,
            index,
            decisions["golden_held_out"]["adjudications"][index],
        )
        for index, item in enumerate(held_out_items)
    )
    template = json.dumps(
        packet["decision_template"],
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Phase 0 Claim Review</title><style>' + _STYLE + '</style></head><body><main>'
        '<header class="top"><div><div class="eyebrow">Requirement Atomizer</div>'
        '<h1>Phase 0 Claim Review</h1>'
        f'<div>Dataset <code>{_e(packet["dataset_id"])}</code></div></div>'
        '<div class="sensitive">Machine-local sensitive evidence</div></header>'
        '<section class="reviewer"><label>Independent reviewer'
        f'<input id="reviewed-by" autocomplete="name" value="{_e(decisions.get("reviewed_by") or "")}"></label>'
        '<label>Reviewed at<input id="reviewed-at" type="datetime-local"></label></section>'
        '<div class="section-title"><div><h2>Shadow evidence</h2>'
        '<p>Real run evidence · not frozen · not held-out</p></div>'
        f'<span class="count">{len(packet["shadow_items"])} items</span></div>{shadow}'
        '<div class="section-title"><div><h2>Frozen held-out</h2>'
        '<p>Repository-owned synthetic cases · frozen and held-out</p></div>'
        f'<span class="count">{len(held_out_items)} items</span></div>{held_out}'
        '<section class="export-result" id="export-result" hidden><div class="kind">Export fallback</div>'
        '<h2>Decisions JSON ready</h2><p>If the browser blocks the download, copy this JSON and return it for validation.</p>'
        '<textarea id="export-json" readonly aria-label="Decisions JSON"></textarea>'
        '<div class="export-actions"><button id="copy-export" type="button">Copy decisions JSON</button></div>'
        '</section></main><div class="actionbar"><output id="message" aria-live="polite"></output>'
        '<button id="export" type="button">Export decisions</button></div>'
        '<script>const template=' + template + ';' + _SCRIPT + '</script></body></html>'
    )


def write_review_packet(packet: dict[str, Any], output_dir: Path | str) -> dict[str, str]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / PACKET_JSON_NAME
    html_path = root / PACKET_HTML_NAME
    atomic_write_json(json_path, packet)
    atomic_write_text(html_path, render_review_html(packet))
    return {"json": str(json_path), "html": str(html_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a machine-local Phase 0 claim review packet."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        output_root = Path(args.output_dir).expanduser().resolve()
        if paths_alias(args.input, output_root / PACKET_JSON_NAME) or paths_alias(
            args.input,
            output_root / PACKET_HTML_NAME,
        ):
            raise ClaimAcceptanceInputError(
                "review packet outputs must differ from acceptance input"
            )
        packet = build_review_packet(args.input)
        outputs = write_review_packet(packet, args.output_dir)
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-packet",
            "ok": True,
            "outputs": outputs,
            "shadow_item_count": len(packet["shadow_items"]),
            "held_out_item_count": len(packet["golden_held_out"]["items"]),
        }
        code = 0
    except (ClaimAcceptanceInputError, ReviewPacketError) as exc:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-packet",
            "ok": False,
            "error": {"type": "input_error", "message": str(exc)},
        }
        code = 2
    except (ClaimArtifactError, HeldOutEvidenceError):
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-packet",
            "ok": False,
            "error": {
                "type": "artifact_error",
                "message": "Review evidence is missing, stale, or invalid.",
            },
        }
        code = 3
    except OSError:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-packet",
            "ok": False,
            "error": {
                "type": "output_error",
                "message": "The review packet could not be written.",
            },
        }
        code = 3
    print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
