from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


def _initialize_lock_file(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_owner(handle: BinaryIO, nonce: str) -> None:
    payload = json.dumps(
        {"pid": os.getpid(), "nonce": nonce},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    handle.seek(0)
    handle.write(payload)
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


@contextmanager
def process_file_lock(path: Path, *, timeout_s: float, label: str) -> Iterator[None]:
    """Acquire a stable OS lock without guessing liveness from file age.

    The lock file intentionally remains on disk. Unlinking a lock inode after release
    permits waiters and new openers to lock different files during the unlink/open race.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(fd, "r+b", buffering=0)
    _initialize_lock_file(handle)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    acquired = False
    nonce = uuid.uuid4().hex
    try:
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for {label}: {path}")
            time.sleep(0.01)
        acquired = True
        _write_owner(handle, nonce)
        yield
    finally:
        try:
            if acquired:
                _unlock(handle)
        finally:
            handle.close()
