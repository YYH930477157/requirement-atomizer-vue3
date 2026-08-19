from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from claim_artifacts import (
    ClaimArtifactError,
    _validate_schema,
    atomic_write_jsonl,
    canonical_json_value_bytes,
    claim_artifact_path,
    digest_hex,
    hash_json,
    sha256_bytes,
)
from omission_actions import extraction_operation_lock


CLAIM_REEXTRACT_ATTEMPTS = "claim_reextract_attempts.jsonl"
CLAIM_REEXTRACT_ATTEMPT_SCHEMA = "claim-reextract-attempt/v2"
CLAIM_REEXTRACT_ATTEMPT_VERSION = "claim-reextract-attempt-log-v3"
_SUPPORTED_ATTEMPT_SCHEMAS = frozenset({
    "claim-reextract-attempt/v1",
    CLAIM_REEXTRACT_ATTEMPT_SCHEMA,
})
_EMPTY_SHA256 = sha256_bytes(b"")
_TERMINAL_EVENTS = frozenset({
    "reextract_succeeded",
    "reextract_failed",
    "reextract_interrupted",
    "reextract_aborted_stale",
})


class ClaimReextractAttemptError(ClaimArtifactError):
    pass


# --- Append-mode chain state -------------------------------------------------
#
# S10 redesign (2026-08-14): appends used to rewrite the whole canonical file
# per event (scan + atomic rewrite + re-scan → O(N²); N=300 measured 366.8s).
# The log is now opened in append mode with one fsync per event. The hash chain
# and canonical row bytes are byte-for-byte what the atomic writer produced, so
# the on-disk format and reader semantics (incl. torn-tail fail-closed reads)
# are unchanged; CLAIM_REEXTRACT_ATTEMPT_VERSION stays ``*-v3``.
#
# A crash mid-line can leave a torn (newline-less) tail. Readers keep failing
# closed on it; write-side paths (append/compaction, under the extraction
# operation lock) truncate the uncommitted partial line back to the last
# complete generation before appending. Compaction re-materializes the file
# through the atomic path when on-disk bytes drift from the canonical rows.
_ATTEMPT_MEMO_GUARD = threading.RLock()
_ATTEMPT_MEMO: dict[Path, "_AttemptLogMemo"] = {}
_ATTEMPT_LOG_COMPACT_MAX_BYTES = max(
    1,
    int(os.environ.get("RATOMIZER_ATTEMPT_LOG_COMPACT_MAX_BYTES") or 8 * 1024 * 1024),
)
_ATTEMPT_LOG_COMPACT_MAX_ROWS = max(
    1,
    int(os.environ.get("RATOMIZER_ATTEMPT_LOG_COMPACT_MAX_ROWS") or 2000),
)
# P2 consistency (2026-08-15): the true-append write paths (open("ab") appends
# and the torn-tail truncation open("r+b")) were bare writes. Windows AV /
# indexer handles can transiently deny those opens with PermissionError, which
# would abort a locked append outright. Same discipline as the
# review_state/desktop_tasks replacers and the translation sidecar journal:
# 8 attempts × 0.02s×(1..7) linear backoff, re-raise after the budget —
# failures stay loud.
_APPEND_RETRY_ATTEMPTS = 8
_APPEND_RETRY_DELAY_S = 0.02


