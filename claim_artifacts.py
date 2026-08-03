"""Crash-recoverable persistence for Phase 0 claim shadow artifacts.

Fixed-name snapshots are materialized under one publication lock. A durable
journal preserves the prior generation until every new file has been reloaded
and validated; journal removal is the global commit point.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from result_package import governed_artifact_path


CLAIM_CATALOG = "claim_catalog.jsonl"
CLAIM_CATALOG_META = "claim_catalog.meta.json"
CLAIM_COVERAGE_GROUPS = "claim_coverage_groups.jsonl"
CLAIM_LEDGER = "claim_ledger.jsonl"
CLAIM_EFFECTIVE_LEDGER = "claim_effective_ledger.jsonl"
CLAIM_SHADOW_METRICS = "claim_shadow_metrics.json"
CLAIM_GENERATION_META = "claim_generation.meta.json"
CLAIM_EFFECTIVE_META = "claim_effective.meta.json"
CLAIM_REVIEW_EVENTS = "claim_review_events.jsonl"
CLAIM_QUEUE_PROPOSALS = "claim_queue_proposals.jsonl"
CLAIM_EFFECTIVE_HEALTH = "claim_effective_health.json"
CLAIM_VERIFIER_ATTEMPTS = "claim_verifier_attempts.jsonl"
CLAIM_VERIFIER_ATTEMPT_CHECKPOINT = ".claim_verifier_attempt.checkpoint.json"
CLAIM_BUDGET_CHECKPOINT_OUTBOX = ".claim_budget_checkpoint.outbox.json"
CLAIM_PUBLICATION_JOURNAL = ".claim_publication.journal.json"
CLAIM_EFFECTIVE_PUBLICATION_JOURNAL = ".claim_effective_publication.journal.json"

CLAIM_SNAPSHOT_FILES = (
    CLAIM_CATALOG,
    CLAIM_CATALOG_META,
    CLAIM_COVERAGE_GROUPS,
    CLAIM_LEDGER,
    CLAIM_EFFECTIVE_LEDGER,
    CLAIM_SHADOW_METRICS,
    CLAIM_GENERATION_META,
    CLAIM_EFFECTIVE_META,
)

CLAIM_ARTIFACT_PROTOCOL_VERSION = "claim-artifacts-v7"
LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION = "claim-effective-snapshot-v1"
PREVIOUS_CLAIM_EFFECTIVE_SNAPSHOT_VERSION = "claim-effective-snapshot-v2"
CLAIM_EFFECTIVE_SNAPSHOT_VERSION = "claim-effective-snapshot-v3"
PREVIOUS_CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION = "claim-effective-artifacts-v1"
CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION = "claim-effective-artifacts-v2"
CLAIM_VERIFIER_ATTEMPT_SCHEMA = "claim-verifier-attempt/v2"
CLAIM_VERIFIER_ATTEMPT_BINDING_SCHEMA = "claim-verifier-attempt-chain-binding/v2"
LEGACY_CLAIM_ARTIFACT_PROTOCOL_VERSION = "claim-artifacts-v4"
PREVIOUS_CLAIM_ARTIFACT_PROTOCOL_VERSION = "claim-artifacts-v6"
CLAIM_PUBLICATION_JOURNAL_SCHEMA = "claim-publication-journal/v1"
CLAIM_EFFECTIVE_PUBLICATION_JOURNAL_SCHEMA = "claim-effective-publication-journal/v1"
CLAIM_VERIFIER_ATTEMPT_CHECKPOINT_SCHEMA = "claim-verifier-attempt-checkpoint/v1"
CLAIM_BUDGET_CHECKPOINT_OUTBOX_SCHEMA = "claim-budget-checkpoint-outbox/v1"

_REPLACE_ATTEMPTS = 8
_REPLACE_RETRY_DELAY_S = 0.02
_PUBLICATION_LOCK_NAME = "claim_artifacts.lock"
_PUBLICATION_LOCK_TIMEOUT_S = 15.0
_PUBLICATION_LOCKS: dict[Path, RLock] = {}
_PUBLICATION_LOCK_STATES: dict[Path, dict[str, Any]] = {}
_PUBLICATION_LOCKS_GUARD = RLock()
_ACTIVE_VERIFIER_CHECKPOINTS: set[tuple[Path, str]] = set()
_ACTIVE_VERIFIER_CHECKPOINTS_GUARD = RLock()
_EMPTY_SHA256 = "sha256:" + hashlib.sha256(b"").hexdigest()
_SCHEMA_VALIDATORS: dict[str, Any] = {}
CLAIM_EFFECTIVE_SNAPSHOT_FILES = (
    CLAIM_EFFECTIVE_META,
    CLAIM_EFFECTIVE_LEDGER,
    CLAIM_QUEUE_PROPOSALS,
)
_VERIFIER_ATTEMPT_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "claim_verifier_attempt_context",
    default=None,
)


class ClaimArtifactError(RuntimeError):
    """Raised when a claim artifact generation is absent, malformed, or stale."""


class ClaimEffectiveRecoveryPending(ClaimArtifactError):
    """Raised when a read-only consumer sees an unfinished publication WAL."""


class ClaimEffectiveAuthorityChanged(ClaimArtifactError):
    """Raised when a committed effective snapshot no longer matches live authority."""


class ClaimAttemptLogTornTail(ClaimArtifactError):
    """Raised when a verdict-attempt ledger ends in a partial line that never settles.

    A missing trailing newline is only a *suspected* torn tail — the publisher may
    still be appending. Read paths re-read within a bounded window and only raise
    this once the partial tail stays stable across the whole window. A complete line
    whose hash/chain/schema is forged is a different failure: ``_validate_attempt_rows``
    rejects it immediately, never retried.
    """


def claim_artifact_path(root: Path | str, filename: str) -> Path:
    return governed_artifact_path(root, filename, category="state")


def _claim_state_root(root: Path | str) -> Path:
    return claim_artifact_path(root, ".claim-state-anchor").parent


def _publication_process_lock(root: Path) -> RLock:
    with _PUBLICATION_LOCKS_GUARD:
        return _PUBLICATION_LOCKS.setdefault(root, RLock())


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return int(kernel32.GetLastError()) == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return int(exit_code.value) == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_identity(pid: int) -> str | None:
    """Return an OS process-birth token so a recycled PID is not an owner."""
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            value = (int(creation.dwHighDateTime) << 32) | int(
                creation.dwLowDateTime
            )
            return f"windows-filetime:{value}"
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2 :].split()
        return f"proc-start-ticks:{fields[19]}"
    except (OSError, UnicodeError, IndexError):
        return None


def _open_publication_lock_file(lock_path: Path):
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(str(lock_path), flags, 0o600)
    handle = os.fdopen(fd, "r+b", buffering=0)
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        return handle
    except BaseException:
        handle.close()
        raise


def _try_acquire_publication_file_lock(handle) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import errno
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if (
                isinstance(exc, PermissionError)
                or exc.errno in {errno.EACCES, errno.EAGAIN}
                or getattr(exc, "winerror", None) in {33, 36}
            ):
                return False
            raise
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _release_publication_file_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_publication_lock_owner(handle, owner: dict[str, Any]) -> None:
    payload = _canonical_json_bytes(owner)
    handle.seek(0)
    offset = 0
    while offset < len(payload):
        written = handle.write(payload[offset:])
        if written is None or written <= 0:
            raise OSError("failed to initialize claim publication lock")
        offset += written
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def _publication_lock_handle_is_owned(handle, nonce: str) -> bool:
    try:
        handle.seek(0)
        owner = json.loads(handle.read().decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(owner, dict) and owner.get("nonce") == nonce


@contextmanager
def claim_publication_lock(out_dir: Path | str):
    """Serialize every multi-file claim generation, including direct rebuilds."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    process_lock = _publication_process_lock(root)
    with process_lock:
        active = _PUBLICATION_LOCK_STATES.get(root)
        if active is not None:
            active["depth"] = int(active["depth"]) + 1
            try:
                yield
            finally:
                active["depth"] = int(active["depth"]) - 1
            return

        lock_path = claim_artifact_path(root, _PUBLICATION_LOCK_NAME)
        deadline = time.monotonic() + _PUBLICATION_LOCK_TIMEOUT_S
        handle = _open_publication_lock_file(lock_path)
        nonce = uuid.uuid4().hex
        acquired = False
        initialized = False
        try:
            while not _try_acquire_publication_file_lock(handle):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "timed out waiting for claim artifact publication lock"
                    )
                time.sleep(0.02)
            acquired = True
            owner = {
                "pid": os.getpid(),
                "process_identity": _process_identity(os.getpid()) or "",
                "nonce": nonce,
            }
            _write_publication_lock_owner(handle, owner)
            initialized = True
            _PUBLICATION_LOCK_STATES[root] = {
                "handle": handle,
                "nonce": nonce,
                "depth": 1,
            }
            try:
                yield
            finally:
                state = _PUBLICATION_LOCK_STATES.pop(root)
                if int(state["depth"]) != 1:
                    raise ClaimArtifactError("unbalanced claim publication lock depth")
        finally:
            try:
                owned = (
                    not initialized
                    or _publication_lock_handle_is_owned(handle, nonce)
                )
                if acquired:
                    _release_publication_file_lock(handle)
            finally:
                handle.close()
            if initialized and not owned:
                raise ClaimArtifactError("claim publication lock owner changed")


def _canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_json_value_bytes(payload: Any) -> bytes:
    """Canonical JSON value bytes used by Phase 1 identities (no JSONL newline)."""
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ClaimArtifactError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def hash_json(domain: str, payload: Any) -> str:
    domain = str(domain or "")
    if not domain:
        raise ClaimArtifactError("hash domain is required")
    digest = hashlib.sha256(canonical_json_value_bytes({
        "domain": domain,
        "payload": payload,
    })).hexdigest()
    return "sha256:" + digest


def sha256_bytes(payload: bytes) -> str:
    """Return the canonical wire representation for a raw-byte SHA-256 digest."""
    if not isinstance(payload, bytes):
        raise ClaimArtifactError("sha256 payload must be bytes")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_target_fingerprint(value: object) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        digest = text[7:]
    else:
        digest = text
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ClaimArtifactError("invalid target fingerprint")
    return "sha256:" + digest


def digest_hex(value: object) -> str:
    normalized = canonical_target_fingerprint(value)
    return normalized.removeprefix("sha256:")


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_value_bytes(row) + b"\n" for row in rows)


def _schema_validator(schema_name: str):
    validator = _SCHEMA_VALIDATORS.get(schema_name)
    if validator is not None:
        return validator
    try:
        from jsonschema import Draft202012Validator, RefResolver

        schema_dir = Path(__file__).resolve().parent / "schemas"
        path = schema_dir / schema_name
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        store: dict[str, Any] = {}
        for candidate in schema_dir.glob("*.schema.json"):
            try:
                candidate_schema = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            schema_id = candidate_schema.get("$id")
            if isinstance(schema_id, str) and schema_id:
                store[schema_id] = candidate_schema
        validator = Draft202012Validator(
            schema,
            resolver=RefResolver.from_schema(schema, store=store),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ImportError) as exc:
        raise ClaimArtifactError(f"unable to load claim schema {schema_name}") from exc
    _SCHEMA_VALIDATORS[schema_name] = validator
    return validator


def _validate_schema(payload: Any, schema_name: str, *, label: str) -> None:
    errors = sorted(
        _schema_validator(schema_name).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise ClaimArtifactError(f"invalid {label} at {location}: {error.message}")


def _require_canonical_json_value(path: Path, payload: Any, *, label: str) -> None:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ClaimArtifactError(f"missing {label}: {path.name}") from exc
    if raw != canonical_json_value_bytes(payload):
        raise ClaimArtifactError(f"non-canonical {label}: {path.name}")


def _require_canonical_jsonl(
    path: Path,
    rows: Iterable[dict[str, Any]],
    *,
    label: str,
) -> None:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ClaimArtifactError(f"missing {label}: {path.name}") from exc
    if raw != _jsonl_bytes(rows):
        raise ClaimArtifactError(f"non-canonical {label}: {path.name}")


def file_sha256(path: Path | str) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))


def _unlink_with_retry(target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            target.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))


def _atomic_write_bytes(path: Path | str, payload: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            # Publication backups can sit near Windows MAX_PATH. The random
            # tempfile suffix already provides uniqueness; repeating the full
            # target name here only consumes path budget.
            prefix=".tmp.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path | str, payload: Any) -> None:
    _atomic_write_bytes(path, _canonical_json_bytes(payload))


def atomic_write_canonical_json(path: Path | str, payload: Any) -> None:
    """Write a Phase 1 canonical JSON value without a trailing newline."""
    _atomic_write_bytes(path, canonical_json_value_bytes(payload))


def atomic_write_text(path: Path | str, payload: str) -> None:
    _atomic_write_bytes(path, payload.encode("utf-8"))


def paths_alias(left: Path | str, right: Path | str) -> bool:
    left_path = Path(left).expanduser().resolve()
    right_path = Path(right).expanduser().resolve()
    if left_path == right_path:
        return True
    try:
        return (
            left_path.exists()
            and right_path.exists()
            and left_path.samefile(right_path)
        )
    except OSError:
        return False


def atomic_write_jsonl(path: Path | str, rows: Iterable[dict[str, Any]]) -> None:
    _atomic_write_bytes(path, _jsonl_bytes(rows))


def _restore_claim_snapshot(
    root: Path,
    snapshot: dict[str, bytes | None],
) -> None:
    commit_files = {
        CLAIM_CATALOG_META,
        CLAIM_GENERATION_META,
        CLAIM_EFFECTIVE_META,
    }
    ordered_names = [
        *[name for name in CLAIM_SNAPSHOT_FILES if name not in commit_files],
        CLAIM_CATALOG_META,
        CLAIM_GENERATION_META,
        CLAIM_EFFECTIVE_META,
    ]
    for name in ordered_names:
        payload = snapshot[name]
        path = claim_artifact_path(root, name)
        if payload is None:
            _unlink_with_retry(path)
        else:
            _atomic_write_bytes(path, payload)


def _publication_backup_dir(root: Path, transaction_id: str) -> Path:
    return _claim_state_root(root) / f".claim-publication-backup-{transaction_id}"


def _effective_publication_backup_dir(root: Path, transaction_id: str) -> Path:
    return _claim_state_root(root) / f".claim-effective-publication-backup-{transaction_id}"


def _cleanup_publication_backup(
    root: Path,
    journal: dict[str, Any],
) -> None:
    transaction_id = str(journal.get("transaction_id") or "")
    if len(transaction_id) != 32 or any(ch not in "0123456789abcdef" for ch in transaction_id):
        raise ClaimArtifactError("invalid claim publication transaction id")
    backup_dir = _publication_backup_dir(root, transaction_id)
    for entry in journal.get("snapshot_files") or []:
        if entry.get("present") is True:
            _unlink_with_retry(backup_dir / str(entry.get("name") or ""))
    try:
        backup_dir.rmdir()
    except FileNotFoundError:
        pass


def _cleanup_orphan_publication_backups_unlocked(root: Path) -> None:
    prefix = ".claim-publication-backup-"
    for backup_dir in _claim_state_root(root).glob(f"{prefix}*"):
        transaction_id = backup_dir.name[len(prefix):]
        if (
            not backup_dir.is_dir()
            or len(transaction_id) != 32
            or any(ch not in "0123456789abcdef" for ch in transaction_id)
        ):
            continue
        try:
            children = list(backup_dir.iterdir())
        except OSError:
            continue
        if any(
            not child.is_file()
            or (
                child.name not in CLAIM_SNAPSHOT_FILES
                and not (child.name.startswith(".") and child.name.endswith(".tmp"))
            )
            for child in children
        ):
            continue
        try:
            for child in children:
                _unlink_with_retry(child)
            backup_dir.rmdir()
        except OSError:
            pass


def _cleanup_orphan_effective_backups_unlocked(root: Path) -> None:
    prefix = ".claim-effective-publication-backup-"
    for backup_dir in _claim_state_root(root).glob(f"{prefix}*"):
        transaction_id = backup_dir.name[len(prefix):]
        if (
            not backup_dir.is_dir()
            or len(transaction_id) != 32
            or any(character not in "0123456789abcdef" for character in transaction_id)
        ):
            continue
        try:
            children = list(backup_dir.iterdir())
        except OSError:
            continue
        if any(
            not child.is_file()
            or (
                child.name not in CLAIM_EFFECTIVE_SNAPSHOT_FILES
                and not (child.name.startswith(".") and child.name.endswith(".tmp"))
            )
            for child in children
        ):
            continue
        try:
            for child in children:
                _unlink_with_retry(child)
            backup_dir.rmdir()
        except OSError:
            pass


def _journal_without_hash(journal: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in journal.items() if key != "journal_sha256"}


def _validate_attempt_recovery(
    recovery: object,
    *,
    run_id: str,
) -> dict[str, Any]:
    recovery_fields = {
        "attempt_kind",
        "attempt_status",
        "chain_identity",
        "attempt_policy_identity",
        "source_locator",
        "attempt_metrics",
    }
    if not isinstance(recovery, dict) or set(recovery) != recovery_fields:
        raise ClaimArtifactError("invalid claim publication attempt recovery")
    attempt_kind = str(recovery.get("attempt_kind") or "")
    if attempt_kind not in {"cold", "ledger_only"}:
        raise ClaimArtifactError("invalid claim publication attempt kind")
    if recovery.get("attempt_status") not in {"complete", "incomplete", "failed"}:
        raise ClaimArtifactError("invalid claim publication attempt status")
    chain_identity = dict(recovery.get("chain_identity") or {})
    attempt_policy_identity = dict(recovery.get("attempt_policy_identity") or {})
    source_locator = dict(recovery.get("source_locator") or {})
    _validate_attempt_identity(chain_identity)
    _validate_attempt_policy_identity(attempt_policy_identity)
    _validate_attempt_source(source_locator, attempt_kind=attempt_kind)
    _normalize_attempt_metrics(dict(recovery.get("attempt_metrics") or {}))
    if str(run_id) != source_locator["attempt_request_id"]:
        raise ClaimArtifactError("claim publication run differs from verifier attempt")
    return dict(recovery)


def _validate_publication_journal(
    root: Path,
    journal: dict[str, Any],
) -> dict[str, bytes | None]:
    expected_fields = {
        "schema",
        "transaction_id",
        "run_id",
        "prepared_at",
        "snapshot_files",
        "attempt_recovery",
        "journal_sha256",
    }
    if set(journal) != expected_fields:
        raise ClaimArtifactError("invalid claim publication journal fields")
    if journal.get("schema") != CLAIM_PUBLICATION_JOURNAL_SCHEMA:
        raise ClaimArtifactError("unsupported claim publication journal")
    transaction_id = str(journal.get("transaction_id") or "")
    if len(transaction_id) != 32 or any(ch not in "0123456789abcdef" for ch in transaction_id):
        raise ClaimArtifactError("invalid claim publication transaction id")
    if journal.get("journal_sha256") != _sha256_payload(_journal_without_hash(journal)):
        raise ClaimArtifactError("claim publication journal hash mismatch")
    entries = journal.get("snapshot_files")
    if not isinstance(entries, list) or [entry.get("name") for entry in entries] != list(
        CLAIM_SNAPSHOT_FILES
    ):
        raise ClaimArtifactError("invalid claim publication backup manifest")

    snapshot: dict[str, bytes | None] = {}
    backup_dir = _publication_backup_dir(root, transaction_id)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "present", "sha256"}:
            raise ClaimArtifactError("invalid claim publication backup entry")
        name = str(entry["name"])
        present = entry.get("present") is True
        expected_hash = str(entry.get("sha256") or "")
        if present:
            backup = backup_dir / name
            _require_hash(backup, expected_hash, label=f"publication backup {name}")
            snapshot[name] = backup.read_bytes()
        else:
            if expected_hash != _EMPTY_SHA256:
                raise ClaimArtifactError("invalid absent claim publication backup hash")
            snapshot[name] = None

    _validate_attempt_recovery(
        journal.get("attempt_recovery"),
        run_id=str(journal.get("run_id") or ""),
    )
    return snapshot


def _validate_effective_publication_journal(
    root: Path,
    journal: dict[str, Any],
) -> dict[str, bytes | None]:
    _validate_schema(
        journal,
        "claim_effective_publication_journal.schema.json",
        label="effective publication journal",
    )
    _require_canonical_json_value(
        claim_artifact_path(root, CLAIM_EFFECTIVE_PUBLICATION_JOURNAL),
        journal,
        label="effective publication journal",
    )
    expected_fields = {
        "schema",
        "transaction_kind",
        "transaction_id",
        "state",
        "created_at",
        "base_generation_id",
        "generation_meta_sha256",
        "base_ledger_sha256",
        "snapshot_files",
        "candidate",
        "journal_sha256",
    }
    if set(journal) != expected_fields:
        raise ClaimArtifactError("invalid effective publication journal fields")
    if journal.get("schema") != CLAIM_EFFECTIVE_PUBLICATION_JOURNAL_SCHEMA:
        raise ClaimArtifactError("unsupported effective publication journal")
    if journal.get("transaction_kind") != "effective_fold" or journal.get("state") != "prepared":
        raise ClaimArtifactError("invalid effective publication journal state")
    transaction_id = str(journal.get("transaction_id") or "")
    if (
        len(transaction_id) != 32
        or any(character not in "0123456789abcdef" for character in transaction_id)
    ):
        raise ClaimArtifactError("invalid effective publication transaction id")
    if journal.get("journal_sha256") != hash_json(
        "claim-effective-publication-journal/v1",
        _journal_without_hash(journal),
    ):
        raise ClaimArtifactError("effective publication journal hash mismatch")
    for field in ("base_generation_id", "generation_meta_sha256", "base_ledger_sha256"):
        if not _is_sha256(journal.get(field)):
            raise ClaimArtifactError(f"invalid effective publication journal {field}")
    candidate = journal.get("candidate")
    candidate_fields = {
        "effective_ledger_sha256",
        "effective_ledger_count",
        "queue_sha256",
        "queue_count",
        "effective_meta_sha256",
        "document_effective_revision",
    }
    if not isinstance(candidate, dict) or set(candidate) != candidate_fields:
        raise ClaimArtifactError("invalid effective publication candidate")
    for field in (
        "effective_ledger_sha256",
        "queue_sha256",
        "effective_meta_sha256",
        "document_effective_revision",
    ):
        if not _is_sha256(candidate.get(field)):
            raise ClaimArtifactError(f"invalid effective publication candidate {field}")
    for field in ("effective_ledger_count", "queue_count"):
        value = candidate.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ClaimArtifactError(f"invalid effective publication candidate {field}")
    entries = journal.get("snapshot_files")
    if not isinstance(entries, list) or [entry.get("name") for entry in entries] != list(
        CLAIM_EFFECTIVE_SNAPSHOT_FILES
    ):
        raise ClaimArtifactError("invalid effective publication backup manifest")

    snapshot: dict[str, bytes | None] = {}
    backup_dir = _effective_publication_backup_dir(root, transaction_id)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "name", "present", "sha256", "backup_name"
        }:
            raise ClaimArtifactError("invalid effective publication backup entry")
        name = str(entry["name"])
        present = entry.get("present") is True
        expected_hash = str(entry.get("sha256") or "")
        if present:
            if entry.get("backup_name") != name:
                raise ClaimArtifactError("invalid effective publication backup name")
            backup = backup_dir / name
            _require_hash(backup, expected_hash, label=f"effective publication backup {name}")
            snapshot[name] = backup.read_bytes()
        else:
            if entry.get("sha256") is not None or entry.get("backup_name") is not None:
                raise ClaimArtifactError("invalid absent effective publication backup hash")
            snapshot[name] = None
    return snapshot


def _restore_effective_snapshot(
    root: Path,
    snapshot: dict[str, bytes | None],
) -> None:
    for name in (CLAIM_EFFECTIVE_LEDGER, CLAIM_QUEUE_PROPOSALS, CLAIM_EFFECTIVE_META):
        payload = snapshot[name]
        path = claim_artifact_path(root, name)
        if payload is None:
            _unlink_with_retry(path)
        else:
            _atomic_write_bytes(path, payload)


