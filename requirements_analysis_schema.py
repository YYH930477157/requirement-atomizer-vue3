from __future__ import annotations

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


def apply_ownership_override(item: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    updated = deepcopy(item)
    if not state or not state.get("ownership_override"):
        return updated

    original_ownership = updated.get("ownership")
    override_ownership = normalize_ownership(state["ownership_override"])
    updated["ownership"] = override_ownership
    updated["ownership_source"] = "reviewer_override"
    updated["ownership_confidence"] = 1.0

    if original_ownership != override_ownership:
        notes = updated.setdefault("notes", [])
        reason = state.get("reason")
        message = "规则或 LLM 判断被人工归属覆盖"
        if reason:
            message = f"{message}: {reason}"
        notes.append(message)

    return updated


def validate_analysis_item(item: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    analysis_id = str(item.get("analysis_id") or "")
    if not analysis_id.startswith("ANREQ-"):
        issues.append("analysis_id must start with ANREQ-")

    try:
        normalize_ownership(item.get("ownership"))
    except ValueError as exc:
        issues.append(str(exc))

    if not item.get("source_requirement_ids"):
        issues.append("source_requirement_ids is required")
    if not item.get("source_block_ids"):
        issues.append("source_block_ids is required")

    return issues
