"""Fenced, resumable coordinator for claim structural overrides."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from claim_artifacts import (
    ClaimArtifactError,
    claim_publication_lock,
    hash_json,
    load_committed_claim_base,
)
import claim_structural_overrides as overrides


def _matching_override(
    root: Path,
    request: dict[str, Any],
) -> tuple[dict[str, Any], overrides.StructuralOverrideSnapshot] | None:
    snapshot = overrides.read_structural_overrides(root)
    for row in snapshot.rows:
        if (
            row.get("claim_id") != request["claim_id"]
            or row.get("claim_hash") != request["claim_hash"]
        ):
            continue
        expected_key = overrides._idempotency_key(
            claim_id=str(row["claim_id"]),
            claim_hash=str(row["claim_hash"]),
            document_generation_id=str(row["document_generation_id"]),
            catalog_generation_id=str(row["catalog_generation_id"]),
            prior_structural_reason=str(row["prior_structural_reason"]),
            original_exclusion=dict(row["original_exclusion"]),
            actor=str(request["actor"]).strip(),
            reason=str(request["reason"]).strip(),
            request_idempotency_key=str(request["request_idempotency_key"]),
        )
        if row.get("idempotency_key") != expected_key:
            continue
        if (
            int(row.get("override_seq") or 0) != snapshot.last_override_seq
            or row.get("override_hash") != snapshot.last_override_hash
        ):
            raise overrides.ClaimStructuralOverrideStale(
                "structural override authority advanced after the operation write"
            )
        return dict(row), snapshot
    return None


def _recover_authority_checkpoints(
    root: Path,
    *,
    operation_id: str,
    request: dict[str, Any],
    state: dict[str, Any],
    append_events: Any,
    current_state: Any,
) -> dict[str, Any]:
    checkpoints = dict(state.get("checkpoints") or {})
    if "override_registered" not in checkpoints:
        recovered = _matching_override(root, request)
        if recovered is not None:
            row, registry = recovered
            identity = overrides.structural_override_identity(registry)
            append_events(root, [{
                "operation_id": operation_id,
                "event_kind": "override_registered",
                "idempotency_key": overrides._event_key(
                    operation_id, "override_registered",
                ),
                "override_id": row["override_id"],
                "override_hash": row["override_hash"],
                "registry_prefix_sha256": identity["prefix_sha256"],
                "registry_prefix_count": identity["prefix_count"],
            }])
            state = current_state()
            checkpoints = dict(state["checkpoints"])

    checkpoint = checkpoints.get("override_registered")
    if isinstance(checkpoint, dict) and "audit_appended" not in checkpoints:
        event_key = hash_json(
            "claim-structural-falsification-idempotency/v1",
            {
                "override_id": checkpoint["override_id"],
                "override_hash": checkpoint["override_hash"],
            },
        )
        from claim_review_actions import read_claim_review_events

        events = read_claim_review_events(root, repair=False)
        event = next(
            (
                dict(row) for row in events.rows
                if row.get("idempotency_key") == event_key
            ),
            None,
        )
        if event is not None:
            if int(event.get("event_seq") or 0) != events.last_event_seq:
                raise overrides.ClaimStructuralOverrideStale(
                    "claim review authority advanced after the structural audit"
                )
            append_events(root, [{
                "operation_id": operation_id,
                "event_kind": "audit_appended",
                "idempotency_key": overrides._event_key(
                    operation_id, "audit_appended",
                ),
                "audit_event_hash": str(event["event_hash"]),
                "event_prefix_sha256": events.event_prefix_sha256,
                "last_event_seq": events.last_event_seq,
            }])
            state = current_state()
    return state


def _register_and_audit(
    root: Path,
    *,
    operation_id: str,
    request: dict[str, Any],
    snapshot: dict[str, Any],
    state: dict[str, Any],
    append_events: Any,
    current_state: Any,
) -> None:
    from claim_review_actions import (
        append_claim_review_events,
        read_claim_review_events,
    )

    claim_id = str(request["claim_id"])
    claim_hash = str(request["claim_hash"])
    base_by_claim = {
        str(row.get("claim_id") or ""): row
        for row in snapshot.get("ledger") or []
    }
    effective_by_claim = {
        str(row.get("claim_id") or ""): row
        for row in snapshot.get("effective_ledger") or []
    }
    base_row = base_by_claim.get(claim_id)
    effective_row = effective_by_claim.get(claim_id)
    if base_row is None or effective_row is None:
        raise overrides.ClaimStructuralOverrideStale(
            "claim is absent from the current effective snapshot"
        )

    checkpoints = dict(state.get("checkpoints") or {})
    checkpoint = checkpoints.get("override_registered")
    if isinstance(checkpoint, dict):
        registry = overrides.read_structural_overrides(root)
        identity = overrides.structural_override_identity(registry)
        row = next(
            (
                dict(item) for item in registry.rows
                if item.get("override_id") == checkpoint.get("override_id")
                and item.get("override_hash") == checkpoint.get("override_hash")
            ),
            None,
        )
        if (
            row is None
            or identity["prefix_sha256"]
            != checkpoint.get("registry_prefix_sha256")
            or identity["prefix_count"]
            != checkpoint.get("registry_prefix_count")
        ):
            raise overrides.ClaimStructuralOverrideStale(
                "operation registry checkpoint no longer matches the authority"
            )
    else:
        registered = overrides.register_structural_override(
            root,
            claim_id=claim_id,
            claim_hash=claim_hash,
            expected_catalog_generation_id=str(
                request["expected_catalog_generation_id"]
            ),
            prior_structural_reason=str(request["prior_structural_reason"]),
            actor=str(request["actor"]),
            reason=str(request["reason"]),
            request_idempotency_key=str(request["request_idempotency_key"]),
        )
        row = dict(registered["override"])
        identity = dict(registered["registry"])
        append_events(root, [{
            "operation_id": operation_id,
            "event_kind": "override_registered",
            "idempotency_key": overrides._event_key(
                operation_id, "override_registered",
            ),
            "override_id": row["override_id"],
            "override_hash": row["override_hash"],
            "registry_prefix_sha256": identity["prefix_sha256"],
            "registry_prefix_count": identity["prefix_count"],
        }])
        state = current_state()
        checkpoints = dict(state["checkpoints"])

    event_key = hash_json(
        "claim-structural-falsification-idempotency/v1",
        {"override_id": row["override_id"], "override_hash": row["override_hash"]},
    )
    audit_checkpoint = checkpoints.get("audit_appended")
    if isinstance(audit_checkpoint, dict):
        events = read_claim_review_events(root, repair=False)
        event = next(
            (
                item for item in events.rows
                if item.get("idempotency_key") == event_key
                and item.get("event_hash")
                == audit_checkpoint.get("audit_event_hash")
            ),
            None,
        )
        if (
            event is None
            or events.event_prefix_sha256
            != audit_checkpoint.get("event_prefix_sha256")
            or events.last_event_seq != audit_checkpoint.get("last_event_seq")
        ):
            raise overrides.ClaimStructuralOverrideStale(
                "operation audit checkpoint no longer matches the authority"
            )
        return

    generation = dict(snapshot.get("generation_meta") or {})
    result = append_claim_review_events(
        root,
        [{
            "schema": "claim-review-event/v2",
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "document_generation_id": generation["document_generation_id"],
            "catalog_generation_id": generation["catalog_generation_id"],
            "event_kind": "structural_falsification",
            "actor": str(request["actor"]).strip(),
            "reason": str(request["reason"]).strip(),
            "idempotency_key": event_key,
            "expected_base_claim_row_hash": hash_json(
                "claim-base-row/v1", base_row,
            ),
            "expected_claim_effective_revision": str(
                request["expected_claim_effective_revision"]
            ),
            "prior_structural_reason": str(request["prior_structural_reason"]),
            "override_id": row["override_id"],
            "override_hash": row["override_hash"],
            "route": "deterministic",
        }],
        base_by_claim=base_by_claim,
        effective_by_claim=effective_by_claim,
    )
    if result["appended"]:
        event = dict(result["appended"][0])
    else:
        event = next(
            dict(item)
            for item in read_claim_review_events(root, repair=False).rows
            if item.get("idempotency_key") == event_key
        )
    events = read_claim_review_events(root, repair=False)
    append_events(root, [{
        "operation_id": operation_id,
        "event_kind": "audit_appended",
        "idempotency_key": overrides._event_key(operation_id, "audit_appended"),
        "audit_event_hash": str(event["event_hash"]),
        "event_prefix_sha256": events.event_prefix_sha256,
        "last_event_seq": events.last_event_seq,
    }])


def _append_success(
    root: Path,
    *,
    operation_id: str,
    binding: dict[str, Any],
    append_events: Any,
) -> None:
    append_events(root, [{
        "operation_id": operation_id,
        "event_kind": "base_rebuild_published",
        "idempotency_key": overrides._event_key(
            operation_id, "base_rebuild_published",
        ),
        "base_generation_id": binding["base_generation_id"],
    }, {
        "operation_id": operation_id,
        "event_kind": "effective_folded",
        "idempotency_key": overrides._event_key(operation_id, "effective_folded"),
        "effective_fresh": True,
        "binding": binding,
    }, {
        "operation_id": operation_id,
        "event_kind": "operation_succeeded",
        "idempotency_key": overrides._event_key(operation_id, "operation_succeeded"),
        "outcome": {"code": "rebuilt", "message": "", "retryable": False},
        "binding": binding,
    }])


def _recover_published(
    root: Path,
    *,
    operation_id: str,
    request: dict[str, Any],
    state: dict[str, Any],
    append_events: Any,
) -> bool:
    checkpoints = dict(state.get("checkpoints") or {})
    override_checkpoint = checkpoints.get("override_registered")
    audit_checkpoint = checkpoints.get("audit_appended")
    if not (
        isinstance(override_checkpoint, dict)
        and isinstance(audit_checkpoint, dict)
    ):
        return False

    base = load_committed_claim_base(root)
    committed_prefix = str(
        dict(base.get("catalog_meta") or {}).get(
            "structural_override_prefix_sha256"
        )
        or ""
    )
    registry = overrides.read_structural_overrides(root)
    row = next(
        (
            dict(item) for item in registry.rows
            if item.get("override_id") == override_checkpoint.get("override_id")
            and item.get("override_hash") == override_checkpoint.get("override_hash")
        ),
        None,
    )
    if row is None:
        raise overrides.ClaimStructuralOverrideStale(
            "published structural rebuild lost its override authority"
        )
    if committed_prefix == str(row.get("registry_prefix_sha256") or ""):
        return False
    if committed_prefix != override_checkpoint.get("registry_prefix_sha256"):
        raise overrides.ClaimStructuralOverrideStale(
            "published claim base has a different structural authority"
        )

    generation = dict(base.get("generation_meta") or {})
    preconditions = dict(request.get("preconditions") or {})
    if (
        generation.get("target_generation_id")
        != preconditions.get("target_generation_id")
        or generation.get("target_review_authority_revision")
        != preconditions.get("target_review_authority_revision")
    ):
        raise overrides.ClaimStructuralOverrideStale(
            "published structural rebuild changed target authority"
        )
    claim = next(
        (
            item for item in base.get("catalog") or []
            if item.get("claim_id") == request["claim_id"]
        ),
        None,
    )
    if (
        claim is None
        or claim.get("claim_hash") != request["claim_hash"]
        or claim.get("eligibility") != "claim"
    ):
        raise overrides.ClaimStructuralOverrideStale(
            "published structural rebuild does not contain the authorized claim"
        )
    from claim_review_actions import (
        assess_effective_freshness,
        fold_effective_ledger,
        read_claim_review_events,
    )

    events = read_claim_review_events(root, repair=False)
    if (
        events.event_prefix_sha256 != audit_checkpoint.get("event_prefix_sha256")
        or events.last_event_seq != audit_checkpoint.get("last_event_seq")
    ):
        raise overrides.ClaimStructuralOverrideStale(
            "claim review authority changed after structural publication"
        )
    fold_effective_ledger(root, actor_trigger="claim-structural-override-recovery")
    from claim_artifacts import load_committed_effective_snapshot_readonly

    snapshot = load_committed_effective_snapshot_readonly(root)
    freshness = assess_effective_freshness(root, snapshot, readonly=True)
    if freshness.get("effective_fresh") is not True:
        raise overrides.ClaimStructuralOverrideError(
            "published structural base could not be folded to a fresh snapshot"
        )
    binding = overrides._effective_binding(
        root,
        snapshot,
        claim_id=str(request["claim_id"]),
        override_hash=str(override_checkpoint["override_hash"]),
    )
    _append_success(
        root,
        operation_id=operation_id,
        binding=binding,
        append_events=append_events,
    )
    return True


def _settle_unknown_budget(snapshot: dict[str, Any]) -> dict[str, Any]:
    settled = dict(snapshot)
    reserved = int(settled.get("reserved_tokens") or 0)
    if reserved <= 0:
        return settled
    settled["tokens"] = int(settled.get("tokens") or 0) + reserved
    settled["reserved_tokens"] = 0
    settled["failed_calls"] = int(settled.get("failed_calls") or 0) + 1
    settled["usage_complete"] = False
    settled["remaining_calls"] = max(
        0, int(settled["max_calls"]) - int(settled["attempted_calls"]),
    )
    settled["remaining_tokens"] = max(
        0, int(settled["max_tokens"]) - int(settled["tokens"]),
    )
    settled["termination_reason"] = "unknown_remote_result_charged"
    settled["status"] = "failed"
    return settled


def _has_unconfirmed_paid_work(state: dict[str, Any]) -> bool:
    """Return whether a paid attempt lacks a decision or later confirmation."""
    checkpoints = dict(state.get("checkpoints") or {})
    if "verifier_checkpoint" in checkpoints:
        return False
    latest = dict(state.get("latest_budget") or {})
    attempted = int(latest.get("attempted_calls") or 0)
    if attempted <= 0:
        return False
    reconfirmed = state.get("last_reconfirmation")
    if not isinstance(reconfirmed, dict):
        return True
    confirmed_budget_hash = str(reconfirmed.get("budget_event_hash") or "")
    confirmed_attempts = -1
    for row in state.get("history") or []:
        if (
            row.get("event_kind") == "budget_checkpoint"
            and row.get("event_hash") == confirmed_budget_hash
        ):
            confirmed_attempts = int(
                dict(row.get("checkpoint") or {}).get("attempted_calls") or 0
            )
            break
    return attempted > confirmed_attempts


def _validate_call(
    *,
    allow_llm: Any,
    route: Any,
    verifier_max_calls: Any,
    verifier_max_total_tokens: Any,
    reconfirm_paid_work: Any,
) -> None:
    if not isinstance(allow_llm, bool):
        raise overrides.ClaimStructuralOverrideError("allow_llm must be boolean")
    if not isinstance(route, str) or not route.strip():
        raise overrides.ClaimStructuralOverrideError("route is required")
    if (
        not isinstance(verifier_max_calls, int)
        or isinstance(verifier_max_calls, bool)
        or verifier_max_calls < 0
        or not isinstance(verifier_max_total_tokens, int)
        or isinstance(verifier_max_total_tokens, bool)
        or verifier_max_total_tokens < 0
    ):
        raise overrides.ClaimStructuralOverrideError(
            "verifier budgets must be non-negative integers"
        )
    if allow_llm and (verifier_max_calls <= 0 or verifier_max_total_tokens <= 0):
        raise overrides.ClaimStructuralOverrideError(
            "allow_llm requires positive verifier call and token budgets"
        )
    if not isinstance(reconfirm_paid_work, bool):
        raise overrides.ClaimStructuralOverrideError(
            "reconfirm_paid_work must be boolean"
        )


def confirm_structural_override(
    out_dir: Path | str,
    *,
    claim_id: str,
    claim_hash: str,
    expected_catalog_generation_id: str,
    expected_claim_effective_revision: str,
    prior_structural_reason: str,
    actor: str,
    reason: str,
    request_idempotency_key: str,
    allow_llm: bool,
    route: str,
    verifier_max_calls: int,
    verifier_max_total_tokens: int,
    operation_id: str | None = None,
    reconfirm_paid_work: bool = False,
) -> dict[str, Any]:
    """Execute or resume one structural override under all mutation fences."""
    _validate_call(
        allow_llm=allow_llm,
        route=route,
        verifier_max_calls=verifier_max_calls,
        verifier_max_total_tokens=verifier_max_total_tokens,
        reconfirm_paid_work=reconfirm_paid_work,
    )
    from claim_structural_operations import (
        ClaimStructuralOperationConflict,
        append_operation_events,
        derive_operation_states,
        get_or_create_operation,
        make_operation_id,
        operation_budget_view,
        read_operation_log,
        structural_execution_lease,
    )

    root = Path(out_dir).expanduser().resolve()
    supplied = {
        "claim_id": str(claim_id),
        "claim_hash": str(claim_hash),
        "expected_catalog_generation_id": str(expected_catalog_generation_id),
        "expected_claim_effective_revision": str(
            expected_claim_effective_revision
        ),
        "prior_structural_reason": str(prior_structural_reason),
        "actor": str(actor),
        "reason": str(reason),
        "request_idempotency_key": str(request_idempotency_key),
        "allow_llm": allow_llm,
        "route": route.strip(),
        "verifier_max_calls": verifier_max_calls,
        "verifier_max_total_tokens": verifier_max_total_tokens,
    }
    operation_key = str(operation_id or "")
    if not operation_key:
        if not supplied["request_idempotency_key"]:
            raise overrides.ClaimStructuralOverrideError(
                "structural request idempotency key is required"
            )
        operation_key = make_operation_id(supplied["request_idempotency_key"])

    with structural_execution_lease(
        root, operation_id=operation_key,
    ) as execution_fence:
        from omission_actions import extraction_operation_lock

        with extraction_operation_lock(root, operation="claim-structural-override"):
            with claim_publication_lock(root):
                states = derive_operation_states(read_operation_log(root).rows)
                state = states.get(operation_key)
                initial_snapshot: dict[str, Any] | None = None
                initial_route_config: Any | None = None
                created = False
                if state is None:
                    if operation_id:
                        raise overrides.ClaimStructuralOverrideError(
                            f"unknown structural operation: {operation_id}"
                        )
                    (
                        initial_snapshot,
                        preconditions,
                        initial_route_config,
                    ) = overrides._initial_preflight(root, supplied)
                    request = {**supplied, "preconditions": preconditions}
                    try:
                        result = get_or_create_operation(
                            root, request, execution_fence=execution_fence,
                        )
                    except ClaimStructuralOperationConflict as exc:
                        raise overrides.ClaimStructuralOverrideStale(str(exc)) from exc
                    state = dict(result["state"])
                    created = bool(result["created"])
                else:
                    stored = dict(state["request"])
                    if supplied["claim_id"] and supplied["claim_id"] != stored.get(
                        "claim_id"
                    ):
                        raise overrides.ClaimStructuralOverrideError(
                            "structural operation belongs to a different claim"
                        )
                    if not operation_id and (
                        overrides._request_without_preconditions(supplied)
                        != overrides._request_without_preconditions(stored)
                    ):
                        raise overrides.ClaimStructuralOverrideStale(
                            "request idempotency key is bound to a different payload"
                        )
                    request = stored

                assert state is not None
                request = dict(state["request"])
                claim_id = str(request["claim_id"])
                allow_llm = bool(request["allow_llm"])
                route = str(request["route"])
                verifier_max_calls = int(request["verifier_max_calls"])
                verifier_max_total_tokens = int(
                    request["verifier_max_total_tokens"]
                )

                def current_state() -> dict[str, Any]:
                    return derive_operation_states(
                        read_operation_log(root).rows
                    )[operation_key]

                def authority_projection() -> tuple[Any, dict[str, Any], Any]:
                    latest = current_state()
                    checkpoints = dict(latest.get("checkpoints") or {})
                    override_checkpoint = dict(
                        checkpoints.get("override_registered") or {}
                    )
                    registry = overrides.read_structural_overrides(root)
                    override_row = next(
                        (
                            dict(row) for row in registry.rows
                            if row.get("override_hash")
                            == override_checkpoint.get("override_hash")
                        ),
                        None,
                    )
                    audit_checkpoint = dict(
                        checkpoints.get("audit_appended") or {}
                    )
                    audit_row = None
                    if audit_checkpoint:
                        from claim_review_actions import read_claim_review_events

                        audit_row = next(
                            (
                                dict(row)
                                for row in read_claim_review_events(
                                    root, repair=False,
                                ).rows
                                if row.get("event_hash")
                                == audit_checkpoint.get("audit_event_hash")
                            ),
                            None,
                        )
                    return (
                        override_row,
                        overrides.structural_override_identity(registry),
                        audit_row,
                    )

                def response(
                    *,
                    ok: bool,
                    status: str,
                    replay: bool = False,
                    error: str = "",
                    refresh: dict[str, Any] | None = None,
                ) -> dict[str, Any]:
                    latest = current_state()
                    override_row, registry_identity, audit_row = (
                        authority_projection()
                    )
                    return {
                        "ok": ok,
                        "status": status,
                        "operation_id": operation_key,
                        "idempotent_replay": replay,
                        "override": override_row,
                        "event": audit_row,
                        "registry": registry_identity,
                        "route_requested": route,
                        "route_model": dict(request["preconditions"]).get(
                            "route_model"
                        ),
                        "route_config_revision": dict(
                            request["preconditions"]
                        ).get("route_config_revision"),
                        "allow_llm": allow_llm,
                        "verifier_budget": operation_budget_view(latest),
                        "needs_reconfirmation": status == "needs_reconfirmation",
                        "effective_fresh": ok,
                        **({"error": error} if error else {}),
                        **({"refresh": refresh} if refresh is not None else {}),
                    }

                if state["lifecycle"] == "succeeded":
                    overrides._load_verified_replay(root, state)
                    return response(ok=True, status="rebuilt", replay=True)
                if state["lifecycle"] == "aborted_stale":
                    raise overrides.ClaimStructuralOverrideStale(
                        "structural operation was aborted after its authority changed"
                    )
                checkpoints = dict(state["checkpoints"])
                if "effective_folded" in checkpoints:
                    binding = dict(checkpoints["effective_folded"]["binding"])
                    from claim_artifacts import (
                        load_committed_effective_snapshot_readonly,
                    )

                    try:
                        snapshot = load_committed_effective_snapshot_readonly(root)
                        current_binding = overrides._effective_binding(
                            root,
                            snapshot,
                            claim_id=claim_id,
                            override_hash=str(binding["override_hash"]),
                        )
                    except (ClaimArtifactError, OSError) as exc:
                        raise overrides.ClaimStructuralOverrideStale(
                            "folded structural operation lost its effective artifacts"
                        ) from exc
                    if current_binding != binding:
                        raise overrides.ClaimStructuralOverrideStale(
                            "folded structural operation no longer matches current artifacts"
                        )
                    append_operation_events(root, [{
                        "operation_id": operation_key,
                        "event_kind": "operation_succeeded",
                        "idempotency_key": overrides._event_key(
                            operation_key, "operation_succeeded",
                        ),
                        "outcome": {
                            "code": "rebuilt", "message": "", "retryable": False,
                        },
                        "binding": binding,
                    }])
                    return response(ok=True, status="rebuilt", replay=True)

                try:
                    state = _recover_authority_checkpoints(
                        root,
                        operation_id=operation_key,
                        request=request,
                        state=state,
                        append_events=append_operation_events,
                        current_state=current_state,
                    )
                    if _recover_published(
                        root,
                        operation_id=operation_key,
                        request=request,
                        state=state,
                        append_events=append_operation_events,
                    ):
                        return response(ok=True, status="rebuilt", replay=True)
                    if created and initial_snapshot is not None:
                        authority_snapshot = initial_snapshot
                        resolved_route_config = initial_route_config
                    else:
                        (
                            authority_snapshot,
                            resolved_route_config,
                        ) = overrides._resume_preflight(root, request, state)
                except overrides.ClaimStructuralOverrideStale as exc:
                    append_operation_events(root, [{
                        "operation_id": operation_key,
                        "event_kind": "operation_aborted_stale",
                        "idempotency_key": overrides._event_key(
                            operation_key, "operation_aborted_stale", str(exc),
                        ),
                        "outcome": {
                            "code": "authority_changed",
                            "message": str(exc)[:1000],
                            "retryable": False,
                            "needs_reconfirmation": True,
                        },
                        "usage": overrides._operation_usage(state),
                    }])
                    raise

                _register_and_audit(
                    root,
                    operation_id=operation_key,
                    request=request,
                    snapshot=authority_snapshot,
                    state=state,
                    append_events=append_operation_events,
                    current_state=current_state,
                )
                state = current_state()
                latest_budget = overrides._operation_usage(state)
                verifier_checkpoint = dict(
                    state["checkpoints"].get("verifier_checkpoint") or {}
                ) or None
                if (
                    _has_unconfirmed_paid_work(state)
                    and state["lifecycle"] != "needs_reconfirmation"
                ):
                    budget_event = dict(state["latest_budget_event"])
                    append_operation_events(root, [{
                        "operation_id": operation_key,
                        "event_kind": "operation_reconfirmation_required",
                        "idempotency_key": overrides._event_key(
                            operation_key,
                            "operation_reconfirmation_required",
                            budget_event["event_hash"],
                        ),
                        "budget_event_hash": budget_event["event_hash"],
                        "usage": latest_budget,
                        "reason": (
                            "provider work has no durable verifier decision; "
                            "automatic replay is blocked"
                        ),
                    }])
                    state = current_state()

                if state["lifecycle"] == "needs_reconfirmation":
                    if not reconfirm_paid_work:
                        return response(
                            ok=False,
                            status="needs_reconfirmation",
                            error=(
                                "paid verifier outcome is incomplete; explicit "
                                "reconfirmation is required before retry"
                            ),
                        )
                    budget_event = dict(state["latest_budget_event"])
                    drafts = [{
                        "operation_id": operation_key,
                        "event_kind": "operation_reconfirmed",
                        "idempotency_key": overrides._event_key(
                            operation_key,
                            "operation_reconfirmed",
                            budget_event["event_hash"],
                        ),
                        "budget_event_hash": budget_event["event_hash"],
                        "actor": str(request["actor"]),
                    }]
                    settled = _settle_unknown_budget(dict(state["latest_budget"]))
                    if settled != state["latest_budget"]:
                        drafts.append({
                            "operation_id": operation_key,
                            "event_kind": "budget_checkpoint",
                            "idempotency_key": overrides._event_key(
                                operation_key, "budget_checkpoint", settled,
                            ),
                            "checkpoint": settled,
                        })
                    append_operation_events(root, drafts)
                    state = current_state()
                    latest_budget = overrides._operation_usage(state)

                reusable_groups = None
                reusable_negatives = None
                verifier_checkpoint = dict(
                    state["checkpoints"].get("verifier_checkpoint") or {}
                ) or None
                if verifier_checkpoint is not None:
                    reusable_groups, reusable_negatives = (
                        overrides._load_decision_sidecar(
                            root,
                            operation_id=operation_key,
                            request=request,
                            state=state,
                            checkpoint=verifier_checkpoint,
                        )
                    )

                from llm_client import LLMRequestBudget

                budget = None
                if allow_llm:
                    budget = (
                        LLMRequestBudget(
                            max_calls=verifier_max_calls,
                            max_tokens=verifier_max_total_tokens,
                        )
                        if latest_budget is None
                        else LLMRequestBudget.from_settled_snapshot(latest_budget)
                    )

                def persist_budget(raw: dict[str, Any]) -> None:
                    if int(raw.get("attempted_calls") or 0) <= 0:
                        return
                    checkpoint = {
                        **raw,
                        "status": (
                            "reserved"
                            if int(raw.get("reserved_tokens") or 0) > 0
                            else "failed"
                            if int(raw.get("failed_calls") or 0) > 0
                            else "settled"
                        ),
                    }
                    append_operation_events(root, [{
                        "operation_id": operation_key,
                        "event_kind": "budget_checkpoint",
                        "idempotency_key": overrides._event_key(
                            operation_key, "budget_checkpoint", checkpoint,
                        ),
                        "checkpoint": checkpoint,
                    }])

                budget_proxy = (
                    overrides._StructuralBudgetProxy(budget, persist_budget)
                    if budget is not None else None
                )
                budget_start = (
                    budget_proxy.snapshot() if budget_proxy is not None else {}
                )

                def persist_decision(shadow: dict[str, Any]) -> None:
                    latest = current_state()
                    current_budget = dict(latest.get("latest_budget") or {})
                    if (
                        int(current_budget.get("attempted_calls") or 0)
                        <= int(budget_start.get("attempted_calls") or 0)
                        or int(current_budget.get("failed_calls") or 0)
                        != int(budget_start.get("failed_calls") or 0)
                        or int(current_budget.get("reserved_tokens") or 0) != 0
                    ):
                        raise overrides.ClaimStructuralOverrideError(
                            "structural verifier work is not durably settled"
                        )
                    checkpoint = overrides._write_decision_sidecar(
                        root,
                        operation_id=operation_key,
                        request=request,
                        state=latest,
                        shadow=shadow,
                    )
                    append_operation_events(root, [{
                        "operation_id": operation_key,
                        "event_kind": "verifier_checkpoint",
                        "idempotency_key": overrides._event_key(
                            operation_key, "verifier_checkpoint",
                        ),
                        **checkpoint,
                    }])

                refresh = None
                try:
                    from ai_extract import refresh_claim_shadow

                    refresh = refresh_claim_shadow(
                        root,
                        route=route,
                        allow_llm=bool(allow_llm and budget_proxy is not None),
                        verifier_max_calls=verifier_max_calls,
                        verifier_max_total_tokens=verifier_max_total_tokens,
                        verifier_request_budget=budget_proxy,
                        resolved_route_config=resolved_route_config,
                        shadow_built_hook=(
                            None
                            if verifier_checkpoint is not None
                            else persist_decision
                            if allow_llm else None
                        ),
                        extra_reusable_groups=reusable_groups,
                        extra_reusable_negatives=reusable_negatives,
                        operation_lock_held=True,
                    )
                    from claim_artifacts import (
                        load_committed_effective_snapshot_readonly,
                    )
                    from claim_review_actions import assess_effective_freshness

                    folded = load_committed_effective_snapshot_readonly(root)
                    if assess_effective_freshness(
                        root, folded, readonly=True,
                    ).get("effective_fresh") is not True:
                        raise overrides.ClaimStructuralOverrideError(
                            "structural override rebuild did not publish a fresh "
                            "effective snapshot"
                        )
                except Exception as exc:
                    state = current_state()
                    usage = overrides._operation_usage(state)
                    ordinal = len(state.get("failures") or []) + 1
                    append_operation_events(root, [{
                        "operation_id": operation_key,
                        "event_kind": "operation_failed",
                        "idempotency_key": overrides._event_key(
                            operation_key,
                            "operation_failed",
                            {
                                "ordinal": ordinal,
                                "error": f"{type(exc).__name__}:{exc}"[:300],
                                "usage": usage,
                            },
                        ),
                        "outcome": {
                            "code": "rebuild_failed",
                            "message": f"{type(exc).__name__}: {exc}"[:1000],
                            "retryable": True,
                        },
                        "usage": usage,
                    }])
                    state = current_state()
                    if _has_unconfirmed_paid_work(state):
                        budget_event = dict(state["latest_budget_event"])
                        append_operation_events(root, [{
                            "operation_id": operation_key,
                            "event_kind": "operation_reconfirmation_required",
                            "idempotency_key": overrides._event_key(
                                operation_key,
                                "operation_reconfirmation_required",
                                budget_event["event_hash"],
                            ),
                            "budget_event_hash": budget_event["event_hash"],
                            "usage": dict(state["latest_budget"]),
                            "reason": (
                                "provider work has no durable verifier decision; "
                                "automatic replay is blocked"
                                ),
                            }])
                        # The reconfirmation request can be an idempotent replay
                        # of one the reviewer has already satisfied.  Report the
                        # durable lifecycle after the append instead of returning
                        # a 409 that the pending-operation view cannot reproduce.
                        if current_state()["lifecycle"] == "needs_reconfirmation":
                            return response(
                                ok=False,
                                status="needs_reconfirmation",
                                error=f"{type(exc).__name__}: {exc}"[:1000],
                            )
                    return response(
                        ok=False,
                        status="rebuild_pending",
                        error=f"{type(exc).__name__}: {exc}"[:1000],
                    )
                finally:
                    if budget_proxy is not None:
                        budget_proxy.close()

                state = current_state()
                checkpoint = dict(state["checkpoints"]["override_registered"])
                binding = overrides._effective_binding(
                    root,
                    folded,
                    claim_id=claim_id,
                    override_hash=str(checkpoint["override_hash"]),
                )
                _append_success(
                    root,
                    operation_id=operation_key,
                    binding=binding,
                    append_events=append_operation_events,
                )
                return response(ok=True, status="rebuilt", refresh=refresh)
