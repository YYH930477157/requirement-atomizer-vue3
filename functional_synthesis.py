from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_review_actions import read_ai_review_states, source_ai_requirement_id
from functional_catalog import CatalogChat, build_function_catalog
from llm_pipeline import read_jsonl

FUNCTIONAL_SYNTHESIS_VERSION = "functional-synthesis-v5"
FUNCTIONAL_REQUIREMENTS = "functional_requirements.json"


def synthesize_requirements(requirements: list[dict[str, Any]], *, chat: CatalogChat | None = None) -> list[dict[str, Any]]:
    items = build_function_catalog(requirements, chat=chat)
    for index, item in enumerate(items, start=1):
        item["synthesis_index"] = index
    return items


def _resolve_catalog_chat(route: str | None, chat: CatalogChat | None) -> tuple[CatalogChat | None, str]:
    if chat is not None:
        return chat, "injected"
    if not route or route == "stub":
        return None, "stub"
    try:
        from ai_extract import DEFAULT_PIPELINE_PATH, config_for_route
        from llm_client import chat_json
        config = config_for_route(route, DEFAULT_PIPELINE_PATH)
    except Exception:
        return None, "stub"
    if config is None:
        return None, "stub"
    local_endpoint = any(host in config.base_url.casefold() for host in ("127.0.0.1", "localhost", "::1"))
    if not local_endpoint and not os.environ.get(config.api_key_env):
        return None, "stub"

    def invoke(system: str, user: str) -> dict[str, Any]:
        return chat_json(config, system, user)

    return invoke, f"llm:{config.model}"


def run_functional_synthesis(out_dir: Path, *, route: str | None = "stub",
                             chat: CatalogChat | None = None) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    source = out_dir / "ai_requirements.jsonl"
    if not source.exists():
        raise FileNotFoundError(f"ai_requirements.jsonl not found in {out_dir}")
    requirements = read_jsonl(source)
    states = read_ai_review_states(out_dir)
    eligible: list[dict[str, Any]] = []
    for requirement in requirements:
        stable_id = source_ai_requirement_id(requirement)
        state = states.get(stable_id, {})
        if str(state.get("status") or "").strip() == "rejected":
            continue
        reviewed = dict(requirement)
        reviewed["ai_req_id"] = stable_id
        module_override = str(state.get("module_override") or "").strip()
        if module_override:
            reviewed["module"] = module_override
        ownership_override = str(state.get("ownership_override") or "").strip()
        if ownership_override:
            reviewed["ownership_override"] = ownership_override
        eligible.append(reviewed)
    active_chat, executed_route = _resolve_catalog_chat(route, chat)
    items = synthesize_requirements(eligible, chat=active_chat)
    payload = {
        "schema_version": 1,
        "producer": FUNCTIONAL_SYNTHESIS_VERSION,
        "route_requested": route or "stub",
        "route": executed_route,
        "source": source.name,
        "source_requirements": len(requirements),
        "eligible_requirements": len(eligible),
        "functional_requirements": len(items),
        "items": items,
    }
    target = out_dir / FUNCTIONAL_REQUIREMENTS
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "kind": "functional_synthesis",
        "out_dir": str(out_dir),
        "source_requirements": len(requirements),
        "functional_requirements": len(items),
        "route_requested": route or "stub",
        "route": executed_route,
        "written": [target.name],
    }
