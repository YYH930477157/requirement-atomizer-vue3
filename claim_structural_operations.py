"""Durable, fenced lifecycle log for claim structural overrides."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Iterable, Iterator

from claim_artifacts import (
    ClaimArtifactError,
    _atomic_write_bytes,
    _validate_schema,
    canonical_json_value_bytes,
    claim_artifact_path,
    digest_hex,
    hash_json,
    sha256_bytes,
)
from process_file_lock import process_file_lock


CLAIM_STRUCTURAL_OPERATIONS = "claim_structural_operations.jsonl"
CLAIM_STRUCTURAL_OPERATION_SCHEMA = "claim-structural-operation/v3"
_SUPPORTED_OPERATION_SCHEMAS = frozenset({
    "claim-structural-operation/v2",
    CLAIM_STRUCTURAL_OPERATION_SCHEMA,
})

_LOCK_NAME = "claim_structural_operations.lock"
_EXECUTION_LOCK_NAME = "claim_structural_execution.lock"
_LOCK_TIMEOUT_S = 15.0
_EMPTY_SHA256 = sha256_bytes(b"")
_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
_EXECUTION_LOCKS: dict[Path, Lock] = {}
_EXECUTION_LOCKS_GUARD = RLock()

_OPERATION_EVENT_KINDS = frozenset({
    "operation_started",
    "override_registered",
    "audit_appended",
    "budget_checkpoint",
    "verifier_checkpoint",
    "operation_failed",
    "operation_reconfirmation_required",
    "operation_reconfirmed",
    "base_rebuild_published",
    "effective_folded",
    "operation_succeeded",
    "operation_aborted_stale",
    "operation_recovery_failed_post_publication",
})
_CLOSING_KINDS = frozenset({
    "operation_succeeded",
    "operation_aborted_stale",
    "operation_recovery_failed_post_publication",
})
_SINGLE_CHECKPOINT_KINDS = frozenset({
    "override_registered",
    "audit_appended",
    "verifier_checkpoint",
    "base_rebuild_published",
    "effective_folded",
    "operation_succeeded",
    "operation_aborted_stale",
    "operation_recovery_failed_post_publication",
})


class ClaimStructuralOperationError(ClaimArtifactError):
    """Raised when the structural operation log or transition is invalid."""


class ClaimStructuralOperationConflict(ClaimStructuralOperationError):
    """Raised when an idempotency identity is reused for another request."""


@dataclass(frozen=True)
class StructuralOperationSnapshot:
    rows: list[dict[str, Any]]
    prefix_sha256: str
    last_event_seq: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _process_lock(root: Path) -> RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(root, RLock())


def _execution_process_lock(root: Path) -> Lock:
    with _EXECUTION_LOCKS_GUARD:
        return _EXECUTION_LOCKS.setdefault(root, Lock())


@contextmanager
def structural_execution_lease(
    out_dir: Path | str,
    *,
    operation_id: str,
    timeout_s: float = _LOCK_TIMEOUT_S,
) -> Iterator[str]:
    """Serialize structural mutation across threads and processes.

    The returned opaque fence is bound into a newly-created operation. The OS
    lock is the authority: a crashed process releases it automatically, while a
    live holder prevents another worker from reaching rebuild or the verifier.
    """
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _execution_process_lock(root):
        with process_file_lock(
            claim_artifact_path(root, _EXECUTION_LOCK_NAME),
            timeout_s=timeout_s,
            label="claim structural operation execution lease",
        ):
            yield hash_json(
                "claim-structural-execution-fence/v1",
                {"operation_id": str(operation_id), "nonce": uuid.uuid4().hex},
            )


def make_operation_id(request_idempotency_key: str) -> str:
    digest = hash_json(
        "claim-structural-operation-id/v1",
        {"request_idempotency_key": str(request_idempotency_key)},
    )
    return "CSOP-" + digest_hex(digest)[:16]


def operation_request_fingerprint(request: dict[str, Any]) -> str:
    return hash_json("claim-structural-operation-request/v2", request)


def _event_id(event_seq: int, idempotency_key: str) -> str:
    return f"CSOE-{event_seq}-{digest_hex(idempotency_key)[:12]}"


def _without_hash(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "event_hash"}


def _validate_row(row: dict[str, Any], expected_seq: int, previous_hash: str) -> None:
    try:
        _validate_schema(
            row,
            "claim_structural_operation.schema.json",
            label="claim structural operation",
        )
    except ClaimArtifactError as exc:
        raise ClaimStructuralOperationError(str(exc)) from exc
    row_schema = str(row.get("schema") or "")
    if row_schema not in _SUPPORTED_OPERATION_SCHEMAS:
        raise ClaimStructuralOperationError(
            "claim structural operation row has an invalid schema"
        )
    if row.get("event_seq") != expected_seq:
        raise ClaimStructuralOperationError(
            "claim structural operation sequence is not contiguous"
        )
    key = str(row.get("idempotency_key") or "")
    if row.get("event_id") != _event_id(expected_seq, key):
        raise ClaimStructuralOperationError(
            "claim structural operation event id is invalid"
        )
    if row.get("prev_event_hash") != previous_hash:
        raise ClaimStructuralOperationError(
            "claim structural operation hash chain is broken"
        )
    expected_hash = hash_json(row_schema, _without_hash(row))
    if row.get("event_hash") != expected_hash:
        raise ClaimStructuralOperationError(
            "claim structural operation event hash is invalid"
        )
    if row.get("event_kind") not in _OPERATION_EVENT_KINDS:
        raise ClaimStructuralOperationError(
            "claim structural operation event kind is invalid"
        )


def _budget_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("checkpoint") or {})


def _validate_budget_transition(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    authorized_calls: int,
    authorized_tokens: int,
) -> None:
    max_calls = int(current.get("max_calls") or 0)
    max_tokens = int(current.get("max_tokens") or 0)
    calls = int(current.get("attempted_calls") or 0)
    failed = int(current.get("failed_calls") or 0)
    tokens = int(current.get("tokens") or 0)
    reserved = int(current.get("reserved_tokens") or 0)
    status = str(current.get("status") or "")
    if max_calls != authorized_calls or max_tokens != authorized_tokens:
        raise ClaimStructuralOperationError(
            "structural budget checkpoint changed its authorization"
        )
    if calls > max_calls or failed > calls:
        raise ClaimStructuralOperationError(
            "structural budget checkpoint exceeds its call authorization"
        )
    if int(current.get("remaining_calls") or 0) != max(0, max_calls - calls):
        raise ClaimStructuralOperationError(
            "structural budget remaining call count is invalid"
        )
    if int(current.get("remaining_tokens") or 0) != max(
        0, max_tokens - tokens - reserved,
    ):
        raise ClaimStructuralOperationError(
            "structural budget remaining token count is invalid"
        )
    if status == "reserved" and reserved <= 0:
        raise ClaimStructuralOperationError(
            "reserved structural budget checkpoint has no reservation"
        )
    if status != "reserved" and reserved != 0:
        raise ClaimStructuralOperationError(
            "settled structural budget checkpoint retains a reservation"
        )
    if status == "failed" and failed <= 0:
        raise ClaimStructuralOperationError(
            "failed structural budget checkpoint has no failed call"
        )
    if tokens > max_tokens and current.get("denied") is not True:
        raise ClaimStructuralOperationError(
            "over-budget structural usage is not marked denied"
        )
    if previous is None:
        return
    if (
        int(previous.get("max_calls") or 0) != max_calls
        or int(previous.get("max_tokens") or 0) != max_tokens
    ):
        raise ClaimStructuralOperationError(
            "structural operation budget limits changed"
        )
    previous_calls = int(previous.get("attempted_calls") or 0)
    previous_failed = int(previous.get("failed_calls") or 0)
    previous_tokens = int(previous.get("tokens") or 0)
    if (
        calls < previous_calls
        or failed < previous_failed
        or tokens < previous_tokens
    ):
        raise ClaimStructuralOperationError(
            "structural operation budget accounting moved backwards"
        )
    if calls > previous_calls + 1:
        raise ClaimStructuralOperationError(
            "structural operation budget skipped an attempted call"
        )
    if failed > previous_failed + 1:
        raise ClaimStructuralOperationError(
            "structural operation budget skipped a failed call"
        )
    if calls == previous_calls + 1 and status != "reserved":
        raise ClaimStructuralOperationError(
            "structural operation call was not durably reserved first"
        )
    if str(previous.get("status") or "") == "reserved" and calls != previous_calls:
        raise ClaimStructuralOperationError(
            "structural operation started another call before settling the prior one"
        )
    if (
        previous.get("usage_complete") is False
        and current.get("usage_complete") is True
    ):
        raise ClaimStructuralOperationError(
            "structural operation restored incomplete usage to complete"
        )
    if previous.get("denied") is True and current.get("denied") is not True:
        raise ClaimStructuralOperationError(
            "structural operation cleared a denied budget state"
        )


def _validate_operation_history(operation_rows: list[dict[str, Any]]) -> None:
    if operation_rows[0].get("event_kind") != "operation_started":
        raise ClaimStructuralOperationError(
            "claim structural operation does not begin with operation_started"
        )
    started = operation_rows[0]
    request = started.get("request")
    if not isinstance(request, dict) or not request.get("claim_id"):
        raise ClaimStructuralOperationError(
            "claim structural operation lacks its original request"
        )
    if make_operation_id(
        str(started.get("request_idempotency_key") or "")
    ) != str(started.get("operation_id")):
        raise ClaimStructuralOperationError(
            "claim structural operation id does not match its request key"
        )
    if started.get("request_fingerprint") != operation_request_fingerprint(request):
        raise ClaimStructuralOperationError(
            "claim structural operation request fingerprint is invalid"
        )

    seen: set[str] = set()
    stage = 0
    closed = False
    latest_budget: dict[str, Any] | None = None
    latest_budget_event_hash = ""
    override_hash = ""
    base_generation_id = ""
    effective_binding: dict[str, Any] = {}
    reconfirmation_required = False
    for index, row in enumerate(operation_rows):
        kind = str(row.get("event_kind") or "")
        if index == 0:
            seen.add(kind)
            continue
        if closed:
            raise ClaimStructuralOperationError(
                "claim structural operation continues after a closing event"
            )
        if kind in _SINGLE_CHECKPOINT_KINDS and kind in seen:
            raise ClaimStructuralOperationError(
                f"claim structural operation checkpoint is duplicated: {kind}"
            )
        if kind == "operation_started":
            raise ClaimStructuralOperationError(
                "claim structural operation contains a duplicate start"
            )
        if kind == "override_registered":
            if stage != 0:
                raise ClaimStructuralOperationError(
                    "structural override registration is out of order"
                )
            stage = 1
            override_hash = str(row.get("override_hash") or "")
        elif kind == "audit_appended":
            if stage != 1:
                raise ClaimStructuralOperationError(
                    "structural audit append is out of order"
                )
            stage = 2
        elif kind == "budget_checkpoint":
            if stage != 2:
                raise ClaimStructuralOperationError(
                    "structural budget checkpoint is out of order"
                )
            if "verifier_checkpoint" in seen:
                raise ClaimStructuralOperationError(
                    "structural budget checkpoint follows a verifier decision checkpoint"
                )
            current_budget = _budget_snapshot(row)
            if request.get("allow_llm") is not True:
                raise ClaimStructuralOperationError(
                    "deterministic structural operation has a paid budget checkpoint"
                )
            _validate_budget_transition(
                latest_budget,
                current_budget,
                authorized_calls=int(request.get("verifier_max_calls") or 0),
                authorized_tokens=int(
                    request.get("verifier_max_total_tokens") or 0
                ),
            )
            latest_budget = current_budget
            latest_budget_event_hash = str(row.get("event_hash") or "")
        elif kind == "verifier_checkpoint":
            if stage != 2:
                raise ClaimStructuralOperationError(
                    "structural verifier checkpoint is out of order"
                )
            if latest_budget is None or int(
                latest_budget.get("attempted_calls") or 0
            ) <= 0:
                raise ClaimStructuralOperationError(
                    "structural verifier decisions have no paid budget checkpoint"
                )
            if latest_budget.get("status") == "reserved":
                raise ClaimStructuralOperationError(
                    "structural verifier decisions precede budget settlement"
                )
            verifier_binding = dict(row.get("binding") or {})
            if (
                verifier_binding.get("override_hash") != override_hash
                or verifier_binding.get("budget_event_hash")
                != latest_budget_event_hash
                or verifier_binding.get("budget_checkpoint_hash")
                != hash_json(
                    "claim-structural-budget-checkpoint/v1", latest_budget,
                )
            ):
                raise ClaimStructuralOperationError(
                    "structural verifier decision binding is invalid"
                )
        elif kind == "operation_failed":
            if stage >= 4:
                raise ClaimStructuralOperationError(
                    "structural failure follows an effective fold"
                )
        elif kind == "operation_reconfirmation_required":
            if stage != 2 or latest_budget is None:
                raise ClaimStructuralOperationError(
                    "structural reconfirmation request has no paid checkpoint"
                )
            if (
                row.get("budget_event_hash") != latest_budget_event_hash
                or dict(row.get("usage") or {}) != latest_budget
            ):
                raise ClaimStructuralOperationError(
                    "structural reconfirmation is not bound to the latest budget"
                )
            reconfirmation_required = True
        elif kind == "operation_reconfirmed":
            if not reconfirmation_required:
                raise ClaimStructuralOperationError(
                    "structural paid work was reconfirmed without a request"
                )
            if row.get("budget_event_hash") != latest_budget_event_hash:
                raise ClaimStructuralOperationError(
                    "structural reconfirmation changed its budget binding"
                )
            reconfirmation_required = False
        elif kind == "base_rebuild_published":
            if stage != 2 or reconfirmation_required:
                raise ClaimStructuralOperationError(
                    "structural base rebuild is out of order"
                )
            if (
                latest_budget is not None
                and int(latest_budget.get("attempted_calls") or 0) > 0
                and "verifier_checkpoint" not in seen
            ):
                raise ClaimStructuralOperationError(
                    "paid structural rebuild lacks a verifier decision checkpoint"
                )
            stage = 3
            base_generation_id = str(row.get("base_generation_id") or "")
        elif kind == "effective_folded":
            if stage != 3:
                raise ClaimStructuralOperationError(
                    "structural effective fold is out of order"
                )
            if row.get("effective_fresh") is not True:
                raise ClaimStructuralOperationError(
                    "structural effective fold is not fresh"
                )
            stage = 4
            effective_binding = dict(row.get("binding") or {})
            if effective_binding.get("override_hash") != override_hash:
                raise ClaimStructuralOperationError(
                    "structural effective fold changed the override identity"
                )
            if effective_binding.get("base_generation_id") != base_generation_id:
                raise ClaimStructuralOperationError(
                    "structural effective fold changed the base identity"
                )
        elif kind == "operation_succeeded":
            if stage != 4 or dict(row.get("binding") or {}) != effective_binding:
                raise ClaimStructuralOperationError(
                    "successful structural operation lacks its exact effective binding"
                )
            stage = 5
            closed = True
        elif kind == "operation_aborted_stale":
            if stage >= 3:
                raise ClaimStructuralOperationError(
                    "published structural operation cannot be aborted as stale"
                )
            closed = True
        elif kind == "operation_recovery_failed_post_publication":
            if stage < 3:
                raise ClaimStructuralOperationError(
                    "post-publication recovery failure requires a published base"
                )
            binding = dict(row.get("binding") or {})
            expected_binding = (
                effective_binding
                if stage == 4
                else {"base_generation_id": base_generation_id}
            )
            if binding != expected_binding:
                raise ClaimStructuralOperationError(
                    "post-publication recovery failure lacks its exact publication binding"
                )
            closed = True
        else:  # pragma: no cover - schema and row validation guard this
            raise ClaimStructuralOperationError(
                "claim structural operation event kind is invalid"
            )
        seen.add(kind)


def _validate_histories(rows: list[dict[str, Any]]) -> None:
    by_operation: dict[str, list[dict[str, Any]]] = {}
    keys: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("idempotency_key") or "")
        if key in keys:
            raise ClaimStructuralOperationError(
                "claim structural operation idempotency key is duplicated"
            )
        keys[key] = row
        by_operation.setdefault(str(row["operation_id"]), []).append(row)
    for operation_rows in by_operation.values():
        _validate_operation_history(operation_rows)


def _scan_bytes(raw: bytes) -> StructuralOperationSnapshot:
    rows: list[dict[str, Any]] = []
    previous_hash = _EMPTY_SHA256
    offset = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise ClaimStructuralOperationError(
                "claim structural operation log has a torn tail"
            )
        line = raw[offset:newline + 1]
        try:
            row = json.loads(line[:-1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClaimStructuralOperationError(
                "invalid claim structural operation JSONL"
            ) from exc
        if not isinstance(row, dict) or canonical_json_value_bytes(row) + b"\n" != line:
            raise ClaimStructuralOperationError(
                "claim structural operation row is not canonical"
            )
        _validate_row(row, len(rows) + 1, previous_hash)
        rows.append(row)
        previous_hash = str(row["event_hash"])
        offset = newline + 1
    _validate_histories(rows)
    return StructuralOperationSnapshot(
        rows=rows,
        prefix_sha256=sha256_bytes(raw),
        last_event_seq=len(rows),
    )


def read_operation_log(out_dir: Path | str) -> StructuralOperationSnapshot:
    root = Path(out_dir).expanduser().resolve()
    path = claim_artifact_path(root, CLAIM_STRUCTURAL_OPERATIONS)
    if not path.is_file():
        return StructuralOperationSnapshot([], _EMPTY_SHA256, 0)
    return _scan_bytes(path.read_bytes())


def _draft_matches_event(draft: dict[str, Any], event: dict[str, Any]) -> bool:
    ignored = {
        "schema", "recorded_at", "event_seq", "event_id",
        "prev_event_hash", "event_hash",
    }
    return (
        {key: value for key, value in draft.items() if key not in ignored}
        == {key: value for key, value in event.items() if key not in ignored}
    )


def _append_unlocked(root: Path, drafts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    path = claim_artifact_path(root, CLAIM_STRUCTURAL_OPERATIONS)
    raw = path.read_bytes() if path.is_file() else b""
    snapshot = _scan_bytes(raw)
    rows = list(snapshot.rows)
    by_key = {str(row["idempotency_key"]): row for row in rows}
    appended: list[dict[str, Any]] = []
    previous_hash = str(rows[-1]["event_hash"]) if rows else _EMPTY_SHA256
    for raw_draft in drafts:
        draft = dict(raw_draft)
        if {"event_seq", "event_id", "prev_event_hash", "event_hash"}.intersection(draft):
            raise ClaimStructuralOperationError(
                "claim structural operation draft contains chain fields"
            )
        key = str(draft.get("idempotency_key") or "")
        if not key:
            raise ClaimStructuralOperationError(
                "claim structural operation idempotency key is required"
            )
        existing = by_key.get(key)
        if existing is not None:
            if not _draft_matches_event(draft, existing):
                raise ClaimStructuralOperationConflict(
                    "claim structural operation idempotency key changed payload"
                )
            continue
        draft.setdefault("schema", CLAIM_STRUCTURAL_OPERATION_SCHEMA)
        draft.setdefault("recorded_at", _utc_now())
        seq = len(rows) + 1
        event = {
            **draft,
            "event_seq": seq,
            "event_id": _event_id(seq, key),
            "prev_event_hash": previous_hash,
        }
        event["event_hash"] = hash_json(
            CLAIM_STRUCTURAL_OPERATION_SCHEMA, _without_hash(event)
        )
        _validate_row(event, seq, previous_hash)
        _validate_histories(rows + [event])
        rows.append(event)
        appended.append(event)
        by_key[key] = event
        previous_hash = str(event["event_hash"])
    if appended:
        payload = b"".join(
            canonical_json_value_bytes(row) + b"\n" for row in rows
        )
        _atomic_write_bytes(path, payload)
    return {"appended": appended, "appended_count": len(appended)}


def append_operation_events(
    out_dir: Path | str,
    drafts: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and atomically append operation events under the file lock."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _process_lock(root):
        with process_file_lock(
            claim_artifact_path(root, _LOCK_NAME),
            timeout_s=_LOCK_TIMEOUT_S,
            label="claim structural operation log",
        ):
            return _append_unlocked(root, drafts)


def get_or_create_operation(
    out_dir: Path | str,
    request: dict[str, Any],
    *,
    execution_fence: str | None = None,
) -> dict[str, Any]:
    """Atomically bind one request payload to its idempotency identity."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    request_copy = json.loads(canonical_json_value_bytes(request).decode("utf-8"))
    request_key = str(request_copy.get("request_idempotency_key") or "")
    if not request_key:
        raise ClaimStructuralOperationError(
            "structural request idempotency key is required"
        )
    operation_id = make_operation_id(request_key)
    fingerprint = operation_request_fingerprint(request_copy)
    fence = execution_fence or hash_json(
        "claim-structural-execution-fence/v1",
        {"operation_id": operation_id, "nonce": uuid.uuid4().hex},
    )
    with _process_lock(root):
        with process_file_lock(
            claim_artifact_path(root, _LOCK_NAME),
            timeout_s=_LOCK_TIMEOUT_S,
            label="claim structural operation log",
        ):
            snapshot = read_operation_log(root)
            states = derive_operation_states(snapshot.rows)
            existing = states.get(operation_id)
            if existing is not None:
                if existing.get("request_fingerprint") != fingerprint:
                    raise ClaimStructuralOperationConflict(
                        "request idempotency key is bound to a different payload"
                    )
                return {
                    "operation_id": operation_id,
                    "created": False,
                    "state": existing,
                }
            claim_id = str(request_copy.get("claim_id") or "")
            for state in states.values():
                if (
                    state.get("closed") is not True
                    and str(dict(state.get("request") or {}).get("claim_id") or "")
                    == claim_id
                ):
                    raise ClaimStructuralOperationConflict(
                        "claim already has an active structural operation"
                    )
            started = {
                "operation_id": operation_id,
                "event_kind": "operation_started",
                "idempotency_key": hash_json(
                    "claim-structural-operation-start/v2",
                    {"operation_id": operation_id, "request_fingerprint": fingerprint},
                ),
                "request_idempotency_key": request_key,
                "request_fingerprint": fingerprint,
                "execution_fence": fence,
                "request": request_copy,
            }
            result = _append_unlocked(root, [started])
            state = derive_operation_states(read_operation_log(root).rows)[operation_id]
            return {
                "operation_id": operation_id,
                "created": bool(result["appended_count"]),
                "state": state,
            }