def _verify_restored_effective_snapshot(
    root: Path,
    snapshot: dict[str, bytes | None],
) -> None:
    for name in (CLAIM_EFFECTIVE_LEDGER, CLAIM_QUEUE_PROPOSALS, CLAIM_EFFECTIVE_META):
        expected = snapshot[name]
        path = claim_artifact_path(root, name)
        if expected is None:
            if path.exists():
                raise ClaimArtifactError(f"effective recovery did not remove {name}")
            continue
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise ClaimArtifactError(f"effective recovery did not restore {name}") from exc
        if actual != expected:
            raise ClaimArtifactError(f"effective recovery restored different bytes for {name}")


def _cleanup_effective_publication_backup(
    root: Path,
    journal: dict[str, Any],
) -> None:
    transaction_id = str(journal.get("transaction_id") or "")
    if (
        len(transaction_id) != 32
        or any(character not in "0123456789abcdef" for character in transaction_id)
    ):
        raise ClaimArtifactError("invalid effective publication transaction id")
    backup_dir = _effective_publication_backup_dir(root, transaction_id)
    for entry in journal.get("snapshot_files") or []:
        if entry.get("present") is True:
            _unlink_with_retry(backup_dir / str(entry.get("name") or ""))
    try:
        backup_dir.rmdir()
    except FileNotFoundError:
        pass


def _checkpoint_without_hash(checkpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in checkpoint.items()
        if key != "checkpoint_sha256"
    }


def _validate_verifier_attempt_checkpoint(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "schema",
        "run_id",
        "owner",
        "created_at",
        "updated_at",
        "attempt_recovery",
        "checkpoint_sha256",
    }
    if set(checkpoint) != expected_fields:
        raise ClaimArtifactError("invalid verifier attempt checkpoint fields")
    if checkpoint.get("schema") != CLAIM_VERIFIER_ATTEMPT_CHECKPOINT_SCHEMA:
        raise ClaimArtifactError("unsupported verifier attempt checkpoint")
    if checkpoint.get("checkpoint_sha256") != _sha256_payload(
        _checkpoint_without_hash(checkpoint)
    ):
        raise ClaimArtifactError("verifier attempt checkpoint hash mismatch")
    owner = checkpoint.get("owner")
    if (
        not isinstance(owner, dict)
        or set(owner) != {"pid", "process_identity", "nonce"}
        or not isinstance(owner.get("pid"), int)
        or isinstance(owner.get("pid"), bool)
        or int(owner.get("pid") or 0) <= 0
        or not isinstance(owner.get("process_identity"), str)
        or not isinstance(owner.get("nonce"), str)
        or len(str(owner.get("nonce") or "")) != 32
        or any(
            ch not in "0123456789abcdef"
            for ch in str(owner.get("nonce") or "")
        )
    ):
        raise ClaimArtifactError("invalid verifier attempt checkpoint owner")
    if any(
        not isinstance(checkpoint.get(field), str) or not checkpoint.get(field)
        for field in ("run_id", "created_at", "updated_at")
    ):
        raise ClaimArtifactError("invalid verifier attempt checkpoint timestamp")
    _validate_attempt_recovery(
        checkpoint.get("attempt_recovery"),
        run_id=str(checkpoint.get("run_id") or ""),
    )
    return checkpoint


def _checkpoint_owner_is_alive(checkpoint: dict[str, Any]) -> bool:
    owner = dict(checkpoint.get("owner") or {})
    pid = int(owner.get("pid") or 0)
    if not _pid_is_alive(pid):
        return False
    expected_identity = str(owner.get("process_identity") or "")
    if expected_identity:
        actual_identity = _process_identity(pid)
        if actual_identity is not None and actual_identity != expected_identity:
            return False
    return True


def _register_active_verifier_checkpoint(root: Path, nonce: str) -> None:
    key = (root, nonce)
    with _ACTIVE_VERIFIER_CHECKPOINTS_GUARD:
        if key in _ACTIVE_VERIFIER_CHECKPOINTS:
            raise ClaimArtifactError("verifier attempt checkpoint is already registered")
        _ACTIVE_VERIFIER_CHECKPOINTS.add(key)


def _unregister_active_verifier_checkpoint(root: Path, nonce: str) -> None:
    with _ACTIVE_VERIFIER_CHECKPOINTS_GUARD:
        _ACTIVE_VERIFIER_CHECKPOINTS.discard((root, nonce))


def _checkpoint_owner_is_active(root: Path, checkpoint: dict[str, Any]) -> bool:
    if not _checkpoint_owner_is_alive(checkpoint):
        return False
    owner = dict(checkpoint.get("owner") or {})
    if int(owner.get("pid") or 0) != os.getpid():
        return True
    nonce = str(owner.get("nonce") or "")
    with _ACTIVE_VERIFIER_CHECKPOINTS_GUARD:
        return (root, nonce) in _ACTIVE_VERIFIER_CHECKPOINTS


def _checkpoint_attempt_id(recovery: dict[str, Any]) -> str:
    chain_identity = dict(recovery.get("chain_identity") or {})
    return _attempt_id(
        _sha256_payload(chain_identity),
        str(recovery.get("attempt_kind") or ""),
        dict(recovery.get("source_locator") or {}),
    )


def _write_verifier_attempt_checkpoint_unlocked(
    root: Path,
    checkpoint: dict[str, Any],
) -> None:
    payload = _checkpoint_without_hash(checkpoint)
    payload["checkpoint_sha256"] = _sha256_payload(payload)
    atomic_write_json(claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT), payload)


def _begin_verifier_attempt_checkpoint_unlocked(
    root: Path,
    *,
    run_id: str,
    attempt_recovery: dict[str, Any],
) -> dict[str, Any]:
    path = claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)
    if path.exists():
        raise ClaimArtifactError("unfinished verifier attempt checkpoint was not recovered")
    nonce = uuid.uuid4().hex
    now = _utc_now()
    checkpoint = {
        "schema": CLAIM_VERIFIER_ATTEMPT_CHECKPOINT_SCHEMA,
        "run_id": str(run_id),
        "owner": {
            "pid": os.getpid(),
            "process_identity": _process_identity(os.getpid()) or "",
            "nonce": nonce,
        },
        "created_at": now,
        "updated_at": now,
        "attempt_recovery": dict(attempt_recovery),
    }
    _write_verifier_attempt_checkpoint_unlocked(root, checkpoint)
    checkpoint["checkpoint_sha256"] = _sha256_payload(checkpoint)
    return checkpoint


def _read_verifier_attempt_checkpoint_unlocked(root: Path) -> dict[str, Any]:
    checkpoint = _read_json(
        claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT),
        label="verifier attempt checkpoint",
    )
    return _validate_verifier_attempt_checkpoint(checkpoint)


def _update_verifier_attempt_checkpoint_unlocked(
    root: Path,
    *,
    nonce: str,
    budget_snapshot: dict[str, Any] | None = None,
    candidate_group_count: int | None = None,
    reused_group_count: int | None = None,
) -> None:
    checkpoint = _read_verifier_attempt_checkpoint_unlocked(root)
    owner = dict(checkpoint["owner"])
    if owner.get("nonce") != nonce:
        raise ClaimArtifactError("verifier attempt checkpoint owner changed")
    recovery = dict(checkpoint["attempt_recovery"])
    metrics = dict(recovery["attempt_metrics"])
    if budget_snapshot is not None:
        reserved_tokens = max(0, int(budget_snapshot.get("reserved_tokens") or 0))
        metrics.update({
            "verifier_call_count": max(
                0,
                int(budget_snapshot.get("attempted_calls") or 0),
            ),
            "verifier_failed_call_count": max(
                0,
                int(budget_snapshot.get("failed_calls") or 0),
            ),
            "verifier_tokens": max(
                0,
                int(budget_snapshot.get("tokens") or 0) + reserved_tokens,
            ),
            "verifier_usage_complete": (
                budget_snapshot.get("usage_complete") is True
                and reserved_tokens == 0
            ),
        })
    if candidate_group_count is not None:
        metrics["semantic_verifier_candidate_count"] = max(
            0,
            int(candidate_group_count),
        )
    if reused_group_count is not None:
        metrics["semantic_validation_reused_group_count"] = max(
            0,
            int(reused_group_count),
        )
    recovery["attempt_metrics"] = _normalize_attempt_metrics(metrics)
    recovery["attempt_status"] = "incomplete"
    checkpoint["attempt_recovery"] = recovery
    checkpoint["updated_at"] = _utc_now()
    _write_verifier_attempt_checkpoint_unlocked(root, checkpoint)


def _budget_outbox_without_hash(outbox: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in outbox.items()
        if key != "outbox_sha256"
    }


