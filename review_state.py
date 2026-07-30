from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from process_file_lock import process_file_lock


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
CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION = "claim-authority-write-v1"
ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION = "atomic-target-authority-write-revision-v1"
TARGET_PUBLICATION_REVISION_VERSION = "target-publication-revision-v1"


class ReviewAuthorityConflict(ValueError):
    """The displayed A-track authority row is stale and must be refreshed."""

    def __init__(self, message: str, *, current_revision: str) -> None:
        super().__init__(message)
        self.current_revision = str(current_revision)


def target_publication_revision(path: Path) -> str:
    """Bind an authority write to the exact target publication bytes."""
    from claim_artifacts import hash_json, sha256_bytes

    target = Path(path)
    present = target.is_file()
    raw = target.read_bytes() if present else b""
    return hash_json(
        TARGET_PUBLICATION_REVISION_VERSION,
        {
            "source_store": target.name,
            "source_present": present,
            "source_file_sha256": sha256_bytes(raw),
        },
    )


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
    expected_target_fingerprint: str | None = None,
    expected_target_authority_write_revision: str | None = None,
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
        current_write_revision = atomic_target_authority_write_revision(
            requirement_id,
            states,
        )
        if (
            expected_target_authority_write_revision is not None
            and str(expected_target_authority_write_revision)
            != current_write_revision
        ):
            raise ReviewAuthorityConflict(
                "review authority changed; refresh before adjudicating",
                current_revision=current_write_revision,
            )
        if expected_target_fingerprint is not None:
            binding = _current_atomic_review_binding(out_dir, requirement_id)
            current_target_fingerprint = (
                str(binding.get("review_subject_fingerprint") or "")
                if binding is not None
                else ""
            )
            if current_target_fingerprint != str(expected_target_fingerprint):
                raise ReviewAuthorityConflict(
                    "atomic requirement changed; refresh before adjudicating",
                    current_revision=current_write_revision,
                )
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
            binding = _current_atomic_review_binding(out_dir, requirement_id)
            if binding is None:
                state.metadata["needs_reconfirmation"] = True
            else:
                state.metadata.update({
                    "source_fingerprint": binding["source_fingerprint"],
                    "review_subject_fingerprint": binding[
                        "review_subject_fingerprint"
                    ],
                    "needs_reconfirmation": False,
                })
            review_event = ReviewEvent(from_status=state.status, to_status=status, actor=actor, reason=reason)
            state.history.append(review_event)
            state.status = status
            event = review_event.__dict__
        states[state_index] = state.to_dict()

        _atomic_write_jsonl(states_path, states)
        result = dict(states[state_index])
        result["target_authority_write_revision"] = atomic_target_authority_write_revision(
            requirement_id,
            states,
        )
        if expected_target_fingerprint is not None:
            result["target_fingerprint"] = str(expected_target_fingerprint)
        if event is not None:
            try:
                _append_review_state_event(events_path, result, event)
            except OSError as exc:
                # state.history 已原子提交，是权威审计记录；事件 JSONL 只是投影。
                # 此时返回 503 会诱导同状态重试，而重试不会产生新 transition。
                logging.getLogger("requirement_atomizer").warning(
                    "裁决状态已保存，但事件日志追加失败：%s", exc)
                result = dict(result)
                result["audit_warning"] = "裁决已保存，但独立事件日志写入失败；完整历史仍保存在状态文件中"
    if (out_dir / "claim_generation.meta.json").is_file():
        try:
            from claim_review_actions import fold_effective_ledger

            fold_effective_ledger(
                out_dir,
                actor_trigger="requirement-review-action",
                authority_hook_track="A",
            )
        except Exception as exc:
            # The requirement-level authority is already atomically committed.
            # Effective materialization is derived and may catch up later.
            logging.getLogger("requirement_atomizer").warning(
                "expert decision saved; claim effective fold lagged: %s",
                exc,
            )
    return result


def _current_atomic_review_binding(
    out_dir: Path,
    requirement_id: str,
) -> dict[str, str] | None:
    path = out_dir / "atomic_requirements.jsonl"
    if not path.is_file():
        return None
    matches = [
        row for row in _read_jsonl(path)
        if requirement_id in requirement_identity_keys(row)
    ]
    if len(matches) != 1:
        return None
    from claim_ledger import (
        atomic_target_fingerprint,
        atomic_target_source_fingerprint,
    )

    return {
        "source_fingerprint": atomic_target_source_fingerprint(matches[0]),
        "review_subject_fingerprint": atomic_target_fingerprint(matches[0]),
    }


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


def _empty_review_authority_snapshot(path: Path) -> dict[str, Any]:
    empty_hash = "sha256:" + hashlib.sha256(b"").hexdigest()
    return {
        "source_store": path.name,
        "states": [],
        "source_records": {},
        "ordered_records": [],
        "audit_gaps": [],
        "torn_tail_recovered": False,
        "authority_file_sha256": empty_hash,
    }


