from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from result_package import governed_artifact_path
from typing import Any, Callable

import yaml

from domain_pack import load_domain_pack
from io_utils import read_jsonl, read_jsonl_recover_torn_tail
from llm_client import (
    LLMClientConfig,
    LLMConnectionError,
    LLMError,
    LLMResponseError,
    _aggregate_usage,
    chat_json,
    chat_json_messages,
    chat_with_tools,
)
from llm_review_schema import validate_llm_review_result_payload, validate_llm_review_results
from resources import package_root
from review_state import (
    CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION,
    RequirementReviewState,
    _atomic_write_jsonl as atomic_write_review_states,
    atomic_target_authority_write_revision,
    merge_review_states,
    review_event_key,
    review_state_lock,
    target_publication_revision,
)
from review_tools import REVIEW_TOOLS_VERSION, TOOLS as REVIEW_TOOLS, evidence_fingerprint, make_tool_executor


LOGGER = logging.getLogger("requirement_atomizer")
_PACKAGE_ROOT = package_root()
DEFAULT_PIPELINE_PATH = _PACKAGE_ROOT / "llm_agents" / "review_pipeline.yaml"
DEFAULT_DOMAIN_PACK_PATH = _PACKAGE_ROOT / "domain_packs" / "dlms_cosem" / "pack.yaml"
# m2-review-v3：首轮 KB 证据固定 top-3×300 字，review tool-loop 成本上限收紧；
# v2：Agent Phase 2 工具化融合审查（tool-loop 调用 review_tools 只读工具取证）；
# v1：单次融合 prompt（无工具）
PROMPT_VERSION = "m2-review-v3"
# Cache rows contain policy-normalized output. Bump this whenever deterministic
# review post-processing changes so an older normalized decision cannot leak through.
# v5：schema 修复改为续接原 transcript 的 chat_with_tools（含 role=tool 取证上下文、
# 仍带 tools，修复轮工具调用并入 tool_calls 摘要）——修复路径行为变化影响缓存行
# v4：缓存 key 纳入工具证据内容指纹（review_tools.evidence_fingerprint——KB/blocks/
# 原子需求/蓝皮书索引），改证据后旧审查不再静默复用；schema 修复纳入共享预算计量
# v3：缓存 key 纳入 REVIEW_TOOLS_VERSION 与执行器模式（tool_loop/single_shot）
LLM_REVIEW_CACHE_VERSION = "llm-review-cache-v6"
# Agent Phase 2 冻结口径：每需求 tool-loop tokens 上限（yaml route.tool_loop_token_budget 可调）；
# 超限的需求进 stub 并在 llm_failed 记数（全跑不设总顶——审查本质是批处理）
TOOL_LOOP_DEFAULT_TOKEN_BUDGET = 20000
REVIEW_TOOL_LOOP_MAX_ROUNDS = 5
FAST_FAIL_SAMPLE_SIZE = 5
PROGRESS_INTERVAL = 20
SOURCE_TYPE_CONFIDENCE_THRESHOLD = 0.85


SYSTEM_PROMPT = """You are a DLMS/COSEM requirements review expert.
Review one atomic requirement candidate at a time.
Return only JSON with these fields:
- decision: one of accept, revise, split, merge, reject, needs_expert
- risk: low_risk, high_risk, or mandatory_review
- confidence: number from 0 to 1
- revised_requirement: optional corrected requirement text
- review_notes: list of short review notes
- expert_questions: list of questions for a human expert
Do not add Markdown fences or explanatory prose."""


@dataclass(frozen=True)
class ReviewPipeline:
    pipeline_id: str
    operations: list[dict[str, Any]]
    model_routing: dict[str, Any]
    risk_policy: dict[str, Any]
    model_routes: dict[str, Any]
    review_scope: dict[str, Any]


@dataclass(frozen=True)
class ReviewBatchResult:
    reviews: list[dict[str, Any]]
    states: list[dict[str, Any]]
    llm_reviewed: int
    rule_stub: int
    llm_failed: int
    # tool-loop 审查实际使用的 KB 路径（显式传入或默认回退解析后的真实值）——
    # 审查汇总如实记录 KB 选择；空 = 本次未走工具化审查（stub/单发不读 KB）
    kb_paths: tuple[str, ...] = ()


def load_review_pipeline(path: Path) -> ReviewPipeline:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ReviewPipeline(
        pipeline_id=str(payload.get("pipeline_id") or path.stem),
        operations=list(payload.get("operations", [])),
        model_routing=dict(payload.get("model_routing", {})),
        risk_policy=dict(payload.get("risk_policy", {})),
        model_routes=dict(payload.get("model_routes") or {"default": "stub"}),
        review_scope=dict(payload.get("review_scope") or {}),
    )


def merge_review_policy(pipeline: ReviewPipeline, domain_pack_path: Path | None) -> ReviewPipeline:
    if domain_pack_path is None:
        return pipeline
    pack = load_domain_pack(domain_pack_path)
    review_policy = dict(pack.payload.get("review_policy") or {})
    merged_risk_policy = dict(pipeline.risk_policy)
    for key in ("mandatory_review_types", "high_risk_types"):
        values = [
            *list(merged_risk_policy.get(key, [])),
            *list(review_policy.get(key, [])),
        ]
        merged_risk_policy[key] = list(dict.fromkeys(str(value) for value in values))
    if "low_confidence_threshold" in review_policy:
        merged_risk_policy["low_confidence_threshold"] = review_policy["low_confidence_threshold"]
    return ReviewPipeline(
        pipeline_id=pipeline.pipeline_id,
        operations=pipeline.operations,
        model_routing=pipeline.model_routing,
        risk_policy=merged_risk_policy,
        model_routes=pipeline.model_routes,
        review_scope=pipeline.review_scope,
    )


