"""局部升级执行接线（quality-first 方案 §9.3/§19，M5）。

把 routing gaps 的 ``targeted_secondary_route``/``targeted_reextract`` 缺口接入
**既有 claim queue**（claim-queue-proposal/v3 → ``execute_claim_queue_proposal``）：
CAS（expected_claim_effective_revision + 产品指纹复核）、attempt WAL、预算
（maximum_calls/total_token_budget 透传同一记账钩）、幂等全部复用队列既有机械，
**不新建第八条重抽通道**（§19 红线）。

接入语义（诚实边界）：
- gap 的块集合（gap.extra.block_ids 或 unit 的 source_block_ids）与**已发布
  pending proposal**（lifecycle=open，parent_block_id 命中）匹配 → 走标准队列执行
  （直抽模式即 functional_targeted_reextract 条款族重抽）；
- 无匹配 proposal → ``no_matching_proposal``：claim 队列只为已发布 claim 存在；
  本模块**绝不伪造 claim 锚**（proposal_id/claim_hash/generation 绑定不可造），
  缺口留给专家评审；
- ``expert_review``/``needs_work`` 缺口永不自动执行；
- 幂等键 = ``gap-{gap_id}-{salt}``——同缺口重放复用队列自身的幂等语义
  （已执行的同键请求不再发起付费调用）。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable

from artifact_store import ArtifactStore
from extraction_units import load_extraction_units
from routing_gaps import load_routing_gaps

ROUTING_ESCALATION_VERSION = "routing-escalation-v1"
ROUTING_ESCALATIONS_FILENAME = "routing_escalations.jsonl"
ROUTING_ESCALATION_REPORT_SCHEMA = "routing-escalation-report/v1"

ACTIONABLE_RECOMMENDATIONS = ("targeted_secondary_route", "targeted_reextract")

OUTCOME_EXECUTED = "executed"
OUTCOME_NO_MATCH = "no_matching_proposal"
OUTCOME_CONFLICT = "cas_conflict"
OUTCOME_RETRYABLE = "retryable_error"
OUTCOME_FAILED = "failed"


def actionable_gaps(gaps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [gap for gap in gaps
            if str(gap.get("recommended_action") or "") in ACTIONABLE_RECOMMENDATIONS]


def gap_block_ids(gap: dict[str, Any],
                  units_by_id: dict[str, dict[str, Any]] | None = None) -> set[str]:
    """缺口的块辖域：显式 block_ids 优先，否则解析 unit 的溯源块。

    表格行/格单元的 source_block_ids 在 planner 里就是宿表块——表格缺口同样
    落到该表的重抽辖域（functional_targeted_reextract 按条款族展开）。
    """
    blocks = {str(b) for b in (gap.get("block_ids") or []) if b}
    unit_id = str(gap.get("unit_id") or "")
    if not blocks and unit_id and units_by_id:
        unit = units_by_id.get(unit_id) or {}
        blocks = {str(b) for b in unit.get("source_block_ids") or [] if b}
    return blocks


def pending_queue_proposals(root) -> list[dict[str, Any]]:
    from claim_artifacts import load_committed_effective_snapshot

    snapshot = load_committed_effective_snapshot(root)
    return [dict(row) for row in snapshot.get("queue_proposals") or []
            if str(row.get("lifecycle") or "") == "open"]


def escalate_gaps(
    root,
    gaps: Iterable[dict[str, Any]],
    *,
    route: str = "openai_compatible",
    actor: str = "quality-first:local-escalation",
    allow_llm: bool = True,
    maximum_calls: int = 4,
    total_token_budget: int = 200_000,
    chat_with_meta: Callable[..., tuple[dict[str, Any], dict[str, Any]]] | None = None,
    route_config: Any = None,
    executor: Callable[..., dict[str, Any]] | None = None,
    idempotency_salt: str = "1",
    write_ledger: bool = True,
) -> dict[str, Any]:
    """按缺口执行局部升级；逐缺口落 ``routing_escalations.jsonl`` 审计行。"""
    root_path = _as_path(root)
    if executor is None:
        from claim_queue_execution import execute_claim_queue_proposal as executor
    expected_route_config_revision = None
    if route_config is not None:
        from claim_queue_execution import _resolved_route_preflight

        expected_route_config_revision = _resolved_route_preflight(
            route, route_config)[1]["route_config_revision"]

    units_by_id: dict[str, dict[str, Any]] = {}
    try:
        units_by_id = {str(unit.get("unit_id")): unit
                       for unit in load_extraction_units(root_path)}
    except Exception:  # noqa: BLE001 — 单元产物缺失只影响块解析，不阻断队列匹配
        units_by_id = {}
    pending = pending_queue_proposals(root_path)

    outcomes: list[dict[str, Any]] = []
    for gap in actionable_gaps(gaps):
        gap_id = str(gap.get("gap_id") or "")
        blocks = gap_block_ids(gap, units_by_id)
        base_record: dict[str, Any] = {
            "gap_id": gap_id,
            "gate": gap.get("gate"),
            "recommended_action": gap.get("recommended_action"),
            "unit_id": gap.get("unit_id"),
            "block_ids": sorted(blocks),
            "ts": time.time(),
            "escalation_version": ROUTING_ESCALATION_VERSION,
        }
        if not blocks:
            outcomes.append({**base_record, "outcome": OUTCOME_NO_MATCH,
                             "detail": "缺口无可定位块辖域"})
            continue
        matches = [proposal for proposal in pending
                   if str(proposal.get("parent_block_id") or "") in blocks]
        if not matches:
            outcomes.append({
                **base_record, "outcome": OUTCOME_NO_MATCH,
                "detail": ("无覆盖该块辖域的 pending 队列 proposal——本模块不伪造 "
                           "claim 锚，缺口留待专家评审")})
            continue
        proposal = matches[0]
        outcome = {"proposal_id": proposal.get("proposal_id"),
                   "attempt_key": f"gap-{gap_id}-{idempotency_salt}"}
        try:
            result = executor(
                root_path,
                proposal_id=str(proposal.get("proposal_id") or ""),
                expected_claim_effective_revision=str(
                    proposal.get("claim_effective_revision") or ""),
                expected_ledger_state="uncertain",
                actor=actor,
                allow_llm=allow_llm,
                route=route,
                maximum_calls=maximum_calls,
                total_token_budget=total_token_budget,
                request_idempotency_key=outcome["attempt_key"],
                chat_with_meta=chat_with_meta,
                expected_route_config_revision=expected_route_config_revision,
            )
            outcome.update({
                "outcome": OUTCOME_EXECUTED,
                "lifecycle": result.get("lifecycle") if isinstance(result, dict) else None,
                "resolution": result.get("resolution") if isinstance(result, dict) else None,
                "result": result if not isinstance(result, dict) else {
                    key: result.get(key) for key in
                    ("lifecycle", "resolution", "attempt_id", "schema")},
            })
            # 该 proposal 已消费——后续缺口不得重复执行同一提案
            pending.remove(proposal)
        except Exception as exc:  # noqa: BLE001 — 队列异常分类如实记录，缺口不丢
            outcome.update({
                "outcome": _classify_queue_error(exc),
                "detail": f"{type(exc).__name__}: {exc}"[:500],
                "retryable": _retryable_queue_error(exc),
            })
        outcomes.append({**base_record, **outcome})

    skipped = [str(gap.get("gap_id")) for gap in gaps
               if str(gap.get("recommended_action") or "") not in ACTIONABLE_RECOMMENDATIONS]
    report = {
        "schema": ROUTING_ESCALATION_REPORT_SCHEMA,
        "escalation_version": ROUTING_ESCALATION_VERSION,
        "route": route,
        "actor": actor,
        "actionable_count": len(outcomes),
        "skipped_gap_ids": skipped,
        "counts_by_outcome": _count_by(outcomes, "outcome"),
        "outcomes": outcomes,
    }
    if write_ledger and outcomes:
        store = ArtifactStore(root_path, category="pipeline")
        with store.locked():
            for row in outcomes:
                store.append_jsonl(ROUTING_ESCALATIONS_FILENAME, row)
    return report


def load_routing_escalations(root) -> list[dict[str, Any]]:
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    path = governed_artifact_path(root, ROUTING_ESCALATIONS_FILENAME,
                                  category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []


def escalate_document_gaps(root, **kwargs: Any) -> dict[str, Any]:
    """便捷入口：读 routing_gaps.jsonl → escalate（expert_review/needs_work 自动跳过）。"""
    return escalate_gaps(root, load_routing_gaps(root), **kwargs)


def _as_path(root) -> Any:
    from pathlib import Path

    return Path(root).expanduser().resolve()


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _classify_queue_error(exc: Exception) -> str:
    name = type(exc).__name__
    if "Conflict" in name:
        return OUTCOME_CONFLICT
    if name in ("ClaimQueueExecutionRemoteError", "ClaimQueueExecutionUnavailable"):
        return OUTCOME_RETRYABLE
    return OUTCOME_FAILED


def _retryable_queue_error(exc: Exception) -> bool:
    return type(exc).__name__ in ("ClaimQueueExecutionRemoteError",
                                  "ClaimQueueExecutionUnavailable")
