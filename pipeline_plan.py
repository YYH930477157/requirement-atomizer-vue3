"""PipelinePlan（quality-first 方案 §11，M4 feature flag）。

生成/校验/指纹化执行计划：声明执行策略、交付选项、翻译模式、预算模式与
逻辑阶段。**默认策略保持 legacy_combined**（§31：Router 未过真实语料门禁前
不翻默认执行方式）；quality_first/force_a/force_b/full_dual_audit 是显式
opt-in（CLI --execution-policy 或 RATOMIZER_EXECUTION_POLICY）。

plan_fingerprint = sha256(canonical plan payload)——同输入同配置必同指纹；
delivery/翻译/预算选项变化会改变指纹（它们影响执行集合），无关配置不进入
指纹（§15 指纹隔离）。
"""
from __future__ import annotations

from typing import Any

from artifact_store import ArtifactStore
from claim_artifacts import hash_json
from config import get_env
from io_utils import read_jsonl
from pipeline_contracts import (
    ALL_STAGE_CONTRACTS,
    LOGICAL_STAGE_CONTRACTS,
    PIPELINE_CONTRACTS_VERSION,
)

PIPELINE_PLAN_SCHEMA = "ratomizer-pipeline-plan/v2"
PIPELINE_PLAN_FILENAME = "pipeline_plan.json"

EXECUTION_POLICIES = ("quality_first", "force_a", "force_b",
                      "full_dual_audit", "legacy_combined")
TRANSLATION_MODES = ("off", "markers", "full")
BUDGET_MODES = ("off", "observe", "enforce")

EXECUTION_POLICY_ENV = "RATOMIZER_EXECUTION_POLICY"
TRANSLATION_MODE_ENV = "RATOMIZER_TRANSLATION_MODE"
BUDGET_MODE_ENV = "RATOMIZER_BUDGET_MODE"

DELIVERY_KEYS = ("software_requirements", "cosem_spec", "template_workbook",
                 "annotation_bundle")

_QUALITY_FIRST_STAGES = [
    "atomize", "plan-extraction-units", "route-units", "execute-routed-units",
    "merge-routed-results", "quality-gates", "targeted-escalation",
    "publish-deliverables",
]

# legacy 策略的既有阶段序（CHAIN_ORDER 投影，不改变现状）
_LEGACY_STAGES = [
    "ai-extract", "functional-extract", "functional-synthesis", "assemble",
    "requirements-analysis", "template-write", "clarification-report",
    "full-translation", "compose", "export-annotation-html",
]


def resolve_execution_policy(*, override: str | None = None) -> str:
    policy = str(override or get_env(EXECUTION_POLICY_ENV) or "legacy_combined").strip()
    if policy not in EXECUTION_POLICIES:
        raise ValueError(
            f"未知执行策略: {policy}（可用: {', '.join(EXECUTION_POLICIES)}）")
    return policy


def resolve_translation_mode(*, override: str | None = None) -> str:
    mode = str(override or get_env(TRANSLATION_MODE_ENV) or "full").strip()
    if mode not in TRANSLATION_MODES:
        raise ValueError(f"未知翻译模式: {mode}（可用: {', '.join(TRANSLATION_MODES)}）")
    return mode


def resolve_budget_mode(*, override: str | None = None) -> str:
    mode = str(override or get_env(BUDGET_MODE_ENV) or "off").strip()
    if mode not in BUDGET_MODES:
        raise ValueError(f"未知预算模式: {mode}（可用: {', '.join(BUDGET_MODES)}）")
    return mode


def _delivery_stages(delivery: dict[str, bool], translation_mode: str,
                     policy: str) -> list[str]:
    if policy == "legacy_combined":
        stages = list(_LEGACY_STAGES)
        if translation_mode == "off":
            stages = [stage for stage in stages if stage != "full-translation"]
        return stages
    stages = list(_QUALITY_FIRST_STAGES)
    if translation_mode != "off":
        stages.insert(-1, "translation")
    return stages


def build_pipeline_plan(out_dir=None, *, execution_policy: str | None = None,
                        delivery: dict[str, bool] | None = None,
                        translation_mode: str | None = None,
                        budget_mode: str | None = None) -> dict[str, Any]:
    """构建（并可写盘）执行计划。out_dir 为 None 时只构建不落盘。"""
    policy = resolve_execution_policy(override=execution_policy)
    translation = resolve_translation_mode(override=translation_mode)
    budget = resolve_budget_mode(override=budget_mode)
    resolved_delivery = {key: bool((delivery or {}).get(key, True))
                         for key in DELIVERY_KEYS}
    resolved_delivery["translation_mode"] = translation

    stages = _delivery_stages(resolved_delivery, translation, policy)
    unknown = [stage for stage in stages if stage not in ALL_STAGE_CONTRACTS]
    if unknown:  # pragma: no cover - 阶段表与契约表同步维护
        raise ValueError(f"计划阶段缺契约: {unknown}")

    payload: dict[str, Any] = {
        "schema": PIPELINE_PLAN_SCHEMA,
        "execution_policy": policy,
        "delivery": resolved_delivery,
        "budget_mode": budget,
        "stages": stages,
        "contracts_version": PIPELINE_CONTRACTS_VERSION,
        "stage_versions": {stage: ALL_STAGE_CONTRACTS[stage]["versions"]
                           for stage in stages},
    }
    payload["plan_fingerprint"] = hash_json("pipeline-plan", payload)
    return payload


def validate_pipeline_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != PIPELINE_PLAN_SCHEMA:
        raise ValueError(f"计划 schema 不符: {plan.get('schema')}")
    if plan.get("execution_policy") not in EXECUTION_POLICIES:
        raise ValueError(f"非法执行策略: {plan.get('execution_policy')}")
    if plan.get("delivery", {}).get("translation_mode") not in TRANSLATION_MODES:
        raise ValueError("非法翻译模式")
    if plan.get("budget_mode") not in BUDGET_MODES:
        raise ValueError(f"非法预算模式: {plan.get('budget_mode')}")
    fingerprint = plan.get("plan_fingerprint")
    recomputed = hash_json("pipeline-plan",
                           {key: value for key, value in plan.items()
                            if key != "plan_fingerprint"})
    if fingerprint != recomputed:
        raise ValueError("plan_fingerprint 与内容不一致（计划被改动或损坏）")


def write_pipeline_plan(out_dir, plan: dict[str, Any]) -> None:
    validate_pipeline_plan(plan)
    store = ArtifactStore(out_dir, category="pipeline")
    store.write_json(PIPELINE_PLAN_FILENAME, plan)


def load_pipeline_plan(out_dir) -> dict[str, Any] | None:
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, PIPELINE_PLAN_FILENAME,
                                  category="pipeline", for_write=False)
    if not path.is_file():
        return None
    import json

    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return plan if isinstance(plan, dict) else None


def routing_summary_for_plan(out_dir) -> dict[str, int] | None:
    """计划附带的路由统计（旧结果无 routing 产物时返回 None——只读兼容，不伪造）。"""
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, "unit_routing_decisions.jsonl",
                                  category="pipeline", for_write=False)
    if not path.is_file():
        return None
    decisions = read_jsonl(path)
    if not decisions:
        return None
    counts: dict[str, int] = {}
    for decision in decisions:
        route = str(decision.get("route") or "")
        counts[route] = counts.get(route, 0) + 1
    return counts