def derive_operation_states(
    rows: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        histories.setdefault(str(row.get("operation_id") or ""), []).append(dict(row))
    states: dict[str, dict[str, Any]] = {}
    for operation_id, history in histories.items():
        started = history[0]
        checkpoints: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, Any]] = []
        budget_rows: list[dict[str, Any]] = []
        reconfirmation_required: dict[str, Any] | None = None
        last_reconfirmation: dict[str, Any] | None = None
        for row in history[1:]:
            kind = str(row.get("event_kind") or "")
            if kind == "budget_checkpoint":
                budget_rows.append(row)
            elif kind == "operation_failed":
                failures.append(row)
            elif kind == "operation_reconfirmation_required":
                reconfirmation_required = row
            elif kind == "operation_reconfirmed":
                last_reconfirmation = row
            elif kind not in {
                "operation_succeeded",
                "operation_aborted_stale",
                "operation_recovery_failed_post_publication",
            }:
                checkpoints[kind] = row
        last = history[-1]
        last_kind = str(last.get("event_kind") or "")
        if last_kind == "operation_succeeded":
            lifecycle = "succeeded"
            closed = True
        elif last_kind == "operation_aborted_stale":
            lifecycle = "aborted_stale"
            closed = True
        elif last_kind == "operation_recovery_failed_post_publication":
            lifecycle = "recovery_failed_post_publication"
            closed = True
        elif (
            reconfirmation_required is not None
            and (
                last_reconfirmation is None
                or int(last_reconfirmation["event_seq"])
                < int(reconfirmation_required["event_seq"])
            )
        ):
            lifecycle = "needs_reconfirmation"
            closed = False
        elif failures:
            lifecycle = "failed"
            closed = False
        else:
            lifecycle = "executing"
            closed = False
        states[operation_id] = {
            "operation_id": operation_id,
            "request": dict(started.get("request") or {}),
            "request_idempotency_key": str(
                started.get("request_idempotency_key") or ""
            ),
            "request_fingerprint": str(started.get("request_fingerprint") or ""),
            "execution_fence": str(started.get("execution_fence") or ""),
            "lifecycle": lifecycle,
            "closed": closed,
            "checkpoints": checkpoints,
            "budget_checkpoints": budget_rows,
            "latest_budget": (
                dict(budget_rows[-1].get("checkpoint") or {})
                if budget_rows else None
            ),
            "latest_budget_event": budget_rows[-1] if budget_rows else None,
            "failures": failures,
            "reconfirmation_required": reconfirmation_required,
            "last_reconfirmation": last_reconfirmation,
            "terminal": last if closed else None,
            "history": history,
        }
    return states


