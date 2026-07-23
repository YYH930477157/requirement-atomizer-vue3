"""Phase 1.5 comparison harness: rule vs llm decider over copies of one output directory.

Never mutates the source directory. If no LLM endpoint is available the rule side still
runs and the report truthfully records ``llm_ran: false`` — a rule-only result is never
presented as a comparison conclusion.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from agent_loop import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_TOKENS,
    MAX_ITERATIONS,
    AgentLoopInputError,
    run_agent_loop,
)
from decide_trace import DECIDE_TRACE_FILE

ENVELOPE_SCHEMA_VERSION = "1.0"
_COMPARE_SKIP_FILES = {"decide_trace.jsonl", "agent_loop_summary.json"}


class AgentCompareInputError(ValueError):
    """The requested comparison input is invalid."""


def _copy_run_dir(src: Path, dst: Path) -> None:
    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _COMPARE_SKIP_FILES}

    shutil.copytree(src, dst, ignore=_ignore)


def _trace_actions(run_dir: Path) -> list[str]:
    path = run_dir / DECIDE_TRACE_FILE
    if not path.exists():
        return []
    return [
        str(json.loads(line).get("action") or "")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _trace_details(run_dir: Path) -> list[dict[str, Any]]:
    """逐轮 trace 明细——必须在临时目录清理前读出,否则 reason/result 随副本丢失。"""
    path = run_dir / DECIDE_TRACE_FILE
    if not path.exists():
        return []
    details: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        result = row.get("result") or {}
        details.append({
            "iteration": row.get("iteration"),
            "action": str(row.get("action") or ""),
            "decider": str(row.get("decider") or ""),
            "reason": str(row.get("reason") or ""),
            "result": {
                "status": str(result.get("status") or ""),
                "summary": str(result.get("summary") or ""),
            },
        })
    return details


def _agreement(rule_actions: list[str], llm_actions: list[str]) -> dict[str, Any]:
    overlap = min(len(rule_actions), len(llm_actions))
    same = sum(
        1 for index in range(overlap) if rule_actions[index] == llm_actions[index]
    )
    return {
        "sequence_identical": rule_actions == llm_actions,
        "compared_positions": overlap,
        "matching_positions": same,
        "position_agreement": round(same / overlap, 4) if overlap else 1.0,
    }


def run_comparison(
    out_dir: Path,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    llm_config: Any = None,
) -> dict[str, Any]:
    # 预算预校验必须先于任何循环：rule 侧不传 max_tokens、无 key 时 llm 侧根本不跑,
    # 依赖循环内部校验会让非法 --max-tokens 静默 exit 0（2026-07-23 审计实证 -1 退出 0）
    if not 1 <= int(max_iterations) <= MAX_ITERATIONS:
        raise AgentCompareInputError(
            f"max_iterations must be between 1 and {MAX_ITERATIONS}"
        )
    if int(max_tokens) < 0:
        raise AgentCompareInputError(f"max_tokens must be >= 0, got {max_tokens}")
    root = Path(out_dir).expanduser().resolve()
    if not root.is_dir():
        raise AgentCompareInputError(f"Output directory does not exist: {root}")
    with tempfile.TemporaryDirectory(prefix="agent_compare_") as tmp:
        rule_dir = Path(tmp) / "rule"
        llm_dir = Path(tmp) / "llm"
        _copy_run_dir(root, rule_dir)
        rule_summary = run_agent_loop(rule_dir, max_iterations=max_iterations, decider="rule")
        rule_actions = _trace_actions(rule_dir)
        rule_trace = _trace_details(rule_dir)

        llm_summary: dict[str, Any] | None = None
        llm_actions: list[str] = []
        llm_trace: list[dict[str, Any]] = []
        llm_error = ""
        if llm_config is not None:
            _copy_run_dir(root, llm_dir)
            try:
                llm_summary = run_agent_loop(
                    llm_dir,
                    max_iterations=max_iterations,
                    decider="llm",
                    max_tokens=max_tokens,
                    llm_config=llm_config,
                )
                llm_actions = _trace_actions(llm_dir)
                llm_trace = _trace_details(llm_dir)
            except Exception as exc:  # 对比器不因 llm 侧失败丢弃 rule 侧结果
                llm_error = f"{type(exc).__name__}: {exc}"

    llm_ran = llm_summary is not None
    return {
        "out_dir": str(root),
        "rule": {
            "iterations": rule_summary["iterations"],
            "termination_reason": rule_summary["termination_reason"],
            "readiness": rule_summary["readiness"],
            "actions": rule_actions,
            "trace": rule_trace,
            "decider_usage": rule_summary["decider_usage"],
            "tokens_used": rule_summary["tokens_used"],
            "token_accounting": rule_summary["token_accounting"],
        },
        "llm": (
            {
                "iterations": llm_summary["iterations"],
                "termination_reason": llm_summary["termination_reason"],
                "readiness": llm_summary["readiness"],
                "actions": llm_actions,
                "trace": llm_trace,
                "decider_usage": llm_summary["decider_usage"],
                "tokens_used": llm_summary["tokens_used"],
                "token_accounting": llm_summary["token_accounting"],
            }
            if llm_ran
            else None
        ),
        "llm_ran": llm_ran,
        "llm_error": llm_error or ("llm_unavailable: no endpoint config" if llm_config is None else ""),
        "agreement": _agreement(rule_actions, llm_actions) if llm_ran else None,
    }


def _llm_config_or_none() -> Any:
    try:
        import os

        from ai_extract import config_for_route

        config = config_for_route("openai_compatible")
        if config is None or not os.environ.get(
            str(getattr(config, "api_key_env", "")), ""
        ).strip():
            return None
        return config
    except Exception:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare rule vs llm deciders on copies of one output directory."
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out_dir = args.out_dir.expanduser().resolve()
    try:
        report = run_comparison(
            out_dir,
            max_iterations=args.max_iterations,
            max_tokens=args.max_tokens,
            llm_config=_llm_config_or_none(),
        )
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "agent-compare",
            "ok": True,
            "output_dir": str(out_dir),
            "llm_ran": report["llm_ran"],
            "comparison": report,
        }
        code = 0
    except (AgentCompareInputError, AgentLoopInputError) as exc:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "agent-compare",
            "ok": False,
            "output_dir": str(out_dir),
            "error": {"type": "input_error", "message": str(exc)},
        }
        code = 2
    except Exception as exc:  # 与 agent_loop 同款最终兜底——运行时错误也出 envelope,不裸崩
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "agent-compare",
            "ok": False,
            "output_dir": str(out_dir),
            "error": {"type": "pipeline_error", "message": f"{type(exc).__name__}: {exc}"},
        }
        code = 3
    print(json.dumps(envelope, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
