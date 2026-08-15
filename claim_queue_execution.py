from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable

import ai_extract
from claim_artifacts import (
    ClaimArtifactError,
    canonical_target_fingerprint,
    claim_budget_checkpoint_event_idempotency_key,
    claim_budget_checkpoint_payload,
    claim_base_generation_id,
    file_sha256,
    hash_json,
    load_committed_claim_base,
    load_committed_effective_snapshot,
)
from claim_focus import ClaimFocusError, build_claim_focus_adapter
from claim_ledger import CLAIM_QUEUE_PROPOSAL_SCHEMA
from claim_reextract_attempts import (
    CLAIM_REEXTRACT_ATTEMPT_SCHEMA,
    append_attempt_events,
    attempt_id as make_attempt_id,
    derive_attempt_states,
    read_attempt_log,
    recover_interrupted_attempts,
)
from claim_review_actions import (
    ClaimReviewActionError,
    _load_b_track_authority,
    assess_effective_freshness,
)
from io_utils import read_jsonl
from llm_client import (
    LLMBudgetExceeded,
    LLMConnectionError,
    LLMRequestBudget,
    LLMResponseError,
    apply_min_tokens,
)
from omission_actions import (
    OmissionConflictError,
    OmissionNoResultError,
    extraction_operation_lock,
    omission_source_fingerprint,
    targeted_reextract,
)


class ClaimQueueExecutionError(RuntimeError):
    pass


class ClaimQueueExecutionConflict(ClaimQueueExecutionError):
    pass


class ClaimQueueExecutionUnprocessable(ClaimQueueExecutionError):
    pass


class ClaimQueueExecutionRemoteError(ClaimQueueExecutionError):
    pass


class ClaimQueueExecutionUnavailable(ClaimQueueExecutionError):
    def __init__(self, message: str, *, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = dict(result or {})


def _event_key(attempt_id: str, kind: str, detail: Any) -> str:
    return hash_json(
        "claim-reextract-event-idempotency/v1",
        {"attempt_id": attempt_id, "event_kind": kind, "detail": detail},
    )


CLAIM_QUEUE_ROUTE_CONFIG_REVISION_VERSION = "claim-queue-route-config/v2"
CLAIM_BUDGET_CHECKPOINT_FANOUT_VERSION = "claim-budget-checkpoint-fanout-v1"

# Persisted attempt schemas are a read contract, not an alias for the current
# writer version. Keep every supported reader identity explicit so a future v3
# writer does not accidentally make historical v2 attempts unreadable.
_REPLAY_ATTEMPT_SCHEMA_POLICIES = {
    "claim-reextract-attempt/v1": {
        "allow_legacy_revision_key": True,
        "has_route_config_revision": False,
    },
    "claim-reextract-attempt/v2": {
        "allow_legacy_revision_key": False,
        "has_route_config_revision": True,
    },
}


def _credential_identity(config: Any) -> dict[str, Any]:
    """Return a non-secret identity for the credential used by this route."""
    api_key_env = str(config.api_key_env or "")
    credential = os.environ.get(api_key_env, "") if api_key_env else ""
    return {
        "api_key_env": api_key_env,
        "credential_present": bool(credential),
        "credential_fingerprint": (
            hash_json(
                "claim-queue-route-credential/v1",
                {"api_key_env": api_key_env, "credential": credential},
            )
            if credential
            else None
        ),
    }


def _resolved_route_preflight(
    route: str,
    config: Any,
) -> tuple[Any, dict[str, Any]]:
    """Bind confirmation and execution to one resolved config object."""
    resolved = apply_min_tokens(config, "extract")
    revision = hash_json(
        CLAIM_QUEUE_ROUTE_CONFIG_REVISION_VERSION,
        {
            "route": str(route),
            "base_url": str(resolved.base_url),
            "model": str(resolved.model or ""),
            **_credential_identity(resolved),
            "temperature": float(resolved.temperature),
            "max_tokens": int(resolved.max_tokens),
            "timeout_s": float(resolved.timeout_s),
            "max_retries": int(resolved.max_retries),
        },
    )
    return resolved, {
        "route": str(route),
        "configured": True,
        "model": str(resolved.model or ""),
        "route_config_revision": revision,
    }


def claim_queue_route_preflight(route: str = "openai_compatible") -> dict[str, Any]:
    """Read-only route preflight: the exact config a paid call would use."""
    config = ai_extract.config_for_route(route)
    if config is None:
        return {
            "route": str(route),
            "configured": False,
            "model": None,
            "route_config_revision": None,
        }
    _resolved, preflight = _resolved_route_preflight(route, config)
    return preflight


def _common_event(
    *,
    attempt_id: str,
    proposal: dict[str, Any],
    actor: str,
    event_kind: str,
    detail: Any,
) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "proposal_id": str(proposal["proposal_id"]),
        "claim_id": str(proposal["claim_id"]),
        "claim_hash": str(proposal["claim_hash"]),
        "event_kind": event_kind,
        "actor": actor,
        "idempotency_key": _event_key(attempt_id, event_kind, detail),
    }


