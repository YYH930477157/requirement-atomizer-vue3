"""Bounded agent decision loop (Phase 1/1.5): rule decider by default, LLM decider opt-in."""
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

from agent_decider import AgentDeciderError, llm_decide
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
TOKENS_MAX = 0   # 规则模式 tokens 恒为 0（Phase 1 契约）
DEFAULT_MAX_TOKENS = 20000   # llm 模式决策预算（仅决策调用,口径见 docs/agent-phase1.5-spec.md）
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
    candidates: list[str] = []
    # 批量登记：一个动作覆盖全部未排队缺口（test3 实测逐块登记 26 个缺口耗尽 10 轮预算,
    # ask_clarification 轮不到）。已排队（needs_extraction/issue_confirmed）的块由
    # state.unqueued_gap_block_ids 跨运行剔除,不再重复登记。
    if state.unqueued_gap_block_ids and "queue_all_gaps" not in excluded:
        candidates.append("queue_all_gaps")
    if state.open_question_count > 0 and "ask_clarification" not in excluded:
        candidates.append("ask_clarification")
    candidates.append("stop")
    return candidates


def rule_decider_v2(
    state: AnalysisState,
    candidates: list[str],
) -> tuple[str, str]:
    if state.readiness.get("verdict") == "READY":
        return "stop", "The READY gate passed."
    if "queue_all_gaps" in candidates:
        return (
            "queue_all_gaps",
            "Failed extraction sections or uncovered blocks remain and are not yet queued.",
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
    decider: str = "rule",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    llm_config: Any = None,
    state_loader: StateLoader = load_analysis_state,
    tool_runner: ToolRunner = execute_action,
) -> dict[str, Any]:
    if not 1 <= int(max_iterations) <= MAX_ITERATIONS:
        raise AgentLoopInputError(
            f"max_iterations must be between 1 and {MAX_ITERATIONS}"
        )
    # 审计纪律：全部参数校验必须先于状态读取与工具执行——此前 max_tokens=-1 会
    # 先写 omission 副作用、再因轨迹 schema 拒负值崩掉（有副作用、无轨迹）
    if int(max_tokens) < 0:
        raise AgentLoopInputError(f"max_tokens must be >= 0, got {max_tokens}")
    if decider not in ("rule", "llm"):
        raise AgentLoopInputError(f"decider must be 'rule' or 'llm', got: {decider!r}")
    if decider == "llm" and llm_config is None:
        raise AgentLoopInputError(
            "decider='llm' requires an LLM endpoint config (RATOMIZER_LLM_API_KEY 未设置时 "
            "不得伪造 stub 决策)"
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
    tokens_used = 0
    token_accounting = "none" if decider == "rule" else "complete"
    decider_usage = {"rule": 0, "llm": 0}

    for iteration in range(1, int(max_iterations) + 1):
        iterations = iteration
        candidates = build_candidates(state, excluded_actions=excluded_actions)
        decision_decider = "rule"
        action, reason = rule_decider_v2(state, candidates)
        if decider == "llm" and candidates != ["stop"]:
            if tokens_used >= int(max_tokens):
                reason = f"llm 决策预算耗尽回退（tokens_used={tokens_used} >= {max_tokens}）: {reason}"
            else:
                try:
                    picked, picked_reason, meta = llm_decide(
                        llm_config, state.state_digest(), candidates
                    )
                    tokens_used += int(meta["usage"]["total_tokens"])
                    if not meta.get("usage_complete"):
                        token_accounting = "partial"
                    action, reason = picked, picked_reason
                    decision_decider = "llm"
                except AgentDeciderError as exc:
                    reason = f"llm 决策失败回退: {exc}; {reason}"
        decider_usage[decision_decider] += 1
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
            "decider": decision_decider,
            "reason": reason,
            "budget": {
                "iterations_used": iteration,
                "iterations_max": int(max_iterations),
                "tokens_used": tokens_used,
                "tokens_max": int(max_tokens) if decider == "llm" else TOKENS_MAX,
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
        decider=decider,
        decider_usage=decider_usage,
        tokens_used=tokens_used,
        max_tokens=int(max_tokens) if decider == "llm" else TOKENS_MAX,
        token_accounting=token_accounting,
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
    decider: str = "rule",
    decider_usage: dict[str, int] | None = None,
    tokens_used: int = 0,
    max_tokens: int = TOKENS_MAX,
    token_accounting: str = "none",
) -> dict[str, Any]:
    digest = state.state_digest()
    return {
        "schema": SUMMARY_SCHEMA,
        "policy_version": AGENT_POLICY_VERSION,
        "run_id": run_id,
        "output_dir": str(root),
        "iterations": iterations,
        "iterations_max": max_iterations,
        "decider": decider,
        "decider_usage": dict(decider_usage or {"rule": iterations, "llm": 0}),
        "tokens_used": tokens_used,
        "tokens_max": max_tokens,
        "token_accounting": token_accounting,
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
    parser = argparse.ArgumentParser(description="Run the bounded agent decision loop.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--decider", choices=["rule", "llm"], default="rule")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser


def _llm_config_for_decider(decider: str) -> Any:
    if decider != "llm":
        return None
    import os

    from ai_extract import config_for_route

    config = config_for_route("openai_compatible")
    if config is None or not os.environ.get(str(getattr(config, "api_key_env", "")), "").strip():
        raise AgentLoopInputError(
            "decider=llm 需要可用的 openai_compatible 端点（检查 RATOMIZER_LLM_API_KEY "
            "与 llm_agents/review_pipeline.yaml）"
        )
    return config


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
            decider=args.decider,
            max_tokens=args.max_tokens,
            llm_config=_llm_config_for_decider(args.decider),
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
