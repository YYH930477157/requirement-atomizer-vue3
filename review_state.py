from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
