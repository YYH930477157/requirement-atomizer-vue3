from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_index(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def lookup_class(index: dict[str, Any] | None, class_id: int | str) -> dict[str, Any] | None:
    if not isinstance(index, dict):
        return None
    classes = index.get("interface_classes")
    if not isinstance(classes, dict):
        return None
    return classes.get(str(class_id))


def lookup_class_by_name(index: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not isinstance(index, dict):
        return None
    classes = index.get("interface_classes")
    if not isinstance(classes, dict):
        return None
    needle = str(name or "").strip().casefold()
    if not needle:
        return None
    for entry in classes.values():
        if isinstance(entry, dict) and str(entry.get("name") or "").strip().casefold() == needle:
            return entry
    return None


def condensed_text(entry: dict[str, Any], max_chars: int = 4000) -> str:
    text = str(entry.get("text") or "") if isinstance(entry, dict) else ""
    if not text:
        return ""
    max_chars = max(80, int(max_chars))
    if len(text) <= max_chars:
        return text

    section = str(entry.get("section") or "").strip() or "?"
    suffix = f"\n...(节选，完整定义见 Blue Book §{section})"
    head_len = max(0, max_chars - len(suffix))
    return text[:head_len].rstrip() + suffix
