from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    hash_json,
    load_committed_effective_snapshot_readonly,
)
from claim_review_actions import (
    assess_effective_freshness,
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
        "effective_fresh": False,
        "freshness_reasons": ["claim_generation_unavailable"],
        "reason": "当前输出目录尚无 Claim Ledger generation",
    }
    collection_key = _COLLECTION_KEYS.get(view)
    if collection_key:
        payload[collection_key] = []
        payload["total"] = 0
    if view in {"catalog", "ledger", "coverage_groups", "review_events"}:
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
    return payload


def _has_no_generation(root: Path) -> bool:
    return not any((root / name).exists() for name in _BASE_FILES)


def _check_migration(snapshot: dict[str, Any]) -> None:
    if (
        dict(snapshot["effective_meta"]).get("effective_snapshot_version")
        == "claim-effective-snapshot-v1"
    ):
        raise ClaimViewMigrationRequired("Phase 1 effective migration is required")


def _context(root: Path) -> dict[str, Any] | None:
    if _has_no_generation(root):
        return None
    # The loader checks both publication journals before and after its snapshot
    # read.  A pending journal always takes precedence over a legacy snapshot:
    # readers must request recovery, not report migration, and must not write.
    snapshot = load_committed_effective_snapshot_readonly(root, require_v2=False)
    _check_migration(snapshot)
    freshness = assess_effective_freshness(root, snapshot, readonly=True)
    effective = dict(snapshot["effective_meta"])
    generation = dict(snapshot["generation_meta"])
    event_log = read_claim_review_events(root, repair=False, readonly=True)
    committed_count = int(effective["last_event_seq"])
    health = read_effective_health(root)
    if freshness.get("authority_audit_gap"):
        health = {**health, "authority_audit_gap": True}
    return {
        "snapshot": snapshot,
        "effective": effective,
        "generation": generation,
        "freshness": freshness,
        "events": event_log.rows[:committed_count],
        "health": health,
    }


def _envelope(view: str, context: dict[str, Any]) -> dict[str, Any]:
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


def _catalog_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = context["snapshot"]
    effective_by_claim = _effective_by_claim(snapshot)
    rows: list[dict[str, Any]] = []
    for claim in snapshot["catalog"]:
        claim_id = str(claim.get("claim_id") or "")
        effective = effective_by_claim[claim_id]
        rows.append({
            **claim,
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
    generation = context["generation"]
    shadow_meta = dict(generation.get("shadow_meta") or {})
    return bool(
        shadow_meta.get("document_ready") is True
        and context["freshness"]["effective_fresh"]
        and not context["health"].get("authority_audit_gap")
        and int(context["effective"]["effective_metrics"].get("uncertain_count") or 0)
        == 0
    )


def build_claim_metrics_view(
    root: Path,
    context: dict[str, Any],
) -> dict[str, Any]:
    generation = context["generation"]
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
) -> dict[str, Any]:
    rows = sorted(
        (dict(row) for row in context["snapshot"]["queue_proposals"]),
        key=lambda row: (
            str(row.get("claim_id") or ""),
            str(row.get("proposal_id") or ""),
        ),
    )
    page, total, page_limit, page_offset = _page(
        rows,
        limit=limit,
        offset=offset,
    )
    compat_omissions = _compat_omissions(root)
    return {
        **_envelope("queue", context),
        "proposals": page,
        "compat_omissions": compat_omissions,
        "compat_omission_revision": hash_json(
            "claim-compat-omission-revision/v1",
            compat_omissions,
        ),
        "compat_omission_total": len(compat_omissions),
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
) -> dict[str, Any]:
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
    )
