"""Validated append-only storage for future agent decision traces."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Iterator

from jsonschema import Draft202012Validator, FormatChecker


DECIDE_TRACE_VERSION = "decide-trace-v1"
DECIDE_TRACE_FILE = "decide_trace.jsonl"
DECIDE_TRACE_SCHEMA = Path(__file__).resolve().parent / "schemas" / "decide_trace.schema.json"

_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = Lock()
_APPEND_ATTEMPTS = 5
_APPEND_RETRY_DELAY_S = 0.02


class DecideTraceValidationError(ValueError):
    """A decision trace does not satisfy the frozen v1 contract."""


def load_decide_trace_schema() -> dict[str, Any]:
    return json.loads(DECIDE_TRACE_SCHEMA.read_text(encoding="utf-8"))


def validate_decide_trace(trace: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trace, dict):
        raise DecideTraceValidationError("Decision trace must be a JSON object.")
    validator = Draft202012Validator(
        load_decide_trace_schema(),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(trace), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(value) for value in error.absolute_path) or "$"
        raise DecideTraceValidationError(f"{location}: {error.message}")
    if trace["action"] not in trace["candidates"]:
        raise DecideTraceValidationError("action: must be one of candidates")
    return trace


def append_decide_trace(out_dir: Path, trace: dict[str, Any]) -> Path:
    validated = validate_decide_trace(trace)
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / DECIDE_TRACE_FILE
    line = json.dumps(validated, ensure_ascii=False, separators=(",", ":")) + "\n"
    with decide_trace_lock(root):
        _append_with_retry(path, line)
    return path


@contextmanager
def decide_trace_lock(
    out_dir: Path,
    *,
    timeout_s: float = 10.0,
    stale_after_s: float = 300.0,
) -> Iterator[None]:
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock_for(root)
    with process_lock:
        lock_path = root / "decide_trace.lock"
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_lock(lock_path, stale_after_s):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for decision trace lock: {lock_path}")
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


def _append_with_retry(path: Path, line: str) -> None:
    for attempt in range(_APPEND_ATTEMPTS):
        try:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            return
        except PermissionError:
            if attempt + 1 >= _APPEND_ATTEMPTS:
                raise
            time.sleep(_APPEND_RETRY_DELAY_S)
