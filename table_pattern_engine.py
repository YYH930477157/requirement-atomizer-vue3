from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TablePattern:
    pattern_id: str
    generic_type: str
    raw: dict[str, Any]


def load_table_patterns(path: Path) -> list[TablePattern]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        TablePattern(
            pattern_id=str(raw["pattern_id"]),
            generic_type=str(raw.get("generic_type") or "unknown"),
            raw=dict(raw),
        )
        for raw in payload.get("patterns", [])
    ]


def match_table_pattern(table: dict[str, Any], patterns: list[TablePattern]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    headers = normalize_headers(table.get("headers", []))
    title = str(table.get("table_title") or table.get("title") or "")
    for pattern in patterns:
        score = score_pattern(headers, title, pattern.raw)
        if score <= 0:
            continue
        matches.append(
            {
                "pattern_id": pattern.pattern_id,
                "generic_type": pattern.generic_type,
                "score": score,
            }
        )
    matches.sort(key=lambda row: (-row["score"], row["pattern_id"]))
    return matches


def score_pattern(headers: set[str], title: str, pattern: dict[str, Any]) -> int:
    score = 0
    required_headers = pattern.get("required_headers") or []
    if required_headers:
        normalized_required = {normalize_header(header) for header in required_headers}
        if not normalized_required.issubset(headers):
            return 0
        score += 50 + len(normalized_required)

    header_indicators = pattern.get("header_indicators") or []
    indicator_hits = sum(1 for indicator in header_indicators if normalize_header(indicator) in headers)
    if header_indicators and indicator_hits == 0:
        return 0
    score += indicator_hits * 10

    value_indicators = pattern.get("value_indicators") or []
    title_low = title.lower()
    score += sum(5 for value in value_indicators if str(value).lower() in title_low)
    return score


def normalize_headers(headers: list[str]) -> set[str]:
    normalized = {normalize_header(header) for header in headers}
    expanded: set[str] = set(normalized)
    for header in headers:
        parts = [part.strip() for part in str(header).split("/") if part.strip()]
        expanded.update(normalize_header(part) for part in parts)
    return {value for value in expanded if value}


def normalize_header(value: str) -> str:
    return " ".join(str(value).lower().replace("_", " ").replace("-", " ").split())
