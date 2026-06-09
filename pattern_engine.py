from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RequirementPattern:
    pattern_id: str
    name: str
    generic_type: str
    domain_type: str
    trigger: dict[str, Any]
    template: str
    object_template: str
    verification_method: str
    default_confidence: float


def load_requirement_patterns(path: Path) -> list[RequirementPattern]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    patterns: list[RequirementPattern] = []
    for raw in payload.get("patterns", []):
        patterns.append(
            RequirementPattern(
                pattern_id=str(raw["pattern_id"]),
                name=str(raw.get("name") or raw["pattern_id"]),
                generic_type=str(raw.get("generic_type") or "domain_specific"),
                domain_type=str(raw.get("domain_type") or raw["pattern_id"]),
                trigger=dict(raw.get("trigger") or {}),
                template=str(raw.get("template") or ""),
                object_template=str(raw.get("object") or ""),
                verification_method=str(raw.get("verification_method") or "inspection"),
                default_confidence=float(raw.get("default_confidence", 0.75)),
            )
        )
    return patterns


def apply_requirement_patterns(source: dict[str, Any], patterns: list[RequirementPattern]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern in patterns:
        if not pattern_matches(source, pattern):
            continue
        rows.append(
            {
                "pattern_id": pattern.pattern_id,
                "generic_type": pattern.generic_type,
                "requirement_type": pattern.domain_type,
                "object": render_template(pattern.object_template, source),
                "requirement": render_template(pattern.template, source),
                "verification_method": pattern.verification_method,
                "confidence": pattern.default_confidence,
            }
        )
    return rows


def pattern_matches(source: dict[str, Any], pattern: RequirementPattern) -> bool:
    trigger = pattern.trigger
    source_type = trigger.get("source_type")
    if source_type and source.get("source_type") != source_type:
        return False

    for field in trigger.get("required_fields", []):
        if not resolve_path(source, field):
            return False

    for field, expected in (trigger.get("field_equals") or {}).items():
        if str(resolve_path(source, field)) != str(expected):
            return False

    return True


def render_template(template: str, source: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = resolve_path(source, match.group(1).strip())
        return "" if value is None else str(value)

    return re.sub(r"\{([^{}]+)\}", replace, template).strip()


def resolve_path(source: dict[str, Any], path: str) -> Any:
    current: Any = source
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
