from __future__ import annotations

import json
import os
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from claim_artifacts import (
    ClaimArtifactError,
    _validate_schema,
    canonical_json_value_bytes,
    digest_hex,
    hash_json,
    sha256_bytes,
)
from omission_actions import extraction_operation_lock


CLAIM_REEXTRACT_ATTEMPTS = "claim_reextract_attempts.jsonl"
CLAIM_REEXTRACT_ATTEMPT_SCHEMA = "claim-reextract-attempt/v1"
CLAIM_REEXTRACT_ATTEMPT_VERSION = "claim-reextract-attempt-log-v1"
_EMPTY_SHA256 = sha256_bytes(b"")
_TERMINAL_EVENTS = frozenset({
    "reextract_succeeded",
    "reextract_failed",
    "reextract_interrupted",
    "reextract_aborted_stale",
})


class ClaimReextractAttemptError(ClaimArtifactError):
    pass


@dataclass(frozen=True)
class AttemptLogSnapshot:
    rows: list[dict[str, Any]]
    prefix_bytes: bytes
    prefix_sha256: str
    last_event_seq: int
    last_event_hash: str
    idempotency_keys: frozenset[str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def attempt_id(proposal_id: str, request_idempotency_key: str) -> str:
    value = hash_json(
        "claim-reextract-attempt-id/v1",
        {
            "proposal_id": str(proposal_id),
            "request_idempotency_key": str(request_idempotency_key),
        },
    )
    return f"CRA-{digest_hex(value)[:16]}"


def _event_id(event_seq: int, idempotency_key: str) -> str:
    return f"CRAE-{event_seq}-{digest_hex(idempotency_key)[:12]}"


def _without_hash(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "event_hash"}


def _scan(root: Path) -> AttemptLogSnapshot:
    path = root / CLAIM_REEXTRACT_ATTEMPTS
    if not path.is_file():
        return AttemptLogSnapshot([], b"", _EMPTY_SHA256, 0, _EMPTY_SHA256, frozenset())
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    previous_hash = _EMPTY_SHA256
    offset = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise ClaimReextractAttemptError("claim re-extract attempt log has a torn tail")
        line = raw[offset:newline + 1]
        try:
            row = json.loads(line[:-1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClaimReextractAttemptError("invalid claim re-extract attempt JSONL") from exc
        if not isinstance(row, dict) or canonical_json_value_bytes(row) + b"\n" != line:
            raise ClaimReextractAttemptError("claim re-extract attempt row is not canonical")
        _validate_schema(
            row,
            "claim_reextract_attempt.schema.json",
            label="claim re-extract attempt",
        )
        expected_seq = len(rows) + 1
        key = str(row.get("idempotency_key") or "")
        if row.get("event_seq") != expected_seq:
            raise ClaimReextractAttemptError("claim re-extract event sequence is not contiguous")
        if row.get("event_id") != _event_id(expected_seq, key):
            raise ClaimReextractAttemptError("claim re-extract event id is invalid")
        if row.get("prev_event_hash") != previous_hash:
            raise ClaimReextractAttemptError("claim re-extract event hash chain is broken")
        expected_hash = hash_json(CLAIM_REEXTRACT_ATTEMPT_SCHEMA, _without_hash(row))
        if row.get("event_hash") != expected_hash:
            raise ClaimReextractAttemptError("claim re-extract event hash is invalid")
        if key in keys:
            raise ClaimReextractAttemptError("claim re-extract idempotency key is duplicated")
        rows.append(row)
        keys.add(key)
        previous_hash = str(row["event_hash"])
        offset = newline + 1
    _validate_attempt_histories(rows)
    return AttemptLogSnapshot(
        rows,
        raw,
        sha256_bytes(raw),
        len(rows),
        previous_hash,
        frozenset(keys),
    )


def _validate_attempt_histories(rows: list[dict[str, Any]]) -> None:
    by_attempt: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_attempt.setdefault(str(row["attempt_id"]), []).append(row)
    for attempt_rows in by_attempt.values():
        first = attempt_rows[0]
        if first.get("event_kind") != "reextract_started":
            raise ClaimReextractAttemptError("attempt history must begin with reextract_started")
        terminal_seen = False
        identity = tuple(first.get(key) for key in ("proposal_id", "claim_id", "claim_hash"))
        seen_kinds: set[str] = set()
        for row in attempt_rows:
            if tuple(row.get(key) for key in ("proposal_id", "claim_id", "claim_hash")) != identity:
                raise ClaimReextractAttemptError("attempt identity changed within its history")
            kind = str(row["event_kind"])
            if terminal_seen:
                raise ClaimReextractAttemptError("attempt history continues after a terminal event")
            if kind in _TERMINAL_EVENTS:
                terminal_seen = True
            if kind in {
                "supplement_persisted",
                "requirements_published",
                "base_rebuild_published",
                "effective_folded",
            } and kind in seen_kinds:
                raise ClaimReextractAttemptError(f"attempt checkpoint is duplicated: {kind}")
            seen_kinds.add(kind)
        kinds = [str(row["event_kind"]) for row in attempt_rows]
        if "requirements_published" in kinds and "supplement_persisted" not in kinds:
            raise ClaimReextractAttemptError("requirements publication lacks a supplement checkpoint")
        if "base_rebuild_published" in kinds and "requirements_published" not in kinds:
            raise ClaimReextractAttemptError("base rebuild lacks a requirements checkpoint")
        if "effective_folded" in kinds and "base_rebuild_published" not in kinds:
            raise ClaimReextractAttemptError("effective fold lacks a base rebuild checkpoint")
        if kinds[-1] == "reextract_succeeded" and "effective_folded" not in kinds:
            raise ClaimReextractAttemptError("successful attempt lacks an effective fold checkpoint")


def read_attempt_log(out_dir: Path | str) -> AttemptLogSnapshot:
    return _scan(Path(out_dir).expanduser().resolve())


def _append_unlocked(root: Path, drafts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    snapshot = _scan(root)
    rows = list(snapshot.rows)
    keys = set(snapshot.idempotency_keys)
    appended: list[dict[str, Any]] = []
    handle = None
    try:
        for raw in drafts:
            draft = dict(raw)
            if {"event_seq", "event_id", "prev_event_hash", "event_hash"}.intersection(draft):
                raise ClaimReextractAttemptError("attempt draft contains chain fields")
            draft.setdefault("schema", CLAIM_REEXTRACT_ATTEMPT_SCHEMA)
            draft.setdefault("recorded_at", _utc_now())
            key = str(draft.get("idempotency_key") or "")
            if not key:
                raise ClaimReextractAttemptError("attempt event idempotency key is required")
            if key in keys:
                continue
            seq = len(rows) + 1
            event = {
                **draft,
                "event_seq": seq,
                "event_id": _event_id(seq, key),
                "prev_event_hash": str(rows[-1]["event_hash"]) if rows else _EMPTY_SHA256,
            }
            event["event_hash"] = hash_json(CLAIM_REEXTRACT_ATTEMPT_SCHEMA, _without_hash(event))
            _validate_schema(
                event,
                "claim_reextract_attempt.schema.json",
                label="claim re-extract attempt",
            )
            candidate_rows = rows + [event]
            _validate_attempt_histories(candidate_rows)
            if handle is None:
                handle = (root / CLAIM_REEXTRACT_ATTEMPTS).open("ab")
            handle.write(canonical_json_value_bytes(event) + b"\n")
            rows.append(event)
            appended.append(event)
            keys.add(key)
        if handle is not None:
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if handle is not None:
            handle.close()
    committed = _scan(root)
    return {
        "appended": appended,
        "appended_count": len(appended),
        "prefix_sha256": committed.prefix_sha256,
        "last_event_seq": committed.last_event_seq,
        "last_event_hash": committed.last_event_hash,
    }


def append_attempt_events(
    out_dir: Path | str,
    drafts: Iterable[dict[str, Any]],
    *,
    operation_lock_held: bool = False,
) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (
        nullcontext()
        if operation_lock_held
        else extraction_operation_lock(root, operation="claim-reextract-attempt")
    )
    with lock:
        return _append_unlocked(root, drafts)


def derive_attempt_states(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        histories.setdefault(str(row["attempt_id"]), []).append(dict(row))
    states: dict[str, dict[str, Any]] = {}
    for current_attempt_id, history in histories.items():
        kinds = [str(row["event_kind"]) for row in history]
        terminal = history[-1] if kinds[-1] in _TERMINAL_EVENTS else None
        if terminal is not None:
            lifecycle = str(terminal["event_kind"]).removeprefix("reextract_")
        elif "requirements_published" in kinds and "effective_folded" not in kinds:
            lifecycle = "rebuild_pending"
        else:
            lifecycle = "executing"
        states[current_attempt_id] = {
            "attempt_id": current_attempt_id,
            "proposal_id": history[0]["proposal_id"],
            "claim_id": history[0]["claim_id"],
            "request_idempotency_key": history[0].get(
                "request_idempotency_key"
            ),
            "lifecycle": lifecycle,
            "terminal_event": terminal,
            "last_event": history[-1],
            "event_count": len(history),
            "requirements_published": "requirements_published" in kinds,
            "base_rebuild_published": "base_rebuild_published" in kinds,
            "effective_folded": "effective_folded" in kinds,
        }
    return states


def _recovery_event_key(attempt_id: str, event_kind: str, detail: Any) -> str:
    return hash_json(
        "claim-reextract-event-idempotency/v1",
        {
            "attempt_id": attempt_id,
            "event_kind": event_kind,
            "detail": detail,
        },
    )


def _recovery_common(
    started: dict[str, Any],
    *,
    event_kind: str,
    detail: Any,
) -> dict[str, Any]:
    attempt = str(started["attempt_id"])
    return {
        "attempt_id": attempt,
        "proposal_id": str(started["proposal_id"]),
        "claim_id": str(started["claim_id"]),
        "claim_hash": str(started["claim_hash"]),
        "event_kind": event_kind,
        "actor": "system:claim-reextract-recovery",
        "idempotency_key": _recovery_event_key(attempt, event_kind, detail),
    }


def _recovered_usage(history: list[dict[str, Any]]) -> dict[str, Any]:
    checkpoints = [
        dict(row.get("checkpoint") or {})
        for row in history
        if row.get("event_kind") == "budget_checkpoint"
    ]
    if not checkpoints:
        return {"calls": 0, "total_tokens": 0, "usage_complete": True}
    latest = checkpoints[-1]
    if latest.get("status") == "settled":
        return {
            "calls": int(latest.get("calls") or 0),
            "total_tokens": latest.get("total_tokens"),
            "usage_complete": bool(latest.get("usage_complete")),
        }
    return {
        "calls": int(latest.get("calls") or 0),
        "total_tokens": None,
        "usage_complete": False,
    }


def _published_patch(
    patch: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> bool:
    from ai_review_actions import review_subject_fingerprint, source_ai_requirement_id

    upserts = [dict(row) for row in (patch.get("upserts") or []) if isinstance(row, dict)]
    if not upserts:
        return False
    current = {
        source_ai_requirement_id(row): review_subject_fingerprint(row)
        for row in requirements
    }
    return all(
        current.get(source_ai_requirement_id(row)) == review_subject_fingerprint(row)
        for row in upserts
    )


def recover_interrupted_attempts(
    out_dir: Path | str,
    *,
    operation_lock_held: bool = False,
) -> dict[str, Any]:
    """Reconcile orphaned durable facts, then terminalize ambiguous paid work.

    Acquiring the extraction lease distinguishes a dead process from a live remote
    call. A fully published target is projected as ``rebuild_pending`` so recovery
    can continue without another paid call; every earlier crash window becomes an
    explicit, retryable ``interrupted`` attempt.
    """
    from claim_artifacts import file_sha256
    from io_utils import read_jsonl
    from omission_actions import AI_SUPPLEMENTS, read_supplement_patches

    root = Path(out_dir).expanduser().resolve()
    preflight = _scan(root)
    if not any(
        state.get("lifecycle") == "executing"
        for state in derive_attempt_states(preflight.rows).values()
    ):
        return {"recovered": 0, "interrupted": 0, "appended_count": 0}
    lock = (
        nullcontext()
        if operation_lock_held
        else extraction_operation_lock(root, operation="claim-reextract-recovery")
    )
    with lock:
        snapshot = _scan(root)
        states = derive_attempt_states(snapshot.rows)
        orphan_ids = {
            attempt
            for attempt, state in states.items()
            if state.get("lifecycle") == "executing"
        }
        if not orphan_ids:
            return {"recovered": 0, "interrupted": 0, "appended_count": 0}

        try:
            patches = read_supplement_patches(root) if (root / AI_SUPPLEMENTS).is_file() else []
        except (OSError, ValueError) as exc:
            raise ClaimReextractAttemptError(
                "claim supplement log is unavailable during attempt recovery"
            ) from exc
        patches_by_attempt: dict[str, list[dict[str, Any]]] = {}
        for patch in patches:
            origin = patch.get("origin")
            if not isinstance(origin, dict):
                continue
            attempt = str(origin.get("attempt_id") or "")
            if attempt in orphan_ids:
                patches_by_attempt.setdefault(attempt, []).append(dict(patch))

        requirements_path = root / "ai_requirements.jsonl"
        try:
            requirements = read_jsonl(requirements_path) if requirements_path.is_file() else []
        except (OSError, ValueError) as exc:
            raise ClaimReextractAttemptError(
                "AI requirements are unavailable during attempt recovery"
            ) from exc

        histories: dict[str, list[dict[str, Any]]] = {}
        for row in snapshot.rows:
            histories.setdefault(str(row["attempt_id"]), []).append(dict(row))

        drafts: list[dict[str, Any]] = []
        recovered = 0
        interrupted = 0
        for attempt in sorted(orphan_ids):
            history = histories[attempt]
            started = history[0]
            kinds = {str(row["event_kind"]) for row in history}
            attempt_patches = patches_by_attempt.get(attempt, [])
            patch = attempt_patches[0] if len(attempt_patches) == 1 else None

            if patch is not None and "supplement_persisted" not in kinds:
                supplement_id = str(patch.get("supplement_id") or "")
                drafts.append({
                    **_recovery_common(
                        started,
                        event_kind="supplement_persisted",
                        detail=supplement_id,
                    ),
                    "supplement_id": supplement_id,
                    "supplement_hash": hash_json(
                        "claim-reextract-supplement/v1",
                        patch,
                    ),
                })

            publication_recovered = False
            if (
                patch is not None
                and "requirements_published" not in kinds
                and requirements_path.is_file()
                and _published_patch(patch, requirements)
            ):
                requirements_hash = file_sha256(requirements_path)
                publication_revision = hash_json(
                    "claim-target-publication-revision/v1",
                    {
                        "source_store": "ai_requirements.jsonl",
                        "source_present": True,
                        "source_file_sha256": requirements_hash,
                    },
                )
                drafts.append({
                    **_recovery_common(
                        started,
                        event_kind="requirements_published",
                        detail=publication_revision,
                    ),
                    "requirements_sha256": requirements_hash,
                    "target_publication_revision": publication_revision,
                })
                publication_recovered = True
                recovered += 1

            if "requirements_published" in kinds or publication_recovered:
                continue

            usage = _recovered_usage(history)
            code = "process_interrupted_before_publication"
            detail = {"code": code, "usage": usage}
            drafts.append({
                **_recovery_common(
                    started,
                    event_kind="reextract_interrupted",
                    detail=detail,
                ),
                "outcome": {
                    "code": code,
                    "message": (
                        "the extraction lease was released without a durable "
                        "requirements publication"
                    ),
                    "retryable": True,
                },
                "usage": usage,
            })
            interrupted += 1

        result = _append_unlocked(root, drafts) if drafts else {"appended_count": 0}
        return {
            "recovered": recovered,
            "interrupted": interrupted,
            "appended_count": int(result.get("appended_count") or 0),
        }


def require_published_attempt(
    out_dir: Path | str,
    *,
    attempt_id: str,
    requirements_sha256: str,
) -> dict[str, Any]:
    """Return durable target-mutation provenance or fail closed."""
    root = Path(out_dir).expanduser().resolve()
    attempt_id = str(attempt_id or "").strip()
    history = [
        dict(row)
        for row in _scan(root).rows
        if str(row.get("attempt_id") or "") == attempt_id
    ]
    if not history or history[0].get("event_kind") != "reextract_started":
        raise ClaimReextractAttemptError("claim mutation attempt is unavailable")
    kinds = [str(row.get("event_kind") or "") for row in history]
    if "supplement_persisted" not in kinds or "requirements_published" not in kinds:
        raise ClaimReextractAttemptError(
            "claim mutation attempt has no durable requirements publication"
        )
    terminal = history[-1] if history[-1].get("event_kind") in _TERMINAL_EVENTS else None
    if terminal is not None and terminal.get("event_kind") != "reextract_succeeded":
        raise ClaimReextractAttemptError("claim mutation attempt ended without publication success")
    publication = next(
        row for row in reversed(history) if row.get("event_kind") == "requirements_published"
    )
    if str(publication.get("requirements_sha256") or "") != str(requirements_sha256 or ""):
        raise ClaimReextractAttemptError(
            "claim mutation publication does not match current requirements"
        )
    return {
        "started": history[0],
        "publication": publication,
        "history": history,
    }
