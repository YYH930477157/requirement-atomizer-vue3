from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from result_package import governed_artifact_path

from claim_artifacts import (
    CLAIM_CATALOG,
    CLAIM_CATALOG_META,
    CLAIM_COVERAGE_GROUPS,
    CLAIM_EFFECTIVE_LEDGER,
    CLAIM_EFFECTIVE_META,
    CLAIM_GENERATION_META,
    CLAIM_LEDGER,
    CLAIM_QUEUE_PROPOSALS,
    CLAIM_SHADOW_METRICS,
    ClaimArtifactError,
    claim_base_generation_id,
    effective_snapshot_revision_key,
    hash_json,
    load_committed_effective_snapshot_cached,
)
from claim_review_actions import (
    assess_effective_freshness,
    claim_base_resolution_fact_hashes,
    claim_coverage_group_hash,
    claim_required_supersedes_fact_hashes,
    claim_source_evidence_hash,
    read_claim_review_events,
    read_effective_health,
)


CLAIM_VIEW_PHASE = "production-dual-write-v1"
_VIEW_SCHEMAS = {
    "catalog": "claim-catalog-view/v1",
    "ledger": "claim-ledger-view/v1",
    "coverage_groups": "claim-coverage-group-view/v1",
    "metrics": "claim-metrics-view/v1",
    "review_events": "claim-review-event-view/v1",
    "queue": "claim-queue-view/v1",
}
_COLLECTION_KEYS = {
    "catalog": "rows",
    "ledger": "rows",
    "coverage_groups": "groups",
    "review_events": "events",
    "queue": "proposals",
}
_BASE_FILES = {
    CLAIM_CATALOG,
    CLAIM_CATALOG_META,
    CLAIM_COVERAGE_GROUPS,
    CLAIM_LEDGER,
    CLAIM_SHADOW_METRICS,
    CLAIM_GENERATION_META,
    CLAIM_EFFECTIVE_LEDGER,
    CLAIM_EFFECTIVE_META,
    CLAIM_QUEUE_PROPOSALS,
}


class ClaimViewMigrationRequired(ClaimArtifactError):
    pass


def _unavailable(view: str) -> dict[str, Any]:
    from claim_structural_overrides import (
        empty_structural_candidate_decision_identity,
    )

    payload: dict[str, Any] = {
        "schema": _VIEW_SCHEMAS[view],
        "available": False,
        "phase": CLAIM_VIEW_PHASE,
        "document_effective_revision": None,
        "base_generation_id": None,
        "document_generation_id": None,
        "catalog_generation_id": None,
        "event_prefix_sha256": None,
        "last_event_seq": 0,
        "structural_candidate_decision_registry": (
            empty_structural_candidate_decision_identity()
        ),
        "effective_fresh": False,
        "freshness_reasons": ["claim_generation_unavailable"],
        "reason": "当前输出目录尚无 Claim Ledger generation",
    }
    collection_key = _COLLECTION_KEYS.get(view)
    if collection_key:
        payload[collection_key] = []
        payload["total"] = 0
    if view in {"catalog", "ledger", "coverage_groups", "review_events", "queue"}:
        payload.update({"limit": 0, "offset": 0})
    if view == "catalog":
        payload["owner_unit_ids"] = []
    elif view == "metrics":
        payload.update({
            "generation_metrics": {},
            "effective_metrics": {},
            "document_ready": None,
            "health": {},
        })
    elif view == "queue":
        payload["compat_omissions"] = []
        payload["compat_omission_revision"] = None
        payload["compat_omission_total"] = 0
        payload["compat_omission_limit"] = 0
        payload["compat_omission_offset"] = 0
        payload["route_preflight"] = None
    return payload


def _has_no_generation(root: Path) -> bool:
    return not any(
        governed_artifact_path(root, name, for_write=False).exists()
        for name in _BASE_FILES
    )


# Read-only snapshot cache. The six GETs share one committed snapshot per
# revision. Every input that can change the rendered view or freshness result
# participates in the key, and a per-root single-flight prevents concurrent
# GETs from loading different generations into the cache.
_CONTEXT_CACHE_MAX_ENTRIES = 16
_CONTEXT_CACHE: OrderedDict[Path, tuple[tuple, dict[str, Any]]] = OrderedDict()
_CONTEXT_CACHE_GUARD = threading.RLock()
_CONTEXT_CACHE_INFLIGHT: dict[Path, threading.Event] = {}