def _append_event(
    root: Path,
    event: dict[str, Any],
    *,
    operation_lock_held: bool,
) -> None:
    append_attempt_events(
        root,
        [event],
        operation_lock_held=operation_lock_held,
    )


class _ClaimQueueBudgetCheckpoint:
    """Durable owner for queue budget snapshots.

    ``claim_verifier_attempt_scope`` recognizes ``prepare_fanout_event`` and
    wraps the queue event plus verifier-WAL update in its recoverable outbox.
    Outside that scope this remains a normal single-sink callback.
    """

    FANOUT_VERSION = CLAIM_BUDGET_CHECKPOINT_FANOUT_VERSION

    def __init__(
        self,
        root: Path,
        *,
        attempt_id: str,
        proposal: dict[str, Any],
        actor: str,
    ) -> None:
        self._root = root
        self._attempt_id = attempt_id
        self._proposal = proposal
        self._actor = actor
        self._highest_emitted_calls = 0

    @staticmethod
    def _payload(snapshot: dict[str, Any]) -> dict[str, Any] | None:
        return claim_budget_checkpoint_payload(snapshot)

    def prepare_fanout_event(
        self,
        snapshot: dict[str, Any],
        transition_id: str,
    ) -> dict[str, Any] | None:
        payload = self._payload(snapshot)
        if payload is None:
            return None
        calls = int(payload["calls"])
        if calls < self._highest_emitted_calls:
            return None
        self._highest_emitted_calls = calls
        detail = {
            "transition_id": str(transition_id),
            **payload,
        }
        event = {
            "schema": CLAIM_REEXTRACT_ATTEMPT_SCHEMA,
            **_common_event(
                attempt_id=self._attempt_id,
                proposal=self._proposal,
                actor=self._actor,
                event_kind="budget_checkpoint",
                detail=detail,
            ),
            "checkpoint": payload,
        }
        event["idempotency_key"] = claim_budget_checkpoint_event_idempotency_key(
            attempt_id=self._attempt_id,
            transition_id=str(transition_id),
            checkpoint=payload,
        )
        return event

    def __call__(self, snapshot: dict[str, Any]) -> None:
        event = self.prepare_fanout_event(snapshot, os.urandom(16).hex())
        if event is not None:
            _append_event(
                self._root,
                event,
                operation_lock_held=True,
            )


def _proposal_attempt_state(
    root: Path,
    proposal_id: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], Any]:
    """One attempt-log read feeds both the state map and the caller's rows.

    Previously the caller re-read the whole log just to filter the same
    attempt's rows; the snapshot is returned so the critical section threads
    it through instead of rescanning (the reader is additionally memoized by
    file stat signature, so repeated reads inside one execute are O(1)).
    """
    snapshot = read_attempt_log(root)
    states = derive_attempt_states(snapshot.rows)
    relevant = [
        state
        for state in states.values()
        if str(state.get("proposal_id") or "") == proposal_id
    ]
    relevant.sort(
        key=lambda state: int(dict(state.get("last_event") or {}).get("event_seq") or 0)
    )
    return states, relevant, snapshot


def _proposal_from_attempt_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history or history[0].get("event_kind") != "reextract_started":
        raise ClaimQueueExecutionUnavailable("claim attempt has no durable start record")
    started = history[0]
    focus = dict(started.get("focus") or {})
    return {
        "schema": CLAIM_QUEUE_PROPOSAL_SCHEMA,
        "proposal_id": str(started["proposal_id"]),
        "claim_id": str(started["claim_id"]),
        "claim_hash": str(started["claim_hash"]),
        "parent_block_id": str(focus.get("block_id") or ""),
        "focus": focus,
        "execution_preconditions": dict(started.get("preconditions") or {}),
    }