def claim_budget_checkpoint_payload(
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Project one LLM budget snapshot into the queue accounting contract."""
    calls = int(snapshot.get("attempted_calls") or 0)
    if calls <= 0:
        return None
    reserved = max(0, int(snapshot.get("reserved_tokens") or 0))
    failed = int(snapshot.get("failed_calls") or 0)
    return {
        "phase": "pre_call" if reserved > 0 else "error" if failed else "post_call",
        "calls": calls,
        "total_tokens": int(snapshot.get("tokens") or 0) + reserved,
        "usage_complete": bool(snapshot.get("usage_complete")) and reserved == 0,
        "status": "reserved" if reserved > 0 else "failed" if failed else "settled",
    }


def claim_budget_checkpoint_event_idempotency_key(
    *,
    attempt_id: str,
    transition_id: str,
    checkpoint: dict[str, Any],
) -> str:
    return hash_json(
        "claim-reextract-event-idempotency/v1",
        {
            "attempt_id": str(attempt_id),
            "event_kind": "budget_checkpoint",
            "detail": {
                "transition_id": str(transition_id),
                **dict(checkpoint),
            },
        },
    )


def _validate_budget_checkpoint_outbox(
    outbox: dict[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "schema",
        "transaction_id",
        "verifier_nonce",
        "created_at",
        "budget_snapshot",
        "queue_event",
        "outbox_sha256",
    }
    if set(outbox) != expected_fields:
        raise ClaimArtifactError("invalid budget checkpoint outbox fields")
    if outbox.get("schema") != CLAIM_BUDGET_CHECKPOINT_OUTBOX_SCHEMA:
        raise ClaimArtifactError("unsupported budget checkpoint outbox")
    transaction_id = str(outbox.get("transaction_id") or "")
    verifier_nonce = str(outbox.get("verifier_nonce") or "")
    if any(
        len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
        for value in (transaction_id, verifier_nonce)
    ):
        raise ClaimArtifactError("invalid budget checkpoint outbox identity")
    if not isinstance(outbox.get("created_at"), str) or not outbox.get("created_at"):
        raise ClaimArtifactError("invalid budget checkpoint outbox timestamp")
    snapshot = outbox.get("budget_snapshot")
    required_snapshot_fields = {
        "version",
        "max_calls",
        "max_tokens",
        "attempted_calls",
        "failed_calls",
        "tokens",
        "reserved_tokens",
        "remaining_calls",
        "remaining_tokens",
        "usage_complete",
        "denied",
        "termination_reason",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != required_snapshot_fields:
        raise ClaimArtifactError("invalid budget checkpoint outbox snapshot")
    if snapshot.get("version") != "llm-request-budget-v1":
        raise ClaimArtifactError("unsupported budget checkpoint outbox snapshot")
    for field in (
        "max_calls",
        "max_tokens",
        "attempted_calls",
        "failed_calls",
        "tokens",
        "reserved_tokens",
        "remaining_calls",
        "remaining_tokens",
    ):
        value = snapshot.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ClaimArtifactError("invalid budget checkpoint outbox accounting")
    if (
        not isinstance(snapshot.get("usage_complete"), bool)
        or not isinstance(snapshot.get("denied"), bool)
        or not isinstance(snapshot.get("termination_reason"), str)
    ):
        raise ClaimArtifactError("invalid budget checkpoint outbox state")
    if (
        snapshot["max_calls"] <= 0
        or snapshot["max_tokens"] <= 0
        or snapshot["attempted_calls"] > snapshot["max_calls"]
        or snapshot["failed_calls"] > snapshot["attempted_calls"]
        or snapshot["remaining_calls"]
        != max(0, snapshot["max_calls"] - snapshot["attempted_calls"])
        or snapshot["remaining_tokens"]
        != max(
            0,
            snapshot["max_tokens"]
            - snapshot["tokens"]
            - snapshot["reserved_tokens"],
        )
        or bool(snapshot["termination_reason"]) != snapshot["denied"]
        or (snapshot["failed_calls"] > 0 and snapshot["usage_complete"])
        or (
            snapshot["tokens"] > snapshot["max_tokens"]
            and (
                snapshot["denied"] is not True
                or snapshot["termination_reason"]
                != "reported_token_budget_exceeded"
            )
        )
        or (
            snapshot["reserved_tokens"] > 0
            and snapshot["tokens"] + snapshot["reserved_tokens"]
            > snapshot["max_tokens"]
        )
    ):
        raise ClaimArtifactError("inconsistent budget checkpoint outbox snapshot")
    queue_event = outbox.get("queue_event")
    if (
        not isinstance(queue_event, dict)
        or queue_event.get("event_kind") != "budget_checkpoint"
        or not isinstance(queue_event.get("idempotency_key"), str)
        or not queue_event.get("idempotency_key")
        or {
            "event_seq",
            "event_id",
            "prev_event_hash",
            "event_hash",
        }.intersection(queue_event)
    ):
        raise ClaimArtifactError("invalid budget checkpoint outbox queue event")
    expected_checkpoint = claim_budget_checkpoint_payload(snapshot)
    if (
        expected_checkpoint is None
        or queue_event.get("checkpoint") != expected_checkpoint
        or queue_event.get("idempotency_key")
        != claim_budget_checkpoint_event_idempotency_key(
            attempt_id=str(queue_event.get("attempt_id") or ""),
            transition_id=transaction_id,
            checkpoint=expected_checkpoint,
        )
    ):
        raise ClaimArtifactError("budget checkpoint outbox projections do not match")
    if outbox.get("outbox_sha256") != _sha256_payload(
        _budget_outbox_without_hash(outbox)
    ):
        raise ClaimArtifactError("budget checkpoint outbox hash mismatch")
    return outbox


def _write_budget_checkpoint_outbox_unlocked(
    root: Path,
    *,
    transaction_id: str,
    verifier_nonce: str,
    budget_snapshot: dict[str, Any],
    queue_event: dict[str, Any],
) -> None:
    path = claim_artifact_path(root, CLAIM_BUDGET_CHECKPOINT_OUTBOX)
    if path.exists():
        raise ClaimArtifactError("unfinished budget checkpoint outbox was not recovered")
    outbox = {
        "schema": CLAIM_BUDGET_CHECKPOINT_OUTBOX_SCHEMA,
        "transaction_id": transaction_id,
        "verifier_nonce": verifier_nonce,
        "created_at": _utc_now(),
        "budget_snapshot": dict(budget_snapshot),
        "queue_event": dict(queue_event),
    }
    outbox["outbox_sha256"] = _sha256_payload(outbox)
    atomic_write_json(path, outbox)


def _recover_budget_checkpoint_outbox_unlocked(
    root: Path,
) -> dict[str, Any] | None:
    """Idempotently project one budget transition to both durable sinks."""
    path = claim_artifact_path(root, CLAIM_BUDGET_CHECKPOINT_OUTBOX)
    if not path.is_file():
        return None
    outbox = _validate_budget_checkpoint_outbox(
        _read_json(path, label="budget checkpoint outbox")
    )
    checkpoint = _read_verifier_attempt_checkpoint_unlocked(root)
    nonce = str(outbox["verifier_nonce"])
    if str(dict(checkpoint["owner"])["nonce"]) != nonce:
        raise ClaimArtifactError("budget checkpoint outbox owner changed")

    # The queue event is the recovery authority for the paid operation.  Its
    # append is hash-chained and idempotent, so a kill after fsync simply replays
    # as a no-op.  Only after that projection exists do we advance the verifier
    # WAL to the exact same cumulative snapshot.
    from claim_reextract_attempts import append_attempt_events

    append_attempt_events(
        root,
        [dict(outbox["queue_event"])],
        operation_lock_held=True,
    )
    snapshot = dict(outbox["budget_snapshot"])
    _update_verifier_attempt_checkpoint_unlocked(
        root,
        nonce=nonce,
        budget_snapshot=snapshot,
    )
    _unlink_with_retry(path)
    return snapshot


def recover_claim_budget_checkpoint_outbox(
    out_dir: Path | str,
    *,
    operation_lock_held: bool = False,
) -> dict[str, Any] | None:
    """Recover a queue/verifier budget fanout before attempt-state folding."""
    root = Path(out_dir).expanduser().resolve()
    if not operation_lock_held:
        from omission_actions import extraction_operation_lock

        with extraction_operation_lock(
            root,
            operation="claim-budget-checkpoint-recovery",
        ):
            return recover_claim_budget_checkpoint_outbox(
                root,
                operation_lock_held=True,
            )
    with claim_publication_lock(root):
        return _recover_budget_checkpoint_outbox_unlocked(root)


def _discard_matching_verifier_checkpoint_unlocked(
    root: Path,
    recovery: dict[str, Any],
) -> None:
    path = claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)
    if not path.is_file():
        return
    checkpoint = _read_verifier_attempt_checkpoint_unlocked(root)
    if _checkpoint_attempt_id(dict(checkpoint["attempt_recovery"])) != (
        _checkpoint_attempt_id(recovery)
    ):
        raise ClaimArtifactError("verifier attempt checkpoint belongs to another attempt")
    _unlink_with_retry(path)


def _finalize_verifier_attempt_checkpoint_unlocked(
    root: Path,
    *,
    nonce: str | None,
    error: str,
) -> dict[str, Any] | None:
    path = claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)
    if not path.is_file():
        return None
    checkpoint = _read_verifier_attempt_checkpoint_unlocked(root)
    owner = dict(checkpoint["owner"])
    if nonce is not None and owner.get("nonce") != nonce:
        raise ClaimArtifactError("verifier attempt checkpoint owner changed")
    recovery = dict(checkpoint["attempt_recovery"])
    metrics = dict(recovery["attempt_metrics"])
    metrics["verifier_operation_failure_count"] = max(
        1,
        int(metrics["verifier_operation_failure_count"]) + 1,
    )
    chain_identity = dict(recovery["chain_identity"])
    attempt_id = _checkpoint_attempt_id(recovery)
    rows = _read_claim_verifier_attempts_unlocked(root, allow_missing=True)
    if any(row.get("attempt_id") == attempt_id for row in rows):
        binding = _correct_claim_verifier_attempt_unlocked(
            root,
            attempt_id=attempt_id,
            attempt_metrics=metrics,
            error=error,
        )
    else:
        binding = _append_claim_verifier_attempt_unlocked(
            root,
            attempt_kind=str(recovery["attempt_kind"]),
            attempt_status="failed",
            chain_identity=chain_identity,
            attempt_policy_identity=dict(recovery["attempt_policy_identity"]),
            source_locator=dict(recovery["source_locator"]),
            attempt_metrics=metrics,
            error=error,
        )
    _unlink_with_retry(path)
    return binding


def _recover_abandoned_verifier_checkpoint_unlocked(
    root: Path,
    *,
    allow_live_nonce: str | None = None,
) -> dict[str, Any] | None:
    path = claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)
    if not path.is_file():
        return None
    checkpoint = _read_verifier_attempt_checkpoint_unlocked(root)
    if _checkpoint_owner_is_active(root, checkpoint):
        owner_nonce = str(dict(checkpoint["owner"])["nonce"])
        if allow_live_nonce is not None and owner_nonce == allow_live_nonce:
            return None
        raise ClaimArtifactError("verifier attempt checkpoint is active")
    return _finalize_verifier_attempt_checkpoint_unlocked(
        root,
        nonce=str(dict(checkpoint["owner"])["nonce"]),
        error="ClaimVerifierAttemptInterrupted:recovered abandoned checkpoint",
    )


def _begin_claim_publication_unlocked(
    root: Path,
    *,
    run_id: str,
    attempt_recovery: dict[str, Any],
) -> dict[str, Any]:
    journal_path = claim_artifact_path(root, CLAIM_PUBLICATION_JOURNAL)
    if journal_path.exists():
        raise ClaimArtifactError("unfinished claim publication was not recovered")
    transaction_id = uuid.uuid4().hex
    backup_dir = _publication_backup_dir(root, transaction_id)
    backup_dir.mkdir(parents=False, exist_ok=False)
    entries: list[dict[str, Any]] = []
    try:
        for name in CLAIM_SNAPSHOT_FILES:
            source = claim_artifact_path(root, name)
            if source.is_file():
                payload = source.read_bytes()
                _atomic_write_bytes(backup_dir / name, payload)
                entries.append({
                    "name": name,
                    "present": True,
                    "sha256": _sha256_bytes(payload),
                })
            else:
                entries.append({
                    "name": name,
                    "present": False,
                    "sha256": _EMPTY_SHA256,
                })
        journal = {
            "schema": CLAIM_PUBLICATION_JOURNAL_SCHEMA,
            "transaction_id": transaction_id,
            "run_id": str(run_id),
            "prepared_at": _utc_now(),
            "snapshot_files": entries,
            "attempt_recovery": dict(attempt_recovery),
        }
        journal["journal_sha256"] = _sha256_payload(journal)
        atomic_write_json(journal_path, journal)
        _discard_matching_verifier_checkpoint_unlocked(root, attempt_recovery)
        return journal
    except BaseException:
        if not journal_path.is_file():
            cleanup_journal = {
                "transaction_id": transaction_id,
                "snapshot_files": entries,
            }
            try:
                _cleanup_publication_backup(root, cleanup_journal)
            except OSError:
                pass
        raise


def _finish_claim_publication_unlocked(root: Path, journal: dict[str, Any]) -> None:
    _unlink_with_retry(claim_artifact_path(root, CLAIM_PUBLICATION_JOURNAL))
    try:
        _cleanup_publication_backup(root, journal)
    except OSError:
        # The commit is already durable. A leftover hidden backup is inert.
        pass


def _begin_effective_publication_unlocked(
    root: Path,
    *,
    base_generation_id: str,
    generation_meta_sha256: str,
    base_ledger_sha256: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    journal_path = claim_artifact_path(root, CLAIM_EFFECTIVE_PUBLICATION_JOURNAL)
    if journal_path.exists():
        raise ClaimArtifactError("unfinished effective publication was not recovered")
    transaction_id = uuid.uuid4().hex
    backup_dir = _effective_publication_backup_dir(root, transaction_id)
    backup_dir.mkdir(parents=False, exist_ok=False)
    entries: list[dict[str, Any]] = []
    try:
        for name in CLAIM_EFFECTIVE_SNAPSHOT_FILES:
            source = claim_artifact_path(root, name)
            if source.is_file():
                payload = source.read_bytes()
                _atomic_write_bytes(backup_dir / name, payload)
                entries.append({
                    "name": name,
                    "present": True,
                    "sha256": _sha256_bytes(payload),
                    "backup_name": name,
                })
            else:
                entries.append({
                    "name": name,
                    "present": False,
                    "sha256": None,
                    "backup_name": None,
                })
        journal = {
            "schema": CLAIM_EFFECTIVE_PUBLICATION_JOURNAL_SCHEMA,
            "transaction_kind": "effective_fold",
            "transaction_id": transaction_id,
            "state": "prepared",
            "created_at": _utc_now(),
            "base_generation_id": base_generation_id,
            "generation_meta_sha256": generation_meta_sha256,
            "base_ledger_sha256": base_ledger_sha256,
            "snapshot_files": entries,
            "candidate": dict(candidate),
        }
        journal["journal_sha256"] = hash_json(
            "claim-effective-publication-journal/v1",
            journal,
        )
        _validate_schema(
            journal,
            "claim_effective_publication_journal.schema.json",
            label="effective publication journal",
        )
        atomic_write_canonical_json(journal_path, journal)
        return journal
    except BaseException:
        if not journal_path.is_file():
            cleanup_journal = {
                "transaction_id": transaction_id,
                "snapshot_files": entries,
            }
            try:
                _cleanup_effective_publication_backup(root, cleanup_journal)
            except OSError:
                pass
        raise


def _finish_effective_publication_unlocked(
    root: Path,
    journal: dict[str, Any],
) -> None:
    _unlink_with_retry(claim_artifact_path(root, CLAIM_EFFECTIVE_PUBLICATION_JOURNAL))
    try:
        _cleanup_effective_publication_backup(root, journal)
    except OSError:
        # The commit is already durable. A leftover hidden backup is inert.
        pass


def _recover_interrupted_effective_publication_unlocked(root: Path) -> bool:
    journal_path = claim_artifact_path(root, CLAIM_EFFECTIVE_PUBLICATION_JOURNAL)
    if not journal_path.is_file():
        _cleanup_orphan_effective_backups_unlocked(root)
        return False
    journal = _read_json(journal_path, label="effective publication journal")
    snapshot = _validate_effective_publication_journal(root, journal)
    _require_hash(
        claim_artifact_path(root, CLAIM_GENERATION_META),
        journal.get("generation_meta_sha256"),
        label="effective publication base generation meta",
    )
    _require_hash(
        claim_artifact_path(root, CLAIM_LEDGER),
        journal.get("base_ledger_sha256"),
        label="effective publication base ledger",
    )
    generation = _read_json(
        claim_artifact_path(root, CLAIM_GENERATION_META),
        label="effective publication base generation meta",
    )
    if journal.get("base_generation_id") != claim_base_generation_id(generation):
        raise ClaimArtifactError("effective publication base generation changed")
    _restore_effective_snapshot(root, snapshot)
    _verify_restored_effective_snapshot(root, snapshot)
    _finish_effective_publication_unlocked(root, journal)
    return True


def _recover_interrupted_publication_unlocked(
    root: Path,
) -> dict[str, Any] | None:
    journal_path = claim_artifact_path(root, CLAIM_PUBLICATION_JOURNAL)
    if not journal_path.is_file():
        _cleanup_orphan_publication_backups_unlocked(root)
        return None
    journal = _read_json(journal_path, label="claim publication journal")
    snapshot = _validate_publication_journal(root, journal)
    _restore_claim_snapshot(root, snapshot)

    recovery = journal.get("attempt_recovery")
    if not isinstance(recovery, dict):
        raise ClaimArtifactError("invalid claim publication attempt recovery")
    metrics = _normalize_attempt_metrics(dict(recovery.get("attempt_metrics") or {}))
    metrics["verifier_operation_failure_count"] = max(
        1,
        int(metrics["verifier_operation_failure_count"]) + 1,
    )
    chain_identity = dict(recovery.get("chain_identity") or {})
    attempt_policy_identity = dict(recovery.get("attempt_policy_identity") or {})
    source_locator = dict(recovery.get("source_locator") or {})
    attempt_kind = str(recovery.get("attempt_kind") or "")
    chain_id = _sha256_payload(chain_identity)
    attempt_id = _attempt_id(chain_id, attempt_kind, source_locator)
    rows = _read_claim_verifier_attempts_unlocked(root, allow_missing=True)
    matching = [row for row in rows if row.get("attempt_id") == attempt_id]
    if matching:
        binding = _correct_claim_verifier_attempt_unlocked(
            root,
            attempt_id=attempt_id,
            attempt_metrics=metrics,
            error="ClaimPublicationInterrupted:recovered unfinished publication",
        )
    else:
        binding = _append_claim_verifier_attempt_unlocked(
            root,
            attempt_kind=attempt_kind,
            attempt_status="failed",
            chain_identity=chain_identity,
            attempt_policy_identity=attempt_policy_identity,
            source_locator=source_locator,
            attempt_metrics=metrics,
            error="ClaimPublicationInterrupted:recovered unfinished publication",
        )
    _discard_matching_verifier_checkpoint_unlocked(root, recovery)
    _finish_claim_publication_unlocked(root, journal)
    return binding


def _recover_claim_state_unlocked(
    root: Path,
    *,
    allow_live_checkpoint_nonce: str | None = None,
) -> dict[str, Any] | None:
    if (claim_artifact_path(root, CLAIM_BUDGET_CHECKPOINT_OUTBOX)).is_file():
        # Queue events are protected by the extraction-operation lock.  Claim
        # GETs hold only the publication lock and must remain byte-invariant, so
        # they fail closed until the write-side maintenance path replays this
        # outbox in the canonical extraction -> publication lock order.
        raise ClaimArtifactError(
            "budget checkpoint recovery requires claim maintenance"
        )
    binding = _recover_interrupted_publication_unlocked(root)
    _recover_interrupted_effective_publication_unlocked(root)
    checkpoint_binding = _recover_abandoned_verifier_checkpoint_unlocked(
        root,
        allow_live_nonce=allow_live_checkpoint_nonce,
    )
    return binding or checkpoint_binding


def _active_verifier_checkpoint_nonce(root: Path) -> str | None:
    context = _VERIFIER_ATTEMPT_CONTEXT.get()
    if context is None or context.get("root") != root:
        return None
    nonce = str(context.get("checkpoint_nonce") or "")
    return nonce or None


def record_verifier_attempt_progress(
    out_dir: Path | str,
    *,
    candidate_group_count: int,
    reused_group_count: int,
) -> None:
    """Durably bind candidate and reuse counts before verifier requests begin."""
    if (
        isinstance(candidate_group_count, bool)
        or isinstance(reused_group_count, bool)
        or int(candidate_group_count) < 0
        or int(reused_group_count) < 0
        or int(reused_group_count) > int(candidate_group_count)
    ):
        raise ClaimArtifactError("invalid verifier attempt progress")
    root = Path(out_dir).expanduser().resolve()
    context = _VERIFIER_ATTEMPT_CONTEXT.get()
    if (
        context is None
        or context.get("root") != root
        or not context.get("failure_context")
    ):
        return
    nonce = str(context.get("checkpoint_nonce") or "")
    if not nonce:
        raise ClaimArtifactError("verifier attempt progress has no checkpoint owner")
    candidates = int(candidate_group_count)
    reused = int(reused_group_count)
    failure = context["failure_context"]
    failure["candidate_group_count"] = candidates
    failure["reused_group_count"] = reused
    with claim_publication_lock(root):
        if not (claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)).is_file():
            raise ClaimArtifactError("verifier attempt progress checkpoint is missing")
        _update_verifier_attempt_checkpoint_unlocked(
            root,
            nonce=nonce,
            candidate_group_count=candidates,
            reused_group_count=reused,
        )


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ClaimArtifactError(f"missing {label}: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimArtifactError(f"invalid {label}: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ClaimArtifactError(f"invalid {label}: expected object")
    return payload


def _read_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ClaimArtifactError(f"missing {label}: {path.name}")
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ClaimArtifactError(
                        f"invalid {label}: {path.name}:{line_number} is not an object"
                    )
                rows.append(row)
    except ClaimArtifactError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimArtifactError(f"invalid {label}: {path.name}") from exc
    return rows


def _require_hash(path: Path, expected: object, *, label: str) -> None:
    wanted = str(expected or "")
    if not wanted:
        raise ClaimArtifactError(f"missing committed hash for {label}")
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise ClaimArtifactError(f"missing committed artifact: {path.name}") from exc
    if actual != wanted:
        raise ClaimArtifactError(
            f"hash mismatch for {label}: expected {wanted}, got {actual}"
        )


def _catalog_meta_requires_cell_binding(catalog_meta: dict[str, Any]) -> bool:
    """当前版本表格结构目录且含表块 → cell 产物哈希绑定是硬义务。

    纯段落目录没有 canonical cell（无表即无 cell 产物可绑）；已判
    base_migration_required 的旧结构目录走迁移门禁，不在此绑定。"""
    from table_structure import TABLE_STRUCTURE_VERSION

    if str(catalog_meta.get("table_structure_version") or "") != TABLE_STRUCTURE_VERSION:
        return False
    if str(catalog_meta.get("table_structure_status") or "") == "base_migration_required":
        return False
    mappings = catalog_meta.get("container_mappings") or []
    return any(
        isinstance(mapping, dict) and str(mapping.get("kind") or "") == "table"
        for mapping in mappings
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256_payload(payload: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes(payload))


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return (
        len(text) == 71
        and text.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in text[7:])
    )


def _attempt_ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


_ATTEMPT_METRIC_FIELDS = {
    "verifier_call_count",
    "verifier_failed_call_count",
    "verifier_operation_failure_count",
    "verifier_tokens",
    "verifier_usage_complete",
    "semantic_validation_reused_group_count",
    "semantic_verifier_candidate_count",
    "semantic_validation_reused_group_ratio",
}
_ATTEMPT_IDENTITY_FIELDS = {
    "root_attempt_request_id",
    "requirements_request_id",
    "document_generation_id",
    "requirements_sha256",
}
_ATTEMPT_POLICY_IDENTITY_FIELDS = {
    "target_generation_id",
    "verifier_runtime_fingerprint",
    "baseline_lineage_version",
    "baseline_lineage_fingerprint",
    "baseline_lineage_match",
    "cost_policy_version",
}
_ATTEMPT_SOURCE_FIELDS = {
    "attempt_request_id",
    "requirements_request_id",
    "catalog_generation_id",
    "document_generation_id",
    "target_generation_id",
    "requirements_sha256",
    "reuse_generation_run_id",
    "reuse_attempt_id",
    "source_generation_run_id",
    "source_attempt_id",
}
_ATTEMPT_EVENT_FIELDS = {
    "schema",
    "event_seq",
    "attempt_id",
    "attempt_kind",
    "attempt_status",
    "recorded_at",
    "chain_id",
    "chain_attempt_seq",
    "previous_event_hash",
    "supersedes_event_hash",
    "chain_identity",
    "attempt_policy_identity",
    "source_locator",
    "attempt_metrics",
    "error",
    "event_hash",
}
_ATTEMPT_BINDING_FIELDS = {
    "schema",
    "ledger_file",
    "ledger_prefix_count",
    "ledger_prefix_sha256",
    "chain_id",
    "attempt_id",
    "attempt_count",
    "attempt_kind",
    "attempt_status",
    "source_locator",
    "cumulative_metrics",
}


def _normalize_attempt_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    reused = max(0, int(metrics.get("semantic_validation_reused_group_count") or 0))
    candidates = max(0, int(metrics.get("semantic_verifier_candidate_count") or 0))
    if reused > candidates:
        raise ClaimArtifactError("verifier attempt reused group count exceeds candidates")
    return {
        "verifier_call_count": max(0, int(metrics.get("verifier_call_count") or 0)),
        "verifier_failed_call_count": max(
            0,
            int(
                metrics.get("verifier_failed_call_count")
                if "verifier_failed_call_count" in metrics
                else metrics.get("verifier_failed_calls")
                or 0
            ),
        ),
        "verifier_operation_failure_count": max(
            0,
            int(metrics.get("verifier_operation_failure_count") or 0),
        ),
        "verifier_tokens": max(0, int(metrics.get("verifier_tokens") or 0)),
        "verifier_usage_complete": metrics.get("verifier_usage_complete") is True,
        "semantic_validation_reused_group_count": reused,
        "semantic_verifier_candidate_count": candidates,
        "semantic_validation_reused_group_ratio": _attempt_ratio(reused, candidates),
    }


def _latest_attempt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        attempt_id = str(row.get("attempt_id") or "")
        if attempt_id not in latest:
            order.append(attempt_id)
        latest[attempt_id] = row
    return [latest[attempt_id] for attempt_id in order]


def _attempt_cumulative_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        dict(row.get("attempt_metrics") or {})
        for row in _latest_attempt_rows(rows)
    ]
    reused = sum(int(item["semantic_validation_reused_group_count"]) for item in metrics)
    candidates = sum(int(item["semantic_verifier_candidate_count"]) for item in metrics)
    return {
        "verifier_call_count": sum(int(item["verifier_call_count"]) for item in metrics),
        "verifier_failed_call_count": sum(
            int(item["verifier_failed_call_count"]) for item in metrics
        ),
        "verifier_operation_failure_count": sum(
            int(item["verifier_operation_failure_count"]) for item in metrics
        ),
        "verifier_tokens": sum(int(item["verifier_tokens"]) for item in metrics),
        "verifier_usage_complete": all(
            item["verifier_usage_complete"] is True for item in metrics
        ),
        "semantic_validation_reused_group_count": reused,
        "semantic_verifier_candidate_count": candidates,
        "semantic_validation_reused_group_ratio": _attempt_ratio(reused, candidates),
    }


def _attempt_id(
    chain_id: str,
    attempt_kind: str,
    source_locator: dict[str, Any],
) -> str:
    return _sha256_payload({
        "schema": "claim-verifier-attempt-id/v1",
        "chain_id": chain_id,
        "attempt_kind": attempt_kind,
        "attempt_request_id": source_locator["attempt_request_id"],
        "requirements_request_id": source_locator["requirements_request_id"],
        "reuse_generation_run_id": source_locator["reuse_generation_run_id"],
        "reuse_attempt_id": source_locator["reuse_attempt_id"],
    })


def _validate_attempt_metrics(metrics: object) -> None:
    if not isinstance(metrics, dict) or set(metrics) != _ATTEMPT_METRIC_FIELDS:
        raise ClaimArtifactError("invalid verifier attempt metrics")
    for field in _ATTEMPT_METRIC_FIELDS - {
        "verifier_usage_complete",
        "semantic_validation_reused_group_ratio",
    }:
        value = metrics.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ClaimArtifactError("invalid verifier attempt metric counter")
    if not isinstance(metrics.get("verifier_usage_complete"), bool):
        raise ClaimArtifactError("invalid verifier attempt usage completeness")
    reused = int(metrics["semantic_validation_reused_group_count"])
    candidates = int(metrics["semantic_verifier_candidate_count"])
    if reused > candidates:
        raise ClaimArtifactError("verifier attempt reused group count exceeds candidates")
    if metrics.get("semantic_validation_reused_group_ratio") != _attempt_ratio(
        reused,
        candidates,
    ):
        raise ClaimArtifactError("invalid verifier attempt reuse ratio")


def _validate_attempt_identity(identity: object) -> None:
    if not isinstance(identity, dict) or set(identity) != _ATTEMPT_IDENTITY_FIELDS:
        raise ClaimArtifactError("invalid verifier attempt chain identity")
    if any(
        not isinstance(identity.get(field), str) or not identity.get(field)
        for field in ("root_attempt_request_id", "requirements_request_id")
    ):
        raise ClaimArtifactError("invalid verifier attempt root request identity")
    for field in ("document_generation_id", "requirements_sha256"):
        if not _is_sha256(identity.get(field)):
            raise ClaimArtifactError("invalid verifier attempt generation identity")


def _validate_attempt_policy_identity(identity: object) -> None:
    if (
        not isinstance(identity, dict)
        or set(identity) != _ATTEMPT_POLICY_IDENTITY_FIELDS
    ):
        raise ClaimArtifactError("invalid verifier attempt policy identity")
    for field in ("target_generation_id", "verifier_runtime_fingerprint"):
        if not _is_sha256(identity.get(field)):
            raise ClaimArtifactError("invalid verifier attempt policy generation")
    baseline_fingerprint = identity.get("baseline_lineage_fingerprint")
    if baseline_fingerprint not in {"", None} and not _is_sha256(baseline_fingerprint):
        raise ClaimArtifactError("invalid verifier attempt baseline identity")
    if (
        not isinstance(identity.get("baseline_lineage_version"), str)
        or not isinstance(identity.get("baseline_lineage_fingerprint"), str)
        or not isinstance(identity.get("baseline_lineage_match"), bool)
        or not isinstance(identity.get("cost_policy_version"), str)
        or not identity.get("cost_policy_version")
    ):
        raise ClaimArtifactError("invalid verifier attempt policy identity")


def _validate_attempt_source(source: object, *, attempt_kind: str) -> None:
    if not isinstance(source, dict) or set(source) != _ATTEMPT_SOURCE_FIELDS:
        raise ClaimArtifactError("invalid verifier attempt source locator")
    for field in ("attempt_request_id", "requirements_request_id"):
        if not isinstance(source.get(field), str) or not source.get(field):
            raise ClaimArtifactError("invalid verifier attempt request identity")
    for field in (
        "catalog_generation_id",
        "document_generation_id",
        "target_generation_id",
        "requirements_sha256",
    ):
        if not _is_sha256(source.get(field)):
            raise ClaimArtifactError("invalid verifier attempt source generation")
    reuse_run = source.get("reuse_generation_run_id")
    reuse_attempt = source.get("reuse_attempt_id")
    if source.get("source_generation_run_id") != reuse_run:
        raise ClaimArtifactError("verifier attempt source generation aliases differ")
    if source.get("source_attempt_id") != reuse_attempt:
        raise ClaimArtifactError("verifier attempt source attempt aliases differ")
    if attempt_kind == "cold":
        if reuse_run is not None or reuse_attempt is not None:
            raise ClaimArtifactError("cold verifier attempt cannot claim reuse")
    elif attempt_kind == "ledger_only":
        if not isinstance(reuse_run, str) or not reuse_run or not _is_sha256(reuse_attempt):
            raise ClaimArtifactError("ledger-only verifier attempt is missing reuse lineage")
    else:
        raise ClaimArtifactError("invalid verifier attempt kind")


def _validate_attempt_rows(rows: list[dict[str, Any]]) -> None:
    previous_hash = _EMPTY_SHA256
    chain_counts: dict[str, int] = {}
    attempt_states: dict[str, dict[str, Any]] = {}
    for expected_seq, row in enumerate(rows, start=1):
        if set(row) != _ATTEMPT_EVENT_FIELDS:
            raise ClaimArtifactError("invalid verifier attempt event shape")
        if row.get("schema") != CLAIM_VERIFIER_ATTEMPT_SCHEMA:
            raise ClaimArtifactError("unsupported verifier attempt schema")
        if row.get("event_seq") != expected_seq:
            raise ClaimArtifactError("invalid verifier attempt event sequence")
        if row.get("attempt_kind") not in {"cold", "ledger_only"}:
            raise ClaimArtifactError("invalid verifier attempt kind")
        if row.get("attempt_status") not in {"complete", "incomplete", "failed"}:
            raise ClaimArtifactError("invalid verifier attempt status")
        if not isinstance(row.get("recorded_at"), str) or not row.get("recorded_at"):
            raise ClaimArtifactError("invalid verifier attempt timestamp")
        if not isinstance(row.get("error"), str):
            raise ClaimArtifactError("invalid verifier attempt error")
        if row.get("previous_event_hash") != previous_hash:
            raise ClaimArtifactError("invalid verifier attempt previous event hash")
        _validate_attempt_identity(row.get("chain_identity"))
        _validate_attempt_policy_identity(row.get("attempt_policy_identity"))
        expected_chain_id = _sha256_payload(row["chain_identity"])
        if row.get("chain_id") != expected_chain_id:
            raise ClaimArtifactError("invalid verifier attempt chain id")
        _validate_attempt_source(
            row.get("source_locator"),
            attempt_kind=str(row["attempt_kind"]),
        )
        _validate_attempt_metrics(row.get("attempt_metrics"))
        expected_attempt_id = _attempt_id(
            expected_chain_id,
            str(row["attempt_kind"]),
            row["source_locator"],
        )
        if row.get("attempt_id") != expected_attempt_id:
            raise ClaimArtifactError("invalid verifier attempt id")
        source = row["source_locator"]
        identity = row["chain_identity"]
        if (
            identity["requirements_request_id"] != source["requirements_request_id"]
            or identity["document_generation_id"] != source["document_generation_id"]
            or identity["requirements_sha256"] != source["requirements_sha256"]
        ):
            raise ClaimArtifactError("verifier attempt requirements root differs from source")
        if row["attempt_kind"] == "cold":
            if identity["root_attempt_request_id"] != source["attempt_request_id"]:
                raise ClaimArtifactError("cold verifier chain root differs from request")
        else:
            reuse_attempt_id = str(source["reuse_attempt_id"])
            reused = attempt_states.get(reuse_attempt_id)
            if reused is None:
                raise ClaimArtifactError("ledger-only verifier attempt reuses unknown attempt")
            if (
                reused["chain_id"] != expected_chain_id
                or reused["source_locator"]["attempt_request_id"]
                != source["reuse_generation_run_id"]
                or identity["root_attempt_request_id"]
                != reused["chain_identity"]["root_attempt_request_id"]
            ):
                raise ClaimArtifactError("ledger-only verifier attempt reuse lineage is stale")

        prior = attempt_states.get(expected_attempt_id)
        if prior is None:
            if row.get("supersedes_event_hash") is not None:
                raise ClaimArtifactError("initial verifier attempt cannot supersede an event")
            chain_counts[expected_chain_id] = chain_counts.get(expected_chain_id, 0) + 1
            if row.get("chain_attempt_seq") != chain_counts[expected_chain_id]:
                raise ClaimArtifactError("invalid verifier chain attempt sequence")
        else:
            if (
                row.get("supersedes_event_hash") != prior.get("event_hash")
                or row.get("attempt_kind") != prior.get("attempt_kind")
                or row.get("chain_id") != prior.get("chain_id")
                or row.get("chain_attempt_seq") != prior.get("chain_attempt_seq")
                or row.get("chain_identity") != prior.get("chain_identity")
                or row.get("attempt_policy_identity")
                != prior.get("attempt_policy_identity")
                or row.get("source_locator") != prior.get("source_locator")
                or row.get("attempt_status") != "failed"
                or not row.get("error")
            ):
                raise ClaimArtifactError("invalid verifier attempt status correction")
            old_metrics = dict(prior["attempt_metrics"])
            new_metrics = dict(row["attempt_metrics"])
            for field in _ATTEMPT_METRIC_FIELDS - {
                "verifier_usage_complete",
                "semantic_validation_reused_group_ratio",
            }:
                if int(new_metrics[field]) < int(old_metrics[field]):
                    raise ClaimArtifactError("verifier attempt correction loses accounting")
            if (
                new_metrics["verifier_operation_failure_count"]
                <= old_metrics["verifier_operation_failure_count"]
                or old_metrics["verifier_usage_complete"] is False
                and new_metrics["verifier_usage_complete"] is True
            ):
                raise ClaimArtifactError("invalid verifier attempt failure correction")
        unhashed = dict(row)
        event_hash = unhashed.pop("event_hash")
        if event_hash != _sha256_payload(unhashed):
            raise ClaimArtifactError("invalid verifier attempt event hash")
        attempt_states[expected_attempt_id] = row
        previous_hash = str(event_hash)


def _read_claim_verifier_attempts_unlocked(
    root: Path,
    *,
    allow_missing: bool,
) -> list[dict[str, Any]]:
    path = claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPTS)
    if not path.is_file():
        if allow_missing:
            return []
        raise ClaimArtifactError(f"missing verifier attempt ledger: {path.name}")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        # A missing trailing newline on the final line is a suspected torn tail: the
        # publisher may still be appending. Re-read within a bounded window and only
        # declare permanent corruption if the partial tail never settles. A complete
        # line whose hash/chain/schema is forged is distinguished by
        # _validate_attempt_rows below and rejected immediately, never retried.
        max_retries = int(os.environ.get("RATOMIZER_ATTEMPT_LOG_TORN_RETRIES", "3"))
        retry_delay = float(os.environ.get("RATOMIZER_ATTEMPT_LOG_TORN_DELAY", "0.005"))
        settled = False
        for _ in range(max_retries):
            time.sleep(retry_delay)
            candidate = path.read_bytes()
            if candidate.endswith(b"\n"):
                raw = candidate
                settled = True
                break
            if candidate != raw:
                raw = candidate  # still moving; keep observing within the window
        if not settled and raw and not raw.endswith(b"\n"):
            raise ClaimAttemptLogTornTail(
                "verifier attempt ledger has a persistent torn tail that never settled"
            )
    rows = _read_jsonl(path, label="verifier attempt ledger")
    _validate_attempt_rows(rows)
    return rows


def read_claim_verifier_attempts(out_dir: Path | str) -> list[dict[str, Any]]:
    """Read a complete, hash-consistent verifier-attempt ledger."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        return _read_claim_verifier_attempts_unlocked(root, allow_missing=False)


def _attempt_binding(
    rows: list[dict[str, Any]],
    event: dict[str, Any],
) -> dict[str, Any]:
    chain_rows = [row for row in rows if row["chain_id"] == event["chain_id"]]
    latest_chain_rows = _latest_attempt_rows(chain_rows)
    return {
        "schema": CLAIM_VERIFIER_ATTEMPT_BINDING_SCHEMA,
        "ledger_file": CLAIM_VERIFIER_ATTEMPTS,
        "ledger_prefix_count": len(rows),
        "ledger_prefix_sha256": _sha256_bytes(_jsonl_bytes(rows)),
        "chain_id": event["chain_id"],
        "attempt_id": event["attempt_id"],
        "attempt_count": len(latest_chain_rows),
        "attempt_kind": event["attempt_kind"],
        "attempt_status": event["attempt_status"],
        "source_locator": dict(event["source_locator"]),
        "cumulative_metrics": _attempt_cumulative_metrics(latest_chain_rows),
    }


def _attempt_cost_chain(
    rows: list[dict[str, Any]],
    binding: dict[str, Any],
) -> dict[str, Any]:
    chain_id = str(binding.get("chain_id") or "")
    latest_chain_rows = sorted(
        _latest_attempt_rows([
            row for row in rows if row.get("chain_id") == chain_id
        ]),
        key=lambda row: int(row["chain_attempt_seq"]),
    )
    if not latest_chain_rows:
        raise ClaimArtifactError("committed verifier attempt chain is missing")
    tail = latest_chain_rows[-1]
    return {
        "schema": "claim-verifier-attempt-cost-chain/v1",
        "ledger_file": CLAIM_VERIFIER_ATTEMPTS,
        "validated_full_ledger_count": len(rows),
        "validated_full_ledger_sha256": _sha256_bytes(_jsonl_bytes(rows)),
        "chain_id": chain_id,
        "attempt_count": len(latest_chain_rows),
        "tail_attempt_id": str(tail["attempt_id"]),
        "tail_attempt_kind": str(tail["attempt_kind"]),
        "tail_attempt_status": str(tail["attempt_status"]),
        "cumulative_metrics": _attempt_cumulative_metrics(latest_chain_rows),
    }


def _append_claim_verifier_attempt_unlocked(
    root: Path,
    *,
    attempt_kind: str,
    attempt_status: str,
    chain_identity: dict[str, Any],
    attempt_policy_identity: dict[str, Any],
    source_locator: dict[str, Any],
    attempt_metrics: dict[str, Any],
    error: str = "",
) -> dict[str, Any]:
    rows = _read_claim_verifier_attempts_unlocked(root, allow_missing=True)
    _validate_attempt_identity(chain_identity)
    _validate_attempt_policy_identity(attempt_policy_identity)
    _validate_attempt_source(source_locator, attempt_kind=attempt_kind)
    normalized_metrics = _normalize_attempt_metrics(attempt_metrics)
    chain_id = _sha256_payload(chain_identity)
    attempt_id = _attempt_id(chain_id, attempt_kind, source_locator)
    matching = [row for row in rows if row["attempt_id"] == attempt_id]
    if matching:
        existing = matching[-1]
        expected = {
            "attempt_kind": attempt_kind,
            "attempt_status": attempt_status,
            "chain_identity": chain_identity,
            "attempt_policy_identity": attempt_policy_identity,
            "source_locator": source_locator,
            "attempt_metrics": normalized_metrics,
            "error": str(error),
        }
        if any(existing.get(key) != value for key, value in expected.items()):
            raise ClaimArtifactError("verifier attempt id was reused with different evidence")
        return _attempt_binding(rows, existing)

    chain_attempt_seq = 1 + len(_latest_attempt_rows([
        row for row in rows if row["chain_id"] == chain_id
    ]))
    event = {
        "schema": CLAIM_VERIFIER_ATTEMPT_SCHEMA,
        "event_seq": len(rows) + 1,
        "attempt_id": attempt_id,
        "attempt_kind": attempt_kind,
        "attempt_status": attempt_status,
        "recorded_at": _utc_now(),
        "chain_id": chain_id,
        "chain_attempt_seq": chain_attempt_seq,
        "previous_event_hash": rows[-1]["event_hash"] if rows else _EMPTY_SHA256,
        "supersedes_event_hash": None,
        "chain_identity": dict(chain_identity),
        "attempt_policy_identity": dict(attempt_policy_identity),
        "source_locator": dict(source_locator),
        "attempt_metrics": normalized_metrics,
        "error": str(error),
    }
    event["event_hash"] = _sha256_payload(event)
    updated = [*rows, event]
    _validate_attempt_rows(updated)
    atomic_write_jsonl(claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPTS), updated)
    return _attempt_binding(updated, event)


