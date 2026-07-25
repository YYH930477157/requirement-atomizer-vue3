from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_review_actions import read_ai_review_states, source_ai_requirement_id
from compliance import is_compliance_requirement
from functional_catalog import CatalogChat, build_function_catalog
from llm_pipeline import read_jsonl

FUNCTIONAL_SYNTHESIS_VERSION = "functional-synthesis-v7"  # v7:聚类两规则——period_variant 周期档位不同分家(15min×24h 不并)、legacy_concept 标题共享对象词组合并(误拆修复)
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
    compliance_requirements = 0
    for requirement in requirements:
        stable_id = source_ai_requirement_id(requirement)
        state = states.get(stable_id, {})
        if str(state.get("status") or "").strip() == "rejected":
            continue
        # 合规交付项有独立生命周期，不参与研发功能聚类。否则证书/法令会被合成成
        # “测试合规功能”，随后进入软硬件归属和软件模板，掩盖真实交付责任。
        if is_compliance_requirement(requirement):
            compliance_requirements += 1
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
    # C3（0710 评审）：route 不得夸大——resolver 只凭"有 key"就报 llm:{model}，但每个模块
    # 都可能因调用失败/映射非法回退确定性。按产物实际 merge_method 事后判定。
    if executed_route.startswith("llm:") and not any(
            str(item.get("merge_method") or "") == "llm_catalog" for item in items):
        executed_route = "stub"
    # C5（0710 评审）：确定性侧守恒核对——LLM 侧有 exactly-once 校验，确定性侧此前零防线,
    # 空 id/重复 id 会被 _unique_strings 静默丢弃。违反不阻断（记账+告警），交付可审计。
    eligible_ids = [str(r.get("ai_req_id") or "") for r in eligible]
    assigned: list[str] = []
    for item in items:
        assigned.extend(str(x) for x in item.get("source_ai_requirement_ids") or [])
    from collections import Counter as _Counter
    dup_assigned = sorted(k for k, v in _Counter(assigned).items() if v > 1)
    missing = sorted(set(x for x in eligible_ids if x) - set(assigned))
    if dup_assigned or missing or len(eligible_ids) != len(set(eligible_ids)):
        import logging
        logging.getLogger("requirement_atomizer").warning(
            "功能合成守恒异常：缺失 %d / 重复归属 %d / 输入重复 id %d",
            len(missing), len(dup_assigned), len(eligible_ids) - len(set(eligible_ids)))
    from requirement_record import provenance
    payload = {
        "schema_version": 1,
        "producer": FUNCTIONAL_SYNTHESIS_VERSION,
        # C4（0710 评审）：标准 provenance 块（§43：producer/version/generated_at），消费端校验
        "provenance": provenance("functional_synthesis", FUNCTIONAL_SYNTHESIS_VERSION),
        "route_requested": route or "stub",
        "route": executed_route,
        "source": source.name,
        "source_requirements": len(requirements),
        "eligible_requirements": len(eligible),
        "compliance_requirements": compliance_requirements,
        "functional_requirements": len(items),
        "conservation": {"missing_source_ids": missing[:20], "duplicate_assignments": dup_assigned[:20]},
        "items": items,
    }
    target = out_dir / FUNCTIONAL_REQUIREMENTS
    # 原子写（0711 评审跟进）：manifest 已原子化,主产物同样不能留半截 JSON——消费端
    # (requirements_analysis) 读坏文件会静默回退逐原子输入,合成结果悄悄丢失。
    # 不 import desktop_tasks(它 import 本模块,会循环);os.replace 在 Windows 上可覆盖目标。
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    # 守恒摘要上浮顶层（0711 评审）：此前只在写盘 JSON + WARNING 日志里，桌面/UI 看不到，
    # 丢原子无人察觉。上浮计数（明细仍留 conservation 字段），让调用方可直接显示。
    conservation_summary = {
        "missing": len(missing),
        "duplicates": len(dup_assigned),
        "input_duplicate_ids": len(eligible_ids) - len(set(eligible_ids)),
        "ok": not (missing or dup_assigned or len(eligible_ids) != len(set(eligible_ids))),
    }
    return {
        "kind": "functional_synthesis",
        "out_dir": str(out_dir),
        "source_requirements": len(requirements),
        "compliance_requirements": compliance_requirements,
        "functional_requirements": len(items),
        "route_requested": route or "stub",
        "route": executed_route,
        "conservation": conservation_summary,
        "written": [target.name],
    }
