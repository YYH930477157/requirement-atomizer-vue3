from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claim_artifacts import file_sha256


INPUT_COMPLETENESS_SCHEMA = "ai-input-completeness/v1"
INPUT_COMPLETENESS_VERSION = "ai-input-completeness-v1"


def read_ai_input_completeness(out_dir: Path | str) -> dict[str, Any]:
    """Validate the current B-track publication and report partial inputs honestly."""
    from ai_extract import (
        AI_REQUIREMENTS,
        AI_REQUIREMENTS_META,
        current_ai_requirements_producer_lineage,
        extraction_input_fingerprint,
    )

    root = Path(out_dir).expanduser().resolve()
    requirements_path = root / AI_REQUIREMENTS
    metadata_path = root / AI_REQUIREMENTS_META
    reasons: list[str] = []
    metadata: dict[str, Any] = {}
    requirements_sha256: str | None = None

    if requirements_path.is_file():
        try:
            requirements_sha256 = file_sha256(requirements_path)
        except OSError:
            reasons.append("requirements_unreadable")
    else:
        reasons.append("requirements_missing")

    try:
        candidate = json.loads(metadata_path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict):
            metadata = candidate
        else:
            reasons.append("metadata_not_object")
    except FileNotFoundError:
        reasons.append("metadata_missing")
    except (OSError, UnicodeError, json.JSONDecodeError):
        reasons.append("metadata_invalid")

    if metadata:
        if metadata.get("schema") != "ai-requirements-final/v1":
            reasons.append("metadata_schema_mismatch")
        if metadata.get("producer_lineage") != current_ai_requirements_producer_lineage():
            reasons.append("producer_lineage_mismatch")
        current_input = extraction_input_fingerprint(root)
        if not current_input or str(metadata.get("input_fingerprint") or "") != current_input:
            reasons.append("source_input_mismatch")
        bound_sha256 = str(metadata.get("requirements_sha256") or "")
        if not bound_sha256:
            reasons.append("requirements_hash_missing")
        elif requirements_sha256 is None or bound_sha256 != requirements_sha256:
            reasons.append("requirements_hash_mismatch")
        if str(metadata.get("selected_snapshot") or "final") == "partial":
            reasons.append("partial_snapshot_selected")

    failed_sections = max(0, int(metadata.get("failed_sections") or 0))
    failed_section_ids = [
        str(value) for value in (metadata.get("failed_section_ids") or []) if str(value)
    ]
    failed_section_block_ids = [
        str(value)
        for value in (metadata.get("failed_section_block_ids") or [])
        if str(value)
    ]
    if failed_sections or failed_section_ids or failed_section_block_ids:
        reasons.append("failed_sections")

    ordered_reasons = list(dict.fromkeys(reasons))
    return {
        "schema": INPUT_COMPLETENESS_SCHEMA,
        "version": INPUT_COMPLETENESS_VERSION,
        "incomplete_inputs": bool(ordered_reasons),
        "reasons": ordered_reasons,
        "failed_sections": failed_sections,
        "failed_section_ids": failed_section_ids,
        "failed_section_block_ids": failed_section_block_ids,
        "requirements_sha256": requirements_sha256,
        "metadata_file": AI_REQUIREMENTS_META,
        "requirements_file": AI_REQUIREMENTS,
    }


def attach_input_completeness(
    payload: dict[str, Any],
    out_dir: Path | str,
) -> dict[str, Any]:
    completeness = read_ai_input_completeness(out_dir)
    payload["incomplete_inputs"] = bool(completeness["incomplete_inputs"])
    payload["input_completeness"] = completeness
    return payload