def _correct_claim_verifier_attempt_unlocked(
    root: Path,
    *,
    attempt_id: str,
    attempt_metrics: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    rows = _read_claim_verifier_attempts_unlocked(root, allow_missing=False)
    matching = [row for row in rows if row["attempt_id"] == attempt_id]
    if not matching:
        raise ClaimArtifactError("cannot correct an unknown verifier attempt")
    prior = matching[-1]
    normalized_metrics = _normalize_attempt_metrics(attempt_metrics)
    if (
        prior["attempt_status"] == "failed"
        and prior["attempt_metrics"] == normalized_metrics
    ):
        return _attempt_binding(rows, prior)
    event = {
        **{
            key: prior[key]
            for key in (
                "schema",
                "attempt_id",
                "attempt_kind",
                "chain_id",
                "chain_attempt_seq",
                "chain_identity",
                "attempt_policy_identity",
                "source_locator",
            )
        },
        "event_seq": len(rows) + 1,
        "attempt_status": "failed",
        "recorded_at": _utc_now(),
        "previous_event_hash": rows[-1]["event_hash"],
        "supersedes_event_hash": prior["event_hash"],
        "attempt_metrics": normalized_metrics,
        "error": str(error),
    }
    event["event_hash"] = _sha256_payload(event)
    updated = [*rows, event]
    _validate_attempt_rows(updated)
    atomic_write_jsonl(claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPTS), updated)
    return _attempt_binding(updated, event)


def _requirements_attempt_metadata(root: Path) -> dict[str, Any]:
    path = root / "ai_requirements.meta.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _shadow_baseline_matches_requirements_metadata(
    metrics: dict[str, Any],
    requirements_meta: dict[str, Any],
) -> bool:
    raw_baseline = requirements_meta.get("no_ledger_baseline_cost")
    if raw_baseline is None:
        baseline: dict[str, Any] = {}
    elif isinstance(raw_baseline, dict):
        baseline = raw_baseline
        required_fields = {
            "call_count",
            "failed_call_count",
            "total_tokens",
            "usage_complete",
            "lineage_version",
            "lineage_fingerprint",
            "lineage_context",
            "lineage_match",
        }
        if not required_fields.issubset(baseline):
            return False
    else:
        return False

    expected_numbers = {
        "no_ledger_baseline_call_count": baseline.get("call_count", 0),
        "no_ledger_baseline_failed_call_count": baseline.get(
            "failed_call_count",
            0,
        ),
        "no_ledger_baseline_tokens": baseline.get("total_tokens", 0),
    }
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for value in expected_numbers.values()
    ):
        return False
    if expected_numbers["no_ledger_baseline_failed_call_count"] > expected_numbers[
        "no_ledger_baseline_call_count"
    ]:
        return False
    if any(
        not isinstance(metrics.get(field), int)
        or isinstance(metrics.get(field), bool)
        or metrics.get(field) != expected
        for field, expected in expected_numbers.items()
    ):
        return False

    metadata_usage_complete = baseline.get("usage_complete", False)
    if not isinstance(metadata_usage_complete, bool):
        return False
    lineage_context = baseline.get("lineage_context", {})
    lineage_is_bound = (
        baseline.get("lineage_match") is True
        and isinstance(baseline.get("lineage_version", ""), str)
        and bool(baseline.get("lineage_version"))
        and _is_sha256(baseline.get("lineage_fingerprint"))
        and isinstance(lineage_context, dict)
        and bool(lineage_context)
    )
    reported_lineage_match = metrics.get("no_ledger_baseline_lineage_match")
    if not isinstance(reported_lineage_match, bool):
        return False
    if reported_lineage_match and not lineage_is_bound:
        return False
    expected_usage_complete = metadata_usage_complete and reported_lineage_match
    return (
        isinstance(metrics.get("no_ledger_baseline_usage_complete"), bool)
        and metrics.get("no_ledger_baseline_usage_complete")
        is expected_usage_complete
    )


def _attempt_chain_root_request_id(
    root: Path,
    *,
    attempt_kind: str,
    attempt_request_id: str,
    reuse_attempt_id: str | None,
) -> str:
    if attempt_kind == "cold":
        return str(attempt_request_id)
    rows = _read_claim_verifier_attempts_unlocked(root, allow_missing=False)
    reused = [row for row in rows if row.get("attempt_id") == reuse_attempt_id]
    if not reused:
        raise ClaimArtifactError("ledger-only verifier attempt reuses unknown attempt")
    return str(reused[-1]["chain_identity"]["root_attempt_request_id"])


def _attempt_source_locator(
    *,
    attempt_kind: str,
    attempt_request_id: str,
    requirements_request_id: str,
    catalog_generation_id: str,
    document_generation_id: str,
    target_generation_id: str,
    requirements_sha256: str,
    reuse_generation_run_id: str | None,
    reuse_attempt_id: str | None,
) -> dict[str, Any]:
    reuse_run = reuse_generation_run_id if attempt_kind == "ledger_only" else None
    reuse_id = reuse_attempt_id if attempt_kind == "ledger_only" else None
    return {
        "attempt_request_id": attempt_request_id,
        "requirements_request_id": requirements_request_id,
        "catalog_generation_id": catalog_generation_id,
        "document_generation_id": document_generation_id,
        "target_generation_id": target_generation_id,
        "requirements_sha256": requirements_sha256,
        "reuse_generation_run_id": reuse_run,
        "reuse_attempt_id": reuse_id,
        "source_generation_run_id": reuse_run,
        "source_attempt_id": reuse_id,
    }


def _attempt_status(
    shadow_meta: dict[str, Any],
    metrics: dict[str, Any],
    *,
    error: str = "",
) -> str:
    if (
        error
        or int(metrics.get("verifier_operation_failure_count") or 0) > 0
        or shadow_meta.get("termination_reason") == "llm_error"
    ):
        return "failed"
    runtime = dict(shadow_meta.get("verifier_runtime") or {})
    budget = dict(shadow_meta.get("verifier_budget") or {})
    if (
        shadow_meta.get("accounting_status") != "complete"
        or runtime.get("enabled") is True
        and (
            metrics.get("verifier_usage_complete") is not True
            or metrics.get("no_ledger_baseline_lineage_match") is not True
            or budget.get("denied") is True
        )
    ):
        return "incomplete"
    return "complete"


def _shadow_verifier_attempt_recovery(
    root: Path,
    *,
    catalog_meta: dict[str, Any],
    shadow_meta: dict[str, Any],
    metrics: dict[str, Any],
    run_id: str,
    requirements_sha256: str,
) -> dict[str, Any]:
    context = _VERIFIER_ATTEMPT_CONTEXT.get()
    if context is not None and context.get("root") != root:
        raise ClaimArtifactError("verifier attempt scope belongs to another output directory")
    attempt_kind = str((context or {}).get("attempt_kind") or "cold")
    request_id = str((context or {}).get("attempt_request_id") or run_id)
    if request_id != str(run_id):
        raise ClaimArtifactError("verifier attempt request differs from generation run")
    requirements_meta = _requirements_attempt_metadata(root)
    requirements_request_id = str(
        (context or {}).get("requirements_request_id")
        or requirements_meta.get("run_id")
        or run_id
    )
    metadata_request_id = str(requirements_meta.get("run_id") or "")
    if metadata_request_id and requirements_request_id != metadata_request_id:
        raise ClaimArtifactError("verifier attempt requirements request differs from metadata")
    baseline = dict(requirements_meta.get("no_ledger_baseline_cost") or {})
    runtime = dict(shadow_meta.get("verifier_runtime") or {})
    document_generation_id = str(catalog_meta.get("document_generation_id") or "")
    target_generation_id = str(shadow_meta.get("target_generation_id") or "")
    chain_identity = {
        "root_attempt_request_id": _attempt_chain_root_request_id(
            root,
            attempt_kind=attempt_kind,
            attempt_request_id=request_id,
            reuse_attempt_id=(context or {}).get("reuse_attempt_id"),
        ),
        "requirements_request_id": requirements_request_id,
        "document_generation_id": document_generation_id,
        "requirements_sha256": str(requirements_sha256),
    }
    attempt_policy_identity = {
        "target_generation_id": target_generation_id,
        "verifier_runtime_fingerprint": str(runtime.get("fingerprint") or ""),
        "baseline_lineage_version": str(baseline.get("lineage_version") or ""),
        "baseline_lineage_fingerprint": str(baseline.get("lineage_fingerprint") or ""),
        "baseline_lineage_match": metrics.get("no_ledger_baseline_lineage_match") is True,
        "cost_policy_version": str(
            dict(shadow_meta.get("versions") or {}).get("cost_policy")
            or runtime.get("cost_policy_version")
            or ""
        ),
    }
    source_locator = _attempt_source_locator(
        attempt_kind=attempt_kind,
        attempt_request_id=request_id,
        requirements_request_id=requirements_request_id,
        catalog_generation_id=str(catalog_meta.get("catalog_generation_id") or ""),
        document_generation_id=document_generation_id,
        target_generation_id=target_generation_id,
        requirements_sha256=str(requirements_sha256),
        reuse_generation_run_id=(context or {}).get("reuse_generation_run_id"),
        reuse_attempt_id=(context or {}).get("reuse_attempt_id"),
    )
    return {
        "attempt_kind": attempt_kind,
        "attempt_status": _attempt_status(shadow_meta, metrics),
        "chain_identity": chain_identity,
        "attempt_policy_identity": attempt_policy_identity,
        "source_locator": source_locator,
        "attempt_metrics": _normalize_attempt_metrics(metrics),
    }


def _append_shadow_verifier_attempt_unlocked(
    root: Path,
    *,
    recovery: dict[str, Any],
) -> dict[str, Any]:
    binding = _append_claim_verifier_attempt_unlocked(
        root,
        attempt_kind=str(recovery["attempt_kind"]),
        attempt_status=str(recovery["attempt_status"]),
        chain_identity=dict(recovery["chain_identity"]),
        attempt_policy_identity=dict(recovery["attempt_policy_identity"]),
        source_locator=dict(recovery["source_locator"]),
        attempt_metrics=dict(recovery["attempt_metrics"]),
    )
    context = _VERIFIER_ATTEMPT_CONTEXT.get()
    if context is not None:
        context["recorded_attempt_id"] = binding["attempt_id"]
    return binding


def _scope_attempt_metrics(
    context: dict[str, Any],
    *,
    operation_failure_count: int,
) -> dict[str, Any]:
    failure = dict(context.get("failure_context") or {})
    runtime = dict(failure.get("verifier_runtime") or {})
    budget = failure.get("verifier_budget")
    snapshot = budget.snapshot() if hasattr(budget, "snapshot") else {}
    reused = max(0, int(failure.get("reused_group_count") or 0))
    candidates = max(reused, int(failure.get("candidate_group_count") or reused))
    reserved_tokens = max(0, int(snapshot.get("reserved_tokens") or 0))
    return _normalize_attempt_metrics({
        "verifier_call_count": int(snapshot.get("attempted_calls") or 0),
        "verifier_failed_call_count": int(snapshot.get("failed_calls") or 0),
        "verifier_operation_failure_count": max(0, int(operation_failure_count)),
        "verifier_tokens": int(snapshot.get("tokens") or 0) + reserved_tokens,
        "verifier_usage_complete": (
            snapshot.get("usage_complete") is True and reserved_tokens == 0
            if snapshot
            else runtime.get("enabled") is not True
        ),
        "semantic_validation_reused_group_count": reused,
        "semantic_verifier_candidate_count": candidates,
    })


def _scope_attempt_recovery(
    root: Path,
    context: dict[str, Any],
    *,
    attempt_status: str,
    operation_failure_count: int,
) -> dict[str, Any]:
    failure = dict(context.get("failure_context") or {})
    catalog_meta = dict(dict(failure.get("catalog_build") or {}).get("meta") or {})
    runtime = dict(failure.get("verifier_runtime") or {})
    baseline = dict(failure.get("baseline_cost") or {})
    document_generation_id = str(catalog_meta.get("document_generation_id") or "")
    target_generation_id = str(failure.get("target_generation_id") or "")
    attempt_kind = str(context["attempt_kind"])
    attempt_request_id = str(context["attempt_request_id"])
    chain_identity = {
        "root_attempt_request_id": _attempt_chain_root_request_id(
            root,
            attempt_kind=attempt_kind,
            attempt_request_id=attempt_request_id,
            reuse_attempt_id=context.get("reuse_attempt_id"),
        ),
        "requirements_request_id": str(context["requirements_request_id"]),
        "document_generation_id": document_generation_id,
        "requirements_sha256": str(failure.get("requirements_sha256") or ""),
    }
    attempt_policy_identity = {
        "target_generation_id": target_generation_id,
        "verifier_runtime_fingerprint": str(runtime.get("fingerprint") or ""),
        "baseline_lineage_version": str(baseline.get("lineage_version") or ""),
        "baseline_lineage_fingerprint": str(
            baseline.get("lineage_fingerprint") or ""
        ),
        "baseline_lineage_match": baseline.get("lineage_match") is True,
        "cost_policy_version": str(runtime.get("cost_policy_version") or ""),
    }
    source_locator = _attempt_source_locator(
        attempt_kind=attempt_kind,
        attempt_request_id=attempt_request_id,
        requirements_request_id=str(context["requirements_request_id"]),
        catalog_generation_id=str(catalog_meta.get("catalog_generation_id") or ""),
        document_generation_id=document_generation_id,
        target_generation_id=target_generation_id,
        requirements_sha256=str(failure.get("requirements_sha256") or ""),
        reuse_generation_run_id=context.get("reuse_generation_run_id"),
        reuse_attempt_id=context.get("reuse_attempt_id"),
    )
    return {
        "attempt_kind": attempt_kind,
        "attempt_status": attempt_status,
        "chain_identity": chain_identity,
        "attempt_policy_identity": attempt_policy_identity,
        "source_locator": source_locator,
        "attempt_metrics": _scope_attempt_metrics(
            context,
            operation_failure_count=operation_failure_count,
        ),
    }


def _record_failed_attempt_from_scope(
    root: Path,
    context: dict[str, Any],
    exc: BaseException,
) -> None:
    if not context.get("failure_context"):
        return
    with claim_publication_lock(root):
        recovered_budget_snapshot = _recover_budget_checkpoint_outbox_unlocked(root)
        recovered = _recover_interrupted_publication_unlocked(root)
        if recovered is not None:
            context["recorded_attempt_id"] = recovered["attempt_id"]
            return
        checkpoint_path = claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)
        if checkpoint_path.is_file():
            budget = dict(context["failure_context"]).get("verifier_budget")
            budget_snapshot = recovered_budget_snapshot
            if budget_snapshot is None and hasattr(budget, "snapshot"):
                budget_snapshot = budget.snapshot()
            if budget_snapshot is not None:
                _update_verifier_attempt_checkpoint_unlocked(
                    root,
                    nonce=str(context.get("checkpoint_nonce") or ""),
                    budget_snapshot=budget_snapshot,
                )
            binding = _finalize_verifier_attempt_checkpoint_unlocked(
                root,
                nonce=str(context.get("checkpoint_nonce") or ""),
                error=f"{type(exc).__name__}:{exc}",
            )
            if binding is not None:
                context["recorded_attempt_id"] = binding["attempt_id"]
            return
        recorded_attempt_id = context.get("recorded_attempt_id")
        if recorded_attempt_id:
            return
        recovery = _scope_attempt_recovery(
            root,
            context,
            attempt_status="failed",
            operation_failure_count=1,
        )
        binding = _append_claim_verifier_attempt_unlocked(
            root,
            attempt_kind=str(recovery["attempt_kind"]),
            attempt_status="failed",
            chain_identity=dict(recovery["chain_identity"]),
            attempt_policy_identity=dict(recovery["attempt_policy_identity"]),
            source_locator=dict(recovery["source_locator"]),
            attempt_metrics=dict(recovery["attempt_metrics"]),
            error=f"{type(exc).__name__}:{exc}",
        )
    context["recorded_attempt_id"] = binding["attempt_id"]


@contextmanager
def claim_verifier_attempt_scope(
    out_dir: Path | str,
    *,
    attempt_kind: str,
    attempt_request_id: str,
    requirements_request_id: str,
    reuse_generation_run_id: str | None = None,
    reuse_attempt_id: str | None = None,
    failure_context: dict[str, Any] | None = None,
):
    """Attach attempt provenance to the next shadow publication in this context."""
    root = Path(out_dir).expanduser().resolve()
    context = {
        "root": root,
        "attempt_kind": str(attempt_kind),
        "attempt_request_id": str(attempt_request_id),
        "requirements_request_id": str(requirements_request_id),
        "reuse_generation_run_id": reuse_generation_run_id,
        "reuse_attempt_id": reuse_attempt_id,
        "failure_context": dict(failure_context or {}),
        "recorded_attempt_id": None,
        "checkpoint_nonce": None,
        "checkpoint_registered": False,
        "budget_checkpoint_attached": False,
        "budget_checkpoint_atomic_swap": False,
        "budget_checkpoint_owner": None,
        "previous_budget_checkpoint": None,
    }
    token = _VERIFIER_ATTEMPT_CONTEXT.set(context)
    budget = context["failure_context"].get("verifier_budget")
    try:
        if context["failure_context"]:
            with claim_publication_lock(root):
                _recover_claim_state_unlocked(root)
                recovery = _scope_attempt_recovery(
                    root,
                    context,
                    attempt_status="incomplete",
                    operation_failure_count=0,
                )
                checkpoint = _begin_verifier_attempt_checkpoint_unlocked(
                    root,
                    run_id=str(attempt_request_id),
                    attempt_recovery=recovery,
                )
                context["checkpoint_nonce"] = str(
                    dict(checkpoint["owner"])["nonce"]
                )
                _register_active_verifier_checkpoint(
                    root,
                    str(context["checkpoint_nonce"]),
                )
                context["checkpoint_registered"] = True
            if hasattr(budget, "set_checkpoint"):
                # Preserve the queue owner across the verifier stage. Production
                # owners expose a serializable queue event, allowing the outbox
                # below to project one snapshot to both durable accounting logs.
                previous_checkpoint = (
                    budget.checkpoint() if hasattr(budget, "checkpoint") else None
                )
                swap_checkpoint = getattr(budget, "swap_checkpoint", None)
                if previous_checkpoint is not None and not callable(swap_checkpoint):
                    # set_checkpoint rejects replacing one non-null owner with
                    # another; persist_budget takes ownership temporarily.
                    budget.set_checkpoint(None)

                def persist_budget(snapshot: dict[str, Any]) -> None:
                    with claim_publication_lock(root):
                        prepare_fanout = getattr(
                            previous_checkpoint,
                            "prepare_fanout_event",
                            None,
                        )
                        if callable(prepare_fanout):
                            transaction_id = uuid.uuid4().hex
                            queue_event = prepare_fanout(
                                snapshot,
                                transaction_id,
                            )
                            if queue_event is not None:
                                outbox_path = claim_artifact_path(root, CLAIM_BUDGET_CHECKPOINT_OUTBOX)
                                outbox_preexisted = outbox_path.exists()
                                try:
                                    _write_budget_checkpoint_outbox_unlocked(
                                        root,
                                        transaction_id=transaction_id,
                                        verifier_nonce=str(context["checkpoint_nonce"]),
                                        budget_snapshot=snapshot,
                                        queue_event=queue_event,
                                    )
                                    _recover_budget_checkpoint_outbox_unlocked(root)
                                except BaseException as exc:
                                    if (
                                        not outbox_preexisted
                                        and outbox_path.is_file()
                                    ):
                                        from llm_client import (
                                            mark_budget_checkpoint_durable,
                                        )

                                        mark_budget_checkpoint_durable(exc)
                                    raise
                                return
                        _update_verifier_attempt_checkpoint_unlocked(
                            root,
                            nonce=str(context["checkpoint_nonce"]),
                            budget_snapshot=snapshot,
                        )
                    if previous_checkpoint is not None:
                        previous_checkpoint(snapshot)

                if callable(swap_checkpoint):
                    swap_checkpoint(previous_checkpoint, persist_budget)
                    context["budget_checkpoint_atomic_swap"] = True
                else:
                    budget.set_checkpoint(persist_budget)
                context["budget_checkpoint_attached"] = True
                context["budget_checkpoint_owner"] = persist_budget
                context["previous_budget_checkpoint"] = previous_checkpoint
        yield
        if (
            context["failure_context"]
            and (claim_artifact_path(root, CLAIM_VERIFIER_ATTEMPT_CHECKPOINT)).is_file()
        ):
            raise ClaimArtifactError(
                "verifier attempt scope exited without publishing its checkpoint"
            )
    except BaseException as exc:
        if context["failure_context"]:
            try:
                _record_failed_attempt_from_scope(root, context, exc)
            except Exception as record_exc:
                raise ClaimArtifactError(
                    "failed to persist verifier attempt failure"
                ) from record_exc
        raise
    finally:
        try:
            if (
                context["budget_checkpoint_attached"]
                and hasattr(budget, "set_checkpoint")
            ):
                previous_checkpoint = context.get("previous_budget_checkpoint")
                if context.get("budget_checkpoint_atomic_swap"):
                    budget.swap_checkpoint(
                        context.get("budget_checkpoint_owner"),
                        previous_checkpoint,
                    )
                else:
                    # Compatibility path for injected budget doubles that only
                    # implement the original set_checkpoint protocol.
                    budget.set_checkpoint(None)
                    if previous_checkpoint is not None:
                        budget.set_checkpoint(previous_checkpoint)
        finally:
            if context["checkpoint_registered"]:
                _unregister_active_verifier_checkpoint(
                    root,
                    str(context["checkpoint_nonce"]),
                )
            _VERIFIER_ATTEMPT_CONTEXT.reset(token)


