"""Pipeline 逻辑阶段契约（quality-first 方案 §15，M4）。

声明 quality_first 各逻辑阶段的关键依赖（输入产物 + 行为版本 + 配置依赖）。
用途：PipelinePlan 构造/校验 + stage fingerprint 隔离（无关配置变化不得使
其他阶段失效——§15 末条）。本模块是纯声明，无 I/O、无执行。
"""
from __future__ import annotations

from typing import Any

from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
from quality_gates import QUALITY_GATES_VERSION
from routed_execution import ROUTED_MERGE_VERSION
from unit_router import UNIT_ROUTER_VERSION

PIPELINE_CONTRACTS_VERSION = "pipeline-contracts-v1"

# 逻辑阶段 → 契约。inputs 是 governed pipeline 产物文件名；versions 是进入该阶段
# fingerprint 的行为版本；config 是影响该阶段的 env 名（未列出的配置变化不得
# 使该阶段缓存失效）。
LOGICAL_STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "atomize": {
        "inputs": ["blocks.jsonl", "chunks.jsonl", "table_items.jsonl",
                   "table_cell_items.jsonl", "table_cell_dispositions.jsonl"],
        "versions": [],  # 由 desktop_tasks.stage_producer 既有口径决定（解析侧）
        "config": [],
    },
    "plan-extraction-units": {
        "inputs": ["blocks.jsonl", "table_items.jsonl", "table_cell_items.jsonl",
                   "table_cell_dispositions.jsonl"],
        "versions": [EXTRACTION_UNIT_PLANNER_VERSION],
        "config": [],
    },
    "route-units": {
        "inputs": ["extraction_units.jsonl"],
        "versions": [UNIT_ROUTER_VERSION],
        "config": ["RATOMIZER_UNIT_ROUTER_RULES"],
    },
    "execute-routed-units": {
        # M5 接 processor dispatch：按 route 分派 A/B/Context/Review 处理器
        "inputs": ["extraction_units.jsonl", "unit_routing_decisions.jsonl"],
        "versions": [],
        "config": ["RATOMIZER_LLM_MODEL", "RATOMIZER_LLM_BASE_URL"],
    },
    "merge-routed-results": {
        "inputs": ["extraction_units.jsonl", "unit_routing_decisions.jsonl"],
        "versions": [ROUTED_MERGE_VERSION],
        "config": [],
    },
    "quality-gates": {
        "inputs": ["functional_requirements.json", "table_cell_dispositions.jsonl",
                   "unit_routing_decisions.jsonl"],
        "versions": [QUALITY_GATES_VERSION],
        "config": [],
    },
    "targeted-escalation": {
        # M5：复用 claim queue/CAS/WAL/预算（§19 红线）
        "inputs": ["routing_gaps.jsonl"],
        "versions": [],
        "config": ["RATOMIZER_LLM_BUDGET"],
    },
    "translation": {
        "inputs": ["blocks.jsonl", "chunks.jsonl"],
        "versions": [],  # 由 full_translation/doc_annotation_export 既有版本决定
        "config": ["RATOMIZER_TRANSLATION_MODE"],
    },
    "publish-deliverables": {
        "inputs": [],
        "versions": [],
        "config": [],
    },
}

# legacy 阶段（CHAIN_ORDER 口面）的最小契约：仅供 PipelinePlan 构造/校验使用；
# 它们的生产 fingerprint 权威仍在 desktop_tasks.stage_producer（不在此复刻，
# 避免两套指纹口径漂移）。
LEGACY_STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "ai-extract": {"inputs": ["blocks.jsonl", "table_cell_items.jsonl"],
                   "versions": [], "config": ["RATOMIZER_LLM_MODEL"]},
    "functional-extract": {"inputs": ["blocks.jsonl", "chunks.jsonl"],
                           "versions": [], "config": ["RATOMIZER_FUNCTIONAL_EXTRACT"]},
    "functional-synthesis": {"inputs": ["ai_requirements.jsonl"], "versions": [],
                             "config": []},
    "assemble": {"inputs": ["atomic_requirements.jsonl"], "versions": [], "config": []},
    "requirements-analysis": {"inputs": ["ai_requirements.jsonl"], "versions": [],
                              "config": []},
    "template-write": {"inputs": [], "versions": [], "config": []},
    "clarification-report": {"inputs": [], "versions": [], "config": []},
    "full-translation": {"inputs": ["blocks.jsonl", "chunks.jsonl"], "versions": [],
                         "config": ["RATOMIZER_TRANSLATION_MODE"]},
    "compose": {"inputs": [], "versions": [], "config": []},
    "export-annotation-html": {"inputs": [], "versions": [],
                               "config": ["RATOMIZER_TRANSLATION_MODE"]},
}

ALL_STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    **LOGICAL_STAGE_CONTRACTS, **LEGACY_STAGE_CONTRACTS,
}


def contract_for(stage: str) -> dict[str, Any]:
    contract = ALL_STAGE_CONTRACTS.get(stage)
    if contract is None:
        raise ValueError(
            f"未知逻辑阶段: {stage}（可用: {', '.join(ALL_STAGE_CONTRACTS)}）")
    return contract


def stage_versions_for(stage: str) -> list[str]:
    return list(contract_for(stage).get("versions") or [])


def stage_inputs_for(stage: str) -> list[str]:
    return list(contract_for(stage).get("inputs") or [])