def _require_matching_replay_request(
    started: dict[str, Any],
    *,
    expected_claim_effective_revision: str,
    expected_ledger_state: str,
    actor: str,
    allow_llm: bool,
    route: str,
    maximum_calls: int,
    total_token_budget: int,
    request_idempotency_key: str,
    expected_route_config_revision: str,
    deterministic_recovery: bool = False,
) -> None:
    """Reject reuse of an idempotency key for a different logical request."""
    budgets = dict(started.get("budgets") or {})
    preconditions = dict(started.get("preconditions") or {})
    mismatches: list[str] = []

    def differs(field: str, requested: Any, committed: Any) -> None:
        if requested != committed:
            mismatches.append(field)

    differs(
        "request_idempotency_key",
        request_idempotency_key,
        str(started.get("request_idempotency_key") or ""),
    )
    differs("actor", actor, str(started.get("actor") or ""))
    differs("route", route, str(started.get("route") or ""))
    differs("expected_ledger_state", expected_ledger_state, "uncertain")
    started_schema = str(started.get("schema") or "")
    schema_policy = _REPLAY_ATTEMPT_SCHEMA_POLICIES.get(started_schema)
    if schema_policy is None:
        raise ClaimQueueExecutionConflict(
            f"unsupported re-extract attempt schema: {started_schema or 'missing'}"
        )
    canonical_revision = str(
        preconditions.get("expected_claim_effective_revision") or ""
    )
    legacy_revision = str(preconditions.get("claim_effective_revision") or "")
    if (
        canonical_revision
        and legacy_revision
        and canonical_revision != legacy_revision
    ):
        mismatches.append("claim_effective_revision_keys")
    committed_revision = canonical_revision
    if not committed_revision and schema_policy["allow_legacy_revision_key"]:
        committed_revision = legacy_revision
    differs(
        "expected_claim_effective_revision",
        expected_claim_effective_revision,
        committed_revision,
    )
    if not deterministic_recovery:
        differs("allow_llm", allow_llm is True, True)
        try:
            requested_calls = int(maximum_calls)
        except (TypeError, ValueError):
            requested_calls = None
        try:
            requested_tokens = int(total_token_budget)
        except (TypeError, ValueError):
            requested_tokens = None
        differs("maximum_calls", requested_calls, budgets.get("max_calls"))
        differs(
            "total_token_budget",
            requested_tokens,
            budgets.get("max_total_tokens"),
        )
        if schema_policy["has_route_config_revision"]:
            committed_route_revision = str(
                started.get("route_config_revision") or ""
            )
            differs(
                "expected_route_config_revision",
                expected_route_config_revision,
                committed_route_revision,
            )
    if mismatches:
        raise ClaimQueueExecutionConflict(
            "request idempotency key was already used with different parameters: "
            + ", ".join(sorted(set(mismatches)))
        )


