"""Append-only audit states for internal clarification checks.

The state file is shared by the desktop process, API server, and report
generator.  Writes therefore use a cross-process lock and atomic replacement;
the latest event for each clarification id is the effective state.

队列收敛第 2 步（设计 §4.3）：写路径改为队列先落——单一 ``review_queue``
跨进程锁内先 append 统一评审事件链 ``review_queue_events.jsonl``
（subject_kind=clarification_internal），再按与旧 writer 逐字节相同的行形状
投影回本文件；旧 ``clarification_check_states.lock`` O_EXCL 协议退役为新写
路径不再使用（读者仍持它，旧包遗留 sidecar 不删）。读侧 ``evidence_fingerprint``
失效逻辑一字不动；按设计 §4.2 补 ``expected_evidence_fingerprint`` 写时 CAS
（未传该指纹的调用路径——xlsx 导入等——保持旧行为不拦）。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

import review_queue
from result_package import governed_artifact_path


CHECK_STATES_FILE = "clarification_check_states.jsonl"
CHECK_STATES_LOCK = "clarification_check_states.lock"
VALID_CHECK_ACTIONS = {"verified_ok", "issue_confirmed", "deferred"}
VALID_BLOCKER_LEVELS = {"blocking", "important"}
DEFAULT_MODULE = "未归属"

_LOCK_TIMEOUT_S = 10.0
_LOCK_STALE_AFTER_S = 300.0
_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
LOGGER = logging.getLogger("requirement_atomizer")


class ClarificationCheckConflictError(ValueError):
    """``expected_evidence_fingerprint`` 写时 CAS 失配（设计 §4.2）。

    调用方声明了它的裁决所依据的证据指纹，而当前报告代里该澄清问题的
    ``evidence_fingerprint`` 已不同（或该问题已不在当前报告）——裁决基于过期
    证据，拒绝落账。API 侧映射结构化 409（needs_reconfirmation）。
    """


def read_clarification_check_history(out_dir: Path) -> list[dict[str, Any]]:
    """Read valid audit events in file order; corrupt historical lines are skipped."""
    root = Path(out_dir).expanduser().resolve()
    with clarification_check_state_lock(root):
        return _read_history_unlocked(
            governed_artifact_path(root, CHECK_STATES_FILE, category="state")
        )


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
    expected_evidence_fingerprint: str = "",
    idempotency_key: str = "",
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
    stored = _append_check_events(out_dir, [event], {
        str(event["clarification_id"]): str(expected_evidence_fingerprint or "").strip(),
    }, {
        str(event["clarification_id"]): str(idempotency_key or "").strip(),
    })
    return stored[0]


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
    expected_by_id = {
        str(event["clarification_id"]): str(row.get("expected_evidence_fingerprint") or "").strip()
        for event, row in zip(events, actions)
    }
    idempotency_by_id = {
        str(event["clarification_id"]): str(row.get("idempotency_key") or "").strip()
        for event, row in zip(events, actions)
    }
    return _append_check_events(out_dir, events, expected_by_id, idempotency_by_id)


def _append_check_events(
    out_dir: Path,
    events: list[dict[str, Any]],
    expected_by_id: dict[str, str],
    idempotency_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    """Queue-first dual write: 队列事件先落，旧文件投影后落，单一队列锁内。

    - 先补齐历史事件的投影（崩溃窗口闭合）；
    - ``expected_evidence_fingerprint`` 写时 CAS 全部通过才动账（整批原子，
      与旧行为"一锁一次替换"一致）；未声明的调用路径不拦；
    - 幂等键命中返回既有事件并不再投影（重放不重复记账）。
    """
    root = Path(out_dir).expanduser().resolve()
    path = governed_artifact_path(root, CHECK_STATES_FILE, category="state")
    with review_queue.review_queue_lock(root):
        snapshot = review_queue.scan_review_queue_unlocked(root)
        history = _project_missing_check_rows(path, snapshot)
        _enforce_expected_evidence_fingerprints(root, expected_by_id)
        drafts = []
        for event in events:
            cid = str(event["clarification_id"])
            key = idempotency_by_id.get(cid) or (
                f"clarification_internal:{cid}:{uuid.uuid4().hex}"
            )
            drafts.append({
                "subject_kind": review_queue.SUBJECT_KIND_CLARIFICATION_INTERNAL,
                "subject_id": cid,
                "subject_fingerprint": str(event["evidence_fingerprint"]),
                "idempotency_key": key,
                "event_kind": "deferred" if event["action"] == "deferred" else "decided",
                "actor": str(event.get("actor") or ""),
                "recorded_at": str(event["timestamp"]),
                "reason": str(event.get("note") or ""),
                "payload": event,
            })
        results = review_queue.append_review_queue_events_unlocked(root, snapshot, drafts)
        stored: list[dict[str, Any]] = []
        for event, (queued, replayed) in zip(events, results):
            if replayed:
                stored.append(dict(queued["payload"]))
                continue
            history.append(event)
            stored.append(event)
        _atomic_write_history(path, history)
    return stored


def _project_missing_check_rows(
    path: Path,
    snapshot: review_queue.ReviewQueueSnapshot,
) -> list[dict[str, Any]]:
    """崩溃窗口补投影：返回补齐后的完整历史（含既有行 + 补写行）。"""
    store_events = [
        row for row in snapshot.rows
        if row.get("legacy_source_store") == CHECK_STATES_FILE
    ]
    history = _read_history_unlocked(path)
    if not store_events:
        return history
    missing = review_queue.missing_projection_payloads(store_events, history)
    for row in missing:
        history.append(row)
    if missing:
        _atomic_write_history(path, history)
    return history


def _enforce_expected_evidence_fingerprints(
    root: Path,
    expected_by_id: dict[str, str],
) -> None:
    """Write-time CAS（设计 §4.2）：调用方声明的期望指纹 ≠ 当前报告代即拒绝。

    权威 = 当前报告生成器（``clarification_report.collect_questions``）——与
    omission 写时 CAS 用 blocks.jsonl 重算源指纹同构。惰性 import 避免
    clarification_report ↔ clarification_check_states 的模块加载环。未声明
    （空串）的调用路径保持旧行为不拦；读侧 ``evidence_fingerprint`` 失效逻辑
    一字不动。整批在任何写入之前校验（all-or-nothing）。
    """
    pending = {
        cid: expected for cid, expected in expected_by_id.items() if expected
    }
    if not pending:
        return
    from clarification_report import collect_questions

    current: dict[str, str] = {}
    for entry in collect_questions(root):
        cid = str(entry.get("clarification_id") or "")
        if cid:
            current[cid] = str(entry.get("evidence_fingerprint") or "")
    for cid, expected in pending.items():
        if cid not in current:
            raise ClarificationCheckConflictError(
                "clarification no longer exists in the current report; refresh before confirming"
            )
        if current[cid] != expected:
            raise ClarificationCheckConflictError(
                "clarification evidence changed; refresh before confirming"
            )


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
    """Serialize readers across threads and processes.

    队列收敛第 2 步：新写路径已迁至 ``review_queue.review_queue_lock``（本锁退役
    为写路径不再使用）；读侧仍持本锁与旧包遗留 sidecar 兼容。
    """
    root = Path(out_dir).expanduser().resolve()
    lock_path = governed_artifact_path(root, CHECK_STATES_LOCK, category="state")
    with _process_lock_for(lock_path.parent):
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
        # 单源退避（设计 §5.2）：投影替换与队列文件共用 review_queue 的 8 次线性重试。
        review_queue.replace_with_retry(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
