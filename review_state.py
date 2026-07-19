from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator


# 仅约束自动化路径（llm_pipeline 的 transition()）。专家入口 apply_expert_decision
# 是覆盖式裁决，不受此表约束——见其 docstring。
VALID_TRANSITIONS = {
    "candidate": {"llm_reviewed", "rejected"},
    "llm_reviewed": {"expert_pending", "accepted", "flagged", "rejected"},
    "expert_pending": {"accepted", "rejected", "needs_discussion", "needs_rework"},
    "needs_discussion": {"expert_pending", "rejected"},
    "needs_rework": {"candidate", "llm_reviewed"},
    "flagged": {"expert_pending", "rejected"},
    "accepted": {"frozen"},
    "rejected": set(),
    "frozen": set(),
}

EXPERT_DECISION_STATUSES = {"accepted", "rejected", "needs_discussion", "expert_pending"}
EXPERT_ACTORS = {"expert", "vue3-test", "gui", "vue3-ui"}
_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.02


@dataclass
class ReviewEvent:
    from_status: str
    to_status: str
    actor: str
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RequirementReviewState:
    requirement_id: str
    status: str = "candidate"
    history: list[ReviewEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, to_status: str, *, actor: str, reason: str) -> None:
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if to_status not in allowed:
            raise ValueError(f"Invalid transition: {self.status} -> {to_status}")
        event = ReviewEvent(from_status=self.status, to_status=to_status, actor=actor, reason=reason)
        self.history.append(event)
        self.status = to_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "status": self.status,
            "history": [event.__dict__ for event in self.history],
            "metadata": self.metadata,
        }


def apply_expert_decision(
    out_dir: Path,
    requirement_id: str,
    status: str,
    *,
    actor: str,
    reason: str = "",
) -> dict[str, Any]:
    """专家覆盖式裁决：决策状态间可自由改判（含 accepted→rejected、rejected→
    expert_pending 重审），这是有意语义——专家是权威裁决方，VALID_TRANSITIONS
    只约束自动化 LLM 路径。唯一禁止的跳转是从 frozen 改出（须显式解冻流程，
    不属于本入口）。每次改判都追加 history（actor/reason/timestamp），审计链完整。
    """
    if status not in EXPERT_DECISION_STATUSES:
        raise ValueError(f"Unknown review status: {status}")
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    states_path = out_dir / "review_states.jsonl"
    events_path = out_dir / "review_state_events.jsonl"

    with review_state_lock(out_dir):
        states = _read_jsonl(states_path)
        state_index = _find_state_index(states, requirement_id)
        if state_index is None:
            state = RequirementReviewState(requirement_id)
            states.append(state.to_dict())
            state_index = len(states) - 1
        else:
            state = _state_from_dict(states[state_index])

        if state.status == "frozen" and status != "frozen":
            raise ValueError("Cannot override frozen review state")

        event: dict[str, Any] | None = None
        if state.status != status:
            review_event = ReviewEvent(from_status=state.status, to_status=status, actor=actor, reason=reason)
            state.history.append(review_event)
            state.status = status
            event = review_event.__dict__
        states[state_index] = state.to_dict()

        _atomic_write_jsonl(states_path, states)
        result = states[state_index]
        if event is not None:
            try:
                _append_review_state_event(events_path, result, event)
            except OSError as exc:
                # state.history 已原子提交，是权威审计记录；事件 JSONL 只是投影。
                # 此时返回 503 会诱导同状态重试，而重试不会产生新 transition。
                import logging
                logging.getLogger("requirement_atomizer").warning(
                    "裁决状态已保存，但事件日志追加失败：%s", exc)
                result = dict(result)
                result["audit_warning"] = "裁决已保存，但独立事件日志写入失败；完整历史仍保存在状态文件中"
        return result