def _validate_current_proposal(
    root: Path,
    *,
    proposal_id: str,
    expected_claim_effective_revision: str,
    expected_ledger_state: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        snapshot = load_committed_effective_snapshot(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=False)
    except (ClaimArtifactError, ClaimReviewActionError, OSError, ValueError) as exc:
        raise ClaimQueueExecutionUnavailable(
            f"claim effective snapshot is unavailable: {exc}"
        ) from exc
    if not freshness.get("effective_fresh"):
        reasons = ", ".join(freshness.get("freshness_reasons") or [])
        raise ClaimQueueExecutionUnavailable(
            f"claim effective snapshot requires refresh: {reasons or 'stale'}"
        )
    generation = dict(snapshot.get("generation_meta") or {})
    if (
        str(generation.get("delivery_track") or "") != "B"
        or str(generation.get("target_kind") or "") != "ai_requirement"
    ):
        raise ClaimQueueExecutionUnprocessable(
            "claim queue execution is supported only for B-track AI requirements"
        )
    proposal = next(
        (
            dict(row)
            for row in (snapshot.get("queue_proposals") or [])
            if str(row.get("proposal_id") or "") == proposal_id
        ),
        None,
    )
    if proposal is None:
        raise ClaimQueueExecutionConflict(
            "claim queue proposal is no longer current; refresh before execution"
        )
    if proposal.get("schema") != CLAIM_QUEUE_PROPOSAL_SCHEMA:
        raise ClaimQueueExecutionUnprocessable("claim queue proposal requires v3 migration")
    row = next(
        (
            dict(item)
            for item in (snapshot.get("effective_ledger") or [])
            if item.get("claim_id") == proposal.get("claim_id")
        ),
        None,
    )
    if row is None:
        raise ClaimQueueExecutionConflict("claim is no longer in the effective ledger")
    if (
        str(expected_ledger_state or "") != "uncertain"
        or row.get("resolution") != "uncertain"
        or proposal.get("expected_ledger_state") != "uncertain"
    ):
        raise ClaimQueueExecutionConflict("claim ledger state is no longer uncertain")
    if (
        str(row.get("claim_effective_revision") or "")
        != expected_claim_effective_revision
        or str(proposal.get("claim_effective_revision") or "")
        != expected_claim_effective_revision
    ):
        raise ClaimQueueExecutionConflict(
            "claim effective revision changed; refresh before execution"
        )
    focus = proposal.get("focus")
    if (
        not isinstance(focus, dict)
        or focus.get("kind") == "unavailable"
        or proposal.get("focus_error")
    ):
        raise ClaimQueueExecutionUnprocessable(
            str(proposal.get("focus_error") or "claim focus is unavailable")
        )
    claim = next(
        (
            dict(item)
            for item in (snapshot.get("catalog") or [])
            if item.get("claim_id") == proposal.get("claim_id")
        ),
        None,
    )
    if claim is None:
        raise ClaimQueueExecutionConflict("claim catalog row is no longer current")
    try:
        current_focus = build_claim_focus_adapter(
            claim,
            read_jsonl(root / "blocks.jsonl"),
            read_jsonl(root / "table_items.jsonl")
            if (root / "table_items.jsonl").is_file()
            else [],
            read_jsonl(root / "table_cell_items.jsonl")
            if (root / "table_cell_items.jsonl").is_file()
            else [],
        )
    except (ClaimFocusError, OSError, ValueError) as exc:
        raise ClaimQueueExecutionUnprocessable(str(exc)) from exc
    if current_focus != focus:
        raise ClaimQueueExecutionConflict(
            "claim focus changed; refresh before execution"
        )

    preconditions = dict(proposal.get("execution_preconditions") or {})
    authority = _load_b_track_authority(root)
    expected_authority = {
        "target_publication_revision": authority["target_publication_revision"],
        "target_set_hash": authority["target_set_hash"],
        "requirement_review_state_hash": authority["requirement_review_state_hash"],
    }
    for field, current in expected_authority.items():
        if preconditions.get(field) != current:
            raise ClaimQueueExecutionConflict(
                f"claim target authority changed: {field}"
            )
    if (
        preconditions.get("parent_block_fingerprint")
        != current_focus.get("parent_block_fingerprint")
        or preconditions.get("claim_hash") != row.get("claim_hash")
        or preconditions.get("claim_source_fingerprint")
        != canonical_target_fingerprint(row.get("claim_hash"))
    ):
        raise ClaimQueueExecutionConflict("claim source preconditions changed")
    return snapshot, proposal, row


def _usage_from_budget(budget: LLMRequestBudget) -> dict[str, Any]:
    snapshot = budget.snapshot()
    return {
        "calls": int(snapshot.get("attempted_calls") or 0),
        "total_tokens": int(snapshot.get("tokens") or 0),
        "usage_complete": bool(snapshot.get("usage_complete")),
    }


def _usage_from_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    checkpoints = [
        dict(row.get("checkpoint") or {})
        for row in history
        if row.get("event_kind") == "budget_checkpoint"
    ]
    latest = checkpoints[-1] if checkpoints else {}
    return {
        "calls": int(latest.get("calls") or 0),
        "total_tokens": latest.get("total_tokens"),
        "usage_complete": bool(latest.get("usage_complete")),
    }


def _durable_usage(
    root: Path,
    *,
    attempt_id: str,
    budget: LLMRequestBudget,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    history = [
        row
        for row in (rows if rows is not None else read_attempt_log(root).rows)
        if row.get("attempt_id") == attempt_id
    ]
    if any(row.get("event_kind") == "budget_checkpoint" for row in history):
        return _usage_from_history(history)
    return _usage_from_budget(budget)


def _append_terminal(
    root: Path,
    *,
    attempt_id: str,
    proposal: dict[str, Any],
    actor: str,
    event_kind: str,
    code: str,
    message: str,
    retryable: bool,
    usage: dict[str, Any],
    operation_lock_held: bool,
) -> None:
    detail = {"code": code, "usage": usage}
    _append_event(
        root,
        {
            **_common_event(
                attempt_id=attempt_id,
                proposal=proposal,
                actor=actor,
                event_kind=event_kind,
                detail=detail,
            ),
            "outcome": {
                "code": code,
                "message": str(message)[:1000],
                "retryable": retryable,
            },
            "usage": usage,
        },
        operation_lock_held=operation_lock_held,
    )


def _current_published_base(root: Path, attempt_id: str) -> dict[str, Any] | None:
    from claim_reextract_attempts import require_published_attempt

    requirements_path = root / ai_extract.AI_REQUIREMENTS
    if not requirements_path.is_file():
        return None
    requirements_hash = file_sha256(requirements_path)
    require_published_attempt(
        root,
        attempt_id=attempt_id,
        requirements_sha256=requirements_hash,
    )
    try:
        base = load_committed_claim_base(root)
    except (ClaimArtifactError, OSError, ValueError):
        return None
    generation = dict(base.get("generation_meta") or {})
    if (
        generation.get("delivery_track") != "B"
        or generation.get("target_kind") != "ai_requirement"
        or generation.get("requirements_sha256") != requirements_hash
    ):
        return None
    return base


def _terminal_attempt_is_projected(
    snapshot: dict[str, Any],
    *,
    proposal: dict[str, Any],
    attempt_id: str,
) -> bool:
    claim_id = str(proposal.get("claim_id") or "")
    row = next(
        (
            item
            for item in (snapshot.get("effective_ledger") or [])
            if item.get("claim_id") == claim_id
        ),
        None,
    )
    if row is None:
        return False
    queue_row = next(
        (
            item
            for item in (snapshot.get("queue_proposals") or [])
            if item.get("claim_id") == claim_id
        ),
        None,
    )
    if row.get("resolution") != "uncertain":
        return queue_row is None
    if queue_row is None:
        return False
    if queue_row.get("proposal_id") != proposal.get("proposal_id"):
        return (
            queue_row.get("claim_effective_revision")
            == row.get("claim_effective_revision")
        )
    latest = dict(queue_row.get("latest_attempt") or {})
    return bool(
        queue_row.get("lifecycle") == "executed"
        and latest.get("attempt_id") == attempt_id
        and latest.get("lifecycle") == "succeeded"
    )


def _ensure_terminal_attempt_projection(
    root: Path,
    *,
    proposal: dict[str, Any],
    attempt_id: str,
) -> dict[str, Any]:
    snapshot: dict[str, Any] | None
    try:
        snapshot = load_committed_effective_snapshot(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=False)
    except ClaimArtifactError:
        snapshot = None
        freshness = {"effective_fresh": False}
    if (
        snapshot is not None
        and freshness.get("effective_fresh")
        and _terminal_attempt_is_projected(
            snapshot,
            proposal=proposal,
            attempt_id=attempt_id,
        )
    ):
        return snapshot

    from claim_review_actions import fold_effective_ledger

    try:
        fold_effective_ledger(
            root,
            actor_trigger="claim-reextract-terminal-projection",
        )
        snapshot = load_committed_effective_snapshot(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=False)
    except (ClaimArtifactError, OSError, ValueError) as exc:
        raise ClaimQueueExecutionUnavailable(
            "claim attempt succeeded but its queue projection is pending",
            result={
                "schema": "claim-queue-execution/v1",
                "proposal_id": proposal["proposal_id"],
                "attempt_id": attempt_id,
                "lifecycle": "rebuild_pending",
                "retryable": True,
                "error": f"{type(exc).__name__}: {exc}"[:1000],
            },
        ) from exc
    if (
        not freshness.get("effective_fresh")
        or not _terminal_attempt_is_projected(
            snapshot,
            proposal=proposal,
            attempt_id=attempt_id,
        )
    ):
        raise ClaimQueueExecutionUnavailable(
            "claim attempt succeeded but its queue projection is pending",
            result={
                "schema": "claim-queue-execution/v1",
                "proposal_id": proposal["proposal_id"],
                "attempt_id": attempt_id,
                "lifecycle": "rebuild_pending",
                "retryable": True,
            },
        )
    return snapshot


def _finish_rebuild(
    root: Path,
    *,
    attempt_id: str,
    proposal: dict[str, Any],
    actor: str,
    route: str,
    budget: LLMRequestBudget | None,
    resolved_route_config: Any | None,
    mutation: dict[str, Any] | None,
) -> dict[str, Any]:
    refresh: dict[str, Any] | None = None
    base = _current_published_base(root, attempt_id)
    if base is None:
        # Keep the queue checkpoint owner attached through refresh. The
        # verifier scope fans each cumulative transition through its durable
        # outbox, so recovery retains extraction and verifier costs.
        try:
            refresh = ai_extract.refresh_claim_shadow(
                root,
                route=route if budget is not None else None,
                allow_llm=budget is not None,
                resolved_route_config=(
                    resolved_route_config if budget is not None else None
                ),
                verifier_request_budget=budget,
                claim_mutation_attempt_id=attempt_id,
            )
        except Exception as exc:
            base = _current_published_base(root, attempt_id)
            if base is None:
                if budget is not None:
                    budget.set_checkpoint(None)
                result = {
                    "schema": "claim-queue-execution/v1",
                    "proposal_id": proposal["proposal_id"],
                    "attempt_id": attempt_id,
                    "lifecycle": "rebuild_pending",
                    "retryable": True,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                }
                raise ClaimQueueExecutionUnavailable(
                    "requirements were published but claim rebuild is pending",
                    result=result,
                ) from exc
    if budget is not None:
        budget.set_checkpoint(None)

    with extraction_operation_lock(root, operation="claim-reextract-finalize"):
        try:
            snapshot = load_committed_effective_snapshot(root)
        except ClaimArtifactError:
            base = _current_published_base(root, attempt_id)
            if base is None:
                raise ClaimQueueExecutionUnavailable(
                    "claim base rebuild is not durably published",
                    result={
                        "schema": "claim-queue-execution/v1",
                        "proposal_id": proposal["proposal_id"],
                        "attempt_id": attempt_id,
                        "lifecycle": "rebuild_pending",
                        "retryable": True,
                    },
                )
            generation = dict(base["generation_meta"])
            base_id = claim_base_generation_id(generation)
            _append_event(
                root,
                {
                    **_common_event(
                        attempt_id=attempt_id,
                        proposal=proposal,
                        actor=actor,
                        event_kind="base_rebuild_published",
                        detail=base_id,
                    ),
                    "base_generation_id": base_id,
                },
                operation_lock_held=True,
            )
            from claim_review_actions import fold_effective_ledger

            fold_effective_ledger(
                root,
                actor_trigger="claim-reextract-recovery-fold",
            )
            snapshot = load_committed_effective_snapshot(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=False)
        if not freshness.get("effective_fresh"):
            raise ClaimQueueExecutionUnavailable(
                "claim rebuild published a stale effective snapshot",
                result={
                    "schema": "claim-queue-execution/v1",
                    "proposal_id": proposal["proposal_id"],
                    "attempt_id": attempt_id,
                    "lifecycle": "rebuild_pending",
                    "retryable": True,
                    "freshness_reasons": freshness.get("freshness_reasons") or [],
                },
            )
        row = next(
            (
                dict(item)
                for item in (snapshot.get("effective_ledger") or [])
                if item.get("claim_id") == proposal.get("claim_id")
            ),
            None,
        )
        if row is None:
            raise ClaimQueueExecutionUnavailable(
                "claim is absent after the base rebuild",
                result={
                    "schema": "claim-queue-execution/v1",
                    "proposal_id": proposal["proposal_id"],
                    "attempt_id": attempt_id,
                    "lifecycle": "rebuild_pending",
                    "retryable": True,
                },
            )
        generation = dict(snapshot["generation_meta"])
        effective_meta = dict(snapshot["effective_meta"])
        base_id = claim_base_generation_id(generation)
        _append_event(
            root,
            {
                **_common_event(
                    attempt_id=attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="base_rebuild_published",
                    detail=base_id,
                ),
                "base_generation_id": base_id,
            },
            operation_lock_held=True,
        )
        _append_event(
            root,
            {
                **_common_event(
                    attempt_id=attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="effective_folded",
                    detail={
                        "document": effective_meta["document_effective_revision"],
                        "claim": row["claim_effective_revision"],
                    },
                ),
                "document_effective_revision": effective_meta[
                    "document_effective_revision"
                ],
                "claim_effective_revision": row["claim_effective_revision"],
                "effective_fresh": True,
            },
            operation_lock_held=True,
        )
        # One log read feeds both terminal-usage branches; the append above
        # already refreshed the memoized reader, so this is not another scan.
        finalize_rows = read_attempt_log(root).rows
        if budget is not None:
            usage = _durable_usage(
                root,
                attempt_id=attempt_id,
                budget=budget,
                rows=finalize_rows,
            )
        else:
            attempt_rows = [
                item
                for item in finalize_rows
                if item.get("attempt_id") == attempt_id
            ]
            usage = _usage_from_history(attempt_rows)
        _append_terminal(
            root,
            attempt_id=attempt_id,
            proposal=proposal,
            actor=actor,
            event_kind="reextract_succeeded",
            code=str(row.get("resolution") or "unknown"),
            message="",
            retryable=False,
            usage=usage,
            operation_lock_held=True,
        )
        snapshot = _ensure_terminal_attempt_projection(
            root,
            proposal=proposal,
            attempt_id=attempt_id,
        )
        row = next(
            item
            for item in (snapshot.get("effective_ledger") or [])
            if item.get("claim_id") == proposal.get("claim_id")
        )
        effective_meta = dict(snapshot["effective_meta"])
    return {
        "schema": "claim-queue-execution/v1",
        "proposal_id": proposal["proposal_id"],
        "attempt_id": attempt_id,
        "claim_id": proposal["claim_id"],
        "lifecycle": "executed",
        "resolution": row.get("resolution"),
        "claim_effective_revision": row.get("claim_effective_revision"),
        "document_effective_revision": effective_meta.get(
            "document_effective_revision"
        ),
        "usage": usage,
        "mutation": mutation,
        "refresh": refresh,
        "retryable": False,
    }


def execute_claim_queue_proposal(
    out_dir: Path | str,
    *,
    proposal_id: str,
    expected_claim_effective_revision: str,
    expected_ledger_state: str,
    actor: str,
    allow_llm: bool,
    route: str,
    maximum_calls: int,
    total_token_budget: int,
    request_idempotency_key: str,
    chat_with_meta: Callable[..., tuple[dict[str, Any], dict[str, Any]]] | None = None,
    expected_route_config_revision: str | None = None,
) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    proposal_id = str(proposal_id or "").strip()
    expected_claim_effective_revision = str(
        expected_claim_effective_revision or ""
    ).strip()
    actor = str(actor or "").strip()
    route = str(route or "").strip()
    request_idempotency_key = str(request_idempotency_key or "").strip()
    expected_route_config_revision = str(
        expected_route_config_revision or ""
    ).strip()
    if not all((proposal_id, expected_claim_effective_revision, actor, route,
                request_idempotency_key)):
        raise ValueError(
            "proposal id, expected revision, actor, route, and idempotency key are required"
        )
    if route != "openai_compatible":
        raise ValueError("claim queue execution requires openai_compatible route")
    current_attempt_id = make_attempt_id(proposal_id, request_idempotency_key)
    budget: LLMRequestBudget | None = None
    proposal: dict[str, Any]
    mutation: dict[str, Any] | None = None
    requirements_published = False
    resolved_route_config: Any | None = None

    with extraction_operation_lock(root, operation="claim-reextract"):
        recover_interrupted_attempts(root, operation_lock_held=True)
        states, relevant, attempt_snapshot = _proposal_attempt_state(root, proposal_id)
        existing = states.get(current_attempt_id)
        if existing is not None:
            lifecycle = str(existing.get("lifecycle") or "")
            history = [
                row
                for row in attempt_snapshot.rows
                if row.get("attempt_id") == current_attempt_id
            ]
            if not history:
                raise ClaimQueueExecutionUnavailable(
                    "claim attempt has no durable start record"
                )
            _require_matching_replay_request(
                history[0],
                expected_claim_effective_revision=(
                    expected_claim_effective_revision
                ),
                expected_ledger_state=expected_ledger_state,
                actor=actor,
                allow_llm=allow_llm,
                route=route,
                maximum_calls=maximum_calls,
                total_token_budget=total_token_budget,
                request_idempotency_key=request_idempotency_key,
                expected_route_config_revision=(
                    expected_route_config_revision
                ),
                deterministic_recovery=lifecycle == "rebuild_pending",
            )
            if lifecycle in {"succeeded", "failed", "interrupted", "aborted_stale"}:
                terminal = dict(existing.get("terminal_event") or {})
                if lifecycle == "succeeded":
                    proposal = _proposal_from_attempt_history(history)
                    _ensure_terminal_attempt_projection(
                        root,
                        proposal=proposal,
                        attempt_id=current_attempt_id,
                    )
                return {
                    "schema": "claim-queue-execution/v1",
                    "proposal_id": proposal_id,
                    "attempt_id": current_attempt_id,
                    "lifecycle": (
                        "executed" if lifecycle == "succeeded" else lifecycle
                    ),
                    "outcome": terminal.get("outcome"),
                    "usage": terminal.get("usage"),
                    "idempotent_replay": True,
                }
            if lifecycle != "rebuild_pending":
                raise ClaimQueueExecutionUnavailable(
                    "claim re-extraction attempt is already executing or interrupted"
                )
            proposal = _proposal_from_attempt_history(history)
            publication = next(
                (
                    row
                    for row in reversed(history)
                    if row.get("event_kind") == "requirements_published"
                ),
                None,
            )
            authority = _load_b_track_authority(root)
            if (
                publication is None
                or publication.get("target_publication_revision")
                != authority.get("target_publication_revision")
                or publication.get("requirements_sha256")
                != file_sha256(root / ai_extract.AI_REQUIREMENTS)
            ):
                usage = _usage_from_history(history)
                _append_terminal(
                    root,
                    attempt_id=current_attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="reextract_aborted_stale",
                    code="recovery_target_changed",
                    message="published requirements changed before deterministic recovery",
                    retryable=True,
                    usage=usage,
                    operation_lock_held=True,
                )
                raise ClaimQueueExecutionConflict(
                    "published requirements changed before deterministic recovery"
                )
            # A requirements publication is durable. Recovery below performs only
            # deterministic rebuild/fold work and never repeats the paid call.
            requirements_published = True
        else:
            if any(
                str(state.get("lifecycle") or "") in {"executing", "rebuild_pending"}
                for state in relevant
            ):
                raise ClaimQueueExecutionConflict(
                    "another live attempt already owns this claim proposal"
                )
            if allow_llm is not True:
                raise ValueError("new claim queue execution requires allow_llm=true")
            if (
                isinstance(maximum_calls, bool)
                or isinstance(total_token_budget, bool)
                or int(maximum_calls) <= 0
                or int(total_token_budget) <= 0
            ):
                raise ValueError(
                    "maximum_calls and total_token_budget must be positive integers"
                )
            if not expected_route_config_revision:
                raise ClaimQueueExecutionConflict(
                    "route configuration revision is required for paid execution"
                )
            config = ai_extract.config_for_route(route)
            if config is None:
                raise ClaimQueueExecutionUnavailable(
                    "openai_compatible route is not configured"
                )
            resolved_route_config, route_preflight = _resolved_route_preflight(
                route,
                config,
            )
            current_revision = str(
                route_preflight["route_config_revision"] or ""
            )
            if current_revision != expected_route_config_revision:
                raise ClaimQueueExecutionConflict(
                    "route configuration changed since the paid confirmation"
                )
            _snapshot, proposal, _row = _validate_current_proposal(
                root,
                proposal_id=proposal_id,
                expected_claim_effective_revision=expected_claim_effective_revision,
                expected_ledger_state=expected_ledger_state,
            )
            budget = LLMRequestBudget(
                max_calls=int(maximum_calls),
                max_tokens=int(total_token_budget),
            )
            started = {
                **_common_event(
                    attempt_id=current_attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="reextract_started",
                    detail=request_idempotency_key,
                ),
                "request_idempotency_key": request_idempotency_key,
                "route": route,
                "model": str(route_preflight["model"] or ""),
                "route_config_revision": current_revision,
                "budgets": {
                    "max_calls": int(maximum_calls),
                    "max_total_tokens": int(total_token_budget),
                    "allow_semantic_verifier": True,
                },
                "preconditions": copy.deepcopy(
                    proposal["execution_preconditions"]
                ),
                "focus": copy.deepcopy(proposal["focus"]),
            }
            _append_event(root, started, operation_lock_held=True)
            budget.set_checkpoint(_ClaimQueueBudgetCheckpoint(
                root,
                attempt_id=current_attempt_id,
                proposal=proposal,
                actor=actor,
            ))

            def revalidate() -> None:
                _validate_current_proposal(
                    root,
                    proposal_id=proposal_id,
                    expected_claim_effective_revision=expected_claim_effective_revision,
                    expected_ledger_state=expected_ledger_state,
                )

            def supplement_persisted(patch: dict[str, Any]) -> None:
                _append_event(
                    root,
                    {
                        **_common_event(
                            attempt_id=current_attempt_id,
                            proposal=proposal,
                            actor=actor,
                            event_kind="supplement_persisted",
                            detail=patch["supplement_id"],
                        ),
                        "supplement_id": patch["supplement_id"],
                        "supplement_hash": hash_json(
                            "claim-reextract-supplement/v1", patch
                        ),
                    },
                    operation_lock_held=True,
                )

            def target_published(_requirements: list[dict[str, Any]]) -> None:
                nonlocal requirements_published
                authority = _load_b_track_authority(root)
                _append_event(
                    root,
                    {
                        **_common_event(
                            attempt_id=current_attempt_id,
                            proposal=proposal,
                            actor=actor,
                            event_kind="requirements_published",
                            detail=authority["target_publication_revision"],
                        ),
                        "requirements_sha256": file_sha256(
                            root / ai_extract.AI_REQUIREMENTS
                        ),
                        "target_publication_revision": authority[
                            "target_publication_revision"
                        ],
                    },
                    operation_lock_held=True,
                )
                requirements_published = True

            block_id = str(proposal.get("parent_block_id") or "")
            block = next(
                (
                    item
                    for item in read_jsonl(root / "blocks.jsonl")
                    if str(item.get("block_id") or "") == block_id
                ),
                None,
            )
            if block is None:
                raise ClaimQueueExecutionUnprocessable("claim parent block is unavailable")
            try:
                mutation = targeted_reextract(
                    root,
                    block_id=block_id,
                    actor=actor,
                    reason="claim queue targeted extraction",
                    route=route,
                    expected_source_fingerprint=omission_source_fingerprint(
                        block_id,
                        str(block.get("text") or ""),
                    ),
                    claim_execution={
                        "proposal_id": proposal_id,
                        "attempt_id": current_attempt_id,
                        "claim_id": proposal["claim_id"],
                        "claim_hash": proposal["claim_hash"],
                        "focus": proposal["focus"],
                        "request_budget": budget,
                        "pre_publish_check": revalidate,
                        "on_supplement_persisted": supplement_persisted,
                        "on_requirements_published": target_published,
                        "chat_with_meta": chat_with_meta,
                        "resolved_route_config": resolved_route_config,
                    },
                    operation_lock_held=True,
                )
            except ClaimQueueExecutionConflict:
                usage = _durable_usage(
                    root,
                    attempt_id=current_attempt_id,
                    budget=budget,
                )
                _append_terminal(
                    root,
                    attempt_id=current_attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="reextract_aborted_stale",
                    code="stale_prepublication_cas",
                    message="claim inputs changed after the paid response",
                    retryable=True,
                    usage=usage,
                    operation_lock_held=True,
                )
                budget.set_checkpoint(None)
                raise
            except OmissionConflictError as exc:
                usage = _durable_usage(
                    root,
                    attempt_id=current_attempt_id,
                    budget=budget,
                )
                _append_terminal(
                    root,
                    attempt_id=current_attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="reextract_aborted_stale",
                    code="stale_prepublication_cas",
                    message=str(exc),
                    retryable=True,
                    usage=usage,
                    operation_lock_held=True,
                )
                budget.set_checkpoint(None)
                raise ClaimQueueExecutionConflict(str(exc)) from exc
            except (OmissionNoResultError, LLMBudgetExceeded) as exc:
                usage = _durable_usage(
                    root,
                    attempt_id=current_attempt_id,
                    budget=budget,
                )
                _append_terminal(
                    root,
                    attempt_id=current_attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="reextract_failed",
                    code="no_guarded_output" if isinstance(exc, OmissionNoResultError) else "budget_exhausted",
                    message=str(exc),
                    retryable=False,
                    usage=usage,
                    operation_lock_held=True,
                )
                budget.set_checkpoint(None)
                raise ClaimQueueExecutionUnprocessable(str(exc)) from exc
            except (LLMConnectionError, LLMResponseError) as exc:
                usage = _durable_usage(
                    root,
                    attempt_id=current_attempt_id,
                    budget=budget,
                )
                _append_terminal(
                    root,
                    attempt_id=current_attempt_id,
                    proposal=proposal,
                    actor=actor,
                    event_kind="reextract_failed",
                    code="remote_error",
                    message=str(exc),
                    retryable=True,
                    usage=usage,
                    operation_lock_held=True,
                )
                budget.set_checkpoint(None)
                raise ClaimQueueExecutionRemoteError(str(exc)) from exc
            except Exception as exc:
                if not requirements_published:
                    usage = _durable_usage(
                        root,
                        attempt_id=current_attempt_id,
                        budget=budget,
                    )
                    _append_terminal(
                        root,
                        attempt_id=current_attempt_id,
                        proposal=proposal,
                        actor=actor,
                        event_kind="reextract_failed",
                        code="local_error",
                        message=str(exc),
                        retryable=True,
                        usage=usage,
                        operation_lock_held=True,
                    )
                    budget.set_checkpoint(None)
                    raise ClaimQueueExecutionUnavailable(str(exc)) from exc
                mutation = {
                    "schema": "claim-reextract-mutation/v1",
                    "warning": f"post-publication derived rebuild failed: {exc}"[:1000],
                }

    return _finish_rebuild(
        root,
        attempt_id=current_attempt_id,
        proposal=proposal,
        actor=actor,
        route=route,
        budget=budget,
        resolved_route_config=resolved_route_config,
        mutation=mutation,
    )