class _AttemptLogMemo:
    """Chain-head state for one attempt-log file, keyed by its stat signature.

    ``rows`` and ``raw_bytes`` are shared with snapshot consumers; treat them
    as read-only. The sha256 hasher is advanced incrementally so the committed
    prefix digest stays O(len(event)) per append.
    """

    __slots__ = ("signature", "raw_bytes", "rows", "idempotency_keys", "hasher")

    def __init__(
        self,
        signature: tuple[int, int, int, int, int],
        raw_bytes: bytes,
        rows: list[dict[str, Any]],
        idempotency_keys: Iterable[str],
    ) -> None:
        self.signature = signature
        self.raw_bytes = raw_bytes
        self.rows = rows
        self.idempotency_keys = frozenset(idempotency_keys)
        self.hasher = hashlib.sha256(raw_bytes)

    def snapshot(self) -> AttemptLogSnapshot:
        return AttemptLogSnapshot(
            rows=self.rows,
            prefix_bytes=self.raw_bytes,
            prefix_sha256="sha256:" + self.hasher.hexdigest(),
            last_event_seq=len(self.rows),
            last_event_hash=(
                str(self.rows[-1]["event_hash"]) if self.rows else _EMPTY_SHA256
            ),
            idempotency_keys=self.idempotency_keys,
        )