def _review_authority_snapshot_from_bytes(path: Path, raw: bytes) -> dict[str, Any]:
    from claim_artifacts import hash_json

    # The A-track state file is atomically replaced, but historical/manual
    # files can still contain a complete corrupt record.  Match the B-track
    # authority contract: preserve every later valid record and make the gap
    # visible to the fold health projection.  An unterminated final record is
    # different: it can be an in-flight write, so callers must retry rather
    # than folding an unstable authority snapshot.
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    state_records: list[tuple[int, int, dict[str, Any]]] = []
    audit_gaps: list[dict[str, Any]] = []
    state_ordinal = 0
    lines = body.splitlines(keepends=True)
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        state_ordinal += 1
        try:
            row = json.loads(stripped.decode("utf-8"))
            if not isinstance(row, dict):
                raise ValueError("record is not an object")
            if not requirement_identity_keys(row):
                raise ValueError("record has no requirement identity")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            is_unterminated_tail = (
                index == len(lines) - 1
                and not raw_line.endswith((b"\n", b"\r"))
            )
            if is_unterminated_tail:
                raise ValueError("review authority has a torn tail") from exc
            audit_gaps.append({
                "physical_line_number": index + 1,
                "state_ordinal": state_ordinal,
                "reason": type(exc).__name__,
                "line_sha256": "sha256:" + hashlib.sha256(raw_line).hexdigest(),
            })
            logging.getLogger("requirement_atomizer").warning(
                "preserving audit gap in review_states.jsonl at physical line %d "
                "(state %d)",
                index + 1,
                state_ordinal,
            )
            continue
        state_records.append((state_ordinal, index + 1, row))

    ordered_records: list[dict[str, Any]] = []
    source_record_candidates: dict[str, list[dict[str, Any]]] = {}
    for state_ordinal, physical_line_number, state in state_records:
        identities = requirement_identity_keys(state)
        requirement_id = str(state.get("requirement_id") or identities[0])
        history = state.get("history")
        if not isinstance(history, list):
            audit_gaps.append({
                "physical_line_number": physical_line_number,
                "state_ordinal": state_ordinal,
                "requirement_id": requirement_id,
                "reason": "history_not_array",
            })
            continue
        if not history and str(state.get("status") or "candidate") != "candidate":
            audit_gaps.append({
                "physical_line_number": physical_line_number,
                "state_ordinal": state_ordinal,
                "requirement_id": requirement_id,
                "reason": "state_without_history",
            })
        for history_index, raw_event in enumerate(history):
            if not isinstance(raw_event, dict) or not str(
                raw_event.get("to_status") or ""
            ):
                audit_gaps.append({
                    "physical_line_number": physical_line_number,
                    "state_ordinal": state_ordinal,
                    "requirement_id": requirement_id,
                    "history_index": history_index,
                    "reason": "invalid_history_event",
                })
                continue
            history_event = dict(raw_event)
            source_event_revision = hash_json(
                "claim-source-event-revision/v1",
                {
                    "source_store": path.name,
                    "requirement_id": requirement_id,
                    "history_index": history_index,
                    "history_event": history_event,
                },
            )
            record = {
                "physical_line_number": physical_line_number,
                "state_ordinal": state_ordinal,
                "requirement_id": requirement_id,
                "identity_keys": identities,
                "history_index": history_index,
                "history_event": history_event,
                "source_event_revision": source_event_revision,
                "state": state,
            }
            ordered_records.append(record)
            for identity in identities:
                source_record_candidates.setdefault(identity, []).append(record)
    source_records = {
        identity: records[-1]
        for identity, records in source_record_candidates.items()
        if records
    }
    return {
        "source_store": path.name,
        "states": [state for _ordinal, _line, state in state_records],
        "source_records": source_records,
        "ordered_records": ordered_records,
        "audit_gaps": audit_gaps,
        "torn_tail_recovered": False,
        "authority_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def read_review_authority_snapshot(out_dir: Path) -> dict[str, Any]:
    """Read A-track state and every embedded history event under its authority lock."""
    root = out_dir.expanduser().resolve()
    path = root / "review_states.jsonl"
    with review_state_lock(root):
        if not path.is_file():
            return _empty_review_authority_snapshot(path)
        return _review_authority_snapshot_from_bytes(path, path.read_bytes())


def read_review_authority_snapshot_readonly(out_dir: Path) -> dict[str, Any]:
    """Read A-track authority without creating or changing a lock sidecar."""
    root = out_dir.expanduser().resolve()
    path = root / "review_states.jsonl"
    before = path.read_bytes() if path.is_file() else None
    snapshot = (
        _empty_review_authority_snapshot(path)
        if before is None
        else _review_authority_snapshot_from_bytes(path, before)
    )
    after = path.read_bytes() if path.is_file() else None
    if after != before:
        raise ValueError("review authority changed during read-only read")
    return snapshot


def atomic_target_authority_write_revision(
    requirement_id: str,
    snapshot_or_states: dict[str, Any] | list[dict[str, Any]],
) -> str:
    """Return the physical per-target A-track write revision.

    ``target_review_revision`` is a semantic projection and intentionally ignores
    timestamps/reasons.  This CAS token instead binds every matching state row,
    its physical ordinal, the complete current row hash, and the full history
    prefix hash.  Consequently an ABA sequence (accepted -> rejected -> accepted)
    cannot reuse the original token.
    """
    from claim_artifacts import hash_json

    if isinstance(snapshot_or_states, dict):
        states = snapshot_or_states.get("states") or []
    else:
        states = snapshot_or_states
    wanted = str(requirement_id or "").strip()
    bindings: list[dict[str, Any]] = []
    for ordinal, raw_state in enumerate(states, start=1):
        if not isinstance(raw_state, dict):
            continue
        if wanted not in requirement_identity_keys(raw_state):
            continue
        history = raw_state.get("history")
        history = history if isinstance(history, list) else []
        bindings.append({
            "state_ordinal": ordinal,
            "state_row_hash": hash_json(
                f"{ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION}:row",
                raw_state,
            ),
            "history_prefix_hash": hash_json(
                f"{ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION}:history",
                history,
            ),
        })
    return hash_json(
        ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION,
        {
            "source_store": "review_states.jsonl",
            "target_kind": "atomic_requirement",
            "target_requirement_id": wanted,
            "bindings": bindings,
        },
    )


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
        del stale_after_s
        with process_file_lock(
            lock_path,
            timeout_s=timeout_s,
            label="review state lock",
        ):
            yield


def _process_lock_for(out_dir: Path) -> RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(out_dir, RLock())


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