def merge_review_states(
    existing_states: list[dict[str, Any]],
    generated_states: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = [dict(state) for state in generated_states]
    for existing in existing_states:
        existing_state = _state_from_dict(existing).to_dict()
        index = _find_matching_state_index(merged, existing_state)
        if index is None:
            merged.append(existing_state)
            continue
        if is_expert_controlled(existing_state) or str(existing_state.get("status") or "") == "frozen":
            merged[index] = _merge_state_payload(merged[index], existing_state)
        else:
            merged[index] = _merge_history(merged[index], existing_state)
    return merged


def is_expert_controlled(state: dict[str, Any]) -> bool:
    for event in state.get("history", []) or []:
        if not isinstance(event, dict):
            continue
        actor = str(event.get("actor") or "")
        if actor in EXPERT_ACTORS or actor.startswith("expert") or actor.startswith("user:") or actor.endswith("-ui"):
            return True
    return False


def _find_matching_state_index(states: list[dict[str, Any]], needle: dict[str, Any]) -> int | None:
    for key in requirement_identity_keys(needle):
        index = _find_state_index(states, key)
        if index is not None:
            return index
    return None


def _merge_state_payload(generated: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    metadata = dict(generated.get("metadata") or {})
    metadata.update(dict(existing.get("metadata") or {}))
    merged["metadata"] = metadata
    merged["history"] = _dedupe_history(existing.get("history") or [])
    return merged


def _merge_history(generated: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(generated)
    metadata = dict(existing.get("metadata") or {})
    metadata.update(dict(generated.get("metadata") or {}))
    merged["metadata"] = metadata
    merged["history"] = _dedupe_history([
        *(existing.get("history") or []),
        *(generated.get("history") or []),
    ])
    return merged


def _dedupe_history(events: list[Any]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = dict(event)
        key = review_event_key(payload)
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def requirement_identity_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for name in ("requirement_id", "stable_req_id", "req_id"):
        value = row.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    for name in ("stable_req_id", "req_id"):
        value = metadata.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    return keys


def _find_state_index(states: list[dict[str, Any]], requirement_id: str) -> int | None:
    for index, state in enumerate(states):
        if str(state.get("requirement_id") or "") == requirement_id:
            return index
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        if requirement_id in {str(metadata.get("stable_req_id") or ""), str(metadata.get("req_id") or "")}:
            return index
    return None


def _state_from_dict(payload: dict[str, Any]) -> RequirementReviewState:
    state = RequirementReviewState(
        str(payload.get("requirement_id") or ""),
        status=str(payload.get("status") or "candidate"),
        metadata=dict(payload.get("metadata") or {}),
    )
    state.history = [
        ReviewEvent(
            from_status=str(event.get("from_status") or ""),
            to_status=str(event.get("to_status") or ""),
            actor=str(event.get("actor") or ""),
            reason=str(event.get("reason") or ""),
            timestamp=str(event.get("timestamp") or ""),
        )
        for event in payload.get("history", [])
        if isinstance(event, dict)
    ]
    return state


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@contextmanager
def review_state_lock(out_dir: Path, *, timeout_s: float = 10.0, stale_after_s: float = 300.0) -> Iterator[None]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock_for(out_dir)
    with process_lock:
        lock_path = out_dir / "review_states.lock"
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_lock(lock_path, stale_after_s):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for review state lock: {lock_path}")
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


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _replace_with_retry(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _replace_with_retry(source: Path, target: Path) -> None:
    """Retry short-lived Windows sharing violations without weakening atomic replacement."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _append_review_state_event(path: Path, state: dict[str, Any], event: dict[str, Any]) -> None:
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    row = {
        "requirement_id": state.get("requirement_id"),
        "req_id": metadata.get("req_id"),
        "stable_req_id": metadata.get("stable_req_id"),
        "status_after": event.get("to_status"),
        "current_status": state.get("status"),
        **event,
    }
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def review_event_key(event: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(event.get("timestamp") or ""),
        str(event.get("from_status") or ""),
        str(event.get("to_status") or ""),
        str(event.get("actor") or ""),
        str(event.get("reason") or ""),
    )
