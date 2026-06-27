"""专家审查裁决入口（顶层，被现役 Vue3 后端 `api_server` 与已冻结的 PySide6 `gui/`
共用）。原在 `gui/review_actions.py`，2026-06-27 提升到顶层以解开 API↔GUI 耦合，
使 `gui/`（PySide6，已冻结）成为无人依赖的纯 UI 叶子。"""
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
