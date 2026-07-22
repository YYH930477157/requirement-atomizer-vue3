"""Read-only aggregate view of artifacts consumed by the Phase 1 agent loop."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import clarification_report
from ai_review_actions import source_ai_requirement_id
from clarification_check_states import read_clarification_check_states
from desktop_tasks import read_run_manifest
from io_utils import read_jsonl
from merged_consistency import coverage_denominator_blocks, layered_coverage
from omission_actions import current_non_requirement_block_ids, read_current_omission_states

# 已登记待抽取/已确认待处理的遗漏——agent 不得重复排队（test3 实测：跨运行重复登记同一批 block）。
PENDING_OMISSION_STATUSES = frozenset({"needs_extraction", "issue_confirmed"})


class AgentStateInputError(ValueError):
    """The requested output directory is not a completed extraction directory."""


class AgentStateValidationError(ValueError):
    """An existing output artifact has an invalid structure."""


@dataclass(frozen=True)
class AnalysisState:
    """Current, read-only projection over one extraction output directory."""

    out_dir: Path
    run_id: str
    manifest: dict[str, Any]
    stage_statuses: dict[str, str]
    requirements: tuple[dict[str, Any], ...]
    quality: dict[str, Any]
    coverage: dict[str, Any]
    coverage_gaps: tuple[dict[str, Any], ...]
    open_questions: tuple[dict[str, Any], ...]
    readiness: dict[str, Any]
    failed_sections: int
    failed_section_ids: tuple[str, ...]
    failed_section_block_ids: tuple[str, ...]
    pending_extraction_block_ids: tuple[str, ...]

    @property
    def requirement_count(self) -> int:
        return len(self.requirements)

    @property
    def coverage_gap_block_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({
                str(row.get("block_id") or "")
                for row in self.coverage_gaps
                if str(row.get("block_id") or "")
            })
        )

    @property
    def open_question_count(self) -> int:
        return len(self.open_questions)

    @property
    def coverage_pct(self) -> float | None:
        value = self.quality.get("coverage_pct")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def core_coverage_pct(self) -> float | None:
        value = self.quality.get("core_coverage_pct")
        if not isinstance(value, (int, float)) and self.readiness.get("coverage_basis") == "core":
            value = self.readiness.get("coverage_pct")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(sorted(
            stage for stage, status in self.stage_statuses.items()
            if status in {"failed", "partial"}
        ))

    @property
    def recheck_requirement_ids(self) -> tuple[str, ...]:
        candidates: set[str] = set()
        for requirement in self.requirements:
            confidence = requirement.get("confidence")
            low_confidence = False
            if isinstance(confidence, (int, float)):
                low_confidence = float(confidence) < 0.75
            if requirement.get("suspicion_reasons") or low_confidence:
                candidates.add(source_ai_requirement_id(requirement))
        return tuple(sorted(value for value in candidates if value))

    @property
    def unqueued_gap_block_ids(self) -> tuple[str, ...]:
        """Gaps not yet queued for extraction (cross-run dedup for the agent loop)."""
        pending = set(self.pending_extraction_block_ids)
        return tuple(
            block_id
            for block_id in sorted(set(self.coverage_gap_block_ids) | set(self.failed_section_block_ids))
            if block_id not in pending
        )

    @property
    def action_inputs(self) -> dict[str, list[str]]:
        resample_ids = sorted(set(self.coverage_gap_block_ids) | set(self.failed_section_block_ids))
        return {
            "resample_section": resample_ids,
            "unqueued_resample_section": list(self.unqueued_gap_block_ids),
            "recheck": list(self.recheck_requirement_ids),
            "ask_clarification": [
                str(row.get("clarification_id") or "")
                for row in self.open_questions
                if str(row.get("clarification_id") or "")
            ],
        }

    def state_digest(self) -> dict[str, Any]:
        ready = self.readiness.get("verdict") == "READY"
        reasons = [str(value) for value in (self.readiness.get("reasons") or []) if str(value)]
        if not ready and not reasons:
            reasons = ["readiness gate is blocked"]
        return {
            "counts": {
                "requirements": self.requirement_count,
                "coverage_gaps": len(self.coverage_gap_block_ids),
                "open_questions": self.open_question_count,
            },
            "ready_gate": "pass" if ready else "blocked",
            "blocked_reasons": list(dict.fromkeys(reasons)),
        }


def load_analysis_state(out_dir: Path) -> AnalysisState:
    root = Path(out_dir).expanduser().resolve()
    if not root.is_dir():
        raise AgentStateInputError(f"Output directory does not exist: {root}")
    blocks_path = root / "blocks.jsonl"
    requirements_path = root / "ai_requirements.jsonl"
    missing = [path.name for path in (blocks_path, requirements_path) if not path.is_file()]
    if missing:
        raise AgentStateInputError(
            f"Output directory is missing required artifacts: {', '.join(missing)}"
        )

    try:
        blocks = read_jsonl(blocks_path)
        requirements = read_jsonl(requirements_path)
        quality = _read_json_object(root / "ai_extract_quality.json", optional=True)
        manifest = read_run_manifest(root)
        stage_statuses = _stage_statuses(manifest)
        coverage = layered_coverage(
            requirements,
            coverage_denominator_blocks(blocks),
            source_blocks=blocks,
            expert_excluded_block_ids=current_non_requirement_block_ids(root),
        )
        coverage_gaps = _coverage_gap_rows(coverage)
        open_questions, question_counts = _unresolved_hard_questions(root)
        readiness = clarification_report.readiness_verdict(
            root,
            len(open_questions),
            unresolved_blocking=question_counts["blocking"],
            unresolved_important=question_counts["important"],
            unresolved_internal=question_counts["internal"],
            resolved_internal=question_counts["resolved_internal"],
            resolved=question_counts["resolved"],
        )
    except AgentStateInputError:
        raise
    except (json.JSONDecodeError, OSError, TimeoutError, UnicodeDecodeError, ValueError) as exc:
        raise AgentStateValidationError(f"Invalid agent input under {root}: {exc}") from exc

    failed_sections = _non_negative_int(quality.get("failed_sections"), "failed_sections")
    failed_section_ids = _string_tuple(quality.get("failed_section_ids"), "failed_section_ids")
    failed_block_ids = _string_tuple(
        quality.get("failed_section_block_ids"), "failed_section_block_ids"
    )
    pending_block_ids = tuple(sorted({
        str(state.get("block_id") or "")
        for state in read_current_omission_states(root).values()
        if str(state.get("status") or "") in PENDING_OMISSION_STATUSES
        and str(state.get("block_id") or "")
    }))
    return AnalysisState(
        out_dir=root,
        run_id=_resolve_run_id(root, manifest),
        manifest=manifest,
        stage_statuses=stage_statuses,
        requirements=tuple(requirements),
        quality=quality,
        coverage=coverage,
        coverage_gaps=tuple(coverage_gaps),
        open_questions=tuple(open_questions),
        readiness=readiness,
        failed_sections=failed_sections,
        failed_section_ids=failed_section_ids,
        failed_section_block_ids=failed_block_ids,
        pending_extraction_block_ids=pending_block_ids,
    )


def _read_json_object(path: Path, *, optional: bool = False) -> dict[str, Any]:
    if not path.exists():
        if optional:
            return {}
        raise AgentStateInputError(f"Required artifact does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AgentStateValidationError(f"{path.name} must contain a JSON object")
    return payload


def _stage_statuses(manifest: dict[str, Any]) -> dict[str, str]:
    stages = manifest.get("stages")
    if not isinstance(stages, dict):
        return {}
    return {
        str(stage): str(entry.get("status") or "")
        for stage, entry in stages.items()
        if isinstance(entry, dict) and str(entry.get("status") or "")
    }


def _coverage_gap_rows(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    layers = [coverage, coverage.get("compliance") or {}]
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for sample in layer.get("uncovered_samples") or []:
            if not isinstance(sample, dict):
                continue
            block_id = str(sample.get("block_id") or "")
            if block_id:
                rows_by_id[block_id] = dict(sample)
        for value in layer.get("uncovered_block_ids") or []:
            block_id = str(value or "")
            if block_id:
                rows_by_id.setdefault(block_id, {"block_id": block_id, "section": "", "text": ""})
    return [rows_by_id[block_id] for block_id in sorted(rows_by_id)]


def _unresolved_hard_questions(root: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    entries = [
        row for row in clarification_report.collect_questions(root)
        if row.get("tier", clarification_report.TIER_HARD) == clarification_report.TIER_HARD
    ]
    answers = clarification_report.load_answers(root)
    answers_by_id = {
        str(row.get("clarification_id") or ""): row
        for row in answers.values()
        if str(row.get("clarification_id") or "")
    }
    check_states = read_clarification_check_states(root)
    unresolved: list[dict[str, Any]] = []
    resolved = 0
    resolved_internal = 0
    for entry in entries:
        if entry.get("audience") == clarification_report.AUDIENCE_INTERNAL:
            state = check_states.get(str(entry.get("clarification_id") or "")) or {}
            action = str(state.get("state") or state.get("action") or "")
            current = bool(state.get("evidence_fingerprint")) and str(
                state.get("evidence_fingerprint")
            ) == str(entry.get("evidence_fingerprint") or "")
            if action == "verified_ok" and current:
                resolved_internal += 1
                continue
            unresolved.append(entry)
            continue

        answer = answers_by_id.get(str(entry.get("clarification_id") or ""))
        if answer is None:
            answer = answers.get((entry.get("source_id") or "", entry.get("question") or ""))
        current = bool(answer) and str(answer.get("evidence_fingerprint") or "") == str(
            entry.get("evidence_fingerprint") or ""
        )
        if answer and answer.get("adopted", True) and current:
            resolved += 1
            continue
        unresolved.append(entry)

    blocking = sum(
        1 for row in unresolved
        if row.get("blocker_level") == clarification_report.BLOCKER_BLOCKING
    )
    internal = sum(
        1 for row in unresolved
        if row.get("audience") == clarification_report.AUDIENCE_INTERNAL
    )
    return unresolved, {
        "blocking": blocking,
        "important": len(unresolved) - blocking,
        "internal": internal,
        "resolved_internal": resolved_internal,
        "resolved": resolved + resolved_internal,
    }


def _resolve_run_id(root: Path, manifest: dict[str, Any]) -> str:
    run_id = str(manifest.get("run_id") or "").strip()
    if run_id:
        return run_id
    for name in ("ai_requirements.meta.json", "ai_requirements.partial.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("run_id") or "").strip():
            return str(payload["run_id"]).strip()
    return root.name or "agent-run"


def _non_negative_int(value: Any, field: str) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise AgentStateValidationError(f"{field} must be an integer") from exc
    if result < 0:
        raise AgentStateValidationError(f"{field} must not be negative")
    return result


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AgentStateValidationError(f"{field} must be an array")
    return tuple(dict.fromkeys(str(item) for item in value if str(item)))
