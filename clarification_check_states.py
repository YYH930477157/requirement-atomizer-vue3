"""Append-only audit states for internal clarification checks.

The state file is shared by the desktop process, API server, and report
generator.  Writes therefore use a cross-process lock and atomic replacement;
the latest event for each clarification id is the effective state.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator


CHECK_STATES_FILE = "clarification_check_states.jsonl"
CHECK_STATES_LOCK = "clarification_check_states.lock"
VALID_CHECK_ACTIONS = {"verified_ok", "issue_confirmed", "deferred"}
VALID_BLOCKER_LEVELS = {"blocking", "important"}
DEFAULT_MODULE = "未归属"

_LOCK_TIMEOUT_S = 10.0
_LOCK_STALE_AFTER_S = 300.0
_REPLACE_ATTEMPTS = 20
_REPLACE_RETRY_DELAY_S = 0.05
_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
LOGGER = logging.getLogger("requirement_atomizer")


def read_clarification_check_history(out_dir: Path) -> list[dict[str, Any]]:
    """Read valid audit events in file order; corrupt historical lines are skipped."""
    root = Path(out_dir).expanduser().resolve()
    with clarification_check_state_lock(root):
        return _read_history_unlocked(root / CHECK_STATES_FILE)


def read_clarification_check_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    """Return the latest internal-check event for each clarification id."""
    states: dict[str, dict[str, Any]] = {}
    for row in read_clarification_check_history(out_dir):
        clarification_id = str(row.get("clarification_id") or "").strip()
        if clarification_id:
            states[clarification_id] = row
    return states


def apply_clarification_check_action(
    out_dir: Path,
    clarification_id: str,
    action: str,
    *,
    evidence_fingerprint: str,
    blocker_level: str = "important",
    module: str = "",
    signal: str = "",
    source_id: str = "",
    actor: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Append one audited internal-check action and return the stored event."""
    event = _build_check_event(
        clarification_id,
        action,
        evidence_fingerprint=evidence_fingerprint,
        blocker_level=blocker_level,
        module=module,
        signal=signal,
        source_id=source_id,
        actor=actor,
        note=note,
    )
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / CHECK_STATES_FILE
    with clarification_check_state_lock(root):
        history = _read_history_unlocked(path)
        history.append(event)
        _atomic_write_history(path, history)
    return event


def apply_clarification_check_actions_batch(
    out_dir: Path,
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append a validated batch under one cross-process lock and one atomic replace."""
    events = [
        _build_check_event(
            row.get("clarification_id"),
            row.get("action"),
            evidence_fingerprint=row.get("evidence_fingerprint"),
            blocker_level=row.get("blocker_level") or "important",
            module=row.get("module") or "",
            signal=row.get("signal") or "",
            source_id=row.get("source_id") or "",
            actor=row.get("actor"),
            note=row.get("note") or "",
        )
        for row in actions
    ]
    if not events:
        return []
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / CHECK_STATES_FILE
    with clarification_check_state_lock(root):
        history = _read_history_unlocked(path)
        history.extend(events)
        _atomic_write_history(path, history)
    return events


def _build_check_event(
    clarification_id: Any,
    action: Any,
    *,
    evidence_fingerprint: Any,
    blocker_level: Any = "important",
    module: Any = "",
    signal: Any = "",
    source_id: Any = "",
    actor: Any = None,
    note: Any = "",
) -> dict[str, Any]:
    clarification_id = str(clarification_id or "").strip()
    action = str(action or "").strip()
    evidence_fingerprint = str(evidence_fingerprint or "").strip()
    blocker_level = str(blocker_level or "").strip()
    module = str(module or "").strip() or DEFAULT_MODULE
    if not clarification_id:
        raise ValueError("clarification_id is required")
    if action not in VALID_CHECK_ACTIONS:
        raise ValueError(f"invalid clarification check action: {action}")
    if not evidence_fingerprint:
        raise ValueError("evidence_fingerprint is required")
    if blocker_level not in VALID_BLOCKER_LEVELS:
        raise ValueError(f"invalid clarification blocker level: {blocker_level}")

    return {
        "clarification_id": clarification_id,
        "action": action,
        # ``state`` is the effective snapshot field consumed by report/API clients. Keep
        # ``action`` as the append-only command name so older readers remain compatible.
        "state": action,
        "evidence_fingerprint": evidence_fingerprint,
        "blocker_level": blocker_level,
        "module": module,
        "signal": str(signal or "").strip(),
        "source_id": str(source_id or "").strip(),
        "actor": str(actor or "").strip() or "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": str(note or "").strip(),
    }


@contextmanager
def clarification_check_state_lock(
    out_dir: Path,
    *,
    timeout_s: float = _LOCK_TIMEOUT_S,
    stale_after_s: float = _LOCK_STALE_AFTER_S,
) -> Iterator[None]:
    """Serialize readers and writers across threads and processes."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _process_lock_for(root):
        lock_path = root / CHECK_STATES_LOCK
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_lock(lock_path, stale_after_s):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for clarification check state lock: {lock_path}"
                    )
                time.sleep(0.01)
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _process_lock_for(out_dir: Path) -> RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(out_dir, RLock())


def _remove_stale_lock(lock_path: Path, stale_after_s: float) -> bool:
    if stale_after_s < 0:
        return False
    try:
        age_s = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True
    if age_s < stale_after_s:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    return True


def _read_history_unlocked(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                LOGGER.warning(
                    "skipping corrupt %s record at line %d", CHECK_STATES_FILE, line_number
                )
                continue
            if not isinstance(row, dict):
                LOGGER.warning(
                    "skipping non-object %s record at line %d", CHECK_STATES_FILE, line_number
                )
                continue
            rows.append(row)
    return rows


def _atomic_write_history(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)
