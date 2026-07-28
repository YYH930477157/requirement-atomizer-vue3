"""Deterministic raw-to-repaired text alignment for source provenance."""
from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from requirement_kb.matching import TEXT_REPLACEMENTS


SOURCE_ALIGNMENT_SCHEMA = "source-alignment/v6"
SOURCE_ALIGNMENT_VERSION = "source-alignment-v6"
SOURCE_TRANSFORMATION_POLICY_VERSION = "source-transform-policy-v4"
SOURCE_TEXT_NORMALIZATION_VERSION = "source-clean-text-v2"
SOURCE_REPAIR_PROVENANCE_SCHEMA = "source-repair-provenance/v1"
_VALID_TAGS = frozenset({"equal", "replace", "delete", "insert"})


def _mapping_fingerprint() -> str:
    payload = json.dumps(
        sorted(TEXT_REPLACEMENTS.items()),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


_WHITESPACE_RULE = {
    "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
    "rule_id": "source.whitespace_normalization",
    "rule_version": "source-whitespace-v2",
    "reason": "normalization.whitespace",
    "allowed": True,
}
_CHARACTER_RULE = {
    "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
    "rule_id": "source.character_replacement",
    "rule_version": f"source-character-replacement-{_mapping_fingerprint()}",
    "reason": "normalization.character",
    "allowed": True,
}
_CHARACTER_WHITESPACE_RULE = {
    "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
    "rule_id": "source.composite_character_whitespace",
    "rule_version": f"source-composite-character-whitespace-{_mapping_fingerprint()}-v2",
    "reason": "normalization.character_and_whitespace",
    "allowed": True,
}
_PDF_REPAIR_RULE_TEMPLATE = {
    "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
    "rule_id": "source.pdf_text_repair_replay",
    "reason": "repair.pdf_text_repair_replay",
    "allowed": True,
}
_UNAPPROVED_RULE = {
    "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
    "rule_id": "source.unapproved_transformation",
    "rule_version": "source-unapproved-transformation-v1",
    "reason": "unapproved.non_layout_character_change",
    "allowed": False,
}


def _ruleset_fingerprint() -> str:
    payload = json.dumps(
        {
            "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
            "rules": [
                _WHITESPACE_RULE,
                _CHARACTER_RULE,
                _CHARACTER_WHITESPACE_RULE,
                _PDF_REPAIR_RULE_TEMPLATE,
                _UNAPPROVED_RULE,
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


SOURCE_TRANSFORMATION_RULESET_VERSION = (
    f"source-transform-rules-v4-{_ruleset_fingerprint()}"
)


_LAYOUT_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_layout_whitespace(text: str) -> str:
    return _LAYOUT_WHITESPACE_RE.sub(" ", text).strip()


def _replace_canonical_characters(text: str) -> str:
    output = text
    for source, replacement in TEXT_REPLACEMENTS.items():
        output = output.replace(source, replacement)
    return output


def pdf_text_repair_provenance(
    producer_version: str,
    vocabulary_fingerprint: str,
) -> dict[str, str]:
    """Return the minimal secret-free proof needed to replay PDF repair."""
    return {
        "schema": SOURCE_REPAIR_PROVENANCE_SCHEMA,
        "producer": "pdf_text_repair",
        "producer_version": str(producer_version),
        "vocabulary_fingerprint": str(vocabulary_fingerprint),
    }


@lru_cache(maxsize=1)
def _current_pdf_repair_context() -> tuple[str, str, Any] | None:
    try:
        from parsers.pdf_parser import (
            PDF_TEXT_REPAIR_VERSION,
            defragment_text_with_audit,
            text_repair_vocabulary_fingerprint,
        )
    except (ImportError, RuntimeError):
        return None
    return (
        PDF_TEXT_REPAIR_VERSION,
        text_repair_vocabulary_fingerprint(),
        defragment_text_with_audit,
    )


def _pdf_repair_provenance_is_current(provenance: dict[str, Any]) -> bool:
    context = _current_pdf_repair_context()
    return bool(
        context
        and provenance.get("producer_version") == context[0]
        and provenance.get("vocabulary_fingerprint") == context[1]
    )


def _pdf_repair_rule(
    raw: str,
    repaired: str,
    provenance: object,
) -> dict[str, Any] | None:
    if not isinstance(provenance, dict) or set(provenance) != {
        "schema", "producer", "producer_version", "vocabulary_fingerprint",
    }:
        return None
    if (provenance.get("schema") != SOURCE_REPAIR_PROVENANCE_SCHEMA
            or provenance.get("producer") != "pdf_text_repair"):
        return None
    context = _current_pdf_repair_context()
    if context is None:
        return None
    producer_version, vocabulary_fingerprint, defragment_text_with_audit = context
    if not _pdf_repair_provenance_is_current(provenance):
        return None

    # Preserve hard line boundaries while replaying.  List members and table
    # rows are independent parser repair units; flattening their newlines before
    # replay can invent a cross-row word repair that never occurred.
    canonical_raw = _replace_canonical_characters(raw)
    replayed, events = defragment_text_with_audit(canonical_raw)
    replayed = _normalize_layout_whitespace(_replace_canonical_characters(replayed))
    canonical_repaired = _normalize_layout_whitespace(
        _replace_canonical_characters(repaired)
    )
    if not events or replayed != canonical_repaired:
        return None
    return {
        **_PDF_REPAIR_RULE_TEMPLATE,
        "rule_version": (
            f"source-pdf-text-repair-{producer_version}-"
            f"{vocabulary_fingerprint}"
        ),
    }


def classify_source_transformation(
    raw_text: str,
    repaired_text: str,
    *,
    repair_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the registered, replayable rule for a complete text transformation."""
    raw = str(raw_text or "")
    repaired = str(repaired_text or "")
    if raw == repaired:
        raise ValueError("identity text has no non-equal transformation")
    whitespace_normalized = _normalize_layout_whitespace(raw)
    if whitespace_normalized == repaired:
        return dict(_WHITESPACE_RULE)

    canonical = _replace_canonical_characters(raw)
    character_changed = canonical != raw
    if character_changed:
        if canonical == repaired:
            return dict(_CHARACTER_RULE)
        if _normalize_layout_whitespace(canonical) == repaired:
            return dict(_CHARACTER_WHITESPACE_RULE)
    pdf_rule = _pdf_repair_rule(raw, repaired, repair_provenance)
    if pdf_rule is not None:
        return pdf_rule
    return dict(_UNAPPROVED_RULE)


def _text_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _deterministic_opcode_rows(raw: str, repaired: str) -> list[dict[str, Any]]:
    if raw == repaired:
        return ([{
            "tag": "equal",
            "raw_start": 0,
            "raw_end": len(raw),
            "repaired_start": 0,
            "repaired_end": len(repaired),
        }] if raw else [])
    return [
        {
            "tag": tag,
            "raw_start": raw_start,
            "raw_end": raw_end,
            "repaired_start": repaired_start,
            "repaired_end": repaired_end,
        }
        for tag, raw_start, raw_end, repaired_start, repaired_end
        in SequenceMatcher(a=raw, b=repaired, autojunk=False).get_opcodes()
    ]


def build_source_alignment(
    raw_text: str,
    repaired_text: str,
    *,
    repair_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable opcode map whose intervals cover both texts exactly once."""
    raw = str(raw_text or "")
    repaired = str(repaired_text or "")
    opcodes = _deterministic_opcode_rows(raw, repaired)
    if raw != repaired:
        transformation = classify_source_transformation(
            raw,
            repaired,
            repair_provenance=repair_provenance,
        )
        for opcode in opcodes:
            if opcode["tag"] != "equal":
                opcode["transformation"] = dict(transformation)
                if opcode["tag"] in {"delete", "replace"}:
                    opcode["raw_deletion_reason"] = transformation["reason"]
                if opcode["tag"] in {"insert", "replace"}:
                    opcode["repaired_insertion_source"] = transformation["reason"]
    alignment = {
        "schema": SOURCE_ALIGNMENT_SCHEMA,
        "version": SOURCE_ALIGNMENT_VERSION,
        "transformation_policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
        "repair_provenance": dict(repair_provenance) if repair_provenance else None,
        "raw_length": len(raw),
        "repaired_length": len(repaired),
        "raw_sha256": _text_hash(raw),
        "repaired_sha256": _text_hash(repaired),
        "opcodes": opcodes,
    }
    validate_source_alignment(raw, repaired, alignment)
    return alignment


def source_alignment_fields(
    raw_text: str,
    repaired_text: str,
    *,
    repair_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return both the strict envelope and the flat parser-artifact opcode list."""
    alignment = build_source_alignment(
        raw_text,
        repaired_text,
        repair_provenance=repair_provenance,
    )
    return {
        "source_alignment": alignment,
        "raw_to_repaired_spans": [
            {
                "operation": opcode["tag"],
                "raw_start": opcode["raw_start"],
                "raw_end": opcode["raw_end"],
                "repaired_start": opcode["repaired_start"],
                "repaired_end": opcode["repaired_end"],
            }
            for opcode in alignment["opcodes"]
        ],
    }


def raw_offset_for_repaired_offset(
    raw_text: str,
    repaired_text: str,
    alignment: dict[str, Any],
    repaired_offset: int,
    *,
    bias: str = "right",
) -> int:
    """Project a repaired-text boundary back to the raw coordinate space."""
    raw = str(raw_text or "")
    repaired = str(repaired_text or "")
    validate_source_alignment(raw, repaired, alignment)
    if not isinstance(repaired_offset, int) or isinstance(repaired_offset, bool):
        raise ValueError("repaired offset must be an integer")
    if not 0 <= repaired_offset <= len(repaired):
        raise ValueError("repaired offset exceeds text bounds")
    if bias not in {"left", "right"}:
        raise ValueError("projection bias must be left or right")
    if repaired_offset == 0:
        return 0
    if repaired_offset == len(repaired):
        return len(raw)

    boundary_candidates: list[int] = []
    for opcode in alignment["opcodes"]:
        raw_start = opcode["raw_start"]
        raw_end = opcode["raw_end"]
        repaired_start = opcode["repaired_start"]
        repaired_end = opcode["repaired_end"]
        if repaired_start < repaired_offset < repaired_end:
            if opcode["tag"] == "equal":
                return raw_start + repaired_offset - repaired_start
            if opcode["tag"] == "insert":
                return raw_start
            raw_size = raw_end - raw_start
            repaired_size = repaired_end - repaired_start
            numerator = (repaired_offset - repaired_start) * raw_size
            projected = (
                (numerator + repaired_size - 1) // repaired_size
                if bias == "right"
                else numerator // repaired_size
            )
            return raw_start + projected
        if repaired_start == repaired_offset:
            boundary_candidates.append(raw_start)
        if repaired_end == repaired_offset:
            boundary_candidates.append(raw_end)

    if not boundary_candidates:
        raise ValueError("repaired offset is not covered by source alignment")
    return max(boundary_candidates) if bias == "right" else min(boundary_candidates)


def source_alignment_is_approved(
    raw_text: str,
    repaired_text: str,
    alignment: dict[str, Any],
) -> bool:
    """Return whether every non-equal opcode uses a registered allowed rule."""
    validate_source_alignment(raw_text, repaired_text, alignment)
    return all(
        opcode.get("tag") == "equal"
        or opcode.get("transformation", {}).get("allowed") is True
        for opcode in alignment["opcodes"]
    )


def validate_source_alignment(
    raw_text: str,
    repaired_text: str,
    alignment: dict[str, Any],
) -> None:
    """Raise ``ValueError`` unless an alignment fully and contiguously covers both texts."""
    raw = str(raw_text or "")
    repaired = str(repaired_text or "")
    if not isinstance(alignment, dict):
        raise ValueError("source alignment must be an object")
    if alignment.get("schema") != SOURCE_ALIGNMENT_SCHEMA:
        raise ValueError("unsupported source alignment schema")
    if alignment.get("version") != SOURCE_ALIGNMENT_VERSION:
        raise ValueError("unsupported source alignment version")
    if alignment.get("transformation_policy_version") != SOURCE_TRANSFORMATION_POLICY_VERSION:
        raise ValueError("unsupported source transformation policy version")
    repair_provenance = alignment.get("repair_provenance")
    if repair_provenance is not None and (
        not isinstance(repair_provenance, dict)
        or set(repair_provenance) != {
            "schema", "producer", "producer_version", "vocabulary_fingerprint",
        }
        or repair_provenance.get("schema") != SOURCE_REPAIR_PROVENANCE_SCHEMA
        or repair_provenance.get("producer") != "pdf_text_repair"
        or not str(repair_provenance.get("producer_version") or "")
        or not str(repair_provenance.get("vocabulary_fingerprint") or "")
    ):
        raise ValueError("invalid source repair provenance")
    if (isinstance(repair_provenance, dict)
            and not _pdf_repair_provenance_is_current(repair_provenance)):
        raise ValueError("stale source repair provenance")
    if alignment.get("raw_length") != len(raw) or alignment.get("repaired_length") != len(repaired):
        raise ValueError("source alignment length mismatch")
    if alignment.get("raw_sha256") != _text_hash(raw):
        raise ValueError("source alignment raw hash mismatch")
    if alignment.get("repaired_sha256") != _text_hash(repaired):
        raise ValueError("source alignment repaired hash mismatch")

    opcodes = alignment.get("opcodes")
    if not isinstance(opcodes, list):
        raise ValueError("source alignment opcodes must be a list")
    raw_cursor = 0
    repaired_cursor = 0
    expected_transformation = (
        classify_source_transformation(
            raw,
            repaired,
            repair_provenance=repair_provenance,
        )
        if raw != repaired else None
    )
    for index, opcode in enumerate(opcodes):
        if not isinstance(opcode, dict):
            raise ValueError(f"source alignment opcode {index} must be an object")
        tag = str(opcode.get("tag") or "")
        if tag not in _VALID_TAGS:
            raise ValueError(f"source alignment opcode {index} has invalid tag")
        coordinates = [
            opcode.get("raw_start"), opcode.get("raw_end"),
            opcode.get("repaired_start"), opcode.get("repaired_end"),
        ]
        if any(not isinstance(value, int) or isinstance(value, bool) for value in coordinates):
            raise ValueError(f"source alignment opcode {index} has invalid coordinates")
        raw_start, raw_end, repaired_start, repaired_end = coordinates
        if raw_start != raw_cursor or repaired_start != repaired_cursor:
            raise ValueError("source alignment opcodes must be contiguous")
        if raw_end < raw_start or repaired_end < repaired_start:
            raise ValueError(f"source alignment opcode {index} has reversed coordinates")
        if raw_end > len(raw) or repaired_end > len(repaired):
            raise ValueError(f"source alignment opcode {index} exceeds text bounds")

        raw_size = raw_end - raw_start
        repaired_size = repaired_end - repaired_start
        if tag == "equal":
            if raw_size <= 0 or raw_size != repaired_size:
                raise ValueError(f"source alignment equal opcode {index} is empty or unbalanced")
            if raw[raw_start:raw_end] != repaired[repaired_start:repaired_end]:
                raise ValueError(f"source alignment equal opcode {index} does not match")
        elif tag == "delete" and (raw_size <= 0 or repaired_size != 0):
            raise ValueError(f"source alignment delete opcode {index} has invalid shape")
        elif tag == "insert" and (raw_size != 0 or repaired_size <= 0):
            raise ValueError(f"source alignment insert opcode {index} has invalid shape")
        elif tag == "replace" and (raw_size <= 0 or repaired_size <= 0):
            raise ValueError(f"source alignment replace opcode {index} has invalid shape")
        if tag == "equal":
            if "transformation" in opcode:
                raise ValueError(f"source alignment equal opcode {index} has transformation metadata")
        else:
            transformation = opcode.get("transformation")
            if not isinstance(transformation, dict):
                raise ValueError(f"source alignment {tag} opcode {index} lacks transformation metadata")
            if transformation != expected_transformation:
                raise ValueError(
                    f"source alignment {tag} opcode {index} transformation metadata mismatch")
            reason = str(transformation["reason"])
            if tag in {"delete", "replace"} and opcode.get("raw_deletion_reason") != reason:
                raise ValueError(f"source alignment {tag} opcode {index} lacks deletion reason")
            if tag in {"insert", "replace"} and opcode.get("repaired_insertion_source") != reason:
                raise ValueError(f"source alignment {tag} opcode {index} lacks insertion source")

        raw_cursor = raw_end
        repaired_cursor = repaired_end

    if raw_cursor != len(raw) or repaired_cursor != len(repaired):
        raise ValueError("source alignment opcodes do not cover both texts")
    actual_core = [
        {
            "tag": opcode["tag"],
            "raw_start": opcode["raw_start"],
            "raw_end": opcode["raw_end"],
            "repaired_start": opcode["repaired_start"],
            "repaired_end": opcode["repaired_end"],
        }
        for opcode in opcodes
    ]
    if actual_core != _deterministic_opcode_rows(raw, repaired):
        raise ValueError("source alignment does not match deterministic opcode sequence")