def publish_catalog_probe(out_dir: Path | str, build: dict[str, Any]) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        if (claim_artifact_path(root, CLAIM_GENERATION_META)).is_file():
            raise ClaimArtifactError(
                "catalog probe cannot replace an existing claim generation"
            )
        return _publish_catalog_probe_unlocked(root, build)


def _publish_catalog_probe_unlocked(out_dir: Path | str, build: dict[str, Any]) -> dict[str, Any]:
    """Publish a catalog probe; the catalog meta file is its commit pointer."""
    root = Path(out_dir).expanduser().resolve()
    catalog = list(build.get("catalog") or [])
    units = list(build.get("units") or [])
    build_meta = dict(build.get("meta") or {})
    atomic_write_jsonl(claim_artifact_path(root, CLAIM_CATALOG), catalog)
    catalog_hash = file_sha256(claim_artifact_path(root, CLAIM_CATALOG))
    meta = {
        "schema": "claim-catalog-probe-meta/v1",
        "artifact_protocol_version": CLAIM_ARTIFACT_PROTOCOL_VERSION,
        "published_at": _utc_now(),
        "document_generation_id": str(build_meta.get("document_generation_id") or ""),
        "catalog_generation_id": str(build_meta.get("catalog_generation_id") or ""),
        "catalog_sha256": catalog_hash,
        "catalog_count": len(catalog),
        "units": units,
        "catalog_meta": build_meta,
    }
    atomic_write_json(claim_artifact_path(root, CLAIM_CATALOG_META), meta)
    return meta


def load_catalog_probe(out_dir: Path | str) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        return _load_catalog_probe_unlocked(root)


def _load_catalog_probe_unlocked(root: Path) -> dict[str, Any]:
    committed = _read_json(claim_artifact_path(root, CLAIM_CATALOG_META), label="catalog commit meta")
    if committed.get("schema") != "claim-catalog-probe-meta/v1":
        raise ClaimArtifactError("unsupported catalog commit meta schema")
    if committed.get("artifact_protocol_version") != CLAIM_ARTIFACT_PROTOCOL_VERSION:
        raise ClaimArtifactError("stale catalog artifact protocol")
    _require_hash(
        claim_artifact_path(root, CLAIM_CATALOG),
        committed.get("catalog_sha256"),
        label=CLAIM_CATALOG,
    )
    catalog = _read_jsonl(claim_artifact_path(root, CLAIM_CATALOG), label="claim catalog")
    if len(catalog) != int(committed.get("catalog_count", -1)):
        raise ClaimArtifactError("claim catalog count does not match committed meta")
    meta = dict(committed.get("catalog_meta") or {})
    generation = str(committed.get("catalog_generation_id") or "")
    if generation != str(meta.get("catalog_generation_id") or ""):
        raise ClaimArtifactError("catalog generation does not match committed meta")
    if any(str(row.get("catalog_generation_id") or "") != generation for row in catalog):
        raise ClaimArtifactError("claim catalog contains a mixed generation")
    units = committed.get("units")
    if not isinstance(units, list):
        raise ClaimArtifactError("invalid catalog owner units")
    return {"catalog": catalog, "units": units, "meta": meta}


def _validate_shadow_graph(
    *,
    catalog_meta: dict[str, Any],
    shadow_meta: dict[str, Any],
    catalog: list[dict[str, Any]],
    units: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    requirements: list[dict[str, Any]] | None,
    review_states: dict[str, dict[str, Any]] | None,
    validate_review_authority: bool = True,
) -> None:
    catalog_generation = str(catalog_meta.get("catalog_generation_id") or "")
    document_generation = str(catalog_meta.get("document_generation_id") or "")
    target_generation = str(shadow_meta.get("target_generation_id") or "")
    target_kind = str(shadow_meta.get("target_kind") or "")
    from claim_ledger import (
        b_track_coverage_targets,
        coverage_group_record_error,
        reduce_claim,
        semantic_negative_record_error,
    )

    target_records = (
        b_track_coverage_targets(requirements, review_states or {})
        if requirements is not None and validate_review_authority else None
    )

    catalog_by_id: dict[str, dict[str, Any]] = {}
    for row in catalog:
        claim_id = str(row.get("claim_id") or "")
        if not claim_id or claim_id in catalog_by_id:
            raise ClaimArtifactError("claim catalog contains a missing or duplicate claim ID")
        if str(row.get("catalog_generation_id") or "") != catalog_generation:
            raise ClaimArtifactError("claim catalog contains a mixed generation")
        if str(row.get("document_generation_id") or "") != document_generation:
            raise ClaimArtifactError("claim catalog contains a mixed document generation")
        catalog_by_id[claim_id] = row

    unit_by_id: dict[str, dict[str, Any]] = {}
    for unit in units:
        unit_id = str(unit.get("unit_id") or "")
        if not unit_id or unit_id in unit_by_id:
            raise ClaimArtifactError("claim units contain a missing or duplicate unit ID")
        unit_by_id[unit_id] = unit

    group_by_id: dict[str, dict[str, Any]] = {}
    edge_ids: set[str] = set()
    group_ids_by_claim: dict[str, list[str]] = {}
    groups_by_claim: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        group_id = str(group.get("coverage_group_id") or "")
        claim_id = str(group.get("claim_id") or "")
        claim = catalog_by_id.get(claim_id)
        if not group_id or group_id in group_by_id:
            raise ClaimArtifactError("coverage groups contain a missing or duplicate group ID")
        if claim is None:
            raise ClaimArtifactError("coverage group refers to a claim outside the catalog")
        if str(group.get("claim_hash") or "") != str(claim.get("claim_hash") or ""):
            raise ClaimArtifactError("coverage group claim hash differs from the catalog")
        if (str(group.get("catalog_generation_id") or "") != catalog_generation
                or str(group.get("document_generation_id") or "") != document_generation):
            raise ClaimArtifactError("coverage group refers to a different source generation")
        group_error = coverage_group_record_error(
            group,
            claim,
            target_records=target_records,
            target_generation_id=target_generation,
            verifier_runtime_fingerprint=str(
                dict(shadow_meta.get("verifier_runtime") or {}).get("fingerprint") or ""
            ),
        )
        if group_error:
            raise ClaimArtifactError(
                f"coverage group is not a deterministic replay: {group_error}"
            )
        edges = group.get("edges")
        if not isinstance(edges, list) or not edges:
            raise ClaimArtifactError("coverage group has no target edges")
        for edge in edges:
            if not isinstance(edge, dict):
                raise ClaimArtifactError("coverage group contains an invalid edge")
            edge_id = str(edge.get("edge_id") or "")
            if not edge_id or edge_id in edge_ids:
                raise ClaimArtifactError("coverage graph contains a missing or duplicate edge ID")
            edge_ids.add(edge_id)
            if str(edge.get("target_generation_id") or "") != target_generation:
                raise ClaimArtifactError("coverage edge refers to a different target generation")
            if str(edge.get("target_kind") or "") != target_kind:
                raise ClaimArtifactError("coverage edge uses the wrong target adapter")
        group_by_id[group_id] = group
        group_ids_by_claim.setdefault(claim_id, []).append(group_id)
        groups_by_claim.setdefault(claim_id, []).append(group)

    if len(ledger) != len(catalog):
        raise ClaimArtifactError("base ledger must contain exactly one row per catalog claim")
    seen_ledger_ids: set[str] = set()
    referenced_groups: set[str] = set()
    for index, row in enumerate(ledger):
        claim_id = str(row.get("claim_id") or "")
        claim = catalog_by_id.get(claim_id)
        if claim is None or claim_id in seen_ledger_ids:
            raise ClaimArtifactError("base ledger is not a one-to-one catalog projection")
        seen_ledger_ids.add(claim_id)
        if claim_id != str(catalog[index].get("claim_id") or ""):
            raise ClaimArtifactError("base ledger order differs from the catalog")
        if str(row.get("claim_hash") or "") != str(claim.get("claim_hash") or ""):
            raise ClaimArtifactError("base ledger claim hash differs from the catalog")
        if str(row.get("document_generation_id") or "") != document_generation:
            raise ClaimArtifactError("base ledger contains a mixed document generation")
        if str(row.get("catalog_generation_id") or "") != catalog_generation:
            raise ClaimArtifactError("base ledger contains a mixed catalog generation")
        if row.get("owner_unit_id") != claim.get("owner_unit_id"):
            raise ClaimArtifactError("base ledger owner differs from the catalog")
        row_group_ids = [str(value or "") for value in (row.get("coverage_group_ids") or [])]
        if len(row_group_ids) != len(set(row_group_ids)) or any(not value for value in row_group_ids):
            raise ClaimArtifactError("base ledger contains duplicate or empty coverage group references")
        if set(row_group_ids) != set(group_ids_by_claim.get(claim_id, [])):
            raise ClaimArtifactError("base ledger coverage group references are incomplete or foreign")
        referenced_groups.update(row_group_ids)

        negative = row.get("semantic_negative")
        if negative is not None:
            unit = unit_by_id.get(str(claim.get("owner_unit_id") or ""))
            error = semantic_negative_record_error(
                negative,
                claim,
                unit,
                dict(shadow_meta.get("verifier_runtime") or {}),
            )
            if error:
                raise ClaimArtifactError(f"semantic negative is stale or foreign: {error}")
            if shadow_meta.get("semantic_negative_proposer_enabled") is not True:
                raise ClaimArtifactError("semantic negative has no declared proposer runtime")
            if (
                negative.get("status") == "validated"
                and shadow_meta.get("semantic_negative_verifier_enabled") is not True
            ):
                raise ClaimArtifactError("validated semantic negative has no verifier runtime")
        claim_groups = groups_by_claim.get(claim_id, [])
        expected_row = reduce_claim(
            claim,
            validated_groups=[
                group for group in claim_groups if group.get("status") == "validated"
            ],
            validated_negative=negative,
            all_groups=claim_groups,
        )
        if row != expected_row:
            raise ClaimArtifactError("base ledger row differs from deterministic reduction")
    if referenced_groups != set(group_by_id):
        raise ClaimArtifactError("coverage groups are not fully referenced by the base ledger")

    if requirements is not None:
        from ai_review_actions import source_ai_requirement_id
        from claim_ledger import evidence_is_current, target_fingerprint

        targets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for requirement in requirements:
            key = (source_ai_requirement_id(requirement), target_fingerprint(requirement))
            targets.setdefault(key, []).append(requirement)
        for group in groups:
            for edge in group.get("edges") or []:
                key = (
                    str(edge.get("target_requirement_id") or ""),
                    str(edge.get("target_fingerprint") or ""),
                )
                matches = targets.get(key, [])
                if len(matches) != 1:
                    raise ClaimArtifactError("coverage edge target is missing or ambiguous")
                if not all(evidence_is_current(item, matches[0])
                           for item in (edge.get("produced_evidence") or [])):
                    raise ClaimArtifactError("coverage edge evidence is stale or not locatable")


def publish_shadow_generation(
    out_dir: Path | str,
    catalog_build: dict[str, Any],
    shadow_result: dict[str, Any],
    *,
    run_id: str,
    requirements_sha256: str = "",
) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        active_checkpoint_nonce = _active_verifier_checkpoint_nonce(root)
        _recover_claim_state_unlocked(
            root,
            allow_live_checkpoint_nonce=active_checkpoint_nonce,
        )
        try:
            return _publish_shadow_generation_unlocked(
                root,
                catalog_build,
                shadow_result,
                run_id=run_id,
                requirements_sha256=requirements_sha256,
            )
        except BaseException:
            try:
                binding = _recover_claim_state_unlocked(
                    root,
                    allow_live_checkpoint_nonce=active_checkpoint_nonce,
                )
                context = _VERIFIER_ATTEMPT_CONTEXT.get()
                if (
                    binding is not None
                    and context is not None
                    and context.get("root") == root
                    and dict(binding.get("source_locator") or {}).get(
                        "attempt_request_id"
                    ) == str(run_id)
                ):
                    context["recorded_attempt_id"] = binding["attempt_id"]
            except BaseException as restore_exc:
                raise ClaimArtifactError(
                    "failed to restore the prior committed claim snapshot"
                ) from restore_exc
            raise


def _publish_shadow_generation_unlocked(
    out_dir: Path | str,
    catalog_build: dict[str, Any],
    shadow_result: dict[str, Any],
    *,
    run_id: str,
    requirements_sha256: str = "",
) -> dict[str, Any]:
    """Publish an immutable base generation and its Phase 0 effective snapshot."""
    root = Path(out_dir).expanduser().resolve()
    catalog_meta = dict(catalog_build.get("meta") or {})
    shadow_meta = dict(shadow_result.get("meta") or {})
    catalog = list(catalog_build.get("catalog") or [])
    groups = list(shadow_result.get("groups") or [])
    ledger = list(shadow_result.get("ledger") or [])
    metrics = dict(shadow_result.get("metrics") or {})

    if shadow_result.get("catalog") is not None and list(shadow_result.get("catalog") or []) != catalog:
        raise ClaimArtifactError("shadow result catalog differs from the catalog generation")
    if len(ledger) != len(catalog):
        raise ClaimArtifactError("base ledger must contain exactly one row per catalog claim")
    catalog_generation = str(catalog_meta.get("catalog_generation_id") or "")
    if catalog_generation != str(shadow_meta.get("catalog_generation_id") or ""):
        raise ClaimArtifactError("shadow result and catalog generation do not match")
    if not _shadow_meta_is_well_formed(shadow_meta):
        raise ClaimArtifactError("invalid shadow result meta")
    if not _shadow_cost_metrics_are_well_formed(metrics):
        raise ClaimArtifactError("invalid shadow verifier cost metrics")
    if not _shadow_budget_matches_metrics(shadow_meta, metrics):
        raise ClaimArtifactError("shadow verifier budget differs from its metrics")
    requirements_meta = _requirements_attempt_metadata(root)
    if not _shadow_baseline_matches_requirements_metadata(
        metrics,
        requirements_meta,
    ):
        raise ClaimArtifactError(
            "shadow no-ledger baseline accounting differs from requirements metadata"
        )

    requirements: list[dict[str, Any]] | None = None
    review_states: dict[str, dict[str, Any]] = {}
    if shadow_meta.get("delivery_track") == "B":
        if not requirements_sha256:
            raise ClaimArtifactError("B-track claim generation must bind ai_requirements.jsonl")
        _require_hash(
            root / "ai_requirements.jsonl",
            requirements_sha256,
            label="ai_requirements.jsonl",
        )
        requirements = _read_jsonl(root / "ai_requirements.jsonl", label="AI requirements")
        from ai_review_actions import read_ai_review_states
        from claim_ledger import b_track_authority_state

        review_states = read_ai_review_states(root)
        authority = b_track_authority_state(requirements, review_states)
        if authority["target_generation_id"] != str(shadow_meta.get("target_generation_id") or ""):
            raise ClaimArtifactError("shadow target generation differs from bound requirements")
        if authority["target_review_authority_revision"] != str(
            shadow_meta.get("target_review_authority_revision") or ""
        ):
            raise ClaimArtifactError("shadow review authority differs from the current B-track state")

    _validate_shadow_graph(
        catalog_meta=catalog_meta,
        shadow_meta=shadow_meta,
        catalog=catalog,
        units=list(catalog_build.get("units") or []),
        groups=groups,
        ledger=ledger,
        requirements=requirements,
        review_states=review_states,
    )

    attempt_recovery = _shadow_verifier_attempt_recovery(
        root,
        catalog_meta=catalog_meta,
        shadow_meta=shadow_meta,
        metrics=metrics,
        run_id=run_id,
        requirements_sha256=requirements_sha256,
    )
    publication = _begin_claim_publication_unlocked(
        root,
        run_id=run_id,
        attempt_recovery=attempt_recovery,
    )

    catalog_commit = _publish_catalog_probe_unlocked(root, catalog_build)
    atomic_write_jsonl(claim_artifact_path(root, CLAIM_COVERAGE_GROUPS), groups)
    atomic_write_jsonl(claim_artifact_path(root, CLAIM_LEDGER), ledger)
    atomic_write_json(claim_artifact_path(root, CLAIM_SHADOW_METRICS), metrics)
    attempt_binding = _append_shadow_verifier_attempt_unlocked(
        root,
        recovery=attempt_recovery,
    )

    requirements_producer_lineage: dict[str, Any] | None = None
    requirements_meta_path = root / "ai_requirements.meta.json"
    if requirements_meta_path.is_file():
        requirements_meta_payload = _read_json(
            requirements_meta_path,
            label="AI requirements meta",
        )
        producer_lineage = requirements_meta_payload.get("producer_lineage")
        if isinstance(producer_lineage, dict):
            requirements_producer_lineage = dict(producer_lineage)

    # 含表块的当前版本目录必须带 canonical cell 产物——缺失即哈希绑定空洞，
    # 拒绝提交（base 一旦没有 cell 绑定，篡改/删除 cell 产物将无法检出）
    if _catalog_meta_requires_cell_binding(catalog_meta) and not (
        root / "table_cell_items.jsonl"
    ).is_file():
        raise ClaimArtifactError(
            "table cell items artifact missing for current table structure catalog"
        )

    generation_meta = {
        "schema": "claim-generation-meta/v1",
        "artifact_protocol_version": CLAIM_ARTIFACT_PROTOCOL_VERSION,
        "run_id": str(run_id),
        "committed_at": _utc_now(),
        "document_generation_id": str(catalog_meta.get("document_generation_id") or ""),
        "catalog_generation_id": catalog_generation,
        "structural_override_version": str(
            catalog_meta.get("structural_override_version") or ""
        ),
        "structural_override_prefix_sha256": str(
            catalog_meta.get("structural_override_prefix_sha256") or ""
        ),
        "structural_override_prefix_count": int(
            catalog_meta.get("structural_override_prefix_count") or 0
        ),
        "structural_override_applied_count": int(
            catalog_meta.get("structural_override_applied_count") or 0
        ),
        "target_generation_id": str(shadow_meta.get("target_generation_id") or ""),
        "target_review_authority_revision": str(
            shadow_meta.get("target_review_authority_revision") or ""
        ),
        "delivery_track": str(shadow_meta.get("delivery_track") or "B"),
        "target_kind": str(shadow_meta.get("target_kind") or "ai_requirement"),
        "requirements_sha256": str(requirements_sha256 or ""),
        "requirements_meta_sha256": (
            file_sha256(requirements_meta_path)
            if requirements_meta_path.is_file()
            else ""
        ),
        "requirements_producer_lineage": requirements_producer_lineage,
        "blocks_file_sha256": (
            file_sha256(root / "blocks.jsonl") if (root / "blocks.jsonl").is_file() else ""
        ),
        "table_items_file_sha256": (
            file_sha256(root / "table_items.jsonl")
            if (root / "table_items.jsonl").is_file()
            else ""
        ),
        "table_cell_items_file_sha256": (
            file_sha256(root / "table_cell_items.jsonl")
            if (root / "table_cell_items.jsonl").is_file()
            else ""
        ),
        "catalog_sha256": str(catalog_commit["catalog_sha256"]),
        "catalog_meta_sha256": file_sha256(claim_artifact_path(root, CLAIM_CATALOG_META)),
        "coverage_groups_sha256": file_sha256(claim_artifact_path(root, CLAIM_COVERAGE_GROUPS)),
        "ledger_sha256": file_sha256(claim_artifact_path(root, CLAIM_LEDGER)),
        "shadow_metrics_sha256": file_sha256(claim_artifact_path(root, CLAIM_SHADOW_METRICS)),
        "catalog_count": len(catalog),
        "coverage_group_count": len(groups),
        "ledger_count": len(ledger),
        "attempt_chain": attempt_binding,
        "shadow_meta": shadow_meta,
    }
    atomic_write_json(claim_artifact_path(root, CLAIM_GENERATION_META), generation_meta)
    generation_meta_hash = file_sha256(claim_artifact_path(root, CLAIM_GENERATION_META))

    # Claim review events are deliberately disabled in Phase 0, so effective == base.
    atomic_write_jsonl(claim_artifact_path(root, CLAIM_EFFECTIVE_LEDGER), ledger)
    effective_meta = {
        "schema": "claim-effective-meta/v1",
        "artifact_protocol_version": CLAIM_ARTIFACT_PROTOCOL_VERSION,
        "effective_snapshot_version": LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        "run_id": str(run_id),
        "committed_at": _utc_now(),
        "catalog_generation_id": catalog_generation,
        "target_generation_id": str(shadow_meta.get("target_generation_id") or ""),
        "target_review_authority_revision": str(
            shadow_meta.get("target_review_authority_revision") or ""
        ),
        "generation_meta_sha256": generation_meta_hash,
        "base_ledger_sha256": str(generation_meta["ledger_sha256"]),
        "effective_ledger_sha256": file_sha256(claim_artifact_path(root, CLAIM_EFFECTIVE_LEDGER)),
        "claim_event_prefix_sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        "claim_events_enabled": False,
        "ledger_count": len(ledger),
    }
    atomic_write_json(claim_artifact_path(root, CLAIM_EFFECTIVE_META), effective_meta)
    _load_committed_shadow_unlocked(root)
    _finish_claim_publication_unlocked(root, publication)
    return generation_meta


