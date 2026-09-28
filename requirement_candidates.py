"""Filter semantic units into auditable requirement-analysis candidates."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Sequence

NORMATIVE = re.compile(r"\b(shall|must|required|required to|should|may not|不得|应当|必须)\b", re.I)
PAGE = re.compile(r"^(?:p\s*a\s*g\s*e|page)\s*\d+\s*(?:\||of)\s*\d+", re.I)
NON_REQUIREMENT_REGION = re.compile(r"\b(?:foreword|introduction|references?|definitions?|terms and definitions|contents|bibliography|acknowledg)\b", re.I)


def _region_role(unit: dict[str, Any], text: str) -> str:
    # Use the leaf section plus the explicit parser region when available.
    # Some DOCX table rows inherit a stale TOC ancestor (for example
    # ``2 Normative References / 5 General Requirements``); matching every
    # ancestor would incorrectly turn the normative table into front matter.
    path_parts = [str(x) for x in (unit.get("section_path") or []) if str(x).strip()]
    path = " / ".join(path_parts[-2:])
    doc_region = str(unit.get("doc_region") or "").strip().lower()
    if doc_region == "body":
        return "normative_body"
    heading = str(unit.get("heading") or "")
    # Region words in prose are ordinary requirement data (for example,
    # "display the contents of all registers").  Only the section path or an
    # explicit heading may switch a unit into front-matter classification.
    if NON_REQUIREMENT_REGION.search(f"{path} {heading}"):
        return "informational"
    if re.search(r"\b(?:annex|appendix)\b", f"{path} {heading}", re.I):
        return "annex"
    return "normative_body"


def classify_semantic_units(
    units: Sequence[dict[str, Any]],
    source_blocks: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocks_by_id = {
        str(block.get("block_id")): block
        for block in (source_blocks or [])
        if isinstance(block, dict) and block.get("block_id")
    }
    rows: list[dict[str, Any]] = []
    current_role = "normative_body"
    for unit in units:
        text = str(unit.get("text") or unit.get("text_normalized") or "").strip()
        low = text.lower()
        path_parts = [str(x) for x in (unit.get("section_path") or []) if str(x).strip()]
        unit_path = " / ".join(path_parts)
        source_ids = [str(value) for value in (unit.get("source_block_ids") or [])]
        source_rows = [blocks_by_id.get(value, {}) for value in source_ids]
        heading_text = " ".join(
            str(row.get("text") or "").strip()
            for row in source_rows
            if str(row.get("type") or "") == "heading" and str(row.get("text") or "").strip()
        ).strip()
        # Do not let an arbitrary prose sentence containing "introduction" or
        # "contents" change the role of every later unit.  Role transitions
        # are driven by parser headings (or a compact numbered heading when a
        # PDF parser lost the style marker) only.
        heading_probe = heading_text or str(unit.get("heading") or "").strip()
        heading_like = bool(heading_probe) or bool(
            re.match(r"^\s*\d+(?:\.\d+)*\s+[^.!?]{3,80}$", text)
            and not NORMATIVE.search(text)
        )
        is_table = bool(unit.get("type") == "table") or any(
            str(row.get("type") or "") == "table" for row in source_rows
        )
        explicit_doc_region = next(
            (str(row.get("doc_region") or "").strip().lower()
             for row in source_rows if row.get("doc_region")),
            "",
        )
        region_role = _region_role(
            {**unit, "doc_region": explicit_doc_region}, text)
        role_text = heading_probe or text
        if heading_like and re.search(r"\bforeword\b", role_text, re.I):
            current_role = "informational"
        elif heading_like and re.search(r"\bintroduction\b", role_text, re.I):
            current_role = "informational"
        elif heading_like and re.match(r"^\s*\d+(?:\.\d+)*\s+(?:terms(?: and definitions)?|definitions?)\b", role_text, re.I):
            current_role = "informational"
        elif heading_like and re.match(r"^\s*\d+(?:\.\d+)*\s+(?:scope|requirements|functional)\b", role_text, re.I):
            current_role = "normative_body"
        elif heading_like and region_role == "informational":
            current_role = "informational"
        elif heading_like and region_role == "annex":
            current_role = "annex"
        elif (
            current_role == "informational"
            and heading_like
            and re.match(r"^\s*\d+(?:\.\d+)+\s+", role_text)
            and not NON_REQUIREMENT_REGION.search(f"{unit_path} {heading_probe}")
        ):
            current_role = "normative_body"
        elif (
            current_role == "informational"
            and path_parts
            and re.match(r"^\s*\d+(?:\.\d+)*\s+", path_parts[-1])
            and not NON_REQUIREMENT_REGION.search(path_parts[-1])
        ):
            # A parser may lose the heading style while retaining a new
            # numbered section path.  Treat that path change as a scope reset;
            # otherwise one introductory heading can poison all later clauses.
            current_role = "normative_body"
        # Explicit parser ownership wins.  Otherwise carry the role only when
        # a heading established it; prose must never inherit a stale front
        # matter state merely because it contains a region keyword.
        if not explicit_doc_region:
            region_role = current_role if current_role != "normative_body" else region_role
        if not text or PAGE.match(text) or unit.get("noise"):
            category = "noise"
            reason = "page_or_parser_noise"
        elif is_table or "column_" in low:
            category = "table_candidate"
            reason = "table_context_required"
        elif NORMATIVE.search(text):
            # A modal sentence in a front-matter region is still safer as a
            # reviewable candidate than as silently discarded context.  The
            # expert can reject a false positive; the pipeline must not lose a
            # normative obligation because a heading boundary was uncertain.
            category = "needs_review" if region_role == "informational" else "requirement_candidate"
            reason = (
                "normative_language_in_informational_region"
                if region_role == "informational" else "normative_language"
            )
        elif re.match(r"^\d+(?:\.\d+)+\s+", text):
            category = "context"
            reason = "section_heading"
        elif len(text.split()) <= 2:
            category = "needs_review"
            reason = "short_fragment"
        else:
            category = "context"
            reason = "non_normative_context"
        rows.append({"semantic_unit_id": unit.get("semantic_unit_id") or unit.get("unit_id"), "category": category, "reason": reason, "region_role": region_role, "source_block_ids": source_ids})
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
        region_role = next((row.get("region_role") for row in (candidates.get("units") or []) if str(row.get("semantic_unit_id")) == uid), "normative_body")
        constraint_signal = (
            bool(NORMATIVE.search(text))
            or bool(re.search(
                r"\b(?:at least|at most|minimum|maximum|within|before|after|only if|shall be)\b"
                r"|\d+\s*(?:V|A|Hz|%|days?|years?)\b|应|不得|必须",
                text,
                re.I,
            ))
        )
        # Informational headings remain excluded when they contain no
        # obligation/constraint signal.  Strong signals stay visible in the
        # audit even if a future classifier regression labels them context.
        if constraint_signal:
            suspicious.append({"semantic_unit_id": uid, "text": text, "source_block_ids": list(unit.get("source_block_ids") or []), "region_role": region_role, "reason": "excluded_context_has_constraint_signal"})
    return {
        "schema": "requirement-candidate-coverage/v1",
        "source_units": len(units),
        "candidate_units": len(candidate_ids),
        "excluded_units": max(0, len(units) - len(candidate_ids)),
        "suspicious_excluded_units": len(suspicious),
        "status": "needs_review" if suspicious else "covered",
        "suspicious": suspicious,
    }
