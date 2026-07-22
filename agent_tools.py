"""Thin, provenance-preserving wrappers for Phase 1 agent actions."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import clarification_report
import omission_actions
from ai_review_actions import source_ai_requirement_id
from io_utils import read_jsonl

if TYPE_CHECKING:
    from agent_state import AnalysisState


def resample_section(
    out_dir: Path,
    block_id: str,
    *,
    allow_llm: bool = False,
) -> dict[str, Any]:
    """Queue a gap in zero-LLM mode or delegate to the existing targeted extractor."""
    root = Path(out_dir).expanduser().resolve()
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ValueError("block_id is required")
    if not allow_llm:
        with omission_actions.extraction_operation_lock(root, operation="agent-queue"):
            block, omission_id, source_fingerprint = _current_omission(root, block_id)
            queued = omission_actions.apply_omission_action(
                root,
                block_id=block_id,
                omission_id=omission_id,
                status="needs_extraction",
                reason="Queued by agent-policy-v1; semantic extraction requires an LLM-capable worker.",
                actor="agent-loop",
                expected_source_fingerprint=source_fingerprint,
            )
        return {
            "status": "skipped",
            "summary": (
                f"Queued {block_id} for extraction; Phase 1 zero-LLM mode did not execute "
                "semantic resampling."
            ),
            "details": {"omission": queued},
        }
    _block, omission_id, source_fingerprint = _current_omission(root, block_id)
    payload = omission_actions.targeted_reextract(
        root,
        block_id=block_id,
        omission_id=omission_id,
        actor="agent-loop",
        reason="Selected by agent-policy-v1.",
        route="openai_compatible",
        expected_source_fingerprint=source_fingerprint,
    )
    return {
        "status": "ok",
        "summary": f"Targeted extraction completed for {block_id}.",
        "details": payload,
    }


def recheck(out_dir: Path, req_id: str) -> dict[str, Any]:
    """Validate a recheck target without inventing a new partial semantic-review path."""
    root = Path(out_dir).expanduser().resolve()
    req_id = str(req_id or "").strip()
    if not req_id:
        raise ValueError("req_id is required")
    requirements = read_jsonl(root / "ai_requirements.jsonl")
    if not any(source_ai_requirement_id(row) == req_id for row in requirements):
        raise ValueError(f"unknown requirement id: {req_id}")
    return {
        "status": "skipped",
        "summary": (
            f"Recheck {req_id} was not executed: the existing semantic recheck has no safe "
            "standalone zero-LLM entry point."
        ),
    }


def ask_clarification(out_dir: Path) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    report = clarification_report.run_report(root)
    questions = int(report.get("questions") or 0)
    return {
        "status": "ok",
        "summary": f"Wrote the clarification report with {questions} unresolved hard questions.",
        "details": report,
    }


def stop(state: "AnalysisState") -> dict[str, str]:
    if state.readiness.get("verdict") == "READY":
        summary = "READY gate passed; no further Phase 1 action is needed."
    else:
        reasons = [str(value) for value in (state.readiness.get("reasons") or []) if str(value)]
        detail = "; ".join(reasons) if reasons else "no eligible deterministic action remains"
        summary = f"Stopped with NEEDS WORK: {detail}."
    return {"status": "ok", "summary": summary}


def execute_action(out_dir: Path, action: str, state: "AnalysisState") -> dict[str, Any]:
    action = str(action or "").strip()
    if action.startswith("resample_section:"):
        return resample_section(out_dir, action.split(":", 1)[1], allow_llm=False)
    if action.startswith("recheck:"):
        return recheck(out_dir, action.split(":", 1)[1])
    if action == "ask_clarification":
        return ask_clarification(out_dir)
    if action == "stop":
        return stop(state)
    raise ValueError(f"unsupported agent action: {action}")


def _block_by_id(out_dir: Path, block_id: str) -> dict[str, Any]:
    for block in read_jsonl(out_dir / "blocks.jsonl"):
        if str(block.get("block_id") or "") == block_id:
            return block
    raise ValueError(f"unknown block_id: {block_id}")


def _current_omission(out_dir: Path, block_id: str) -> tuple[dict[str, Any], str, str]:
    if block_id not in omission_actions.current_omission_candidate_ids(out_dir):
        raise ValueError(f"block is not a current omission candidate: {block_id}")
    block = _block_by_id(out_dir, block_id)
    text = str(block.get("text") or "")
    return (
        block,
        omission_actions.make_omission_id(block_id, text),
        omission_actions.omission_source_fingerprint(block_id, text),
    )