def _validate_committed_attempt_binding(
    root: Path,
    generation: dict[str, Any],
    metrics: dict[str, Any],
    *,
    validate_live_target: bool = True,
) -> list[dict[str, Any]]:
    binding = generation.get("attempt_chain")
    if not isinstance(binding, dict) or set(binding) != _ATTEMPT_BINDING_FIELDS:
        raise ClaimArtifactError("invalid verifier attempt-chain binding")
    if (
        binding.get("schema") != CLAIM_VERIFIER_ATTEMPT_BINDING_SCHEMA
        or binding.get("ledger_file") != CLAIM_VERIFIER_ATTEMPTS
    ):
        raise ClaimArtifactError("unsupported verifier attempt-chain binding")
    rows = _read_claim_verifier_attempts_unlocked(root, allow_missing=False)
    prefix_count = binding.get("ledger_prefix_count")
    if (
        not isinstance(prefix_count, int)
        or isinstance(prefix_count, bool)
        or prefix_count < 1
        or prefix_count > len(rows)
    ):
        raise ClaimArtifactError("verifier attempt ledger prefix count is stale")
    prefix = rows[:prefix_count]
    if binding.get("ledger_prefix_sha256") != _sha256_bytes(_jsonl_bytes(prefix)):
        raise ClaimArtifactError("verifier attempt ledger prefix hash is stale")
    if binding.get("attempt_id") != prefix[-1].get("attempt_id"):
        raise ClaimArtifactError("verifier attempt binding is not the committed prefix tip")
    event = prefix[-1]
    chain_rows = [row for row in prefix if row["chain_id"] == event["chain_id"]]
    latest_chain_rows = _latest_attempt_rows(chain_rows)
    mirrored = {
        "chain_id": event["chain_id"],
        "attempt_id": event["attempt_id"],
        "attempt_count": len(latest_chain_rows),
        "attempt_kind": event["attempt_kind"],
        "attempt_status": event["attempt_status"],
        "source_locator": event["source_locator"],
        "cumulative_metrics": _attempt_cumulative_metrics(latest_chain_rows),
    }
    if any(binding.get(key) != value for key, value in mirrored.items()):
        raise ClaimArtifactError("verifier attempt binding differs from its ledger prefix")

    source = event["source_locator"]
    if source["attempt_request_id"] != generation.get("run_id"):
        raise ClaimArtifactError("verifier attempt request differs from committed generation")
    for source_key, generation_key in (
        ("document_generation_id", "document_generation_id"),
        ("catalog_generation_id", "catalog_generation_id"),
        ("target_generation_id", "target_generation_id"),
        ("requirements_sha256", "requirements_sha256"),
    ):
        if source[source_key] != generation.get(generation_key):
            raise ClaimArtifactError("verifier attempt source lineage is stale")
    identity = event["chain_identity"]
    policy_identity = event["attempt_policy_identity"]
    shadow_meta = dict(generation.get("shadow_meta") or {})
    runtime = dict(shadow_meta.get("verifier_runtime") or {})
    baseline: dict[str, Any] = {}
    if validate_live_target:
        requirements_meta = _requirements_attempt_metadata(root)
        if not _shadow_baseline_matches_requirements_metadata(
            metrics,
            requirements_meta,
        ):
            raise ClaimArtifactError(
                "committed no-ledger baseline accounting differs from requirements metadata"
            )
        metadata_request_id = str(requirements_meta.get("run_id") or "")
        if metadata_request_id and source["requirements_request_id"] != metadata_request_id:
            raise ClaimArtifactError("verifier attempt requirements request is stale")
        baseline = dict(requirements_meta.get("no_ledger_baseline_cost") or {})
    if (
        identity["requirements_request_id"]
        != source["requirements_request_id"]
        or identity["document_generation_id"] != generation.get("document_generation_id")
        or identity["requirements_sha256"] != generation.get("requirements_sha256")
        or policy_identity["target_generation_id"]
        != generation.get("target_generation_id")
        or policy_identity["verifier_runtime_fingerprint"]
        != runtime.get("fingerprint")
        or policy_identity["baseline_lineage_match"]
        is not (metrics.get("no_ledger_baseline_lineage_match") is True)
        or policy_identity["cost_policy_version"]
        != dict(shadow_meta.get("versions") or {}).get("cost_policy")
        or validate_live_target
        and (
            policy_identity["baseline_lineage_version"]
            != str(baseline.get("lineage_version") or "")
            or policy_identity["baseline_lineage_fingerprint"]
            != str(baseline.get("lineage_fingerprint") or "")
        )
    ):
        raise ClaimArtifactError("verifier attempt chain identity is stale")
    return rows


def load_committed_attempt_lineage(out_dir: Path | str) -> dict[str, Any]:
    """Load the committed attempt binding without folding versioned ledger rows."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        return _load_committed_attempt_lineage_unlocked(root)


def _load_committed_attempt_lineage_unlocked(root: Path) -> dict[str, Any]:
    generation = _read_json(claim_artifact_path(root, CLAIM_GENERATION_META), label="claim generation meta")
    if (
        generation.get("schema") != "claim-generation-meta/v1"
        or generation.get("artifact_protocol_version")
        not in {
            CLAIM_ARTIFACT_PROTOCOL_VERSION,
            PREVIOUS_CLAIM_ARTIFACT_PROTOCOL_VERSION,
        }
    ):
        raise ClaimArtifactError("stale claim attempt lineage protocol")
    shadow_meta = dict(generation.get("shadow_meta") or {})
    if not _shadow_meta_has_attempt_lineage(shadow_meta):
        raise ClaimArtifactError("invalid committed shadow result meta")
    _require_hash(
        claim_artifact_path(root, CLAIM_SHADOW_METRICS),
        generation.get("shadow_metrics_sha256"),
        label=CLAIM_SHADOW_METRICS,
    )
    metrics = _read_json(claim_artifact_path(root, CLAIM_SHADOW_METRICS), label="shadow metrics")
    if (
        not _shadow_cost_metrics_are_well_formed(metrics)
        or not _shadow_budget_matches_metrics(shadow_meta, metrics)
    ):
        raise ClaimArtifactError("invalid committed verifier accounting")
    requirements_hash = str(generation.get("requirements_sha256") or "")
    if requirements_hash:
        _require_hash(
            root / "ai_requirements.jsonl",
            requirements_hash,
            label="ai_requirements.jsonl",
        )
    requirements_meta_hash = str(generation.get("requirements_meta_sha256") or "")
    if requirements_meta_hash:
        _require_hash(
            root / "ai_requirements.meta.json",
            requirements_meta_hash,
            label="ai_requirements.meta.json",
        )
    _validate_committed_attempt_binding(root, generation, metrics)
    return {
        "generation_run_id": str(generation.get("run_id") or ""),
        "attempt_chain": dict(generation.get("attempt_chain") or {}),
    }


def bootstrap_legacy_attempt_lineage(out_dir: Path | str) -> dict[str, Any]:
    """Import a validated v4 generation as a cost-incomplete chain root.

    The legacy snapshot proves its final counters, but not whether earlier paid
    retries existed. The imported attempt therefore preserves those counters as
    a lower bound while forcing cumulative usage completeness to false.
    """
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        generation = _read_json(
            claim_artifact_path(root, CLAIM_GENERATION_META),
            label="legacy claim generation meta",
        )
        if (
            generation.get("schema") != "claim-generation-meta/v1"
            or generation.get("artifact_protocol_version")
            != LEGACY_CLAIM_ARTIFACT_PROTOCOL_VERSION
            or "attempt_chain" in generation
        ):
            raise ClaimArtifactError("claim generation is not eligible for v4 bootstrap")

        run_id = str(generation.get("run_id") or "")
        shadow_meta = dict(generation.get("shadow_meta") or {})
        if not run_id or not _shadow_meta_has_attempt_lineage(shadow_meta):
            raise ClaimArtifactError("invalid legacy claim attempt lineage")
        for field in (
            "document_generation_id",
            "catalog_generation_id",
            "target_generation_id",
            "requirements_sha256",
        ):
            if not _is_sha256(generation.get(field)):
                raise ClaimArtifactError("invalid legacy claim generation identity")

        committed_files = {
            CLAIM_CATALOG: generation.get("catalog_sha256"),
            CLAIM_CATALOG_META: generation.get("catalog_meta_sha256"),
            CLAIM_COVERAGE_GROUPS: generation.get("coverage_groups_sha256"),
            CLAIM_LEDGER: generation.get("ledger_sha256"),
            CLAIM_SHADOW_METRICS: generation.get("shadow_metrics_sha256"),
        }
        for name, expected in committed_files.items():
            _require_hash(governed_artifact_path(root, name), expected, label=f"legacy {name}")

        catalog_meta = _read_json(
            claim_artifact_path(root, CLAIM_CATALOG_META),
            label="legacy catalog commit meta",
        )
        if (
            catalog_meta.get("schema") != "claim-catalog-probe-meta/v1"
            or catalog_meta.get("artifact_protocol_version")
            != LEGACY_CLAIM_ARTIFACT_PROTOCOL_VERSION
            or catalog_meta.get("catalog_generation_id")
            != generation.get("catalog_generation_id")
        ):
            raise ClaimArtifactError("invalid legacy catalog commit")
        _require_hash(
            claim_artifact_path(root, CLAIM_CATALOG),
            catalog_meta.get("catalog_sha256"),
            label="legacy claim catalog",
        )
        catalog = _read_jsonl(claim_artifact_path(root, CLAIM_CATALOG), label="legacy claim catalog")
        groups = _read_jsonl(
            claim_artifact_path(root, CLAIM_COVERAGE_GROUPS),
            label="legacy coverage groups",
        )
        ledger = _read_jsonl(claim_artifact_path(root, CLAIM_LEDGER), label="legacy claim ledger")
        if (
            len(catalog) != int(generation.get("catalog_count", -1))
            or len(catalog) != int(catalog_meta.get("catalog_count", -1))
            or len(groups) != int(generation.get("coverage_group_count", -1))
            or len(ledger) != int(generation.get("ledger_count", -1))
        ):
            raise ClaimArtifactError("legacy claim snapshot count mismatch")

        requirements_hash = str(generation["requirements_sha256"])
        _require_hash(
            root / "ai_requirements.jsonl",
            requirements_hash,
            label="legacy ai_requirements.jsonl",
        )
        requirements_meta_hash = str(generation.get("requirements_meta_sha256") or "")
        _require_hash(
            root / "ai_requirements.meta.json",
            requirements_meta_hash,
            label="legacy ai_requirements.meta.json",
        )
        requirements_meta = _read_json(
            root / "ai_requirements.meta.json",
            label="legacy AI requirements meta",
        )
        requirements_request_id = str(requirements_meta.get("run_id") or "")
        if not requirements_request_id:
            raise ClaimArtifactError("legacy requirements request identity is missing")

        metrics = _read_json(
            claim_artifact_path(root, CLAIM_SHADOW_METRICS),
            label="legacy shadow metrics",
        )
        if (
            not _shadow_cost_metrics_are_well_formed(metrics)
            or not _shadow_budget_matches_metrics(shadow_meta, metrics)
            or not _shadow_baseline_matches_requirements_metadata(
                metrics,
                requirements_meta,
            )
        ):
            raise ClaimArtifactError("invalid legacy verifier accounting")

        runtime = dict(shadow_meta.get("verifier_runtime") or {})
        baseline = dict(requirements_meta.get("no_ledger_baseline_cost") or {})
        chain_identity = {
            "root_attempt_request_id": run_id,
            "requirements_request_id": requirements_request_id,
            "document_generation_id": str(generation["document_generation_id"]),
            "requirements_sha256": requirements_hash,
        }
        policy_identity = {
            "target_generation_id": str(generation["target_generation_id"]),
            "verifier_runtime_fingerprint": str(runtime.get("fingerprint") or ""),
            "baseline_lineage_version": str(baseline.get("lineage_version") or ""),
            "baseline_lineage_fingerprint": str(
                baseline.get("lineage_fingerprint") or ""
            ),
            "baseline_lineage_match": (
                metrics.get("no_ledger_baseline_lineage_match") is True
            ),
            "cost_policy_version": str(
                dict(shadow_meta.get("versions") or {}).get("cost_policy") or ""
            ),
        }
        source_locator = _attempt_source_locator(
            attempt_kind="cold",
            attempt_request_id=run_id,
            requirements_request_id=requirements_request_id,
            catalog_generation_id=str(generation["catalog_generation_id"]),
            document_generation_id=str(generation["document_generation_id"]),
            target_generation_id=str(generation["target_generation_id"]),
            requirements_sha256=requirements_hash,
            reuse_generation_run_id=None,
            reuse_attempt_id=None,
        )
        imported_metrics = dict(metrics)
        imported_metrics["verifier_usage_complete"] = False
        binding = _append_claim_verifier_attempt_unlocked(
            root,
            attempt_kind="cold",
            attempt_status="incomplete",
            chain_identity=chain_identity,
            attempt_policy_identity=policy_identity,
            source_locator=source_locator,
            attempt_metrics=imported_metrics,
            error="legacy_v4_import:cumulative_attempt_history_unavailable",
        )
        return {
            "generation_run_id": run_id,
            "attempt_chain": binding,
        }


def load_committed_shadow(out_dir: Path | str) -> dict[str, Any]:
    """Load a committed base generation and its internally consistent effective view."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        return _load_committed_shadow_unlocked(root)


def load_committed_shadow_for_effective_refold(
    out_dir: Path | str,
) -> dict[str, Any]:
    """Load a fully validated snapshot while permitting only stale base versions.

    Structural maintenance can intentionally advance the base authority before
    rebuilding it. Effective revisions and live target/review authority remain
    strict here; callers that need to replace a drifted effective snapshot must
    use :func:`load_committed_effective_refold_seed` and rederive every row.
    """
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        base = _load_committed_claim_base_unlocked(root)
        effective = _load_committed_effective_unlocked(
            root,
            base,
            require_v2=False,
            allow_stale_base_versions=True,
        )
        return {**base, **effective}


def load_committed_effective_refold_seed(
    out_dir: Path | str,
) -> dict[str, Any]:
    """Validate a committed snapshot for refold without exposing untrusted rows.

    A current snapshot is returned as ``trusted_current_snapshot`` only when it
    passes normal revision, authority and version validation. When live
    authority or an effective component version has advanced, the persisted
    payload must still be internally hash/revision consistent, but only its
    migration marker is returned; the fold must derive rows and CAS tokens from
    the immutable base, live authority and committed events.
    """
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        base = _load_committed_claim_base_unlocked(root)
        preview = _read_json(claim_artifact_path(root, CLAIM_EFFECTIVE_META), label="effective claim meta")
        effective_version = str(preview.get("effective_snapshot_version") or "")
        trusted: dict[str, Any] | None = None
        if effective_version == CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
            if effective_versions_are_current({"effective_meta": preview}):
                try:
                    loaded = _load_committed_effective_unlocked(
                        root,
                        base,
                        require_v2=True,
                        allow_stale_base_versions=True,
                    )
                except ClaimEffectiveAuthorityChanged:
                    loaded = _load_committed_effective_unlocked(
                        root,
                        base,
                        require_v2=True,
                        allow_stale_base_versions=True,
                        refold_seed_only=True,
                    )
                else:
                    trusted = {**base, **loaded}
            else:
                loaded = _load_committed_effective_unlocked(
                    root,
                    base,
                    require_v2=True,
                    allow_stale_base_versions=True,
                    refold_seed_only=True,
                )
        else:
            loaded = _load_committed_effective_unlocked(
                root,
                base,
                require_v2=False,
                allow_stale_base_versions=True,
            )
        return {
            "source_effective_meta": dict(loaded["effective_meta"]),
            "trusted_current_snapshot": trusted,
        }


def claim_base_generation_id(generation_meta: dict[str, Any]) -> str:
    fields = {
        "document_generation_id": generation_meta.get("document_generation_id"),
        "catalog_generation_id": generation_meta.get("catalog_generation_id"),
        "catalog_sha256": generation_meta.get("catalog_sha256"),
        "coverage_groups_sha256": generation_meta.get("coverage_groups_sha256"),
        "base_ledger_sha256": generation_meta.get("ledger_sha256"),
    }
    if any(not _is_sha256(value) for value in fields.values()):
        raise ClaimArtifactError("base generation identity is incomplete")
    return hash_json("claim-base-generation/v1", fields)


_EFFECTIVE_BASE_FIELDS = (
    "ledger_schema_version",
    "document_generation_id",
    "catalog_generation_id",
    "claim_id",
    "claim_hash",
    "owner_unit_id",
    "coverage_group_ids",
)


def semantic_negative_id(value: object) -> str | None:
    if not isinstance(value, dict) or value.get("status") != "validated":
        return None
    return hash_json("claim-semantic-negative/v1", value)


def _validate_effective_projection(
    base: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    queue_rows: list[dict[str, Any]],
    *,
    last_event_seq: int,
    queue_version: str,
    event_rows: list[dict[str, Any]],
) -> None:
    from claim_ledger import reduce_claim
    from claim_review_actions import _relevant_events

    base_rows = list(base["ledger"])
    catalog_rows = list(base["catalog"])
    groups = list(base["groups"])
    if len(ledger_rows) != len(base_rows):
        raise ClaimArtifactError("effective ledger must project every base claim")
    if [row.get("claim_id") for row in ledger_rows] != [
        row.get("claim_id") for row in base_rows
    ]:
        raise ClaimArtifactError("effective ledger claim order differs from base")

    catalog_by_id = {str(row.get("claim_id") or ""): row for row in catalog_rows}
    groups_by_claim: dict[str, list[dict[str, Any]]] = {}
    group_by_id: dict[str, dict[str, Any]] = {}
    for group in groups:
        claim_id = str(group.get("claim_id") or "")
        group_id = str(group.get("coverage_group_id") or "")
        groups_by_claim.setdefault(claim_id, []).append(group)
        group_by_id[group_id] = group

    effective_by_id: dict[str, dict[str, Any]] = {}
    for base_row, row in zip(base_rows, ledger_rows, strict=True):
        _validate_schema(
            row,
            "claim_effective_ledger.schema.json",
            label="effective ledger row",
        )
        claim_id = str(row.get("claim_id") or "")
        if claim_id in effective_by_id:
            raise ClaimArtifactError("effective ledger contains a duplicate claim")
        if row.get("base_ledger_schema") != base_row.get("schema"):
            raise ClaimArtifactError("effective row base schema differs from base ledger")
        for field in _EFFECTIVE_BASE_FIELDS:
            if row.get(field) != base_row.get(field):
                raise ClaimArtifactError(
                    f"effective row changed immutable base field: {field}"
                )
        expected_base_hash = hash_json("claim-base-row/v1", base_row)
        if row.get("base_claim_row_hash") != expected_base_hash:
            raise ClaimArtifactError("effective row base hash differs from base ledger")
        row_event_seq = row.get("last_relevant_event_seq")
        if (
            not isinstance(row_event_seq, int)
            or isinstance(row_event_seq, bool)
            or row_event_seq < 0
            or row_event_seq > last_event_seq
        ):
            raise ClaimArtifactError("effective row has an invalid relevant event sequence")
        relevant_events = _relevant_events(event_rows, base_row)
        expected_event_hashes = [
            str(event.get("event_hash") or "") for event in relevant_events
        ]
        revision_inputs = dict(row.get("revision_inputs") or {})
        if list(revision_inputs.get("ordered_relevant_event_hashes") or []) != (
            expected_event_hashes
        ):
            raise ClaimArtifactError(
                "effective row event inputs differ from committed review prefix"
            )
        expected_relevant_seq = (
            int(relevant_events[-1]["event_seq"]) if relevant_events else 0
        )
        if row_event_seq != expected_relevant_seq:
            raise ClaimArtifactError(
                "effective row relevant event sequence differs from committed review prefix"
            )

        facts = dict(row.get("effective_facts") or {})
        base_group_ids = [
            str(value or "") for value in (base_row.get("coverage_group_ids") or [])
        ]
        valid_group_ids = [str(value or "") for value in facts.get("valid_group_ids") or []]
        invalid_reasons = dict(facts.get("invalid_group_reasons") or {})
        reused_group_ids = [
            str(value or "") for value in facts.get("reused_validation_group_ids") or []
        ]
        if not set(valid_group_ids).issubset(base_group_ids):
            raise ClaimArtifactError("effective row validates a foreign coverage group")
        if not set(invalid_reasons).issubset(base_group_ids):
            raise ClaimArtifactError("effective row invalidates a foreign coverage group")
        if set(valid_group_ids).intersection(invalid_reasons):
            raise ClaimArtifactError("effective group is both valid and invalid")
        if set(valid_group_ids).union(invalid_reasons) != set(base_group_ids):
            raise ClaimArtifactError("effective group accounting is incomplete")
        if not set(reused_group_ids).issubset(valid_group_ids):
            raise ClaimArtifactError("reused validation is not currently valid")
        for group_id in valid_group_ids:
            group = group_by_id.get(group_id)
            if group is None or group.get("status") != "validated":
                raise ClaimArtifactError("effective row treats an unvalidated base group as valid")

        claim = catalog_by_id.get(claim_id)
        if claim is None:
            raise ClaimArtifactError("effective row has no catalog claim")
        base_positive_fact_hashes = {
            hash_json(
                "claim-resolution-fact/v1",
                {
                    "kind": "coverage_group",
                    "payload": {
                        "claim_hash": claim.get("claim_hash"),
                        "coverage_group_id": group.get("coverage_group_id"),
                        "coverage_group_hash": hash_json(
                            "claim-coverage-group-fact/v1", group
                        ),
                    },
                },
            )
            for group in groups_by_claim.get(claim_id, [])
            if group.get("status") == "validated"
        }

        base_negative = base_row.get("semantic_negative")
        effective_negative = row.get("semantic_negative")
        base_negative_fact_hashes: set[str] = set()
        if (
            isinstance(base_negative, dict)
            and base_negative.get("status") == "validated"
        ):
            base_negative_fact_hashes.add(hash_json(
                "claim-resolution-fact/v1",
                {
                    "kind": "semantic_negative",
                    "payload": {
                        "claim_hash": claim.get("claim_hash"),
                        "semantic_negative_id": semantic_negative_id(base_negative),
                    },
                },
            ))
        superseded_base_fact_hashes = [
            str(value or "")
            for value in facts.get("superseded_base_fact_hashes") or []
        ]
        if (
            superseded_base_fact_hashes
            != sorted(set(superseded_base_fact_hashes))
            or any(not _is_sha256(value) for value in superseded_base_fact_hashes)
        ):
            raise ClaimArtifactError(
                "effective superseded base fact hashes are not canonical"
            )
        allowed_base_fact_hashes = (
            base_positive_fact_hashes | base_negative_fact_hashes
        )
        superseded_base_facts = set(superseded_base_fact_hashes)
        if not superseded_base_facts.issubset(allowed_base_fact_hashes):
            raise ClaimArtifactError(
                "effective row supersedes a fact outside the current base"
            )
        if (
            "positive_negative_conflict" in (base_row.get("invalid_reasons") or [])
            and row.get("resolution") in {"covered", "excluded"}
            and not allowed_base_fact_hashes.issubset(superseded_base_facts)
        ):
            raise ClaimArtifactError(
                "effective row closes a conflicting base without superseding both fact sides"
            )
        if effective_negative != base_negative:
            if effective_negative is None:
                if not base_negative_fact_hashes.issubset(
                    superseded_base_facts
                ):
                    raise ClaimArtifactError(
                        "effective row removed a base semantic-negative fact without supersession"
                    )
            elif not isinstance(effective_negative, dict):
                raise ClaimArtifactError(
                    "effective row removed or replaced a base semantic-negative fact"
                )
            else:
                proposal = dict(effective_negative.get("proposal") or {})
                validation = dict(effective_negative.get("validation") or {})
                event_hash = effective_negative.get("validation_input_hash")
                if (
                    proposal.get("version") != "claim-expert-adjudication-v1"
                    or validation.get("version") != "claim-expert-adjudication-v1"
                    or not _is_sha256(event_hash)
                    or set(invalid_reasons.values()) != {"expert_semantic_exclusion"}
                    or valid_group_ids
                ):
                    raise ClaimArtifactError(
                        "effective expert semantic-negative fact is not event-bound"
                    )
        expected_negative_id = semantic_negative_id(effective_negative)
        if facts.get("validated_negative_id") != expected_negative_id:
            raise ClaimArtifactError("effective semantic-negative identity is invalid")

        adjusted_groups: list[dict[str, Any]] = []
        for group in groups_by_claim.get(claim_id, []):
            adjusted = dict(group)
            group_id = str(group.get("coverage_group_id") or "")
            if group_id not in valid_group_ids:
                adjusted["status"] = "invalid"
                adjusted["invalid_reason"] = str(invalid_reasons[group_id])
            adjusted_groups.append(adjusted)
        expected = reduce_claim(
            claim,
            validated_groups=[
                group for group in adjusted_groups if group.get("status") == "validated"
            ],
            validated_negative=(
                effective_negative if isinstance(effective_negative, dict) else None
            ),
            all_groups=adjusted_groups,
        )
        for field in (
            "resolution",
            "classification",
            "classification_status",
            "exclusion_kind",
            "invalid_reasons",
        ):
            if row.get(field) != expected.get(field):
                raise ClaimArtifactError(
                    f"effective row differs from deterministic reduction: {field}"
                )
        effective_by_id[claim_id] = row

    queue_contracts = {
        "claim-queue-v3": (
            "claim-queue-proposal/v2",
            "claim_queue_proposal_v2.schema.json",
            "claim-queue-proposal-id/v2",
        ),
        "claim-queue-v4": (
            "claim-queue-proposal/v3",
            "claim_queue_proposal_v3.schema.json",
            "claim-queue-proposal-id/v3",
        ),
    }
    queue_contract = queue_contracts.get(queue_version)
    if queue_contract is None:
        raise ClaimArtifactError("unsupported effective queue version")
    expected_proposal_schema, proposal_schema_file, proposal_id_domain = (
        queue_contract
    )

    proposal_by_claim: dict[str, dict[str, Any]] = {}
    for proposal in queue_rows:
        proposal_schema = str(proposal.get("schema") or "")
        if proposal_schema != expected_proposal_schema:
            raise ClaimArtifactError(
                "claim queue proposal schema does not match its queue version"
            )
        _validate_schema(
            proposal,
            proposal_schema_file,
            label="claim queue proposal",
        )
        claim_id = str(proposal.get("claim_id") or "")
        if claim_id in proposal_by_claim:
            raise ClaimArtifactError("claim queue contains a duplicate claim")
        row = effective_by_id.get(claim_id)
        claim = catalog_by_id.get(claim_id)
        if row is None or claim is None or row.get("resolution") != "uncertain":
            raise ClaimArtifactError("claim queue proposal does not refer to an uncertain claim")
        expected_proposal_hash = hash_json(
            proposal_id_domain,
            {
                "claim_id": claim_id,
                "claim_effective_revision": row.get("claim_effective_revision"),
                "action": "needs_extraction",
                "queue_version": queue_version,
            },
        )
        expected_proposal_id = (
            f"CQP-{digest_hex(row['claim_hash'])[:8]}-"
            f"{digest_hex(expected_proposal_hash)[:8]}"
        )
        expected_fields = {
            "proposal_id": expected_proposal_id,
            "parent_block_id": (
                claim.get("parent_block_id")
                or dict(claim.get("locator") or {}).get("block_id")
            ),
            "locator": claim.get("locator"),
            "claim_source_fingerprint": canonical_target_fingerprint(claim.get("claim_hash")),
            "document_generation_id": row.get("document_generation_id"),
            "catalog_generation_id": row.get("catalog_generation_id"),
            "claim_effective_revision": row.get("claim_effective_revision"),
            "queue_version": queue_version,
            "created_from_event_seq": row.get("last_relevant_event_seq"),
        }
        expected_fields["claim_hash"] = row.get("claim_hash")
        preconditions = dict(proposal.get("execution_preconditions") or {})
        expected_preconditions = {
            "claim_id": claim_id,
            "claim_hash": row.get("claim_hash"),
            "claim_source_fingerprint": canonical_target_fingerprint(
                claim.get("claim_hash")
            ),
            "expected_claim_effective_revision": row.get(
                "claim_effective_revision"
            ),
            "expected_ledger_state": "uncertain",
            "document_generation_id": row.get("document_generation_id"),
            "catalog_generation_id": row.get("catalog_generation_id"),
        }
        for field, expected_value in expected_preconditions.items():
            if preconditions.get(field) != expected_value:
                raise ClaimArtifactError(
                    f"claim queue proposal has invalid execution precondition: {field}"
                )
        for field, expected_value in expected_fields.items():
            if proposal.get(field) != expected_value:
                raise ClaimArtifactError(f"claim queue proposal has invalid {field}")
        proposal_by_claim[claim_id] = proposal

    uncertain_claim_ids = {
        claim_id
        for claim_id, row in effective_by_id.items()
        if row.get("resolution") == "uncertain"
    }
    if set(proposal_by_claim) != uncertain_claim_ids:
        raise ClaimArtifactError("claim queue is not a complete uncertain-claim projection")


