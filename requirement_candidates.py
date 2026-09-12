"""Filter semantic units into auditable requirement-analysis candidates."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Sequence

NORMATIVE = re.compile(r"\b(shall|must|required|required to|should|may not|不得|应当|必须)\b", re.I)
PAGE = re.compile(r"^(?:p\s*a\s*g\s*e|page)\s*\d+\s*(?:\||of)\s*\d+", re.I)
NON_REQUIREMENT_REGION = re.compile(r"\b(?:foreword|introduction|references?|definitions?|terms and definitions|contents|bibliography|acknowledg)\b", re.I)


def _region_role(unit: dict[str, Any], text: str) -> str:
    path = " / ".join(str(x) for x in (unit.get("section_path") or []))
    heading = str(unit.get("heading") or "")
    if NON_REQUIREMENT_REGION.search(f"{path} {heading} {text[:120]}"):
        return "informational"
    if re.search(r"\b(?:annex|appendix)\b", f"{path} {heading}", re.I):
        return "annex"
    return "normative_body"


def classify_semantic_units(units: Sequence[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        text = str(unit.get("text") or unit.get("text_normalized") or "").strip()
        low = text.lower()
        region_role = _region_role(unit, text)
        if not text or PAGE.match(text) or unit.get("noise"):
            category = "noise"
            reason = "page_or_parser_noise"
        elif unit.get("type") == "table" or "column_" in low:
            category = "table_candidate"
            reason = "table_context_required"
        elif NORMATIVE.search(text) and region_role != "informational":
            category = "requirement_candidate"
            reason = "normative_language"
        elif re.match(r"^\d+(?:\.\d+)+\s+", text):
            category = "context"
            reason = "section_heading"
        elif len(text.split()) <= 2:
            category = "needs_review"
            reason = "short_fragment"
        else:
            category = "context"
            reason = "non_normative_context"
        rows.append({"semantic_unit_id": unit.get("semantic_unit_id") or unit.get("unit_id"), "category": category, "reason": reason, "region_role": region_role, "source_block_ids": list(unit.get("source_block_ids") or [])})
    counts = Counter(row["category"] for row in rows)
    return {"schema": "requirement-candidates/v1", "counts": dict(counts), "units": rows}


def build_full_coverage_audit(units: Sequence[dict[str, Any]], candidates: dict[str, Any]) -> dict[str, Any]:
    """Audit excluded context so candidate filtering cannot silently hide obligations."""
    candidate_ids = {str(row.get("semantic_unit_id")) for row in (candidates.get("units") or [])
                     if row.get("category") in {"requirement_candidate", "table_candidate", "needs_review"}}
    suspicious: list[dict[str, Any]] = []
    for unit in units:
        uid = str(unit.get("semantic_unit_id") or unit.get("unit_id") or "")
        if uid in candidate_ids:
            continue
        text = str(unit.get("text") or unit.get("text_normalized") or "").strip()
        if not text or PAGE.match(text):
            continue
        # Numeric thresholds, modal verbs in non-English forms, and imperative
        # language are useful recall signals even when shall/must is absent.
        if re.search(r"\b(?:at least|at most|minimum|maximum|within|before|after|only if|shall be|应|不得|必须)\b|\d+\s*(?:V|A|Hz|%|days?|years?)\b", text, re.I):
            suspicious.append({"semantic_unit_id": uid, "text": text, "source_block_ids": list(unit.get("source_block_ids") or []), "reason": "excluded_context_has_constraint_signal"})
    return {
        "schema": "requirement-candidate-coverage/v1",
        "source_units": len(units),
        "candidate_units": len(candidate_ids),
        "excluded_units": max(0, len(units) - len(candidate_ids)),
        "suspicious_excluded_units": len(suspicious),
        "status": "needs_review" if suspicious else "covered",
        "suspicious": suspicious,
    }