def _file_signature(path: Path) -> tuple[int, int, int, int, int] | None:
    """Stat signature extended with file identity (st_ino/st_dev).

    Same rationale as ``claim_artifacts._stat_identity_signature``: the
    toolchain writes through atomic os.replace, which always mints a fresh
    file identity, so a replaced log can never collide with a memoized
    signature even when size and mtime_ns were restored (Windows additionally
    preserves creation time — st_ctime_ns — across a replace). Where the
    filesystem reports ``st_ino == 0`` (some network/reparse paths) the extra
    fields are constant and the key degrades to the legacy
    (size, mtime_ns, ctime_ns) strength.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return (
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_ino,
        stat.st_dev,
    )


def _empty_memo() -> _AttemptLogMemo:
    return _AttemptLogMemo((0, 0, 0, 0, 0), b"", [], ())


def _store_memo(root: Path, memo: _AttemptLogMemo) -> _AttemptLogMemo:
    with _ATTEMPT_MEMO_GUARD:
        _ATTEMPT_MEMO[root] = memo
    return memo


def _memo_hit(
    root: Path,
    signature: tuple[int, int, int, int, int] | None,
) -> _AttemptLogMemo | None:
    if signature is None:
        return None
    with _ATTEMPT_MEMO_GUARD:
        memo = _ATTEMPT_MEMO.get(root)
    if memo is not None and memo.signature == signature:
        return memo
    return None


def _truncate_torn_tail(path: Path, raw: bytes) -> bytes:
    """Drop an uncommitted partial trailing line (write paths only, locked).

    ``truncate(cut)`` targets an absolute offset and is therefore idempotent,
    so retrying the whole open/truncate/fsync unit after a transient
    PermissionError can never truncate past the intended cut.
    """
    cut = raw.rfind(b"\n") + 1
    for attempt in range(_APPEND_RETRY_ATTEMPTS):
        try:
            with path.open("r+b") as handle:
                handle.truncate(cut)
                handle.flush()
                os.fsync(handle.fileno())
            return raw[:cut]
        except PermissionError:
            if attempt + 1 >= _APPEND_RETRY_ATTEMPTS:
                raise
            time.sleep(_APPEND_RETRY_DELAY_S * (attempt + 1))


def _load_for_write(root: Path) -> _AttemptLogMemo:
    """Load (and, when necessary, heal) the log for an append under lock."""
    path = claim_artifact_path(root, CLAIM_REEXTRACT_ATTEMPTS)
    signature = _file_signature(path)
    memo = _memo_hit(root, signature)
    if memo is not None:
        return memo
    if signature is None:
        return _store_memo(root, _empty_memo())
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        # A newline-less tail never fsynced as a complete event; remove it so
        # the chain continues from the last committed generation.
        raw = _truncate_torn_tail(path, raw)
    snapshot = _scan_bytes(raw) if raw else None
    if snapshot is None:
        memo = _empty_memo()
    else:
        signature = _file_signature(path) or signature
        memo = _AttemptLogMemo(
            signature,
            raw,
            snapshot.rows,
            snapshot.idempotency_keys,
        )
    return _store_memo(root, memo)


def _append_lines_unlocked(path: Path, lines: list[bytes]) -> None:
    """Append canonical event lines with one fsync per event.

    The open/write/fsync unit carries the repo-standard 8-attempt linear
    PermissionError retry (Windows AV/indexer handles can transiently deny the
    append-mode open; a denied open lands zero bytes, so a retry is clean).
    Lines already fsynced by an earlier attempt are skipped on retry, so every
    canonical line lands exactly once and an attempt only ever adds complete
    newline-terminated lines — a hypothetical partial in-handle write failure
    would leave at most a torn tail that readers fail closed on and the next
    write-side load truncates, never a silently corrupted chain.
    """
    committed = 0  # lines durably fsynced by this call
    for attempt in range(_APPEND_RETRY_ATTEMPTS):
        try:
            with path.open("ab") as handle:
                while committed < len(lines):
                    handle.write(lines[committed])
                    handle.flush()
                    os.fsync(handle.fileno())
                    committed += 1
            return
        except PermissionError:
            if attempt + 1 >= _APPEND_RETRY_ATTEMPTS:
                raise
            time.sleep(_APPEND_RETRY_DELAY_S * (attempt + 1))


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
    path = claim_artifact_path(root, CLAIM_REEXTRACT_ATTEMPTS)
    signature = _file_signature(path)
    memo = _memo_hit(root, signature)
    if memo is not None:
        return memo.snapshot()
    if signature is None:
        return AttemptLogSnapshot([], b"", _EMPTY_SHA256, 0, _EMPTY_SHA256, frozenset())
    raw = path.read_bytes()
    snapshot = _scan_bytes(raw)
    _store_memo(
        root,
        _AttemptLogMemo(
            signature,
            raw,
            snapshot.rows,
            snapshot.idempotency_keys,
        ),
    )
    return snapshot


def _scan_bytes(raw: bytes) -> AttemptLogSnapshot:
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
        row_schema = str(row.get("schema") or "")
        if row_schema not in _SUPPORTED_ATTEMPT_SCHEMAS:
            raise ClaimReextractAttemptError(
                "claim re-extract attempt schema is unsupported"
            )
        expected_hash = hash_json(row_schema, _without_hash(row))
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


def _validate_attempt_histories(
    rows: list[dict[str, Any]],
    *,
    only_attempts: set[str] | None = None,
) -> None:
    by_attempt: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_attempt.setdefault(str(row["attempt_id"]), []).append(row)
    for attempt_id, attempt_rows in by_attempt.items():
        if only_attempts is not None and attempt_id not in only_attempts:
            # Pre-existing histories were fully validated when the committed
            # prefix was loaded; an append only needs to re-check the attempts
            # it extends (same rules, subset scope).
            continue
        first = attempt_rows[0]
        if first.get("event_kind") != "reextract_started":
            raise ClaimReextractAttemptError("attempt history must begin with reextract_started")
        terminal_seen = False
        identity = tuple(first.get(key) for key in ("proposal_id", "claim_id", "claim_hash"))
        seen_kinds: set[str] = set()
        highest_budget_calls = 0
        for row in attempt_rows:
            if tuple(row.get(key) for key in ("proposal_id", "claim_id", "claim_hash")) != identity:
                raise ClaimReextractAttemptError("attempt identity changed within its history")
            kind = str(row["event_kind"])
            if terminal_seen:
                raise ClaimReextractAttemptError("attempt history continues after a terminal event")
            if kind in _TERMINAL_EVENTS:
                terminal_seen = True
            if kind == "budget_checkpoint":
                checkpoint = dict(row.get("checkpoint") or {})
                calls = int(checkpoint.get("calls") or 0)
                if calls < highest_budget_calls:
                    raise ClaimReextractAttemptError(
                        "attempt budget checkpoint calls regressed"
                    )
                highest_budget_calls = calls
            if kind in {
                "supplement_persisted",
                "publication_prepared",
                "requirements_published",
                "base_rebuild_published",
                "effective_folded",
            } and kind in seen_kinds:
                raise ClaimReextractAttemptError(f"attempt checkpoint is duplicated: {kind}")
            seen_kinds.add(kind)
        kinds = [str(row["event_kind"]) for row in attempt_rows]
        if "requirements_published" in kinds and "supplement_persisted" not in kinds:
            raise ClaimReextractAttemptError("requirements publication lacks a supplement checkpoint")
        if "publication_prepared" in kinds and "supplement_persisted" not in kinds:
            raise ClaimReextractAttemptError(
                "publication preparation lacks a supplement checkpoint"
            )
        if (
            "publication_prepared" in kinds
            and "requirements_published" in kinds
            and kinds.index("publication_prepared") > kinds.index("requirements_published")
        ):
            raise ClaimReextractAttemptError(
                "publication preparation follows the requirements publication"
            )
        if "base_rebuild_published" in kinds and "requirements_published" not in kinds:
            raise ClaimReextractAttemptError("base rebuild lacks a requirements checkpoint")
        if "effective_folded" in kinds and "base_rebuild_published" not in kinds:
            raise ClaimReextractAttemptError("effective fold lacks a base rebuild checkpoint")
        if kinds[-1] == "reextract_succeeded" and "effective_folded" not in kinds:
            raise ClaimReextractAttemptError("successful attempt lacks an effective fold checkpoint")


def read_attempt_log(out_dir: Path | str) -> AttemptLogSnapshot:
    return _scan(Path(out_dir).expanduser().resolve())


def read_attempt_log_stable(
    out_dir: Path | str,
    *,
    max_attempts: int = 5,
    delay_seconds: float = 0.05,
) -> AttemptLogSnapshot:
    """Double-read stable snapshot for lock-free readers (GET paths).

    A concurrent append can make a read observe a torn tail. Invalid bytes are
    retried for the complete bounded window: a slow writer may legitimately
    expose the same partial bytes more than once. Valid bytes still require a
    stable second read unless they appear on the final attempt.
    """
    import time

    root = Path(out_dir).expanduser().resolve()
    path = claim_artifact_path(root, CLAIM_REEXTRACT_ATTEMPTS)
    if not path.is_file():
        return AttemptLogSnapshot([], b"", _EMPTY_SHA256, 0, _EMPTY_SHA256, frozenset())
    attempts = max(2, int(max_attempts))
    previous_valid_raw: bytes | None = None
    last_error: ClaimReextractAttemptError | None = None
    for attempt in range(attempts):
        raw = path.read_bytes()
        try:
            snapshot = _scan_bytes(raw)
        except ClaimReextractAttemptError as exc:
            last_error = exc
            previous_valid_raw = None
        else:
            if previous_valid_raw == raw or attempt == attempts - 1:
                return snapshot
            previous_valid_raw = raw
            last_error = None
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error
    raise ClaimReextractAttemptError(
        "claim re-extraction attempt log did not stabilize during read"
    )


def _append_unlocked(root: Path, drafts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Append events in append mode with one fsync per event (S10 redesign).

    The chain head, idempotency keys, and committed-prefix sha256 come from a
    per-file memo keyed by the file's stat signature, so a steady-state append
    costs O(len(event)) I/O instead of a full-file rewrite + two scans. Readers
    still only ever observe complete newline-terminated generations; a torn
    tail from a crash mid-line is truncated here (under the extraction
    operation lock) before the new events chain onto the committed prefix.
    """
    memo = _load_for_write(root)
    rows = list(memo.rows)
    keys = set(memo.idempotency_keys)
    appended: list[dict[str, Any]] = []
    lines: list[bytes] = []
    touched_attempts: set[str] = set()
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
        event_schema = str(event.get("schema") or "")
        if event_schema not in _SUPPORTED_ATTEMPT_SCHEMAS:
            raise ClaimReextractAttemptError(
                "claim re-extract attempt schema is unsupported"
            )
        event["event_hash"] = hash_json(event_schema, _without_hash(event))
        _validate_schema(
            event,
            "claim_reextract_attempt.schema.json",
            label="claim re-extract attempt",
        )
        candidate_rows = rows + [event]
        _validate_attempt_histories(
            candidate_rows,
            only_attempts=touched_attempts | {str(event["attempt_id"])},
        )
        rows.append(event)
        appended.append(event)
        keys.add(key)
        touched_attempts.add(str(event["attempt_id"]))
        lines.append(canonical_json_value_bytes(event) + b"\n")
    if appended:
        path = claim_artifact_path(root, CLAIM_REEXTRACT_ATTEMPTS)
        _append_lines_unlocked(path, lines)
        payload = b"".join(lines)
        signature = _file_signature(path)
        expected_size = len(memo.raw_bytes) + len(payload)
        if signature is None or signature[0] != expected_size:
            # Fail closed: an unexplained concurrent write invalidated the
            # append; the next load rescans under a fresh signature.
            raise ClaimReextractAttemptError(
                "claim re-extract attempt append did not land durably"
            )
        _store_memo(root, _AttemptLogMemo(signature, memo.raw_bytes + payload, rows, keys))
    committed = _load_for_write(root)
    snapshot = committed.snapshot()
    return {
        "appended": appended,
        "appended_count": len(appended),
        "prefix_sha256": snapshot.prefix_sha256,
        "last_event_seq": snapshot.last_event_seq,
        "last_event_hash": snapshot.last_event_hash,
    }