def _authoritative_effective_reduction(
    root: Path,
    base: dict[str, Any],
    meta: dict[str, Any],
    *,
    require_current_authority: bool,
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]]]:
    """Read the committed event prefix and rebuild rows when authority is current.

    Current snapshots are readable only while target/review authority is still
    identical. A refold seed may observe drift solely to replace the snapshot;
    it never exposes those historical effective rows to the fold.
    """
    from claim_review_actions import (
        _load_declared_authority,
        _scan_event_log_unlocked,
        derive_authoritative_effective_rows,
    )

    event_snapshot = _scan_event_log_unlocked(root, repair=False)
    committed_count = meta.get("last_event_seq")
    if (
        not isinstance(committed_count, int)
        or isinstance(committed_count, bool)
        or committed_count < 0
        or committed_count > event_snapshot.last_event_seq
    ):
        raise ClaimArtifactError("effective meta points beyond the review event log")
    prefix_rows = list(event_snapshot.rows[:committed_count])
    prefix_bytes = b"".join(
        canonical_json_value_bytes(row) + b"\n" for row in prefix_rows
    )
    if sha256_bytes(prefix_bytes) != meta.get("event_prefix_sha256"):
        raise ClaimArtifactError(
            "effective event prefix differs from the committed review event log"
        )

    generation = dict(base["generation_meta"])
    authority = _load_declared_authority(root, generation, readonly=True)
    authority_is_current = all((
        authority.get("target_set_hash") == meta.get("target_set_hash"),
        authority.get("target_publication_revision")
        == meta.get("target_publication_revision"),
        authority.get("requirement_review_state_hash")
        == meta.get("requirement_review_state_hash"),
    ))
    if require_current_authority and not authority_is_current:
        raise ClaimEffectiveAuthorityChanged(
            "effective publication authority changed before commit"
        )
    if not authority_is_current:
        return None, prefix_rows
    return (
        derive_authoritative_effective_rows(base, authority, prefix_rows),
        prefix_rows,
    )


def _validate_effective_migration_identity(meta: dict[str, Any]) -> None:
    migrated_from = meta.get("migrated_from_version")
    migration_id = meta.get("migration_id")
    if migrated_from is None:
        if migration_id is not None:
            raise ClaimArtifactError("effective migration id has no source version")
        return
    expected = hash_json(
        "claim-effective-migration/v1",
        {
            "base_generation_id": meta.get("base_generation_id"),
            "source_effective_snapshot_version": migrated_from,
            "target_effective_snapshot_version": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        },
    )
    if migration_id != expected:
        raise ClaimArtifactError("effective migration identity does not recompute")


def _validate_persisted_effective_consistency(
    meta: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
) -> None:
    """Validate a current-wire snapshot using its persisted component versions.

    This is used only to authorize replacement of a version/authority-stale
    snapshot. It verifies every persisted revision and hash but deliberately
    does not bless the rows as a projection of current live authority.
    """
    from claim_effective_contract import (
        CLAIM_AUTHORITY_PROJECTION_VERSION,
        compute_claim_effective_revision,
        compute_effective_authority_projection_hash,
        compute_effective_metrics,
        compute_effective_state_hash,
    )

    _validate_effective_migration_identity(meta)
    versions = dict(meta.get("versions") or {})
    expected_version_bindings = {
        "effective_snapshot": meta.get("effective_snapshot_version"),
        "effective_artifacts": meta.get("effective_artifact_version"),
        "effective_ledger_schema": meta.get("effective_ledger_schema"),
        "effective_reducer": meta.get("reducer_version"),
        "queue": meta.get("queue_version"),
        "review_bridge": meta.get("bridge_version"),
    }
    for field, expected in expected_version_bindings.items():
        if versions.get(field) != expected:
            raise ClaimArtifactError(
                f"effective persisted version vector disagrees with {field}"
            )

    for row in ledger_rows:
        claim_id = str(row.get("claim_id") or "")
        inputs = dict(row.get("revision_inputs") or {})
        if inputs.get("schema") != versions.get("revision_inputs"):
            raise ClaimArtifactError(
                f"effective row {claim_id} has stale revision inputs"
            )
        if inputs.get("base_claim_row_hash") != row.get("base_claim_row_hash"):
            raise ClaimArtifactError(
                f"effective row {claim_id} revision inputs disagree with its base row hash"
            )
        expected_row_versions = {
            "effective_ledger_schema": meta.get("effective_ledger_schema"),
            "reducer_version": meta.get("reducer_version"),
            "bridge_version": meta.get("bridge_version"),
            "review_adapter_versions": meta.get("review_adapter_versions"),
        }
        if dict(inputs.get("versions") or {}) != expected_row_versions:
            raise ClaimArtifactError(
                f"effective row {claim_id} revision component versions disagree with meta"
            )
        expected_authority_hash = hash_json(
            CLAIM_AUTHORITY_PROJECTION_VERSION,
            {
                "ordered_relevant_event_hashes": list(
                    inputs.get("ordered_relevant_event_hashes") or []
                ),
                "linked_targets": list(inputs.get("linked_targets") or []),
                "expert_overlay": dict(inputs.get("expert_overlay") or {}),
            },
        )
        if inputs.get("authority_projection_hash") != expected_authority_hash:
            raise ClaimArtifactError(
                f"effective row {claim_id} authority projection does not recompute"
            )
        if inputs.get("effective_state_hash") != compute_effective_state_hash(row):
            raise ClaimArtifactError(
                f"effective row {claim_id} state projection does not recompute"
            )
        if row.get("claim_effective_revision") != compute_claim_effective_revision(
            inputs
        ):
            raise ClaimArtifactError(
                f"effective row {claim_id} claim effective revision does not recompute"
            )

    if meta.get("effective_metrics") != compute_effective_metrics(ledger_rows):
        raise ClaimArtifactError(
            "effective metrics do not recompute from the committed ledger"
        )
    projection_hash = compute_effective_authority_projection_hash(ledger_rows)
    if meta.get("authority_projection_hash") != projection_hash:
        raise ClaimArtifactError(
            "effective authority projection does not recompute from the ledger"
        )
    expected_document_revision = hash_json(
        "claim-document-effective-revision/v2",
        {
            "base_generation_id": meta.get("base_generation_id"),
            "last_event_seq": meta.get("last_event_seq"),
            "event_prefix_sha256": meta.get("event_prefix_sha256"),
            "target_set_hash": meta.get("target_set_hash"),
            "requirement_review_state_hash": meta.get(
                "requirement_review_state_hash"
            ),
            "authority_projection_hash": projection_hash,
            "effective_ledger_schema": meta.get("effective_ledger_schema"),
            "effective_snapshot_version": meta.get("effective_snapshot_version"),
            "effective_artifact_version": meta.get("effective_artifact_version"),
            "reducer_version": meta.get("reducer_version"),
            "bridge_version": meta.get("bridge_version"),
            "queue_version": meta.get("queue_version"),
        },
    )
    if meta.get("document_effective_revision") != expected_document_revision:
        raise ClaimArtifactError(
            "effective document revision does not recompute from committed meta"
        )