def _context_revision_key(root: Path) -> tuple:
    # Shared with claim_artifacts.load_committed_effective_snapshot_cached:
    # one canonical input-signature builder for the view context cache and the
    # readonly snapshot cache (stat signatures of every input file, content
    # digests of the two commit anchors, structural sidecars, journal flags).
    return effective_snapshot_revision_key(root)


def _check_migration(snapshot: dict[str, Any]) -> None:
    from claim_artifacts import CLAIM_EFFECTIVE_SNAPSHOT_VERSION

    if (
        dict(snapshot["effective_meta"]).get("effective_snapshot_version")
        != CLAIM_EFFECTIVE_SNAPSHOT_VERSION
    ):
        raise ClaimViewMigrationRequired(
            "committed effective snapshot predates the current contract; "
            "run maintenance to rebuild it"
        )


def _context(root: Path) -> dict[str, Any] | None:
    root = root.resolve()
    if _has_no_generation(root):
        return None
    while True:
        key = _context_revision_key(root)
        with _CONTEXT_CACHE_GUARD:
            cached = _CONTEXT_CACHE.get(root)
            if cached is not None and cached[0] == key:
                _CONTEXT_CACHE.move_to_end(root)
                return cached[1]
            inflight = _CONTEXT_CACHE_INFLIGHT.get(root)
            if inflight is None:
                inflight = threading.Event()
                _CONTEXT_CACHE_INFLIGHT[root] = inflight
                break
        inflight.wait()

    try:
        # The loader checks both publication journals before and after its
        # snapshot read. A pending journal always takes precedence over a
        # legacy snapshot: readers request recovery and never write. The
        # cached loader memoizes the readonly snapshot per input signature, so
        # repeated GETs (and the /table-reviews, /document/pdf style callers)
        # skip re-hashing every claim artifact.
        snapshot = load_committed_effective_snapshot_cached(
            root,
            require_v2=False,
        )
        _check_migration(snapshot)
        freshness = assess_effective_freshness(root, snapshot, readonly=True)
        effective = dict(snapshot["effective_meta"])
        generation = dict(snapshot["generation_meta"])
        event_log = read_claim_review_events(root, repair=False, readonly=True)
        committed_count = int(effective["last_event_seq"])
        health = read_effective_health(root)
        if freshness.get("authority_audit_gap"):
            health = {**health, "authority_audit_gap": True}
        from claim_structural_operations import pending_structural_operations
        from claim_structural_overrides import (
            read_structural_candidate_decisions,
            structural_candidate_decision_identity,
        )

        candidate_decisions = read_structural_candidate_decisions(root)

        context = {
            "snapshot": snapshot,
            "effective": effective,
            "generation": generation,
            "freshness": freshness,
            "events": event_log.rows[:committed_count],
            "health": health,
            "structural_pending": pending_structural_operations(root),
            "structural_candidate_decisions": candidate_decisions.rows,
            "structural_candidate_decision_registry": (
                structural_candidate_decision_identity(candidate_decisions)
            ),
        }
        confirmed_key = _context_revision_key(root)
        if confirmed_key != key:
            raise ClaimArtifactError(
                "claim view inputs changed while loading the committed snapshot"
            )
        with _CONTEXT_CACHE_GUARD:
            _CONTEXT_CACHE[root] = (confirmed_key, context)
            _CONTEXT_CACHE.move_to_end(root)
            while len(_CONTEXT_CACHE) > _CONTEXT_CACHE_MAX_ENTRIES:
                _CONTEXT_CACHE.popitem(last=False)
        return context
    finally:
        with _CONTEXT_CACHE_GUARD:
            current = _CONTEXT_CACHE_INFLIGHT.pop(root, None)
            if current is not None:
                current.set()


