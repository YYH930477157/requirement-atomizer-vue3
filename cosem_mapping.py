"""Deterministic DLMS/COSEM mapping hints for functional requirements.

The functional extractor deliberately leaves domain interpretation to a later,
reviewable step.  This module provides that step with a small stable contract:
it only reports structure that is already present in the item text (OBIS and
interface class identifiers), never asks an LLM, and never invents a mapping.
Unknown identifiers remain visible as unresolved candidates for a future domain
pack or expert mapping table.
"""
from __future__ import annotations

import re
from typing import Any

from cosem_behavior_spec import extract_codes
from cosem_object_model import class_name_for_id, normalize_obis_value


COSEM_MAPPING_VERSION = "cosem-domain-mapping-v1"
COSEM_MAPPING_SCHEMA = "cosem-domain-mapping/v1"
_CLASS_ID_RE = re.compile(
    r"\b(?:interface\s+class|class\s*id|class_id|CL)\s*[:=]?\s*(\d{1,3})\b",
    re.IGNORECASE,
)
_OBIS_RE = re.compile(r"\d+-\d+:\d+(?:\.[0-9A-Za-z*]+){2,3}")


def _item_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "source_quote", "objective", "description", "behaviors",
        "preconditions", "data_constraints", "variants", "exceptions",
        "related_dlms_objects",
    ):
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(entry) for entry in value if str(entry).strip())
        elif value:
            parts.append(str(value))
    return " ".join(parts)


def map_functional_requirement(item: dict[str, Any]) -> dict[str, Any]:
    """Return auditable, deterministic COSEM mapping candidates for one item.

    ``mapped`` means at least one OBIS or whitelisted class id was resolved;
    ``candidate`` means the text names the protocol but has no resolved
    structure; ``unmapped`` contains no DLMS/COSEM signal.  The latter two are
    intentionally non-blocking and are designed for future expert/domain-pack
    mapping.
    """
    text = _item_text(item)
    codes = extract_codes(text)
    obis: list[str] = []
    for code in sorted(codes):
        if _OBIS_RE.fullmatch(code):
            normalized = normalize_obis_value(code)
            if normalized and normalized not in obis:
                obis.append(normalized)

    class_ids: list[str] = []
    class_names: list[str] = []
    unresolved: list[str] = []
    for match in _CLASS_ID_RE.finditer(text):
        class_id = str(int(match.group(1)))
        if class_id in class_ids:
            continue
        class_ids.append(class_id)
        name = class_name_for_id(class_id)
        if name:
            class_names.append(name)
        else:
            unresolved.append(class_id)

    protocol_signal = bool(re.search(r"\b(?:DLMS|COSEM|xDLMS|OBIS)\b", text, re.IGNORECASE))
    status = "mapped" if obis or class_names else ("candidate" if protocol_signal or unresolved else "unmapped")
    return {
        "schema": COSEM_MAPPING_SCHEMA,
        "version": COSEM_MAPPING_VERSION,
        "domain_pack_id": "dlms_cosem" if status != "unmapped" else None,
        "status": status,
        "obis": obis,
        "class_ids": class_ids,
        "class_names": class_names,
        "unresolved_class_ids": unresolved,
        "source": "deterministic_item_text",
    }


def attach_functional_mappings(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach per-item hints and aggregate counts without changing extraction."""
    items = payload.get("items")
    if not isinstance(items, list):
        return payload
    counts = {"mapped": 0, "candidate": 0, "unmapped": 0}
    for item in items:
        if not isinstance(item, dict):
            continue
        mapping = map_functional_requirement(item)
        item["domain_mapping"] = mapping
        counts[mapping["status"]] = counts.get(mapping["status"], 0) + 1
    payload["domain_mapping"] = {
        "schema": COSEM_MAPPING_SCHEMA,
        "version": COSEM_MAPPING_VERSION,
        "domain_pack_id": "dlms_cosem",
        "counts": counts,
        "blocking": False,
    }
    return payload


__all__ = [
    "COSEM_MAPPING_SCHEMA", "COSEM_MAPPING_VERSION",
    "attach_functional_mappings", "map_functional_requirement",
]
