from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    if status not in EXPERT_DECISION_STATUSES:
        raise ValueError(f"Unknown review status: {status}")
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    states_path = out_dir / "review_states.jsonl"
    events_path = out_dir / "review_state_events.jsonl"

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
    if event is not None:
        _append_review_state_event(events_path, states[state_index], event)
    return states[state_index]


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


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


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
