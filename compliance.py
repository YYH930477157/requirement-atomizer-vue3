"""Deterministic compliance requirement classification and projection."""
from __future__ import annotations

import re
from typing import Any


COMPLIANCE_TYPE = "compliance"
COMPLIANCE_SCHEMA = "compliance-requirements/v1"

_COMPLIANCE_PHRASE_RE = re.compile(
    r"\b(?:"
    r"valid\s+(?:type\s+)?certificate|"
    r"certificate\s+(?:according|required|of)|"
    r"declaration\s+of\s+conformity|"
    r"legal\s+requirements?|"
    r"metrological\s+legislation|"
    r"national\s+(?:metrological\s+)?legislation|"
    r"verification\s+period|"
    r"decree\s+(?:no\.?\s*)?\d[0-9A-Z./-]*(?:\s+Coll\.)?|"
    r"act\s+\d+[/-]\d+|"
    r"laws?\s+in\s+force|"
    r"governed\s+by\s+the\s+laws?|"
    r"standards?,\s*regulations?\s+and\s+requirements?"
    r")\b",
    re.IGNORECASE,
)
_COMPLY_WITH_LAW_RE = re.compile(
    r"\b(?:shall|must|is\s+required\s+to)\s+(?:"
    r"meet\s+the\s+legal\s+requirements|"
    r"comply\s+with\b.{0,100}\b(?:metrological\s+legislation|laws?\s+in\s+force)"
    r")\b",
    re.IGNORECASE,
)
_INSTRUMENT_RE = re.compile(
    r"\b(?:STN\s+EN|EN|IEC|ISO|OIML|Act|Decree|Regulation)\s+"
    r"(?:No\.\s*)?(?:\(EU\)\s*)?\d[0-9A-Z./-]*(?:\s+Coll\.)?",
    re.IGNORECASE,
)
_TECHNICAL_ACTION_AFTER_MODAL_RE = re.compile(
    r"\b(?:shall|must|is\s+required\s+to)\b[^.!?;\n]{0,140}\b(?:"
    r"measure(?:s|d|ment)?|record(?:s|ed|ing)?|store(?:s|d|ing)?|"
    r"display(?:s|ed|ing)?|communicat(?:e|es|ed|ing|ion)|support(?:s|ed|ing)?|"
    r"withstand(?:s|ing)?|show\s+resistance|resist(?:s|ed|ance|ant)?|"
    r"detect(?:s|ed|ing)?|calculat(?:e|es|ed|ing|ion)|control(?:s|led|ling)?|"
    r"disconnect(?:s|ed|ing)?|transmit(?:s|ted|ting)?|receiv(?:e|es|ed|ing)|"
    r"log(?:s|ged|ging)?|monitor(?:s|ed|ing)?|perform(?:s|ed|ing)?\s+tests?"
    r")\b",
    re.IGNORECASE,
)
_TECHNICAL_SUBJECT_LOCATION_OR_CONTENT_RE = re.compile(
    r"\b(?:electricity\s+meter|meter|device|type\s+plate|nameplate|display|enclosure|"
    r"terminal(?:\s+cover)?|modem)\b[^.!?;\n]{0,120}"
    r"\b(?:shall|must|is\s+required\s+to)\b[^.!?;\n]{0,80}"
    r"\b(?:locat(?:e|es|ed|ing|ion)|contain(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
_COMPLIANCE_UNIT_SPLIT_RE = re.compile(r"(?:\r?\n+|(?<=[.!?])\s+(?=[A-Z]))")
_CERTIFICATE_DECLARATION_LIST_RE = re.compile(
    r"(?:certificate\b.{0,100}\b(?:and|or)\b.{0,100}\bdeclaration\s+of\s+conformity|"
    r"declaration\s+of\s+conformity\b.{0,100}\b(?:and|or)\b.{0,100}\bcertificate)",
    re.IGNORECASE,
)


def _compact(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def requirement_source_text(requirement: dict[str, Any]) -> str:
    """Return provenance text only; generated narrative must not decide delivery routing."""
    values = [str(requirement.get("source_quote") or "")]
    values.extend(str(value or "") for value in (requirement.get("source_quotes") or []))
    for evidence in requirement.get("evidence") or []:
        if isinstance(evidence, dict):
            values.append(str(evidence.get("source_quote") or ""))
    return "\n".join(value for value in values if value.strip())


def contains_compliance_signal(text: Any) -> bool:
    value = str(text or "")
    return bool(_COMPLIANCE_PHRASE_RE.search(value) or _COMPLY_WITH_LAW_RE.search(value))


def looks_like_compliance(text: Any) -> bool:
    """Return true only when a whole source unit can safely leave the technical core."""
    value = str(text or "")
    return (
        contains_compliance_signal(value)
        and not _TECHNICAL_ACTION_AFTER_MODAL_RE.search(value)
        and not _TECHNICAL_SUBJECT_LOCATION_OR_CONTENT_RE.search(value)
    )


def is_compliance_requirement(requirement: dict[str, Any]) -> bool:
    source = requirement_source_text(requirement)
    # A certificate sentence appended to a technical requirement does not turn the entire
    # requirement into a compliance deliverable. Generated type/title/description are excluded
    # from this decision; only source evidence can move an item out of core.
    return looks_like_compliance(source)


def is_compliance_umbrella_source(source_quote: Any) -> bool:
    """Derive umbrella structure only from multiple source-backed compliance obligations."""
    source = str(source_quote or "")
    units = [
        unit.strip() for unit in _COMPLIANCE_UNIT_SPLIT_RE.split(source)
        if unit.strip() and contains_compliance_signal(unit)
    ]
    return len(units) > 1 or bool(_CERTIFICATE_DECLARATION_LIST_RE.search(source))


def resolve_source_backed_instrument(value: Any, source_quote: Any) -> tuple[str, str]:
    """Resolve one literal instrument and return an audit note when selection is unsafe."""
    source = str(source_quote or "")
    candidate = str(value or "").strip()
    candidate_match = _INSTRUMENT_RE.fullmatch(candidate.rstrip(",;:")) if candidate else None
    if candidate_match and _compact(candidate) in _compact(source):
        return candidate.rstrip(".,;:"), ""
    if candidate:
        return "", f"合规依据未采纳：{candidate[:80]} 未能逐字锚定到原文"

    matches: list[str] = []
    seen: set[str] = set()
    for match in _INSTRUMENT_RE.finditer(source):
        instrument = match.group(0).strip().rstrip(".,;:")
        key = _compact(instrument)
        if key and key not in seen:
            seen.add(key)
            matches.append(instrument)
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return "", "合规依据未自动选择：原文存在多个法规或标准号"
    return "", ""


def source_backed_instrument(value: Any, source_quote: Any) -> str:
    """Validate an explicit instrument without deriving a replacement for an empty value."""
    if not str(value or "").strip():
        return ""
    return resolve_source_backed_instrument(value, source_quote)[0]


def normalize_obligations(value: Any) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    obligations: list[dict[str, str]] = []
    for raw in rows:
        if isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("obligation") or "").strip()
            label = str(raw.get("label") or "").strip()[:20]
        else:
            text = str(raw or "").strip()
            label = ""
        if not text:
            continue
        row = {"text": text}
        if label:
            row["label"] = label
        obligations.append(row)
    return obligations


def compliance_item(requirement: dict[str, Any]) -> dict[str, Any]:
    source_quote = str(requirement.get("source_quote") or "")
    obligations = normalize_obligations(
        requirement.get("compliance_obligations") or requirement.get("obligations")
    )
    if not obligations:
        obligations = [
            {"label": str(item.get("label") or "").strip(), "text": str(item.get("text") or "").strip()}
            for item in (requirement.get("sub_items") or [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
    umbrella = is_compliance_umbrella_source(source_quote)
    return {
        "id": requirement.get("ai_req_id") or requirement.get("id"),
        "title": requirement.get("title"),
        "type": COMPLIANCE_TYPE,
        "priority": requirement.get("priority"),
        "status": requirement.get("status"),
        "umbrella": umbrella,
        "instrument": source_backed_instrument(
            requirement.get("compliance_instrument") or requirement.get("instrument"),
            source_quote,
        ),
        "obligations": obligations,
        "source_section": requirement.get("source_section"),
        "source_quote": source_quote,
        "source_block_ids": list(requirement.get("source_block_ids") or []),
        "source_mapping": requirement.get("source_mapping"),
        "suspicion_reasons": list(requirement.get("suspicion_reasons") or []),
        "notes": requirement.get("notes") or "",
    }


def build_compliance_payload(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    items = [compliance_item(row) for row in requirements if is_compliance_requirement(row)]
    return {
        "schema": COMPLIANCE_SCHEMA,
        "count": len(items),
        "items": items,
    }