def classify_review_risk(requirement: dict[str, Any], pipeline: ReviewPipeline) -> str:
    mandatory_review_types = set(pipeline.risk_policy.get("mandatory_review_types", []))
    high_risk_types = set(pipeline.risk_policy.get("high_risk_types", []))
    threshold = float(pipeline.risk_policy.get("low_confidence_threshold", 0.75))
    if requirement.get("requirement_type") in mandatory_review_types:
        return "mandatory_review"
    if requirement.get("requirement_type") in high_risk_types:
        return "high_risk"
    if float(requirement.get("confidence", 0)) < threshold:
        return "high_risk"
    if requirement.get("ambiguity"):
        return "high_risk"
    return "low_risk"


def requirement_identity(requirement: dict[str, Any]) -> str:
    return str(requirement.get("stable_req_id") or requirement.get("req_id") or requirement.get("source_id") or "UNKNOWN")


def build_stub_review(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    *,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    risk = classify_review_risk(requirement, pipeline)
    needs_expert = risk in {"high_risk", "mandatory_review"}
    decision = "needs_expert" if needs_expert else "accept"
    requirement_id = requirement_identity(requirement)
    route_key = "high_risk" if risk == "mandatory_review" else risk
    review_notes = [f"Stub review routed to {risk}."]
    if unavailable_reason:
        review_notes.append(f"llm_unavailable: {unavailable_reason}")
    return {
        "task_id": f"REVIEW-{requirement_id}",
        "requirement_id": requirement_id,
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "source_refs": requirement.get("source_refs", []),
        "risk": risk,
        "decision": decision,
        "revised_requirement": requirement.get("requirement", ""),
        "review_notes": review_notes,
        "expert_questions": requirement.get("review_questions", []) if needs_expert else [],
        "confidence": 0.5 if needs_expert else 0.8,
        "model_route": pipeline.model_routing.get(route_key, {}),
        "generated_by": "rule_stub",
    }


def review_requirements(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result = review_requirements_detailed(requirements, pipeline)
    return result.reviews, result.states


def review_requirements_detailed(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
    *,
    out_dir: Path | None = None,
    route: str | None = None,
    scope: str | None = None,
    llm_review_limit: int = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    kb_paths: list[Path] | None = None,
) -> ReviewBatchResult:
    route_name = resolve_route_name(pipeline, route)
    if route_name == "stub":
        reviews = [build_stub_review(requirement, pipeline) for requirement in requirements]
        return ReviewBatchResult(
            reviews=reviews,
            states=build_review_states(requirements, reviews),
            llm_reviewed=0,
            rule_stub=len(reviews),
            llm_failed=0,
        )
    if route_name != "openai_compatible":
        raise ValueError(f"Unsupported LLM route: {route_name}")
    if out_dir is None:
        raise ValueError("out_dir is required for openai_compatible review caching")
    return review_requirements_with_openai(
        requirements,
        pipeline,
        out_dir=out_dir,
        scope=scope,
        llm_review_limit=llm_review_limit,
        progress_callback=progress_callback,
        kb_paths=kb_paths,
    )


def resolve_route_name(pipeline: ReviewPipeline, route: str | None) -> str:
    if route:
        return route
    return str(pipeline.model_routes.get("default") or "stub")


def operation_executor_map(pipeline: ReviewPipeline) -> dict[str, str]:
    """yaml operations 的 executor 处置表（Phase 2 首次实现执行器；load_review_pipeline 透传原值）。

    tool_loop=工具化融合审查（classify_risk/correct_errors 合并为每条需求一次 tool-loop 调用）；
    deterministic=确定性承担（merge_duplicates/gap_find 已在 consistency_report，不做 LLM 版）；
    deferred=有据缓建（test_point_generate 零消费者）。未声明 executor 的 operation 不触发
    tool-loop——旧 yaml 保持单发融合审查（向后兼容）。"""
    executors: dict[str, str] = {}
    for operation in pipeline.operations:
        if isinstance(operation, dict) and operation.get("operation_id"):
            executors[str(operation["operation_id"])] = str(operation.get("executor") or "")
    return executors


def tool_loop_enabled(pipeline: ReviewPipeline) -> bool:
    executors = operation_executor_map(pipeline)
    return any(executors.get(operation_id) == "tool_loop" for operation_id in ("classify_risk", "correct_errors"))


def review_requirements_with_openai(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
    *,
    out_dir: Path,
    scope: str | None,
    llm_review_limit: int = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    kb_paths: list[Path] | None = None,
) -> ReviewBatchResult:
    # env 覆盖先行（真实反馈 2026-07-14：审核 33 分钟成瓶颈）——llm_config_from_route 内部
    # 会对 model/base_url 应用覆盖,但 concurrency 此前从**原始 yaml** 读,GUI 设置的并发
    # (RATOMIZER_LLM_CONCURRENCY)对审查阶段一直不生效,被 yaml 锁死。
    route_payload = apply_llm_environment_overrides(dict(pipeline.model_routes.get("openai_compatible") or {}))
    client_config = llm_config_from_route(route_payload)
    scope_config = effective_review_scope(pipeline, scope)
    concurrency = max(1, int(route_payload.get("concurrency", 1) or 1))
    connection_failure_abort = max(1, int(route_payload.get("connection_failure_abort", 10) or 10))
    cache_path = governed_artifact_path(out_dir, "llm_review_cache.jsonl", category="cache")
    cache = read_llm_review_cache(cache_path)
    # Phase 2：yaml operations 声明 executor=tool_loop → 工具化融合审查（每条需求一次
    # 有界 tool-loop 调用，模型可调用 review_tools 的确定性只读工具取证）；未声明保持单发。
    tool_loop: dict[str, Any] | None = None
    evidence = ""
    used_kb_paths: tuple[str, ...] = ()
    if tool_loop_enabled(pipeline):
        token_budget = int(route_payload.get("tool_loop_token_budget") or TOOL_LOOP_DEFAULT_TOKEN_BUDGET)
        max_rounds = int(route_payload.get("tool_loop_max_rounds") or REVIEW_TOOL_LOOP_MAX_ROUNDS)
        if max_rounds <= 0:
            raise ValueError("tool_loop_max_rounds must be a positive integer")
        # 显式 kb_paths 透传（审计 P1-d：调用方 --kb 必须与 atomize 同轨，不得落回默认
        # KB 复核）；None 时按工具执行器同一回退解析为默认 KB——解析后的真实列表同时
        # 进工具执行器与证据指纹，两侧文件集合严格一致
        if kb_paths is None:
            from requirement_kb.cli import default_kb_paths
            resolved_kb = [Path(path) for path in default_kb_paths()]
        else:
            resolved_kb = [Path(path) for path in kb_paths]
        used_kb_paths = tuple(str(path) for path in resolved_kb)
        tool_loop = {
            "executor": make_tool_executor(out_dir, kb_paths=resolved_kb),
            "token_budget": token_budget,
            "max_rounds": max_rounds,
        }
        # 证据指纹必须先于缓存查询——工具实际读取的证据（KB/blocks/原子需求/蓝皮书
        # 索引）变了，旧审查缓存不得命中
        evidence = evidence_fingerprint(out_dir, resolved_kb)

    reviews: list[dict[str, Any] | None] = [None] * len(requirements)
    pending: list[int] = []
    llm_reviewed = 0
    rule_stub = 0
    llm_failed = 0
    new_cache_rows: list[dict[str, Any]] = []

    for index, requirement in enumerate(requirements):
        if not should_llm_review(requirement, pipeline, scope_config):
            reviews[index] = build_stub_review(requirement, pipeline)
            rule_stub += 1
            continue
        if llm_review_limit > 0 and llm_reviewed + len(pending) >= llm_review_limit:
            reviews[index] = build_stub_review(requirement, pipeline)
            rule_stub += 1
            continue
        cache_key = llm_cache_key(requirement, client_config.model, pipeline, scope_config, evidence=evidence)
        cached_review = cache.get(cache_key)
        if cached_review is not None:
            reviews[index] = apply_deterministic_review_policy(requirement, pipeline, cached_review)
            llm_reviewed += 1
        else:
            pending.append(index)

    selected_total = llm_reviewed + len(pending)
    completed_llm = llm_reviewed

    def record_progress() -> None:
        if progress_callback is not None and selected_total:
            progress_callback(
                {
                    "stage": "llm_review",
                    "completed": completed_llm,
                    "total": selected_total,
                    "percent": int(round(completed_llm * 100 / selected_total)),
                    "model": client_config.model,
                }
            )
        if completed_llm and completed_llm % PROGRESS_INTERVAL == 0:
            LOGGER.info("llm review %s/%s", completed_llm, selected_total)

    sample = pending[:FAST_FAIL_SAMPLE_SIZE]
    sample_connection_failures = 0
    sample_connection_errors: list[str] = []
    for index in sample:
        requirement = requirements[index]
        try:
            review = dispatch_openai_review(requirement, pipeline, client_config, tool_loop)
        except LLMConnectionError as exc:
            sample_connection_failures += 1
            sample_connection_errors.append(str(exc))
            review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
            rule_stub += 1
            llm_failed += 1
        except LLMError as exc:
            review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
            rule_stub += 1
            llm_failed += 1
        else:
            llm_reviewed += 1
            completed_llm += 1
            record_progress()
            new_cache_rows.append(llm_cache_row(
                requirement, client_config.model, pipeline, scope_config, review, evidence=evidence,
            ))
        reviews[index] = review

    if sample and sample_connection_failures == len(sample):
        detail = sample_connection_errors[0] if sample_connection_errors else "initial review attempts failed"
        raise LLMConnectionError(f"LLM service unavailable: all initial review attempts failed: {detail}")

    consecutive_connection_failures = 0
    remaining = pending[FAST_FAIL_SAMPLE_SIZE:]
    if remaining:
        executor = ThreadPoolExecutor(max_workers=concurrency)
        try:
            futures = {
                executor.submit(dispatch_openai_review, requirements[index], pipeline, client_config, tool_loop): index
                for index in remaining
            }
            for future in as_completed(futures):
                index = futures[future]
                requirement = requirements[index]
                try:
                    review = future.result()
                except LLMConnectionError as exc:
                    consecutive_connection_failures += 1
                    review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
                    rule_stub += 1
                    llm_failed += 1
                    if consecutive_connection_failures >= connection_failure_abort:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise LLMConnectionError(
                            "LLM service unavailable: "
                            f"{consecutive_connection_failures} consecutive connection failures: {exc}"
                        ) from exc
                except LLMError as exc:
                    consecutive_connection_failures = 0
                    review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
                    rule_stub += 1
                    llm_failed += 1
                else:
                    consecutive_connection_failures = 0
                    llm_reviewed += 1
                    completed_llm += 1
                    record_progress()
                    new_cache_rows.append(llm_cache_row(
                        requirement, client_config.model, pipeline, scope_config, review, evidence=evidence,
                    ))
                reviews[index] = review
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    final_reviews = [review for review in reviews if review is not None]
    if len(final_reviews) != len(requirements):
        raise ValueError("review batch did not produce one review per requirement")
    append_llm_review_cache(cache_path, new_cache_rows)
    return ReviewBatchResult(
        reviews=final_reviews,
        states=build_review_states(requirements, final_reviews),
        llm_reviewed=llm_reviewed,
        rule_stub=rule_stub,
        llm_failed=llm_failed,
        kb_paths=used_kb_paths,
    )


def build_review_states(requirements: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for requirement, review in zip(requirements, reviews):
        state = RequirementReviewState(requirement_identity(requirement))
        state.metadata.update(
            {
                "req_id": requirement.get("req_id"),
                "stable_req_id": requirement.get("stable_req_id"),
                "source_id": requirement.get("source_id"),
                "requirement_type": requirement.get("requirement_type"),
            }
        )
        state.transition("llm_reviewed", actor="llm_pipeline", reason=f"decision={review['decision']}")
        if review["decision"] == "needs_expert":
            state.transition("expert_pending", actor="llm_pipeline", reason=f"risk={review.get('risk', '')}")
        elif review["decision"] == "accept":
            state.transition("accepted", actor="llm_pipeline", reason="low-risk acceptance")
        elif review["decision"] == "reject":
            state.transition("rejected", actor="llm_pipeline", reason="review rejected")
        else:
            state.transition("flagged", actor="llm_pipeline", reason=f"decision={review['decision']}")
        states.append(state.to_dict())
    return states


def _automatic_authority_preconditions(
    out_dir: Path,
    requirements: list[dict[str, Any]],
    states: list[dict[str, Any]],
) -> dict[str, Any]:
    from claim_artifacts import hash_json
    from claim_ledger import atomic_target_fingerprint

    targets: dict[str, dict[str, str]] = {}
    for requirement in requirements:
        requirement_id = requirement_identity(requirement)
        if not requirement_id or requirement_id in targets:
            raise ValueError(
                "automatic review authority snapshot has a missing or duplicate target"
            )
        targets[requirement_id] = {
            "target_fingerprint": atomic_target_fingerprint(requirement),
            "target_authority_write_revision": (
                atomic_target_authority_write_revision(requirement_id, states)
            ),
        }
    payload = {
        "schema": "automatic-review-authority-preconditions/v1",
        "authority_write_protocol_version": (
            CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION
        ),
        "target_publication_revision": target_publication_revision(
            out_dir / "atomic_requirements.jsonl"
        ),
        "targets": targets,
    }
    return {
        **payload,
        "preconditions_hash": hash_json(
            "automatic-review-authority-preconditions/v1",
            payload,
        ),
    }


def _load_automatic_review_snapshot(
    out_dir: Path,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read A-track targets and authority CAS tokens under the global lock order."""
    from omission_actions import extraction_operation_lock

    with extraction_operation_lock(out_dir, operation="llm-review-snapshot"):
        requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
        if limit > 0:
            requirements = requirements[:limit]
        with review_state_lock(out_dir):
            states = read_jsonl(governed_artifact_path(
                out_dir, "review_states.jsonl", category="state"
            ))
            preconditions = _automatic_authority_preconditions(
                out_dir,
                requirements,
                states,
            )
    return requirements, preconditions


def _current_automatic_targets(
    requirements: list[dict[str, Any]],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_ids = list(dict(expected.get("targets") or {}))
    by_id: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        by_id.setdefault(requirement_identity(requirement), []).append(requirement)
    selected: list[dict[str, Any]] = []
    for requirement_id in expected_ids:
        matches = by_id.get(requirement_id, [])
        if len(matches) != 1:
            raise ValueError(
                "automatic review target is missing or ambiguous at commit"
            )
        selected.append(matches[0])
    return selected


def _bind_automatic_review_states(
    generated_states: list[dict[str, Any]],
    preconditions: dict[str, Any],
) -> list[dict[str, Any]]:
    targets = dict(preconditions.get("targets") or {})
    bound: list[dict[str, Any]] = []
    for raw_state in generated_states:
        state = dict(raw_state)
        requirement_id = str(state.get("requirement_id") or "")
        target = dict(targets.get(requirement_id) or {})
        if not target:
            raise ValueError(
                "generated review state is outside the protected target snapshot"
            )
        metadata = dict(state.get("metadata") or {})
        metadata["automatic_authority_write"] = {
            "protocol_version": CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION,
            "preconditions_hash": preconditions["preconditions_hash"],
            "target_fingerprint": target["target_fingerprint"],
            "target_publication_revision": preconditions[
                "target_publication_revision"
            ],
            "expected_target_authority_write_revision": target[
                "target_authority_write_revision"
            ],
        }
        state["metadata"] = metadata
        bound.append(state)
    return bound


def _commit_automatic_review_states(
    out_dir: Path,
    generated_states: list[dict[str, Any]],
    *,
    expected_preconditions: dict[str, Any] | None,
) -> dict[str, Any]:
    """CAS one automatic batch; stale or legacy input never writes authority."""
    from omission_actions import extraction_operation_lock

    if not isinstance(expected_preconditions, dict):
        from claim_review_actions import record_legacy_authority_write_gap

        record_legacy_authority_write_gap(
            out_dir,
            route="llm_pipeline.merge_review_states",
            reason="missing_automatic_merge_preconditions",
        )
        with review_state_lock(out_dir):
            states = read_jsonl(governed_artifact_path(
                out_dir, "review_states.jsonl", category="state"
            ))
        return {
            "status": "needs_reconfirmation",
            "reason": "missing_automatic_merge_preconditions",
            "states": states,
            "event_count": 0,
        }

    with extraction_operation_lock(out_dir, operation="llm-review-commit"):
        current_requirements = read_jsonl(
            out_dir / "atomic_requirements.jsonl"
        )
        try:
            selected_targets = _current_automatic_targets(
                current_requirements,
                expected_preconditions,
            )
        except ValueError as exc:
            with review_state_lock(out_dir):
                existing_states = read_jsonl(governed_artifact_path(
                    out_dir, "review_states.jsonl", category="state"
                ))
            return {
                "status": "needs_reconfirmation",
                "reason": str(exc),
                "states": existing_states,
                "event_count": 0,
            }
        with review_state_lock(out_dir):
            existing_states = read_jsonl(governed_artifact_path(
                out_dir, "review_states.jsonl", category="state"
            ))
            current_preconditions = _automatic_authority_preconditions(
                out_dir,
                selected_targets,
                existing_states,
            )
            if current_preconditions != expected_preconditions:
                reasons: list[str] = []
                if current_preconditions.get(
                    "target_publication_revision"
                ) != expected_preconditions.get("target_publication_revision"):
                    reasons.append("target_publication_changed")
                if current_preconditions.get("targets") != expected_preconditions.get(
                    "targets"
                ):
                    reasons.append("target_or_authority_changed")
                return {
                    "status": "needs_reconfirmation",
                    "reason": ",".join(reasons) or "authority_snapshot_changed",
                    "states": existing_states,
                    "event_count": 0,
                    "current_preconditions": current_preconditions,
                }
            bound_states = _bind_automatic_review_states(
                generated_states,
                expected_preconditions,
            )
            merged_states = merge_review_states(existing_states, bound_states)
            atomic_write_review_states(
                governed_artifact_path(out_dir, "review_states.jsonl", category="state"),
                merged_states,
            )
            event_count = append_review_state_events(
                out_dir / "review_state_events.jsonl",
                merged_states,
            )
    return {
        "status": "applied",
        "reason": "",
        "states": merged_states,
        "event_count": event_count,
    }


def llm_config_from_route(payload: dict[str, Any]) -> LLMClientConfig:
    payload = apply_llm_environment_overrides(payload)
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError("openai_compatible route requires base_url and model")
    return LLMClientConfig(
        base_url=base_url,
        model=model,
        api_key_env=str(payload.get("api_key_env", "RATOMIZER_LLM_API_KEY")),
        temperature=float(payload.get("temperature", 0.0)),
        max_tokens=int(payload.get("max_tokens", 1024)),
        timeout_s=float(payload.get("timeout_s", 60.0)),
        max_retries=int(payload.get("max_retries", 3)),
    )


def apply_llm_environment_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload)
    env_map = {
        "base_url": "RATOMIZER_LLM_BASE_URL",
        "model": "RATOMIZER_LLM_MODEL",
        "api_key_env": "RATOMIZER_LLM_API_KEY_ENV",
        "temperature": "RATOMIZER_LLM_TEMPERATURE",
        "max_tokens": "RATOMIZER_LLM_MAX_TOKENS",
        "timeout_s": "RATOMIZER_LLM_TIMEOUT_S",
        "max_retries": "RATOMIZER_LLM_MAX_RETRIES",
        # 并发此前不在覆盖表——GUI「AI 抽取并发」只影响 ai_extract/analyze（各自读
        # RATOMIZER_LLM_CONCURRENCY），审查管线与装配富化被 yaml 锁死在 4、设置传不进去
        "concurrency": "RATOMIZER_LLM_CONCURRENCY",
    }
    for key, env_name in env_map.items():
        value = os.environ.get(env_name)
        if value is not None and value != "":
            merged[key] = value
    return merged


def effective_review_scope(pipeline: ReviewPipeline, scope: str | None) -> dict[str, Any]:
    payload = {
        "mode": "targeted",
        "confidence_below": 0.75,
        "always_review_ambiguous": True,
        "always_review_source_types": ["paragraph", "table_row"],
        "always_review_types": [],
    }
    payload.update(dict(pipeline.review_scope or {}))
    if scope:
        payload["mode"] = scope
    return payload


def should_llm_review(requirement: dict[str, Any], pipeline: ReviewPipeline, scope_config: dict[str, Any]) -> bool:
    mode = str(scope_config.get("mode") or "targeted")
    if mode == "all":
        return True
    if mode != "targeted":
        raise ValueError(f"Unsupported review scope: {mode}")
    if scope_config.get("always_review_ambiguous", True) and requirement.get("ambiguity"):
        return True
    confidence = safe_float(requirement.get("confidence"), 0.0)
    if confidence < float(scope_config.get("confidence_below", 0.75)):
        return True
    always_types = {
        *{str(item) for item in scope_config.get("always_review_types", [])},
        *{str(item) for item in pipeline.risk_policy.get("mandatory_review_types", [])},
    }
    if str(requirement.get("requirement_type") or "") in always_types:
        return True
    source_types = {str(item) for item in scope_config.get("always_review_source_types", [])}
    if str(requirement.get("source_type") or "") in source_types and confidence < SOURCE_TYPE_CONFIDENCE_THRESHOLD:
        return True
    return False


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_openai_review(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    config: LLMClientConfig,
) -> dict[str, Any]:
    user_prompt = build_user_prompt(requirement)
    payload = chat_json(config, SYSTEM_PROMPT, user_prompt)
    review, errors = review_with_validation_errors(requirement, pipeline, payload, model=config.model)
    if errors:
        repair_prompt = (
            "Only output valid JSON matching the required review schema. "
            "The previous JSON schema validation failed: "
            + "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        )
        payload = chat_json_messages(
            config,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "user", "content": repair_prompt},
            ],
        )
        review, errors = review_with_validation_errors(requirement, pipeline, payload, model=config.model)
    if errors:
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise LLMResponseError(f"invalid LLM review result: {message}")
    return review


def dispatch_openai_review(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    config: LLMClientConfig,
    tool_loop: dict[str, Any] | None,
) -> dict[str, Any]:
    """按 yaml operations 的 executor 处置分发：tool_loop → 工具化融合审查；否则单发（旧行为）。

    tool_loop=None 时逐字调用既有 build_openai_review（三位置参数签名不变——
    测试/嵌入方的 patch 点保持兼容）。"""
    if tool_loop is None:
        return build_openai_review(requirement, pipeline, config)
    return build_openai_review_tool_loop(
        requirement,
        pipeline,
        config,
        tool_executor=tool_loop["executor"],
        token_budget=tool_loop["token_budget"],
        max_rounds=tool_loop["max_rounds"],
    )


def build_openai_review_tool_loop(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    config: LLMClientConfig,
    *,
    tool_executor: Any,
    token_budget: int = TOOL_LOOP_DEFAULT_TOKEN_BUDGET,
    max_rounds: int = REVIEW_TOOL_LOOP_MAX_ROUNDS,
) -> dict[str, Any]:
    """工具化融合审查（Phase 2）：同一融合 prompt，模型可经 chat_with_tools 调用
    review_tools 的确定性只读工具（KB/蓝皮书/原文块/覆盖）取证后再裁决。

    输出契约与单发完全一致（decision/risk/confidence/revised_requirement/review_notes/
    expert_questions 过 llm_review_schema + 确定性政策层，均不动）——tool-loop 只改变
    产出这些字段的过程。审查结果行附加 tool_calls 摘要（工具名+轮次，审计可解释性锚；
    schema additionalProperties 允许）。轮顶耗尽/token 超预算/端点不支持 tools → 抛
    LLMError，调用方按现有失败路径进 stub 并记数（不得伪造模型已审）。"""
    user_prompt = build_user_prompt(requirement)
    # tool-loop 首轮、JSON 解析修复、schema 修复共享同一 usage 汇聚（审计 P1-c）——
    # 此前 schema 修复走无 sink 的 chat_json_messages：首轮花满预算后修复仍放行且不计数
    usage_sink: list[dict[str, Any]] = []
    kb_search_executed = False

    def limited_tool_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal kb_search_executed
        if name == "kb_search":
            if kb_search_executed:
                return {
                    "error": (
                        "kb_search may be executed at most once per requirement; "
                        "use kb_get for an entry_id already returned"
                    )
                }
            kb_search_executed = True
        return tool_executor(name, arguments)

    payload, meta = chat_with_tools(
        config,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        REVIEW_TOOLS,
        max_rounds=max_rounds,
        on_tool_call=limited_tool_executor,
        token_budget=token_budget,
        _usage_sink=usage_sink,
    )
    review, errors = review_with_validation_errors(requirement, pipeline, payload, model=config.model)
    repair_meta: dict[str, Any] | None = None
    if errors:
        repair_prompt = (
            "Only output valid JSON matching the required review schema. "
            "The previous JSON schema validation failed: "
            + "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        )
        spent = _aggregate_usage(usage_sink)["usage"]["total_tokens"]
        if token_budget is not None and spent > token_budget:
            raise LLMResponseError(
                f"tool loop token budget exhausted before schema repair: "
                f"{spent} > {token_budget} tokens")
        # schema 修复续接原 transcript（含 assistant tool_calls 与 role=tool 回灌，
        # 与环内 JSON 修复同型）——不再丢弃取证上下文另起四消息列表；修复轮仍带 tools
        # 可调工具，轮次预算为首轮剩余
        repair_messages = list(meta.get("history") or [])
        repair_messages.append({"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)})
        repair_messages.append({"role": "user", "content": repair_prompt})
        remaining_rounds = max_rounds - int(meta.get("rounds") or 0)
        if remaining_rounds <= 0:
            raise LLMResponseError("tool loop round budget exhausted before schema repair")
        payload, repair_meta = chat_with_tools(
            config,
            repair_messages,
            REVIEW_TOOLS,
            max_rounds=remaining_rounds,
            on_tool_call=limited_tool_executor,
            token_budget=token_budget,
            _usage_sink=usage_sink,
        )
        spent = _aggregate_usage(usage_sink)["usage"]["total_tokens"]
        if token_budget is not None and spent > token_budget:
            raise LLMResponseError(
                f"tool loop token budget exceeded: {spent} > {token_budget} tokens "
                "(schema repair)")
        review, errors = review_with_validation_errors(requirement, pipeline, payload, model=config.model)
    if errors:
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise LLMResponseError(f"invalid LLM review result: {message}")
    tool_calls = list(meta.get("tool_calls") or [])
    if repair_meta is not None:
        # 修复轮的工具调用并入审计摘要（轮次续接首轮之后）——摘要如实覆盖修复路径
        base_rounds = int(meta.get("rounds") or 0)
        tool_calls.extend(
            {"round": base_rounds + int(call.get("round") or 0), "name": call.get("name")}
            for call in repair_meta.get("tool_calls") or []
        )
    review["tool_calls"] = tool_calls
    aggregated = _aggregate_usage(usage_sink)   # 含修复调用的真实聚合值
    LOGGER.info(
        "tool-loop 审查 %s：%s 轮、%s 次工具调用、tokens=%s%s",
        requirement_identity(requirement),
        meta.get("rounds"),
        len(review["tool_calls"]),
        aggregated["usage"].get("total_tokens", 0),
        "" if aggregated["usage_complete"] else "(usage partial)",
    )
    return review


def review_with_validation_errors(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    payload: dict[str, Any],
    *,
    model: str,
) -> tuple[dict[str, Any], list[Any]]:
    review = complete_llm_review_payload(requirement, pipeline, payload, model=model)
    issues = validate_llm_review_result_payload(review)
    errors = [issue for issue in issues if issue.severity == "error"]
    if not errors:
        review = apply_deterministic_review_policy(requirement, pipeline, review)
    return review, errors


def build_user_prompt(requirement: dict[str, Any]) -> str:
    kb_matches = []
    for item in requirement.get("kb_matches", [])[:3]:
        if isinstance(item, dict):
            kb_matches.append(
                {
                    "name": item.get("name"),
                    "definition": str(item.get("definition") or "")[:300],
                }
            )
    prompt_payload = {
        "requirement_id": requirement_identity(requirement),
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "requirement": requirement.get("requirement"),
        "requirement_type": requirement.get("requirement_type"),
        "confidence": requirement.get("confidence"),
        "ambiguity": requirement.get("ambiguity"),
        "source_type": requirement.get("source_type"),
        "source_refs": requirement.get("source_refs", []),
        "source_context": requirement.get("source_context") or requirement.get("parameters") or {},
        "section_path": requirement.get("section_path", []),
        "kb_matches": kb_matches,
    }
    return json.dumps(prompt_payload, ensure_ascii=False, indent=2)


def complete_llm_review_payload(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    payload: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    requirement_id = requirement_identity(requirement)
    review = {
        "task_id": f"REVIEW-{requirement_id}",
        "requirement_id": requirement_id,
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "source_refs": requirement.get("source_refs", []),
        "risk": payload.get("risk") or classify_review_risk(requirement, pipeline),
        "decision": payload.get("decision"),
        "revised_requirement": payload.get("revised_requirement") or requirement.get("requirement", ""),
        "review_notes": payload.get("review_notes", []),
        "expert_questions": payload.get("expert_questions", []),
        "confidence": payload.get("confidence"),
        "model_route": {"provider": "openai_compatible", "model": model},
        "generated_by": f"llm:{model}",
    }
    return review


def apply_deterministic_review_policy(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Apply the configured policy as a floor after LLM or cache retrieval."""
    normalized = dict(review)
    policy_risk = classify_review_risk(requirement, pipeline)
    risk_rank = {"low_risk": 0, "high_risk": 1, "mandatory_review": 2}
    model_risk = str(normalized.get("risk") or "")
    effective_risk = max(
        (policy_risk, model_risk),
        key=lambda value: risk_rank.get(value, -1),
    )
    normalized["risk"] = effective_risk

    if policy_risk == "mandatory_review" and normalized.get("decision") != "needs_expert":
        original_decision = str(normalized.get("decision") or "unknown")
        normalized["decision"] = "needs_expert"
        notes = list(normalized.get("review_notes") or [])
        policy_note = f"Deterministic mandatory-review policy overrode decision={original_decision}."
        if policy_note not in notes:
            notes.append(policy_note)
        normalized["review_notes"] = notes
    return normalized


def llm_cache_key(
    requirement: dict[str, Any],
    model: str,
    pipeline: ReviewPipeline,
    scope_config: dict[str, Any],
    *,
    evidence: str = "",
) -> tuple[str, str, str, str]:
    fingerprint_payload = {
        "cache_version": LLM_REVIEW_CACHE_VERSION,
        "prompt_version": PROMPT_VERSION,
        # 工具定义（名称/参数/返回裁剪）与执行器模式都是产物成因——必须进指纹，
        # 否则旧执行器/旧工具面的缓存审查会静默冒充新产物（AGENTS.md 缓存纪律）
        "review_tools_version": REVIEW_TOOLS_VERSION,
        "review_executor": "tool_loop" if tool_loop_enabled(pipeline) else "single_shot",
        # 工具实际读取的证据内容指纹（审计 P1-d）：改 KB/blocks/原子需求/蓝皮书索引
        # 后旧审查不得命中；single_shot 不读证据，恒为空串
        "evidence_fingerprint": evidence,
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(requirement)},
        ],
        "risk_policy": pipeline.risk_policy,
        "review_scope": scope_config,
    }
    canonical = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    input_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return (requirement_identity(requirement), model, PROMPT_VERSION, input_fingerprint)


def read_llm_review_cache(path: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in read_jsonl_recover_torn_tail(path):
        review = row.get("review")
        if not isinstance(review, dict):
            continue
        key = (
            str(row.get("stable_req_id") or row.get("requirement_id") or ""),
            str(row.get("model") or ""),
            str(row.get("prompt_version") or ""),
            str(row.get("input_fingerprint") or ""),
        )
        if all(key):
            cache[key] = review
    return cache


def llm_cache_row(
    requirement: dict[str, Any],
    model: str,
    pipeline: ReviewPipeline,
    scope_config: dict[str, Any],
    review: dict[str, Any],
    *,
    evidence: str = "",
) -> dict[str, Any]:
    requirement_id = requirement_identity(requirement)
    cache_key = llm_cache_key(requirement, model, pipeline, scope_config, evidence=evidence)
    return {
        "stable_req_id": requirement_id,
        "requirement_id": requirement_id,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "cache_version": LLM_REVIEW_CACHE_VERSION,
        "input_fingerprint": cache_key[-1],
        "review": review,
    }


_CACHE_APPEND_ATTEMPTS = 5
_CACHE_APPEND_RETRY_DELAY_S = 0.02


def append_llm_review_cache(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    # 共享状态纪律（同 review_states.jsonl）：锁内追加 + fsync + PermissionError 重试，
    # 模式对齐 decide_trace._append_with_retry——此前锁外裸追加，并发批可能丢行/撕裂
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    with review_state_lock(path.parent):
        for attempt in range(_CACHE_APPEND_ATTEMPTS):
            try:
                with path.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                break
            except PermissionError:
                if attempt + 1 >= _CACHE_APPEND_ATTEMPTS:
                    raise
                time.sleep(_CACHE_APPEND_RETRY_DELAY_S)
    return len(rows)


def assert_valid_review_results(rows: list[dict[str, Any]]) -> None:
    issues = validate_llm_review_results(rows)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise ValueError(f"invalid llm review results: {message}")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    count = 0
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return count


def append_review_state_events(path: Path, states: list[dict[str, Any]]) -> int:
    existing_keys = {review_event_row_key(row) for row in read_jsonl(path)}
    count = 0
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for state in states:
            metadata = dict(state.get("metadata") or {})
            for event in state.get("history", []):
                row = {
                    "requirement_id": state.get("requirement_id"),
                    "req_id": metadata.get("req_id"),
                    "stable_req_id": metadata.get("stable_req_id"),
                    "status_after": event.get("to_status"),
                    "current_status": state.get("status"),
                    **event,
                }
                key = review_event_row_key(row)
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
    return count


def review_event_row_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    event_key = review_event_key(row)
    return (str(row.get("requirement_id") or row.get("stable_req_id") or ""), *event_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local requirement review pipeline over atomizer output.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory containing atomic_requirements.jsonl")
    parser.add_argument(
        "--pipeline",
        type=Path,
        default=DEFAULT_PIPELINE_PATH,
        help="Review pipeline YAML",
    )
    parser.add_argument(
        "--domain-pack",
        type=Path,
        default=DEFAULT_DOMAIN_PACK_PATH,
        help="Optional domain pack whose review_policy is merged into runtime risk policy",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max requirement count for trial runs")
    parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default=None)
    parser.add_argument("--review-scope", choices=["targeted", "all"], default=None)
    parser.add_argument("--llm-review-limit", type=int, default=0, help="Optional max real LLM review count")
    return parser.parse_args()


def run_review_pipeline(
    out_dir: Path,
    *,
    pipeline_path: Path = DEFAULT_PIPELINE_PATH,
    domain_pack_path: Path | None = DEFAULT_DOMAIN_PACK_PATH,
    limit: int = 0,
    route: str | None = None,
    scope: str | None = None,
    llm_review_limit: int = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    kb_paths: list[Path] | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    pipeline_path = pipeline_path.expanduser().resolve()
    LOGGER.info("loading review pipeline")
    requirements, authority_preconditions = _load_automatic_review_snapshot(
        out_dir,
        limit=limit,
    )
    domain_pack_path = domain_pack_path.expanduser().resolve() if domain_pack_path else None
    pipeline = merge_review_policy(load_review_pipeline(pipeline_path), domain_pack_path)
    LOGGER.info("reviewing %s requirements", len(requirements))
    result = review_requirements_detailed(
        requirements,
        pipeline,
        out_dir=out_dir,
        route=route,
        scope=scope,
        llm_review_limit=llm_review_limit,
        progress_callback=progress_callback,
        kb_paths=kb_paths,
    )
    reviews = result.reviews
    generated_states = result.states
    assert_valid_review_results(reviews)
    authority_merge = _commit_automatic_review_states(
        out_dir,
        generated_states,
        expected_preconditions=authority_preconditions,
    )
    merge_status = str(authority_merge["status"])
    merge_reason = str(authority_merge.get("reason") or "")
    if merge_status != "applied":
        reviews = [
            {
                **review,
                "authority_merge": {
                    "status": "needs_reconfirmation",
                    "reason": merge_reason,
                    "protocol_version": (
                        CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION
                    ),
                    "preconditions_hash": authority_preconditions.get(
                        "preconditions_hash"
                    ),
                },
            }
            for review in reviews
        ]
    write_jsonl(out_dir / "llm_review_results.jsonl", reviews)
    states = list(authority_merge["states"])
    event_count = int(authority_merge["event_count"])
    summary = {
        "pipeline_id": pipeline.pipeline_id,
        "out": str(out_dir),
        "requirements": len(requirements),
        "reviews": len(reviews),
        "llm_reviewed": result.llm_reviewed,
        "rule_stub": result.rule_stub,
        "llm_failed": result.llm_failed,
        "review_state_events": event_count,
        "authority_merge_status": merge_status,
        "authority_merge_reason": merge_reason,
        "authority_write_protocol_version": (
            CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION
        ),
        "authority_merge_proposal_count": (
            0 if merge_status == "applied" else len(generated_states)
        ),
        "expert_pending": sum(1 for state in states if state.get("status") == "expert_pending"),
        "accepted": sum(1 for state in states if state.get("status") == "accepted"),
        "files": {
            "llm_review_results": "llm_review_results.jsonl",
            "review_states": "review_states.jsonl",
            "review_state_events": "review_state_events.jsonl",
        },
    }
    if result.kb_paths:
        # 如实记录本次工具化审查实际使用的 KB（审计 P1-d；stub/单发不读 KB 则无此字段）
        summary["kb_paths"] = list(result.kb_paths)
    return summary


def main() -> int:
    args = parse_args()
    summary = run_review_pipeline(
        args.out,
        pipeline_path=args.pipeline,
        domain_pack_path=args.domain_pack,
        limit=args.limit,
        route=args.llm_route,
        scope=args.review_scope,
        llm_review_limit=args.llm_review_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