def operation_budget_view(state: dict[str, Any]) -> dict[str, Any]:
    request = dict(state.get("request") or {})
    latest = dict(state.get("latest_budget") or {})
    max_calls = int(
        latest.get("max_calls", request.get("verifier_max_calls") or 0) or 0
    )
    max_tokens = int(
        latest.get(
            "max_tokens", request.get("verifier_max_total_tokens") or 0,
        ) or 0
    )
    attempted = int(latest.get("attempted_calls") or 0)
    tokens = int(latest.get("tokens") or 0)
    reserved = int(latest.get("reserved_tokens") or 0)
    return {
        "max_calls": max_calls,
        "max_total_tokens": max_tokens,
        "attempted_calls": attempted,
        "failed_calls": int(latest.get("failed_calls") or 0),
        "used_tokens": tokens,
        "reserved_tokens": reserved,
        "remaining_calls": max(0, max_calls - attempted),
        "remaining_tokens": max(0, max_tokens - tokens - reserved),
        "usage_complete": latest.get("usage_complete", True) is True,
        "unknown_remote_result": bool(reserved),
    }


def pending_structural_operations(
    out_dir: Path | str,
) -> dict[str, dict[str, Any]]:
    """Non-closed operations keyed by claim id for API/read views."""
    snapshot = read_operation_log(out_dir)
    pending: dict[str, dict[str, Any]] = {}
    for state in derive_operation_states(snapshot.rows).values():
        if state.get("closed") is True:
            continue
        request = dict(state.get("request") or {})
        claim_id = str(request.get("claim_id") or "")
        if not claim_id:
            continue
        preconditions = dict(request.get("preconditions") or {})
        pending[claim_id] = {
            "operation_id": state["operation_id"],
            "lifecycle": state["lifecycle"],
            "checkpoints": sorted(state["checkpoints"]),
            "route_requested": str(request.get("route") or ""),
            "route_model": preconditions.get("route_model"),
            "route_config_revision": preconditions.get("route_config_revision"),
            "allow_llm": request.get("allow_llm") is True,
            "verifier_budget": operation_budget_view(state),
            "needs_reconfirmation": state["lifecycle"] == "needs_reconfirmation",
        }
    return pending
