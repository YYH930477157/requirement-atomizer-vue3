"""LLM decision maker for the bounded agent loop (Phase 1.5).

Never the default decider in this phase: the loop falls back to the rule decider per
iteration whenever the LLM path fails, and the trace records which mechanism actually
made each decision.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_client import LLMClientConfig, chat_json_with_meta


DECIDER_PROMPT_VERSION = "agent-decider-v1"

_SYSTEM_PROMPT = (
    "You are the decision maker of a bounded requirements-analysis agent. "
    "Each turn you receive a state digest and a list of candidate actions. "
    "Pick exactly ONE action from the candidates and explain briefly why. "
    "Rules: choose \"stop\" when nothing actionable remains or the READY gate passed; "
    "choose \"ask_clarification\" when required information is missing and cannot be "
    "derived from the source; never invent block ids, requirement ids, or new actions; "
    "never claim extraction or review work as done when it was only queued. "
    "Respond with a single JSON object: {\"action\": \"...\", \"reason\": \"...\"}."
)


class AgentDeciderError(RuntimeError):
    """The LLM decision path failed; the caller must fall back to the rule decider."""


def _state_prompt(state_digest: dict[str, Any], candidates: list[str]) -> str:
    return (
        "State digest:\n"
        + json.dumps(state_digest, ensure_ascii=False, indent=2)
        + "\n\nCandidate actions:\n"
        + json.dumps(candidates, ensure_ascii=False)
        + "\n\nPick one action now."
    )


def llm_decide(
    config: LLMClientConfig,
    state_digest: dict[str, Any],
    candidates: list[str],
) -> tuple[str, str, dict[str, Any]]:
    """Ask the model to pick one candidate action.

    Returns (action, reason, meta). meta carries token usage per the Phase 1.5
    accounting contract. Raises AgentDeciderError on any failure — the loop then
    falls back to the rule decider for that iteration (decider="rule" in the trace).
    """
    if not candidates:
        raise AgentDeciderError("no candidates to decide over")
    try:
        data, meta = chat_json_with_meta(
            config, _SYSTEM_PROMPT, _state_prompt(state_digest, candidates)
        )
    except Exception as exc:
        raise AgentDeciderError(f"{type(exc).__name__}: {exc}") from exc
    action = str(data.get("action") or "").strip()
    reason = str(data.get("reason") or "").strip()
    if action not in candidates:
        raise AgentDeciderError(
            f"llm picked action outside candidates: {action!r}"
        )
    if not reason:
        raise AgentDeciderError("llm returned an empty reason")
    return action, reason, meta


def config_path_default() -> Path:
    return Path(__file__).resolve().parent / "llm_agents" / "review_pipeline.yaml"