def _envelope(view: str, context: dict[str, Any]) -> dict[str, Any]:
    from claim_structural_overrides import (
        empty_structural_candidate_decision_identity,
    )

    effective = context["effective"]
    generation = context["generation"]
    freshness = context["freshness"]
    return {
        "schema": _VIEW_SCHEMAS[view],
        "available": True,
        "phase": CLAIM_VIEW_PHASE,
        "document_effective_revision": effective["document_effective_revision"],
        "base_generation_id": effective["base_generation_id"],
        "document_generation_id": generation["document_generation_id"],
        "catalog_generation_id": generation["catalog_generation_id"],
        "event_prefix_sha256": effective["event_prefix_sha256"],
        "last_event_seq": effective["last_event_seq"],
        "structural_candidate_decision_registry": context.get(
            "structural_candidate_decision_registry"
        ) or empty_structural_candidate_decision_identity(),
        "effective_fresh": freshness["effective_fresh"],
        "freshness_reasons": freshness["freshness_reasons"],
    }


def _page(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, int, int]:
    normalized_limit = max(1, min(500, int(limit)))
    normalized_offset = max(0, int(offset))
    return (
        rows[normalized_offset:normalized_offset + normalized_limit],
        len(rows),
        normalized_limit,
        normalized_offset,
    )


def _effective_by_claim(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("claim_id") or ""): row
        for row in snapshot["effective_ledger"]
    }


_CELL_STRUCTURAL_REVIEW_REASONS = frozenset({
    "ambiguous_table_structure",
    "weak_signal_table_cell",
    "unsignaled_table_cell",
    "rejected_matrix_marker_cell",
    "untyped_colon_spec_cell",
    "parse_incomplete_table_cell",
    "normative_context_conflict",
})


def _structural_review_state(
    context: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], int, int]:
    snapshot = context["snapshot"]
    generation = dict(context.get("generation") or {})
    current_claims = {
        str(row.get("claim_id") or ""): row
        for row in snapshot.get("catalog") or []
    }
    decisions: dict[str, dict[str, Any]] = {}
    for raw in context.get("structural_candidate_decisions") or []:
        row = dict(raw)
        claim_id = str(row.get("claim_id") or "")
        claim = current_claims.get(claim_id)
        if (
            claim is not None
            and row.get("claim_hash") == claim.get("claim_hash")
            and row.get("document_generation_id")
            == generation.get("document_generation_id")
            and row.get("catalog_generation_id")
            == generation.get("catalog_generation_id")
        ):
            decisions[claim_id] = row
    candidates: list[str] = []
    for claim in current_claims.values():
        exclusion = claim.get("exclusion")
        reason = (
            str(exclusion.get("reason") or "")
            if isinstance(exclusion, dict)
            else ""
        )
        if (
            claim.get("eligibility") == "excluded"
            and reason in _CELL_STRUCTURAL_REVIEW_REASONS
        ):
            candidates.append(str(claim.get("claim_id") or ""))
    confirmed = sum(claim_id in decisions for claim_id in candidates)
    return decisions, len(candidates) - confirmed, confirmed


def _catalog_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = context["snapshot"]
    effective_by_claim = _effective_by_claim(snapshot)
    base_by_claim = {
        str(row.get("claim_id") or ""): row for row in snapshot["ledger"]
    }
    groups_by_claim: dict[str, list[dict[str, Any]]] = {}
    for group in snapshot["groups"]:
        groups_by_claim.setdefault(str(group.get("claim_id") or ""), []).append(group)
    pending_operations = dict(context.get("structural_pending") or {})
    candidate_decisions, _pending_count, _confirmed_count = (
        _structural_review_state(context)
    )
    rows: list[dict[str, Any]] = []
    for claim in snapshot["catalog"]:
        claim_id = str(claim.get("claim_id") or "")
        effective = effective_by_claim[claim_id]
        active_facts = list(
            dict(effective.get("effective_facts") or {}).get(
                "active_resolution_facts"
            )
            or []
        )
        exclusion = claim.get("exclusion")
        structural_reason = (
            str(exclusion.get("reason") or "")
            if isinstance(exclusion, dict)
            else ""
        )
        candidate_decision = candidate_decisions.get(claim_id)
        is_review_candidate = structural_reason in _CELL_STRUCTURAL_REVIEW_REASONS
        rows.append({
            **claim,
            "source_text_hash": claim_source_evidence_hash(claim),
            "base_resolution_fact_hashes": claim_base_resolution_fact_hashes(
                claim,
                base_by_claim[claim_id],
                groups_by_claim.get(claim_id, []),
            ),
            "active_resolution_facts": active_facts,
            "required_supersedes_fact_hashes": {
                adjudication: claim_required_supersedes_fact_hashes(
                    adjudication, active_facts
                )
                for adjudication in (
                    "covered", "excluded_non_normative", "reopen",
                )
            },
            "pending_structural_operation": pending_operations.get(claim_id),
            "structural_review_status": (
                "confirmed_excluded"
                if candidate_decision is not None
                else "pending_review"
                if is_review_candidate
                else None
            ),
            "structural_candidate_decision": candidate_decision,
            **{
                key: effective.get(key)
                for key in (
                    "resolution",
                    "classification",
                    "classification_status",
                    "exclusion_kind",
                    "claim_effective_revision",
                )
            },
        })
    rows.sort(key=lambda row: str(row.get("claim_id") or ""))
    return rows


