from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

OWNERSHIP_SOFTWARE = "software"
OWNERSHIP_HARDWARE = "hardware"
OWNERSHIP_CO_DESIGN = "co_design"
VALID_OWNERSHIPS = {
    OWNERSHIP_SOFTWARE,
    OWNERSHIP_HARDWARE,
    OWNERSHIP_CO_DESIGN,
}


def normalize_ownership(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "软件": OWNERSHIP_SOFTWARE,
        "硬件": OWNERSHIP_HARDWARE,
        "软硬件协同": OWNERSHIP_CO_DESIGN,
        "software": OWNERSHIP_SOFTWARE,
        "hardware": OWNERSHIP_HARDWARE,
        "co_design": OWNERSHIP_CO_DESIGN,
        "codesign": OWNERSHIP_CO_DESIGN,
    }
    normalized = aliases.get(text)
    if normalized in VALID_OWNERSHIPS:
        return normalized
    raise ValueError(f"unknown ownership: {value}")


def build_analysis_id(index: int) -> str:
    return f"ANREQ-{index:06d}"


def _state_value(state: Any, key: str) -> Any:
    if isinstance(state, dict):
        return state.get(key)
    return getattr(state, key, None)


def _normalize_notes(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [str(value)]


def apply_ownership_override(item: dict[str, Any], state: Any) -> dict[str, Any]:
    updated = deepcopy(item)
    ownership_override = _state_value(state, "ownership_override")
    if not state or not ownership_override:
        return updated

    original_ownership = updated.get("ownership")
    override_ownership = normalize_ownership(ownership_override)
    updated["ownership"] = override_ownership
    updated["ownership_source"] = "reviewer_override"
    updated["ownership_confidence"] = 1.0

    if original_ownership:
        try:
            original_ownership = normalize_ownership(original_ownership)
        except ValueError:
            pass

    if original_ownership and original_ownership != override_ownership:
        notes = _normalize_notes(updated.get("notes"))
        reason = _state_value(state, "reason")
        message = "规则或 LLM 判断被人工归属覆盖"
        if reason:
            message = f"{message}: {reason}"
        notes.append(message)
        updated["notes"] = notes

    return updated


def validate_analysis_item(item: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    analysis_id = str(item.get("analysis_id") or "")
    if not re.fullmatch(r"ANREQ-\d{6}", analysis_id):
        issues.append("analysis_id must match ANREQ-000000")

    try:
        normalize_ownership(item.get("ownership"))
    except ValueError as exc:
        issues.append(str(exc))

    source_requirement_ids = item.get("source_requirement_ids")
    if not source_requirement_ids:
        issues.append("source_requirement_ids is required")
    elif not isinstance(source_requirement_ids, list):
        issues.append("source_requirement_ids must be a list")

    source_block_ids = item.get("source_block_ids")
    if not source_block_ids:
        issues.append("source_block_ids is required")
    elif not isinstance(source_block_ids, list):
        issues.append("source_block_ids must be a list")

    return issues
