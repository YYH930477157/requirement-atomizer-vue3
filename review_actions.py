"""专家审查裁决入口，被现役 Vue3/Electron 后端 API 共用。"""
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
    expected_target_fingerprint: str | None = None,
    expected_target_authority_write_revision: str | None = None,
) -> dict[str, Any]:
    return apply_expert_decision(
        out_dir,
        requirement_id,
        status,
        actor=actor or getpass.getuser(),
        reason=reason,
        expected_target_fingerprint=expected_target_fingerprint,
        expected_target_authority_write_revision=expected_target_authority_write_revision,
    )