def compact_attempt_log(
    out_dir: Path | str,
    *,
    operation_lock_held: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Re-materialize the attempt log through the atomic path when needed.

    Startup/periodic compaction: heals torn tails (via the write-side load) and
    rewrites canonical bytes with the atomic replace path when on-disk bytes
    drift from the canonical rows, or when ``force`` is set. Rows are never
    dropped — the full history is the idempotency substrate for paid-work
    replay — so this compaction repairs and canonicalizes; it does not shrink.

    The skip decision is ``already canonical`` alone: compaction never drops
    rows, so an over-threshold canonical file would previously rewrite
    byte-identical history on EVERY recovery (``recover_interrupted_attempts``
    runs at startup and per queue execute — pure O(N) disk churn). The
    row/byte thresholds stay as advisory reporting inputs only; a torn tail
    still heals because the write-side load above truncates it before the
    canonical comparison (canonical != raw bytes → rewrite would proceed).
    """
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (
        nullcontext()
        if operation_lock_held
        else extraction_operation_lock(root, operation="claim-reextract-compaction")
    )
    with lock:
        memo = _load_for_write(root)
        canonical = b"".join(
            canonical_json_value_bytes(row) + b"\n" for row in memo.rows
        )
        over_threshold = (
            len(memo.rows) > _ATTEMPT_LOG_COMPACT_MAX_ROWS
            or len(canonical) > _ATTEMPT_LOG_COMPACT_MAX_BYTES
        )
        if not force and canonical == memo.raw_bytes:
            # On-disk bytes already equal the canonical serialization of the
            # committed rows (any torn tail was truncated by the write-side
            # load above), so an atomic rewrite would be byte-identical output.
            # Skip REGARDLESS of thresholds: compaction drops no rows, so an
            # over-threshold canonical history must not re-enter a
            # rewrite-forever loop on every recovery. Thresholds stay advisory
            # (reported via ``over_threshold``) for operators and the force
            # path.
            return {
                "compacted": False,
                "rows": len(memo.rows),
                "bytes": len(canonical),
                "over_threshold": over_threshold,
            }
        path = claim_artifact_path(root, CLAIM_REEXTRACT_ATTEMPTS)
        # Replacing the complete canonical prefix while holding the extraction
        # operation lock means readers see either generation, never a partial row.
        atomic_write_jsonl(path, memo.rows)
        signature = _file_signature(path)
        if signature is None:
            raise ClaimReextractAttemptError(
                "claim re-extract attempt log vanished during compaction"
            )
        _store_memo(
            root,
            _AttemptLogMemo(signature, canonical, memo.rows, memo.idempotency_keys),
        )
        return {
            "compacted": True,
            "rows": len(memo.rows),
            "bytes": len(canonical),
            "over_threshold": over_threshold,
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
    total_tokens = latest.get("total_tokens")
    if latest.get("status") != "settled" and total_tokens == 0:
        # Historical v2 reserved checkpoints stored only settled tokens, so a
        # zero here did not describe the in-flight reservation ceiling.
        total_tokens = None
    return {
        "calls": int(latest.get("calls") or 0),
        # Reserved checkpoints carry the conservative reservation ceiling.
        # Preserve it instead of erasing known paid exposure to ``null``.
        "total_tokens": total_tokens,
        "usage_complete": (
            bool(latest.get("usage_complete"))
            and latest.get("status") == "settled"
        ),
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


def _functional_publication_revision(
    store: str,
    requirements_sha256: str,
) -> str:
    """与 ``claim_review_actions._target_publication_revision`` 同公式——恢复侧
    补记的 requirements_published 必须能通过 rebuild_pending 重放护栏的
    ``target_publication_revision`` 比对。"""
    return hash_json(
        "claim-target-publication-revision/v1",
        {
            "source_store": store,
            "source_present": True,
            "source_file_sha256": requirements_sha256,
        },
    )


def _route_publication_prepared(
    root: Path,
    prepared: dict[str, Any],
) -> dict[str, Any]:
    """复审四轮 P1-1：按 ``publication_prepared`` 事件的新旧产品哈希路由恢复。

    直抽（functional store）路径没有 ai 补丁文件，publication 事实只能从
    prepared 事件携带的哈希对恢复；哈希口径与队列记账一致
    （``root / target_store``，见 ``target_published`` 与 rebuild_pending
    重放护栏）：

    - 当前产品哈希 == 新哈希 → ``published``：publication 事实成立（产品已
      原子替换），补记 requirements_published 后走确定性 rebuild_pending；
    - 当前产品哈希 == 旧哈希 → ``unpublished``：产品未动，按未发布处理
      （interrupted 可重试）；
    - 均不等 → ``conflict``：产品已他变为未知哈希，按既有 CAS 冲突路径
      （recovery_target_changed）终态化。
    """
    from claim_artifacts import file_sha256

    store = str(prepared.get("target_store") or "")
    new_sha = str(prepared.get("requirements_sha256") or "")
    previous_sha = str(prepared.get("previous_requirements_sha256") or "")
    path = root / store
    try:
        current = file_sha256(path) if path.is_file() else ""
    except OSError as exc:
        raise ClaimReextractAttemptError(
            "functional requirements are unavailable during attempt recovery"
        ) from exc
    if new_sha and current == new_sha:
        return {
            "kind": "published",
            "target_store": store,
            "requirements_sha256": current,
        }
    if current == previous_sha:
        return {"kind": "unpublished", "target_store": store}
    return {
        "kind": "conflict",
        "target_store": store,
        "requirements_sha256": current,
    }


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

    复审四轮 P1-1（functional store）：直抽模式的 publication 事实没有 ai 补丁
    文件可对账，改按 ``publication_prepared`` 事件携带的新旧产品哈希路由——
    当前 == 新哈希 → 补记 requirements_published（rebuild_pending，确定性恢复）；
    当前 == 旧哈希 → 未发布（interrupted 可重试）；均不等 → CAS 冲突
    （recovery_target_changed 终态）。原子 ai_requirements 分支行为不变。
    """
    from claim_artifacts import (
        CLAIM_BUDGET_CHECKPOINT_OUTBOX,
        file_sha256,
        recover_claim_budget_checkpoint_outbox,
    )
    from io_utils import read_jsonl
    from omission_actions import AI_SUPPLEMENTS, read_supplement_patches

    root = Path(out_dir).expanduser().resolve()
    if (claim_artifact_path(root, CLAIM_BUDGET_CHECKPOINT_OUTBOX)).is_file():
        # Complete the durable queue/verifier fanout before lifecycle folding.
        # Otherwise an interrupted attempt could be terminalized from the stale
        # queue prefix while the verifier WAL already contains paid work.
        if operation_lock_held:
            recover_claim_budget_checkpoint_outbox(
                root,
                operation_lock_held=True,
            )
        else:
            with extraction_operation_lock(
                root,
                operation="claim-budget-checkpoint-recovery",
            ):
                recover_claim_budget_checkpoint_outbox(
                    root,
                    operation_lock_held=True,
                )
    lock = (
        nullcontext()
        if operation_lock_held
        else extraction_operation_lock(root, operation="claim-reextract-recovery")
    )
    with lock:
        # Startup/periodic compaction: heal a torn tail left by a crashed
        # append before anything scans the log (readers stay fail-closed).
        compact_attempt_log(root, operation_lock_held=True)
        snapshot = _scan(root)
        states = derive_attempt_states(snapshot.rows)
        orphan_ids = {
            attempt
            for attempt, state in states.items()
            if state.get("lifecycle") == "executing"
        }
        if not orphan_ids:
            return {
                "recovered": 0,
                "interrupted": 0,
                "conflicted": 0,
                "appended_count": 0,
            }

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
        conflicted = 0
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

            # 复审四轮 P1-1：functional store 分支——直抽模式没有 ai 补丁文件，
            # publication 事实从 publication_prepared 事件的新旧产品哈希恢复
            # （原子 ai_requirements 行为不变：原子 attempt 不写 prepared 事件）。
            if not publication_recovered and "requirements_published" not in kinds:
                prepared = next(
                    (
                        row
                        for row in reversed(history)
                        if row.get("event_kind") == "publication_prepared"
                    ),
                    None,
                )
                if prepared is not None:
                    route = _route_publication_prepared(root, prepared)
                    if route["kind"] == "published":
                        publication_revision = _functional_publication_revision(
                            str(route["target_store"]),
                            str(route["requirements_sha256"]),
                        )
                        drafts.append({
                            **_recovery_common(
                                started,
                                event_kind="requirements_published",
                                detail=publication_revision,
                            ),
                            "requirements_sha256": route["requirements_sha256"],
                            "target_publication_revision": publication_revision,
                        })
                        publication_recovered = True
                        recovered += 1
                    elif route["kind"] == "conflict":
                        usage = _recovered_usage(history)
                        drafts.append({
                            **_recovery_common(
                                started,
                                event_kind="reextract_aborted_stale",
                                detail={
                                    "code": "recovery_target_changed",
                                    "usage": usage,
                                },
                            ),
                            "outcome": {
                                "code": "recovery_target_changed",
                                "message": (
                                    "the functional product changed to an unknown "
                                    "hash between preparation and recovery"
                                ),
                                "retryable": True,
                            },
                            "usage": usage,
                        })
                        conflicted += 1
                        continue
                    # "unpublished"（当前 == 旧哈希）→ 按未发布处理，落入下方
                    # interrupted 终态（可重试）。

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
            "conflicted": conflicted,
            "appended_count": int(result.get("appended_count") or 0),
        }


def require_published_attempt(
    out_dir: Path | str,
    *,
    attempt_id: str,
    requirements_sha256: str,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return durable target-mutation provenance or fail closed.

    ``rows`` lets a caller that already holds the attempt-log rows (e.g. a
    queue-execution critical section) thread them through instead of forcing
    another scan; the rows are treated as read-only.
    """
    root = Path(out_dir).expanduser().resolve()
    attempt_id = str(attempt_id or "").strip()
    history = [
        dict(row)
        for row in (rows if rows is not None else _scan(root).rows)
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