def build_claim_catalog_view(
    root: Path,
    context: dict[str, Any],
    *,
    resolution: str = "",
    owner_unit_id: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    rows = _catalog_rows(context)
    owner_ids = sorted({
        str(row["owner_unit_id"])
        for row in rows if row.get("owner_unit_id")
    })
    if resolution:
        rows = [row for row in rows if row.get("resolution") == resolution]
    if owner_unit_id:
        rows = [
            row for row in rows
            if str(row.get("owner_unit_id") or "") == owner_unit_id
        ]
    page, total, page_limit, page_offset = _page(
        rows,
        limit=limit,
        offset=offset,
    )
    return {
        **_envelope("catalog", context),
        "rows": page,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
        "owner_unit_ids": owner_ids,
    }


def build_claim_ledger_view(
    root: Path,
    context: dict[str, Any],
    *,
    resolution: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    rows = sorted(
        (dict(row) for row in context["snapshot"]["effective_ledger"]),
        key=lambda row: str(row.get("claim_id") or ""),
    )
    if resolution:
        rows = [row for row in rows if row.get("resolution") == resolution]
    page, total, page_limit, page_offset = _page(
        rows,
        limit=limit,
        offset=offset,
    )
    return {
        **_envelope("ledger", context),
        "rows": page,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


def build_claim_coverage_group_view(
    root: Path,
    context: dict[str, Any],
    *,
    claim_id: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    effective_by_claim = _effective_by_claim(context["snapshot"])
    rows: list[dict[str, Any]] = []
    for raw_group in context["snapshot"]["groups"]:
        group = dict(raw_group)
        group["coverage_group_hash"] = claim_coverage_group_hash(group)
        group_claim_id = str(group.get("claim_id") or "")
        if claim_id and group_claim_id != claim_id:
            continue
        facts = dict(
            effective_by_claim.get(group_claim_id, {}).get("effective_facts") or {}
        )
        group_id = str(group.get("coverage_group_id") or "")
        invalid_reasons = dict(facts.get("invalid_group_reasons") or {})
        is_valid = group_id in set(facts.get("valid_group_ids") or [])
        group.update({
            "effective_status": "validated" if is_valid else "invalid",
            "effective_reason": invalid_reasons.get(group_id, ""),
            "effective_reused": group_id in set(
                facts.get("reused_validation_group_ids") or []
            ),
        })
        rows.append(group)
    rows.sort(key=lambda row: (
        str(row.get("claim_id") or ""),
        str(row.get("coverage_group_id") or ""),
    ))
    page, total, page_limit, page_offset = _page(
        rows,
        limit=limit,
        offset=offset,
    )
    return {
        **_envelope("coverage_groups", context),
        "groups": page,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


def _document_ready(context: dict[str, Any]) -> bool:
    """文档级 claim 就绪 = **当前有效态**属性（复审 2026-08-15 P1 修正）。

    旧实现还要求 base generation 的 ``shadow_meta.document_ready is True``——但
    ``_shadow_meta_is_well_formed`` 按发布时不变量要求该布尔**恒为 False**（Phase 0
    base 发布时评审尚未发生），两个条件做与使 document_ready 在两条轨上结构性永假，
    full closure 的 claim 门永远不可达。就绪应由有效态四条件判定：effective 新鲜、
    无 authority 审计缺口、零 uncertain、无待结构复核。
    """
    _decisions, pending_structural_reviews, _confirmed = (
        _structural_review_state(context)
    )
    return bool(
        context["freshness"]["effective_fresh"]
        and not context["health"].get("authority_audit_gap")
        and int(context["effective"]["effective_metrics"].get("uncertain_count") or 0)
        == 0
        and pending_structural_reviews == 0
    )


def build_claim_metrics_view(
    root: Path,
    context: dict[str, Any],
) -> dict[str, Any]:
    generation = context["generation"]
    _decisions, pending_structural_reviews, confirmed_structural_exclusions = (
        _structural_review_state(context)
    )
    return {
        **_envelope("metrics", context),
        "generation_metrics": context["snapshot"]["metrics"],
        "effective_metrics": context["effective"]["effective_metrics"],
        "generation_metrics_version": dict(
            generation.get("shadow_meta") or {}
        ).get("ledger_schema_version"),
        "effective_metrics_version": context["effective"][
            "effective_ledger_schema"
        ],
        "document_ready": _document_ready(context),
        "structural_review_pending_count": pending_structural_reviews,
        "structural_review_confirmed_exclusion_count": (
            confirmed_structural_exclusions
        ),
        "health": context["health"],
    }


def build_claim_review_event_view(
    root: Path,
    context: dict[str, Any],
    *,
    claim_id: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    generation = context["generation"]
    current_claim_hashes = {
        str(row.get("claim_id") or ""): str(row.get("claim_hash") or "")
        for row in context["snapshot"]["ledger"]
    }
    rows = [
        dict(row) for row in context["events"]
        if (
            str(row.get("document_generation_id") or "")
            == str(generation.get("document_generation_id") or "")
            and str(row.get("catalog_generation_id") or "")
            == str(generation.get("catalog_generation_id") or "")
            and str(row.get("claim_hash") or "")
            == current_claim_hashes.get(str(row.get("claim_id") or ""))
            and (not claim_id or row.get("claim_id") == claim_id)
        )
    ]
    rows.sort(key=lambda row: int(row.get("event_seq") or 0))
    page, total, page_limit, page_offset = _page(
        rows,
        limit=limit,
        offset=offset,
    )
    return {
        **_envelope("review_events", context),
        "events": page,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


def _compat_omissions(root: Path) -> list[dict[str, Any]]:
    from omission_actions import read_current_omission_states_readonly

    try:
        states = read_current_omission_states_readonly(root)
    except (OSError, ValueError) as exc:
        raise ClaimArtifactError(
            "compatibility omissions are unavailable for a consistent read"
        ) from exc
    rows = []
    for key in sorted(states):
        state = dict(states[key])
        if state.get("status") != "needs_extraction":
            continue
        rows.append({
            **state,
            "compat_whole_block": True,
            "dry_run": True,
        })
    return rows


def build_claim_queue_view(
    root: Path,
    context: dict[str, Any],
    *,
    limit: int = 100,
    offset: int = 0,
    compat_limit: int | None = None,
    compat_offset: int = 0,
) -> dict[str, Any]:
    from claim_reextract_attempts import (
        derive_attempt_states,
        read_attempt_log_stable,
    )

    # A GET must never write: interrupted-attempt recovery belongs to API
    # startup, explicit maintenance, and the queue execute write side.  The
    # stable double-read absorbs a torn tail from a concurrent append.
    attempt_snapshot = read_attempt_log_stable(root)
    attempt_states = derive_attempt_states(attempt_snapshot.rows)
    latest_by_proposal: dict[str, dict[str, Any]] = {}
    for state in attempt_states.values():
        proposal_id = str(state.get("proposal_id") or "")
        previous = latest_by_proposal.get(proposal_id)
        if previous is None or int(
            dict(state.get("last_event") or {}).get("event_seq") or 0
        ) > int(dict(previous.get("last_event") or {}).get("event_seq") or 0):
            latest_by_proposal[proposal_id] = state
    rows = sorted(
        (dict(row) for row in context["snapshot"]["queue_proposals"]),
        key=lambda row: (
            str(row.get("claim_id") or ""),
            str(row.get("proposal_id") or ""),
        ),
    )
    for row in rows:
        state = latest_by_proposal.get(str(row.get("proposal_id") or ""))
        if state is None:
            continue
        lifecycle = str(state.get("lifecycle") or "")
        row["lifecycle"] = (
            "executed"
            if lifecycle == "succeeded"
            else lifecycle
            if lifecycle in {"executing", "rebuild_pending"}
            else "open"
        )
        terminal = dict(state.get("terminal_event") or {})
        row["latest_attempt"] = {
            "attempt_id": str(state.get("attempt_id") or ""),
            "request_idempotency_key": str(
                state.get("request_idempotency_key") or ""
            ),
            "lifecycle": lifecycle,
            "last_event_seq": int(
                dict(state.get("last_event") or {}).get("event_seq") or 0
            ),
            "outcome": dict(terminal.get("outcome") or {}) or None,
        }
    page, total, page_limit, page_offset = _page(
        rows,
        limit=limit,
        offset=offset,
    )
    from claim_queue_execution import claim_queue_route_preflight

    compat_omissions = _compat_omissions(root)
    normalized_compat_offset = max(0, int(compat_offset))
    if compat_limit is None:
        compat_page = compat_omissions[normalized_compat_offset:]
        effective_compat_limit = len(compat_page)
    else:
        normalized_compat_limit = max(1, min(500, int(compat_limit)))
        compat_page = compat_omissions[
            normalized_compat_offset:normalized_compat_offset + normalized_compat_limit
        ]
        effective_compat_limit = normalized_compat_limit
    return {
        **_envelope("queue", context),
        "proposals": page,
        "route_preflight": claim_queue_route_preflight("openai_compatible"),
        "compat_omissions": compat_page,
        "compat_omission_revision": hash_json(
            "claim-compat-omission-revision/v1",
            compat_omissions,
        ),
        "compat_omission_total": len(compat_omissions),
        "compat_omission_limit": effective_compat_limit,
        "compat_omission_offset": normalized_compat_offset,
        "attempt_log_revision": attempt_snapshot.prefix_sha256,
        "attempt_event_count": attempt_snapshot.last_event_seq,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


def build_claim_clarification_views(
    out_dir: Path | str,
    *,
    uncertain_limit: int = 50,
) -> dict[str, dict[str, Any]]:
    """Build the clarification report's two ledger views from one snapshot."""
    root = Path(out_dir).expanduser().resolve()
    context = _context(root)
    if context is None:
        return {
            "metrics": _unavailable("metrics"),
            "uncertain_catalog": _unavailable("catalog"),
        }
    return {
        "metrics": build_claim_metrics_view(root, context),
        "uncertain_catalog": build_claim_catalog_view(
            root,
            context,
            resolution="uncertain",
            limit=uncertain_limit,
            offset=0,
        ),
    }


def build_claim_view(
    out_dir: Path | str,
    view: str,
    *,
    resolution: str = "",
    owner_unit_id: str = "",
    claim_id: str = "",
    limit: int = 100,
    offset: int = 0,
    compat_limit: int | None = None,
    compat_offset: int = 0,
) -> dict[str, Any]:
    """Build one revision-pinned Claim Ledger GET view.

    ``compat_limit``/``compat_offset`` page the legacy ``compat_omissions`` partition
    independently of the claim proposals. Omitting ``compat_limit`` means *unpaged*:
    every omission from ``compat_offset`` onward is returned and ``compat_omission_limit``
    echoes the actual returned count (not a request cap). Passing ``compat_limit``
    switches to capped pagination clamped to 1..500. This contract is pinned by tests.
    """
    if view not in _VIEW_SCHEMAS:
        raise ValueError(f"unknown claim view: {view}")
    root = Path(out_dir).expanduser().resolve()
    context = _context(root)
    if context is None:
        return _unavailable(view)
    if view == "catalog":
        return build_claim_catalog_view(
            root,
            context,
            resolution=resolution,
            owner_unit_id=owner_unit_id,
            limit=limit,
            offset=offset,
        )
    if view == "ledger":
        return build_claim_ledger_view(
            root,
            context,
            resolution=resolution,
            limit=limit,
            offset=offset,
        )
    if view == "coverage_groups":
        return build_claim_coverage_group_view(
            root,
            context,
            claim_id=claim_id,
            limit=limit,
            offset=offset,
        )
    if view == "metrics":
        return build_claim_metrics_view(root, context)
    if view == "review_events":
        return build_claim_review_event_view(
            root,
            context,
            claim_id=claim_id,
            limit=limit,
            offset=offset,
        )
    return build_claim_queue_view(
        root,
        context,
        limit=limit,
        offset=offset,
        compat_limit=compat_limit,
        compat_offset=compat_offset,
    )