def publish_effective_snapshot(
    out_dir: Path | str,
    effective_ledger: Iterable[dict[str, Any]],
    queue_proposals: Iterable[dict[str, Any]],
    *,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Atomically publish the mutable effective trio under its own WAL."""
    root = Path(out_dir).expanduser().resolve()
    ledger_rows = [dict(row) for row in effective_ledger]
    queue_rows = [dict(row) for row in queue_proposals]
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        base = _load_committed_claim_base_unlocked(root)
        if not committed_base_versions_are_current(
            base,
            require_environment_match=False,
        ):
            raise ClaimArtifactError("base_migration_required")
        generation = dict(base["generation_meta"])
        required_meta = {
            "event_prefix_sha256",
            "last_event_seq",
            "document_effective_revision",
            "target_set_hash",
            "target_publication_revision",
            "requirement_review_state_hash",
            "authority_projection_hash",
            "effective_ledger_schema",
            "review_adapter_versions",
            "reducer_version",
            "bridge_version",
            "queue_version",
            "effective_metrics",
        }
        if not required_meta.issubset(meta):
            missing = ", ".join(sorted(required_meta.difference(meta)))
            raise ClaimArtifactError(f"effective meta is incomplete: {missing}")
        for field in (
            "event_prefix_sha256",
            "document_effective_revision",
            "target_set_hash",
            "target_publication_revision",
            "requirement_review_state_hash",
            "authority_projection_hash",
        ):
            if not _is_sha256(meta.get(field)):
                raise ClaimArtifactError(f"invalid effective meta hash: {field}")
        last_event_seq = meta.get("last_event_seq")
        if (
            not isinstance(last_event_seq, int)
            or isinstance(last_event_seq, bool)
            or last_event_seq < 0
        ):
            raise ClaimArtifactError("invalid effective event sequence")
        for field in ("reducer_version", "bridge_version", "queue_version"):
            if not isinstance(meta.get(field), str) or not meta.get(field):
                raise ClaimArtifactError(f"invalid effective component version: {field}")
        if not isinstance(meta.get("effective_metrics"), dict):
            raise ClaimArtifactError("invalid effective metrics")

        from claim_ledger import (
            CLAIM_EFFECTIVE_LEDGER_SCHEMA,
            CLAIM_EFFECTIVE_REDUCER_VERSION,
            CLAIM_QUEUE_VERSION,
            CLAIM_REVIEW_BRIDGE_VERSION,
            current_effective_versions,
            effective_review_adapter_versions,
        )

        if meta.get("effective_ledger_schema") != CLAIM_EFFECTIVE_LEDGER_SCHEMA:
            raise ClaimArtifactError("invalid effective ledger schema identity")
        if meta.get("review_adapter_versions") != effective_review_adapter_versions():
            raise ClaimArtifactError("invalid effective review adapter version vector")
        expected_components = {
            "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
            "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
            "queue_version": CLAIM_QUEUE_VERSION,
        }
        for field, expected_value in expected_components.items():
            if meta.get(field) != expected_value:
                raise ClaimArtifactError(
                    f"invalid effective component version: {field}"
                )

        authoritative_rows, event_rows = _authoritative_effective_reduction(
            root,
            base,
            meta,
            require_current_authority=True,
        )
        _validate_effective_projection(
            base,
            ledger_rows,
            queue_rows,
            last_event_seq=last_event_seq,
            queue_version=str(meta["queue_version"]),
            event_rows=event_rows,
        )
        ledger_bytes = _jsonl_bytes(ledger_rows)
        queue_bytes = _jsonl_bytes(queue_rows)

        effective_meta = {
            **dict(meta),
            "schema": "claim-effective-meta/v1",
            "artifact_protocol_version": CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
            "effective_artifact_version": CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
            "effective_snapshot_version": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            "run_id": str(meta.get("run_id") or generation.get("run_id") or ""),
            "committed_at": _utc_now(),
            "base_generation_id": claim_base_generation_id(generation),
            "document_generation_id": str(generation.get("document_generation_id") or ""),
            "catalog_generation_id": str(generation.get("catalog_generation_id") or ""),
            "generation_meta_sha256": file_sha256(claim_artifact_path(root, CLAIM_GENERATION_META)),
            "base_ledger_sha256": str(generation.get("ledger_sha256") or ""),
            "effective_ledger_sha256": _sha256_bytes(ledger_bytes),
            "queue_sha256": _sha256_bytes(queue_bytes),
            "queue_count": len(queue_rows),
            "ledger_count": len(ledger_rows),
            "claim_events_enabled": True,
            "migrated_from_version": meta.get("migrated_from_version"),
            "migration_id": meta.get("migration_id"),
        }
        from claim_effective_contract import CLAIM_REVISION_INPUTS_VERSION

        effective_meta["versions"] = {
            **current_effective_versions(),
            "revision_inputs": CLAIM_REVISION_INPUTS_VERSION,
        }

        from claim_effective_contract import validate_effective_meta_consistency

        # Publish and the read-only loader share one recomputation contract:
        # a forged or drifted revision/metric never reaches the WAL.
        validate_effective_meta_consistency(
            effective_meta,
            ledger_rows,
            authoritative_ledger=authoritative_rows,
        )

        _validate_schema(
            effective_meta,
            "claim_effective_meta.schema.json",
            label="effective claim meta",
        )
        effective_meta_bytes = canonical_json_value_bytes(effective_meta)
        generation_meta_sha256 = file_sha256(claim_artifact_path(root, CLAIM_GENERATION_META))
        base_ledger_sha256 = str(generation.get("ledger_sha256") or "")
        journal = _begin_effective_publication_unlocked(
            root,
            base_generation_id=str(effective_meta["base_generation_id"]),
            generation_meta_sha256=generation_meta_sha256,
            base_ledger_sha256=base_ledger_sha256,
            candidate={
                "effective_ledger_sha256": str(
                    effective_meta["effective_ledger_sha256"]
                ),
                "effective_ledger_count": len(ledger_rows),
                "queue_sha256": str(effective_meta["queue_sha256"]),
                "queue_count": len(queue_rows),
                "effective_meta_sha256": _sha256_bytes(effective_meta_bytes),
                "document_effective_revision": str(
                    effective_meta["document_effective_revision"]
                ),
            },
        )
        _atomic_write_bytes(claim_artifact_path(root, CLAIM_EFFECTIVE_LEDGER), ledger_bytes)
        _atomic_write_bytes(claim_artifact_path(root, CLAIM_QUEUE_PROPOSALS), queue_bytes)
        _atomic_write_bytes(claim_artifact_path(root, CLAIM_EFFECTIVE_META), effective_meta_bytes)
        loaded = _load_committed_effective_unlocked(root, base, require_v2=True)
        if loaded["effective_meta"] != effective_meta:
            raise ClaimArtifactError("effective publication did not reload byte-equivalent meta")
        _finish_effective_publication_unlocked(root, journal)
        return effective_meta


def load_committed_claim_base(out_dir: Path | str) -> dict[str, Any]:
    """Load immutable generation-time facts without consulting live review authority."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        return _load_committed_claim_base_unlocked(root)


def load_committed_effective_snapshot(out_dir: Path | str) -> dict[str, Any]:
    """Load only a Phase 1 effective snapshot committed against a valid base."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        _recover_claim_state_unlocked(root)
        base = _load_committed_claim_base_unlocked(root)
        effective = _load_committed_effective_unlocked(root, base, require_v2=True)
        return {**base, **effective}


def load_committed_effective_snapshot_readonly(
    out_dir: Path | str,
    *,
    require_v2: bool = True,
) -> dict[str, Any]:
    """Read a committed effective snapshot without performing crash recovery.

    Request paths use this entrypoint. Startup maintenance and the explicit fold
    command own WAL recovery; a GET must never mutate or roll back artifacts.

    ``require_v2=False`` is only for the view dispatcher. It lets that
    dispatcher distinguish a committed legacy snapshot (migration required)
    from an unfinished journal (recovery pending) without a second filesystem
    probe that could race the journal check below.
    """
    root = Path(out_dir).expanduser().resolve()

    def pending_journals() -> list[str]:
        return [
            name for name in (
                CLAIM_PUBLICATION_JOURNAL,
                CLAIM_EFFECTIVE_PUBLICATION_JOURNAL,
                CLAIM_BUDGET_CHECKPOINT_OUTBOX,
            )
            if governed_artifact_path(root, name).is_file()
        ]

    pending = pending_journals()
    if pending:
        raise ClaimEffectiveRecoveryPending(
            "claim effective recovery pending: " + ", ".join(pending)
        )
    anchors_before = (
        (claim_artifact_path(root, CLAIM_GENERATION_META)).read_bytes(),
        (claim_artifact_path(root, CLAIM_EFFECTIVE_META)).read_bytes(),
    )
    base = _load_committed_claim_base_unlocked(root)
    effective = _load_committed_effective_unlocked(
        root,
        base,
        require_v2=require_v2,
    )
    pending = pending_journals()
    if pending:
        raise ClaimEffectiveRecoveryPending(
            "claim effective recovery pending: " + ", ".join(pending)
        )
    anchors_after = (
        (claim_artifact_path(root, CLAIM_GENERATION_META)).read_bytes(),
        (claim_artifact_path(root, CLAIM_EFFECTIVE_META)).read_bytes(),
    )
    if anchors_after != anchors_before:
        raise ClaimArtifactError("claim snapshot changed during read-only load")
    return {**base, **effective}


def _load_committed_claim_base_unlocked(root: Path) -> dict[str, Any]:
    generation = _read_json(claim_artifact_path(root, CLAIM_GENERATION_META), label="claim generation meta")
    if generation.get("schema") != "claim-generation-meta/v1":
        raise ClaimArtifactError("unsupported claim generation meta schema")
    if generation.get("artifact_protocol_version") != CLAIM_ARTIFACT_PROTOCOL_VERSION:
        raise ClaimArtifactError("stale claim artifact protocol")
    if not _shadow_meta_is_well_formed(dict(generation.get("shadow_meta") or {})):
        raise ClaimArtifactError("invalid committed shadow result meta")

    committed_files = {
        CLAIM_CATALOG: generation.get("catalog_sha256"),
        CLAIM_CATALOG_META: generation.get("catalog_meta_sha256"),
        CLAIM_COVERAGE_GROUPS: generation.get("coverage_groups_sha256"),
        CLAIM_LEDGER: generation.get("ledger_sha256"),
        CLAIM_SHADOW_METRICS: generation.get("shadow_metrics_sha256"),
    }
    for name, expected in committed_files.items():
        _require_hash(governed_artifact_path(root, name), expected, label=name)

    for name, meta_key in (
        ("blocks.jsonl", "blocks_file_sha256"),
        ("table_items.jsonl", "table_items_file_sha256"),
        ("table_cell_items.jsonl", "table_cell_items_file_sha256"),
    ):
        expected = str(generation.get(meta_key) or "")
        if expected:
            _require_hash(governed_artifact_path(root, name), expected, label=name)

    catalog_build = _load_catalog_probe_unlocked(root)
    catalog_meta = dict(catalog_build["meta"])
    # 含表块的当前版本目录：cell 产物哈希绑定是硬义务（不是可选字段）——
    # 绑定缺失/文件被删除/内容被替换全部 fail-closed，绝不加载无绑定 base
    if _catalog_meta_requires_cell_binding(catalog_meta):
        _require_hash(
            root / "table_cell_items.jsonl",
            generation.get("table_cell_items_file_sha256"),
            label="table_cell_items.jsonl",
        )
    structural_fields = (
        "structural_override_version",
        "structural_override_prefix_sha256",
        "structural_override_prefix_count",
        "structural_override_applied_count",
    )
    for field in structural_fields:
        if (
            field in generation or field in catalog_meta
        ) and generation.get(field) != catalog_meta.get(field):
            raise ClaimArtifactError(
                f"claim generation structural override metadata differs: {field}"
            )
    from claim_structural_overrides import current_structural_override_identity

    live_structural_overrides = current_structural_override_identity(root)
    catalog = catalog_build["catalog"]
    groups = _read_jsonl(claim_artifact_path(root, CLAIM_COVERAGE_GROUPS), label="coverage groups")
    ledger = _read_jsonl(claim_artifact_path(root, CLAIM_LEDGER), label="base claim ledger")
    metrics = _read_json(claim_artifact_path(root, CLAIM_SHADOW_METRICS), label="shadow metrics")
    if not _shadow_cost_metrics_are_well_formed(metrics):
        raise ClaimArtifactError("invalid committed shadow verifier cost metrics")
    if not _shadow_budget_matches_metrics(
        dict(generation.get("shadow_meta") or {}),
        metrics,
    ):
        raise ClaimArtifactError("committed verifier budget differs from its metrics")
    requirements_hash = str(generation.get("requirements_sha256") or "")
    requirements_meta_hash = str(generation.get("requirements_meta_sha256") or "")
    requirements_path = root / "ai_requirements.jsonl"
    requirements_meta_path = root / "ai_requirements.meta.json"
    try:
        live_target_matches = (
            bool(requirements_hash)
            and requirements_path.is_file()
            and file_sha256(requirements_path) == requirements_hash
            and (
                not requirements_meta_hash
                or requirements_meta_path.is_file()
                and file_sha256(requirements_meta_path) == requirements_meta_hash
            )
        )
    except OSError:
        live_target_matches = False
    attempt_rows = _validate_committed_attempt_binding(
        root,
        generation,
        metrics,
        validate_live_target=live_target_matches,
    )
    if len(catalog) != int(generation.get("catalog_count", -1)):
        raise ClaimArtifactError("catalog count does not match generation meta")
    if len(groups) != int(generation.get("coverage_group_count", -1)):
        raise ClaimArtifactError("coverage group count does not match generation meta")
    if len(ledger) != int(generation.get("ledger_count", -1)):
        raise ClaimArtifactError("ledger count does not match generation meta")
    catalog_ids = [str(row.get("claim_id") or "") for row in catalog]
    ledger_ids = [str(row.get("claim_id") or "") for row in ledger]
    if not all(catalog_ids) or catalog_ids != ledger_ids:
        raise ClaimArtifactError("base ledger is not a one-to-one catalog projection")

    if generation.get("delivery_track") == "B" and not requirements_hash:
        raise ClaimArtifactError("B-track claim generation is not bound to requirements")
    bound_requirements: list[dict[str, Any]] | None = None
    if requirements_hash and requirements_path.is_file():
        try:
            if file_sha256(requirements_path) == requirements_hash:
                bound_requirements = _read_jsonl(
                    requirements_path,
                    label="generation-time AI requirements",
                )
        except OSError:
            bound_requirements = None
    requirements_meta: dict[str, Any] | None = None
    if requirements_meta_hash and requirements_meta_path.is_file():
        try:
            if file_sha256(requirements_meta_path) == requirements_meta_hash:
                requirements_meta = _read_json(
                    requirements_meta_path,
                    label="generation-time AI requirements meta",
                )
        except OSError:
            requirements_meta = None

    _validate_shadow_graph(
        catalog_meta=catalog_build["meta"],
        shadow_meta=dict(generation.get("shadow_meta") or {}),
        catalog=catalog,
        units=list(catalog_build.get("units") or []),
        groups=groups,
        ledger=ledger,
        requirements=bound_requirements,
        review_states=None,
        validate_review_authority=False,
    )

    return {
        "catalog": catalog,
        "units": catalog_build["units"],
        "groups": groups,
        "ledger": ledger,
        "metrics": metrics,
        "requirements": bound_requirements or [],
        "requirements_meta": requirements_meta,
        "catalog_meta": catalog_meta,
        "generation_meta": generation,
        "structural_override_registry": live_structural_overrides,
        "attempt_cost_chain": _attempt_cost_chain(
            attempt_rows,
            dict(generation.get("attempt_chain") or {}),
        ),
    }


def _load_committed_shadow_unlocked(root: Path) -> dict[str, Any]:
    base = _load_committed_claim_base_unlocked(root)
    effective = _load_committed_effective_unlocked(root, base, require_v2=False)
    return {**base, **effective}


def _load_committed_effective_unlocked(
    root: Path,
    base: dict[str, Any],
    *,
    require_v2: bool,
    allow_stale_base_versions: bool = False,
    refold_seed_only: bool = False,
) -> dict[str, Any]:
    generation = dict(base["generation_meta"])
    ledger = list(base["ledger"])

    effective = _read_json(claim_artifact_path(root, CLAIM_EFFECTIVE_META), label="effective claim meta")
    if effective.get("schema") != "claim-effective-meta/v1":
        raise ClaimArtifactError("unsupported effective claim meta schema")
    effective_version = str(effective.get("effective_snapshot_version") or "")
    if effective_version not in {
        LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        PREVIOUS_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    }:
        raise ClaimArtifactError("stale effective snapshot version")
    if require_v2 and effective_version != CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
        raise ClaimArtifactError("current effective snapshot is not materialized")
    if (
        effective_version == CLAIM_EFFECTIVE_SNAPSHOT_VERSION
        and not allow_stale_base_versions
        and not committed_base_versions_are_current(
            base,
            require_environment_match=False,
        )
    ):
        raise ClaimArtifactError("base_migration_required")
    if effective_version == CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
        expected_protocol = CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
    elif effective_version == PREVIOUS_CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
        expected_protocol = PREVIOUS_CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
    else:
        # Phase 0 v1 was emitted as part of the immutable base publication and
        # therefore used that generation's artifact protocol.
        expected_protocol = str(generation.get("artifact_protocol_version") or "")
    if effective.get("artifact_protocol_version") != expected_protocol:
        raise ClaimArtifactError("stale effective artifact protocol")
    if str(effective.get("catalog_generation_id") or "") != str(
        generation.get("catalog_generation_id") or ""
    ):
        raise ClaimArtifactError("effective snapshot refers to a different catalog generation")
    if effective_version == LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
        if str(effective.get("target_generation_id") or "") != str(
            generation.get("target_generation_id") or ""
        ):
            raise ClaimArtifactError("effective snapshot refers to a different target generation")
    elif str(effective.get("base_generation_id") or "") != claim_base_generation_id(
        generation
    ):
        raise ClaimArtifactError("effective snapshot refers to a different base generation")
    _require_hash(
        claim_artifact_path(root, CLAIM_GENERATION_META),
        effective.get("generation_meta_sha256"),
        label=CLAIM_GENERATION_META,
    )
    if str(effective.get("base_ledger_sha256") or "") != str(generation.get("ledger_sha256") or ""):
        raise ClaimArtifactError("effective snapshot refers to a different base ledger")
    _require_hash(
        claim_artifact_path(root, CLAIM_EFFECTIVE_LEDGER),
        effective.get("effective_ledger_sha256"),
        label=CLAIM_EFFECTIVE_LEDGER,
    )
    effective_ledger = _read_jsonl(
        claim_artifact_path(root, CLAIM_EFFECTIVE_LEDGER),
        label="effective claim ledger",
    )
    if len(effective_ledger) != int(effective.get("ledger_count", -1)):
        raise ClaimArtifactError("effective ledger count does not match committed meta")
    if (
        effective_version == LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION
        and effective.get("claim_events_enabled") is False
        and effective_ledger != ledger
    ):
        raise ClaimArtifactError("Phase 0 effective ledger differs from its base ledger")
    queue: list[dict[str, Any]] = []
    if effective_version == CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
        _validate_schema(
            effective,
            (
                "claim_effective_meta_seed.schema.json"
                if refold_seed_only
                else "claim_effective_meta.schema.json"
            ),
            label="effective claim meta",
        )
        _require_canonical_json_value(
            claim_artifact_path(root, CLAIM_EFFECTIVE_META),
            effective,
            label="effective claim meta",
        )
        _require_hash(
            claim_artifact_path(root, CLAIM_QUEUE_PROPOSALS),
            effective.get("queue_sha256"),
            label=CLAIM_QUEUE_PROPOSALS,
        )
        queue = _read_jsonl(claim_artifact_path(root, CLAIM_QUEUE_PROPOSALS), label="claim queue proposals")
        if len(queue) != int(effective.get("queue_count", -1)):
            raise ClaimArtifactError("claim queue count does not match committed meta")
        if effective.get("effective_artifact_version") != CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION:
            raise ClaimArtifactError("stale effective component version")
        if effective.get("queue_version") is None:
            raise ClaimArtifactError("effective queue version is missing")
        if not _is_sha256(effective.get("event_prefix_sha256")):
            raise ClaimArtifactError("effective event prefix hash is invalid")
        if not _is_sha256(effective.get("document_effective_revision")):
            raise ClaimArtifactError("effective document revision is invalid")
        if not _is_sha256(effective.get("target_set_hash")):
            raise ClaimArtifactError("effective target set hash is invalid")
        if not _is_sha256(effective.get("requirement_review_state_hash")):
            raise ClaimArtifactError("effective review state hash is invalid")
        if not isinstance(effective.get("effective_metrics"), dict):
            raise ClaimArtifactError("effective metrics are missing")
        base_ids = [str(row.get("claim_id") or "") for row in ledger]
        effective_ids = [str(row.get("claim_id") or "") for row in effective_ledger]
        if base_ids != effective_ids:
            raise ClaimArtifactError("effective ledger is not a one-to-one base projection")
        from claim_ledger import CLAIM_EFFECTIVE_LEDGER_SCHEMA as _row_schema

        if any(row.get("schema") != _row_schema for row in effective_ledger):
            raise ClaimArtifactError("invalid effective ledger row schema")
        expected_queue_schema = (
            "claim-queue-proposal/v3"
            if str(effective.get("queue_version") or "") == "claim-queue-v4"
            else "claim-queue-proposal/v2"
        )
        if any(row.get("schema") != expected_queue_schema for row in queue):
            raise ClaimArtifactError(
                "claim queue proposal schema does not match effective queue version"
            )
        _require_canonical_jsonl(
            claim_artifact_path(root, CLAIM_EFFECTIVE_LEDGER),
            effective_ledger,
            label="effective claim ledger",
        )
        _require_canonical_jsonl(
            claim_artifact_path(root, CLAIM_QUEUE_PROPOSALS),
            queue,
            label="claim queue proposals",
        )
        authoritative_rows, event_rows = _authoritative_effective_reduction(
            root,
            base,
            effective,
            require_current_authority=False,
        )
        _validate_effective_projection(
            base,
            effective_ledger,
            queue,
            last_event_seq=int(effective.get("last_event_seq", -1)),
            queue_version=str(effective.get("queue_version") or ""),
            event_rows=event_rows,
        )
        from claim_effective_contract import validate_effective_meta_consistency

        # Recompute persisted revisions before consulting authority freshness.
        # A forged revision must not be laundered into a bridge event merely
        # because target/review authority advanced at the same time.
        if refold_seed_only:
            _validate_persisted_effective_consistency(
                effective,
                effective_ledger,
            )
        else:
            _validate_effective_migration_identity(effective)
            validate_effective_meta_consistency(
                effective,
                effective_ledger,
                authoritative_ledger=None,
            )
        if authoritative_rows is None:
            if not refold_seed_only:
                raise ClaimEffectiveAuthorityChanged(
                    "effective publication authority changed before commit"
                )
        elif not refold_seed_only:
            validate_effective_meta_consistency(
                effective,
                effective_ledger,
                authoritative_ledger=authoritative_rows,
            )
    return {
        "effective_ledger": effective_ledger,
        "queue_proposals": queue,
        "effective_meta": effective,
    }


def committed_base_versions_are_current(
    snapshot: dict[str, Any],
    *,
    require_environment_match: bool = True,
) -> bool:
    """Check component versions without adding them to the extraction cache key.

    Offline acceptance can validate the persisted runtime envelope without requiring
    the original endpoint credentials to be present in the current process.
    """
    from claim_catalog import CLAIM_CATALOG_VERSION, CLAIM_UNIT_PACKING_VERSION
    from claim_structural_overrides import CLAIM_STRUCTURAL_OVERRIDE_VERSION
    from table_structure import TABLE_STRUCTURE_VERSION
    from claim_ledger import (
        CLAIM_COVERAGE_RUNTIME_VERSION,
        current_base_versions,
        semantic_verifier_runtime,
        semantic_verifier_runtime_is_valid,
    )
    from source_spans import (
        SOURCE_ALIGNMENT_VERSION,
        SOURCE_TRANSFORMATION_POLICY_VERSION,
        SOURCE_TRANSFORMATION_RULESET_VERSION,
    )

    catalog_meta = dict(snapshot.get("catalog_meta") or {})
    generation = dict(snapshot.get("generation_meta") or {})
    shadow_meta = dict(generation.get("shadow_meta") or {})
    runtime = dict(shadow_meta.get("verifier_runtime") or {})
    parser_provenance = dict(catalog_meta.get("parser_provenance") or {})
    live_structural_overrides = dict(
        snapshot.get("structural_override_registry") or {}
    )
    structural_overrides_are_current = (
        catalog_meta.get("structural_override_version")
        == CLAIM_STRUCTURAL_OVERRIDE_VERSION
        and generation.get("structural_override_version")
        == CLAIM_STRUCTURAL_OVERRIDE_VERSION
        and catalog_meta.get("structural_override_prefix_sha256")
        == generation.get("structural_override_prefix_sha256")
        == live_structural_overrides.get("prefix_sha256")
        and catalog_meta.get("structural_override_prefix_count")
        == generation.get("structural_override_prefix_count")
        == live_structural_overrides.get("prefix_count")
        and live_structural_overrides.get("version")
        == CLAIM_STRUCTURAL_OVERRIDE_VERSION
    )
    target_producer_is_current = True
    if generation.get("delivery_track") == "B":
        from ai_extract import current_ai_requirements_producer_lineage

        if "requirements_producer_lineage" in generation:
            target_producer_is_current = (
                generation.get("requirements_producer_lineage")
                == current_ai_requirements_producer_lineage()
            )
    source_versions_are_current = (
        parser_provenance.get("source_alignment_version") == SOURCE_ALIGNMENT_VERSION
        and parser_provenance.get("source_transformation_policy_version")
        == SOURCE_TRANSFORMATION_POLICY_VERSION
        and parser_provenance.get("source_transformation_ruleset_version")
        == SOURCE_TRANSFORMATION_RULESET_VERSION
    )
    runtime_is_current = (
        runtime.get("version") == CLAIM_COVERAGE_RUNTIME_VERSION
        and semantic_verifier_runtime_is_valid(runtime)
    )
    if (
        require_environment_match
        and runtime_is_current
        and runtime.get("policy_source") == "environment"
    ):
        try:
            from ai_extract import (
                config_for_route,
                resolve_claim_shadow_verify,
                resolve_claim_shadow_verify_max_calls,
                resolve_claim_shadow_verify_max_total_tokens,
                resolve_claim_shadow_verify_rounds,
            )
            from llm_client import LLMRequestBudget

            route_mode = "stub" if shadow_meta.get("route_mode") == "stub" else "llm"
            config = config_for_route(
                "stub" if route_mode == "stub" else "openai_compatible"
            )
            if config is not None:
                from llm_client import apply_min_tokens

                config = apply_min_tokens(config, "extract")
            max_calls = resolve_claim_shadow_verify_max_calls()
            max_total_tokens = resolve_claim_shadow_verify_max_total_tokens()
            enabled = (
                config is not None
                and resolve_claim_shadow_verify()
                and max_calls > 0
                and max_total_tokens > 0
            )
            expected_runtime = semantic_verifier_runtime(
                route_mode=route_mode,
                enabled=enabled,
                rounds=resolve_claim_shadow_verify_rounds(),
                config=config,
                policy_source="environment",
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=max_calls if enabled else 0,
                max_total_tokens=max_total_tokens if enabled else 0,
            )
            runtime_is_current = runtime.get("fingerprint") == expected_runtime.get("fingerprint")
        except Exception:
            runtime_is_current = False
    return (
        catalog_meta.get("catalog_version") == CLAIM_CATALOG_VERSION
        and catalog_meta.get("packing_version") == CLAIM_UNIT_PACKING_VERSION
        # 表格结构版本是 base 迁移门的一部分：旧结构产物（或目录层已判
        # base_migration_required）不算 current，必须经上游 extraction/base
        # publication 重建——startup/maintenance 不得绕过该门禁
        and catalog_meta.get("table_structure_version") == TABLE_STRUCTURE_VERSION
        and catalog_meta.get("table_structure_status") != "base_migration_required"
        and source_versions_are_current
        and structural_overrides_are_current
        and target_producer_is_current
        and dict(shadow_meta.get("versions") or {}) == current_base_versions()
        and runtime_is_current
    )


def effective_versions_are_current(snapshot: dict[str, Any]) -> bool:
    from claim_ledger import current_effective_versions
    from claim_effective_contract import CLAIM_REVISION_INPUTS_VERSION

    effective = dict(snapshot.get("effective_meta") or {})
    return (
        effective.get("effective_snapshot_version") == CLAIM_EFFECTIVE_SNAPSHOT_VERSION
        and effective.get("artifact_protocol_version")
        == CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
        and effective.get("effective_artifact_version")
        == CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
        and dict(effective.get("versions") or {}) == {
            **current_effective_versions(),
            "revision_inputs": CLAIM_REVISION_INPUTS_VERSION,
        }
    )


def committed_shadow_versions_are_current(
    snapshot: dict[str, Any],
    *,
    require_environment_match: bool = True,
) -> bool:
    """Compatibility alias: stage reuse depends only on immutable base currency."""
    return committed_base_versions_are_current(
        snapshot,
        require_environment_match=require_environment_match,
    )


def _verifier_budget_is_well_formed(meta: dict[str, Any]) -> bool:
    runtime = meta.get("verifier_runtime")
    budget = meta.get("verifier_budget")
    if not isinstance(runtime, dict) or not isinstance(budget, dict):
        return False
    expected_fields = {
        "schema", "policy_version", "max_calls", "max_total_tokens",
        "attempted_calls", "failed_calls", "accounted_tokens",
        "remaining_calls", "remaining_tokens", "usage_complete", "denied",
        "exhaustion_reason",
    }
    if set(budget) != expected_fields:
        return False
    integer_fields = (
        "max_calls", "max_total_tokens", "attempted_calls", "failed_calls",
        "accounted_tokens", "remaining_calls", "remaining_tokens",
    )
    if any(
        not isinstance(budget.get(field), int)
        or isinstance(budget.get(field), bool)
        or budget[field] < 0
        for field in integer_fields
    ):
        return False
    if (
        budget.get("schema") != "claim-verifier-budget-outcome/v1"
        or not isinstance(budget.get("policy_version"), str)
        or not budget.get("policy_version")
        or not isinstance(budget.get("usage_complete"), bool)
        or not isinstance(budget.get("denied"), bool)
        or budget.get("exhaustion_reason") not in {
            "", "call_budget_exhausted", "token_budget_exhausted",
            "reported_token_budget_exceeded", "external_budget_exhausted",
        }
        or budget["policy_version"] != runtime.get("budget_policy_version")
        or budget["max_calls"] != runtime.get("max_calls")
        or budget["max_total_tokens"] != runtime.get("max_total_tokens")
        or budget["failed_calls"] > budget["attempted_calls"]
    ):
        return False
    managed = budget["max_calls"] > 0 and budget["max_total_tokens"] > 0
    if managed:
        token_overrun = budget["accounted_tokens"] > budget["max_total_tokens"]
        if (
            budget["attempted_calls"] > budget["max_calls"]
            or budget["remaining_calls"]
            != budget["max_calls"] - budget["attempted_calls"]
            or budget["remaining_tokens"]
            != max(0, budget["max_total_tokens"] - budget["accounted_tokens"])
            or (
                token_overrun
                and (
                    budget["denied"] is not True
                    or budget["exhaustion_reason"] != "reported_token_budget_exceeded"
                )
            )
        ):
            return False
    if not managed and (budget["remaining_calls"] or budget["remaining_tokens"]):
        return False
    if budget["denied"] is not bool(budget["exhaustion_reason"]):
        return False
    termination = meta.get("termination_reason")
    if (termination == "budget_exhausted") is not budget["denied"]:
        return False
    if (
        termination == "budget_exhausted"
        and budget["exhaustion_reason"] != "reported_token_budget_exceeded"
        and meta.get("resolution_status") != "open"
    ):
        return False
    if meta.get("semantic_verifier_enabled") is not True and (
        budget["attempted_calls"] or budget["failed_calls"] or budget["accounted_tokens"]
    ):
        return False
    return True


def _shadow_budget_matches_metrics(
    meta: dict[str, Any],
    metrics: dict[str, Any],
) -> bool:
    budget = dict(meta.get("verifier_budget") or {})
    return (
        int(metrics.get("verifier_call_count") or 0) == budget.get("attempted_calls")
        and int(metrics.get("verifier_failed_calls") or 0) == budget.get("failed_calls")
        and int(metrics.get("verifier_tokens") or 0) == budget.get("accounted_tokens")
        and metrics.get("verifier_usage_complete") is budget.get("usage_complete")
        and int(metrics.get("verifier_budget_max_calls") or 0) == budget.get("max_calls")
        and int(metrics.get("verifier_budget_max_total_tokens") or 0)
        == budget.get("max_total_tokens")
        and int(metrics.get("verifier_budget_remaining_calls") or 0)
        == budget.get("remaining_calls")
        and int(metrics.get("verifier_budget_remaining_tokens") or 0)
        == budget.get("remaining_tokens")
        and metrics.get("verifier_budget_denied") is budget.get("denied")
        and str(metrics.get("verifier_budget_exhaustion_reason") or "")
        == budget.get("exhaustion_reason")
    )


def _shadow_cost_metrics_are_well_formed(metrics: dict[str, Any]) -> bool:
    failures = metrics.get("verifier_operation_failure_count")
    baseline_lineage_match = metrics.get("no_ledger_baseline_lineage_match")
    verifier_calls = metrics.get("verifier_call_count")
    verifier_tokens = metrics.get("verifier_tokens")
    independent_calls = metrics.get("independent_verifier_call_count")
    independent_tokens = metrics.get("independent_verifier_tokens")
    if (
        not isinstance(failures, int)
        or isinstance(failures, bool)
        or failures < 0
        or not isinstance(baseline_lineage_match, bool)
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in (
                verifier_calls,
                verifier_tokens,
                independent_calls,
                independent_tokens,
            )
        )
    ):
        return False
    invalid_usage = (
        (verifier_calls > 0 and verifier_tokens == 0)
        or (independent_calls > 0 and independent_tokens == 0)
    )
    if invalid_usage and metrics.get("verifier_usage_complete") is True:
        return False
    lineage_blocks_cost = (
        baseline_lineage_match is False
        and metrics.get("verifier_cost_gate_status") != "not_run"
    )
    if (failures > 0 or lineage_blocks_cost or invalid_usage) and (
        metrics.get("verifier_cost_gate_status") != "insufficient_data"
        or metrics.get("phase0_cost_gate_met") is not None
    ):
        return False
    return True


def _shadow_meta_has_attempt_lineage(meta: dict[str, Any]) -> bool:
    """Validate stored accounting shape without requiring current policy versions."""
    runtime = meta.get("verifier_runtime")
    versions = meta.get("versions")
    return (
        meta.get("schema") == "claim-shadow-result/v1"
        and isinstance(runtime, dict)
        and _is_sha256(runtime.get("fingerprint"))
        and runtime.get("route_mode") in {"llm", "stub"}
        and isinstance(runtime.get("enabled"), bool)
        and isinstance(runtime.get("budget_policy_version"), str)
        and isinstance(runtime.get("max_calls"), int)
        and not isinstance(runtime.get("max_calls"), bool)
        and int(runtime.get("max_calls")) >= 0
        and isinstance(runtime.get("max_total_tokens"), int)
        and not isinstance(runtime.get("max_total_tokens"), bool)
        and int(runtime.get("max_total_tokens")) >= 0
        and isinstance(meta.get("semantic_verifier_enabled"), bool)
        and runtime.get("enabled") is meta.get("semantic_verifier_enabled")
        and isinstance(versions, dict)
        and isinstance(versions.get("cost_policy"), str)
        and bool(versions.get("cost_policy"))
        and _verifier_budget_is_well_formed(meta)
    )


def _shadow_meta_is_well_formed(meta: dict[str, Any]) -> bool:
    from claim_ledger import (
        CLAIM_LEDGER_SCHEMA_VERSION,
        semantic_verifier_runtime_is_valid,
    )

    runtime = meta.get("verifier_runtime")
    return (
        meta.get("schema") == "claim-shadow-result/v1"
        and meta.get("ledger_schema_version") == CLAIM_LEDGER_SCHEMA_VERSION
        and meta.get("delivery_track") in {"A", "B"}
        and meta.get("target_kind") in {"ai_requirement", "atomic_requirement"}
        and meta.get("route_mode") in {"llm", "stub"}
        and isinstance(meta.get("semantic_verifier_enabled"), bool)
        and isinstance(meta.get("coverage_verifier_enabled"), bool)
        and isinstance(meta.get("semantic_negative_proposer_enabled"), bool)
        and isinstance(meta.get("semantic_negative_verifier_enabled"), bool)
        and meta.get("semantic_verifier_enabled") == any((
            meta.get("coverage_verifier_enabled"),
            meta.get("semantic_negative_proposer_enabled"),
            meta.get("semantic_negative_verifier_enabled"),
        ))
        and semantic_verifier_runtime_is_valid(runtime)
        and runtime.get("route_mode") == meta.get("route_mode")
        and runtime.get("enabled")
        is meta.get("semantic_verifier_enabled")
        and _verifier_budget_is_well_formed(meta)
        and meta.get("scope") in {"full", "sample"}
        and meta.get("extraction_status") in {"success", "partial", "failed"}
        and meta.get("accounting_status") in {"complete", "incomplete"}
        and meta.get("resolution_status") in {"resolved", "open"}
        and meta.get("termination_reason") in {
            "converged", "budget_exhausted", "round_cap", "llm_error",
            "validation_error", "stalled_open", "cancelled",
        }
        and meta.get("document_ready") is False
    )
