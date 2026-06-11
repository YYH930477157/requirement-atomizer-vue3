from __future__ import annotations

import getpass
from pathlib import Path
from typing import Any

from review_state import apply_expert_decision


def apply_review_action(
    out_dir: Path,
    requirement_id: str,
    status: str,
    *,
    actor: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return apply_expert_decision(out_dir, requirement_id, status, actor=actor or getpass.getuser(), reason=reason)
