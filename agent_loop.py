"""Deterministic Phase 1 decision loop for bounded requirements triage."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from agent_policy import AGENT_POLICY_VERSION
from agent_state import (
    AgentStateInputError,
    AgentStateValidationError,
    AnalysisState,
    load_analysis_state,
)
from agent_tools import execute_action, stop
from decide_trace import (
    DECIDE_TRACE_FILE,
    DECIDE_TRACE_VERSION,
    append_decide_trace,
    decide_trace_lock,
)


DEFAULT_MAX_ITERATIONS = 10
MAX_ITERATIONS = 50
TOKENS_MAX = 0
SUMMARY_FILE = "agent_loop_summary.json"
SUMMARY_SCHEMA = "agent-loop-summary/v1"
ENVELOPE_SCHEMA_VERSION = "1.0"
_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.02

StateLoader = Callable[[Path], AnalysisState]
ToolRunner = Callable[[Path, str, AnalysisState], dict[str, Any]]


class AgentLoopInputError(ValueError):
    """CLI or API input is outside the bounded Phase 1 contract."""


def build_candidates(
    state: AnalysisState,
    *,
    excluded_actions: set[str] | None = None,
) -> list[str]:
    excluded = excluded_actions or set()
    if state.readiness.get("verdict") == "READY":
        return ["stop"]
    block_ids = sorted(
        set(state.failed_section_block_ids) | set(state.coverage_gap_block_ids)
    )
    candidates = [
        f"resample_section:{block_id}"
        for block_id in block_ids
        if f"resample_section:{block_id}" not in excluded
    ]
    if state.open_question_count > 0 and "ask_clarification" not in excluded:
        candidates.append("ask_clarification")
    candidates.append("stop")
    return candidates


def rule_decider_v1(
    state: AnalysisState,
    candidates: list[str],
) -> tuple[str, str]:
    if state.readiness.get("verdict") == "READY":
        return "stop", "The READY gate passed."
    resample_actions = sorted(
        action for action in candidates if action.startswith("resample_section:")
    )
    if resample_actions:
        return (
            resample_actions[0],
            "A failed extraction section or current uncovered block remains.",
        )
    if "ask_clarification" in candidates and state.open_question_count > 0:
        return (
            "ask_clarification",
            "Unresolved hard clarification questions require external input.",
        )
    return "stop", "No eligible deterministic Phase 1 action remains."


def run_agent_loop(
    out_dir: Path,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    state_loader: StateLoader = load_analysis_state,
    tool_runner: ToolRunner = execute_action,
) -> dict[str, Any]:
    if not 1 <= int(max_iterations) <= MAX_ITERATIONS:
        raise AgentLoopInputError(
            f"max_iterations must be between 1 and {MAX_ITERATIONS}"
        )
    root = Path(out_dir).expanduser().resolve()
    state = state_loader(root)
    run_id = state.run_id
    excluded_actions: set[str] = set()
    failed_actions: set[str] = set()
    unavailable_actions: set[str] = set()
    completed_actions: set[str] = set()
    iterations = 0
    last_action = ""
    termination_reason = "stopped"

    for iteration in range(1, int(max_iterations) + 1):
        iterations = iteration
        candidates = build_candidates(state, excluded_actions=excluded_actions)
        action, reason = rule_decider_v1(state, candidates)
        last_action = action
        if action == "stop":
            result: dict[str, Any] = stop(state)
        else:
            try:
                result = tool_runner(root, action, state)
                _validate_tool_result(result)
            except Exception as exc:
                result = {
                    "status": "error",
                    "summary": f"{type(exc).__name__}: {exc}",
                }

        status = str(result["status"])
        if status == "error":
            failed_actions.add(action)
            excluded_actions.add(action)
        elif status == "skipped":
            unavailable_actions.add(action)
            excluded_actions.add(action)
        elif action == "ask_clarification":
            completed_actions.add(action)
            excluded_actions.add(action)

        next_state = state
        if action != "stop":
            next_state = state_loader(root)
        reached_ready = next_state.readiness.get("verdict") == "READY"
        budget_exhausted = (
            iteration == int(max_iterations)
            and action != "stop"
            and not reached_ready
        )
        trace_result = {
            "status": status,
            "summary": str(result["summary"]),
        }
        if budget_exhausted:
            trace_result = {
                "status": "skipped",
                "summary": (
                    f"{trace_result['summary']} Iteration budget exhausted; no further action ran."
                ),
            }
            termination_reason = "budget_exhausted"

        append_decide_trace(root, {
            "trace_version": DECIDE_TRACE_VERSION,
            "run_id": run_id,
            "iteration": iteration,
            "ts": _utc_now(),
            "policy_version": AGENT_POLICY_VERSION,
            "state_digest": state.state_digest(),
            "candidates": candidates,
            "action": action,
            "decider": "rule",
            "reason": reason,
            "budget": {
                "iterations_used": iteration,
                "iterations_max": int(max_iterations),
                "tokens_used": 0,
                "tokens_max": TOKENS_MAX,
            },
            "result": trace_result,
        })

        if action == "stop":
            termination_reason = "ready" if state.readiness.get("verdict") == "READY" else "stopped"
            break

        state = next_state
        if reached_ready:
            termination_reason = "ready"
            break
        if budget_exhausted:
            break

    summary = _build_summary(
        root,
        state,
        run_id=run_id,
        iterations=iterations,
        max_iterations=int(max_iterations),
        termination_reason=termination_reason,
        last_action=last_action,
        failed_actions=failed_actions,
        unavailable_actions=unavailable_actions,
        completed_actions=completed_actions,
    )
    _write_summary(root, summary)
    return summary


def _validate_tool_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("agent tool result must be an object")
    if result.get("status") not in {"ok", "error", "skipped"}:
        raise ValueError("agent tool result has an invalid status")
    if not str(result.get("summary") or "").strip():
        raise ValueError("agent tool result summary is required")


def _build_summary(
    root: Path,
    state: AnalysisState,
    *,
    run_id: str,
    iterations: int,
    max_iterations: int,
    termination_reason: str,
    last_action: str,
    failed_actions: set[str],
    unavailable_actions: set[str],
    completed_actions: set[str],
) -> dict[str, Any]:
    digest = state.state_digest()
    return {
        "schema": SUMMARY_SCHEMA,
        "policy_version": AGENT_POLICY_VERSION,
        "run_id": run_id,
        "output_dir": str(root),
        "iterations": iterations,
        "iterations_max": max_iterations,
        "tokens_used": 0,
        "tokens_max": TOKENS_MAX,
        "termination_reason": termination_reason,
        "last_action": last_action,
        "readiness": str(state.readiness.get("verdict") or "NEEDS WORK"),
        "ready_gate": digest["ready_gate"],
        "blocked_reasons": digest["blocked_reasons"],
        "counts": digest["counts"],
        "failed_actions": sorted(failed_actions),
        "unavailable_actions": sorted(unavailable_actions),
        "completed_actions": sorted(completed_actions),
        "trace_file": DECIDE_TRACE_FILE,
        "completed_at": _utc_now(),
    }


def _write_summary(root: Path, payload: dict[str, Any]) -> None:
    path = root / SUMMARY_FILE
    temp = root / f".{SUMMARY_FILE}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with decide_trace_lock(root):
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(temp, path)
                    break
                except PermissionError:
                    if attempt + 1 >= _REPLACE_ATTEMPTS:
                        raise
                    time.sleep(_REPLACE_RETRY_DELAY_S)
        finally:
            temp.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the bounded Phase 1 agent decision loop.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out_dir = args.out_dir.expanduser().resolve()
    try:
        if not 1 <= args.max_iterations <= MAX_ITERATIONS:
            raise AgentLoopInputError(
                f"max_iterations must be between 1 and {MAX_ITERATIONS}"
            )
        summary = run_agent_loop(
            out_dir,
            max_iterations=args.max_iterations,
        )
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "agent-loop",
            "ok": True,
            "output_dir": str(out_dir),
            "summary": summary,
        }
        code = 0
    except (AgentLoopInputError, AgentStateInputError) as exc:
        envelope = _error_envelope(out_dir, "input_error", str(exc))
        code = 2
    except (AgentStateValidationError, OSError, TimeoutError, ValueError) as exc:
        envelope = _error_envelope(out_dir, "validation_error", str(exc))
        code = 3
    except Exception as exc:  # pragma: no cover - final CLI safety net
        envelope = _error_envelope(out_dir, "pipeline_error", str(exc))
        code = 3
    print(json.dumps(envelope, ensure_ascii=False))
    return code


def _error_envelope(out_dir: Path, error_type: str, message: str) -> dict[str, Any]:
    return {
        "tool": "requirement-atomizer",
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "command": "agent-loop",
        "ok": False,
        "output_dir": str(out_dir),
        "error": {"type": error_type, "message": message},
    }


if __name__ == "__main__":
    sys.exit(main())
