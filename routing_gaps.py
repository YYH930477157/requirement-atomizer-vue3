"""Routing Gap 与局部升级模型（quality-first 方案 §19，M3）。

Gap = 质量门禁发现的、可定位到单元或文档级检查的可执行缺口。本模块只负责
gap 的确定性构建/落盘/读取；**局部升级执行必须复用现有 claim queue/CAS/WAL/
预算机械**（§19 红线：不再造第八条独立重抽通道）——M5 才接线执行。

Gap 来源（M3 shadow）：
- 路由 review 单元：物化为 gap（recommended_action=expert_review），不静默丢弃；
- 文档级门禁失败（quality_gates 报告）：逐失败 gate 生成 gap，blocking 语义与
  该 gate 的既有 blocking 定义一致（守恒/table closure 等），本模块不新设门槛。

gap_id 稳定：sha256(unit_id|gate|reason) 前 16 位——同一缺口重复评估得到同一 id，
重放可去重。
"""
from __future__ import annotations

from typing import Any, Iterable

from artifact_store import ArtifactStore
from claim_artifacts import sha256_bytes
from io_utils import read_jsonl

ROUTING_GAP_SCHEMA = "routing-gap/v1"
ROUTING_GAPS_FILENAME = "routing_gaps.jsonl"
ROUTING_GAPS_SUMMARY_SCHEMA = "routing-gaps-summary/v1"

GAP_SCHEMA_VERSION = ROUTING_GAP_SCHEMA

RECOMMENDED_ACTIONS = (
    "targeted_secondary_route",  # 局部第二路径（M5 复用 claim queue）
    "targeted_reextract",        # 定点重抽（M5 复用 functional_reextract/claim queue）
    "expert_review",             # 专家确认（review 单元/候选提升）
    "needs_work",                # 预算/模型/来源问题——如实标记，不降质冒充
    "resolve_conflict",          # 结构约束与叙述需求冲突——专家/第二路径
)

# gap_id 稳定所需字段（缺一不可，防同因不同 id）
_REQUIRED_GAP_FIELDS = ("unit_id", "gate", "reason")


def _gap_id(unit_id: str, gate: str, reason: str) -> str:
    return "GAP-" + sha256_bytes(
        f"{unit_id}|{gate}|{reason}".encode("utf-8"))[len("sha256:"):][:16]


def build_gap(*, unit_id: str, gate: str, reason: str,
              primary_route: str | None = None,
              recommended_action: str = "expert_review",
              blocking: bool = False,
              source_hash: str = "",
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if recommended_action not in RECOMMENDED_ACTIONS:
        raise ValueError(f"未知 recommended_action: {recommended_action}")
    gap: dict[str, Any] = {
        "schema": ROUTING_GAP_SCHEMA,
        "gap_id": _gap_id(unit_id or "<document>", gate, reason),
        "unit_id": unit_id,
        "gate": gate,
        "reason": reason,
        "primary_route": primary_route,
        "recommended_action": recommended_action,
        "blocking": bool(blocking),
        "source_hash": source_hash,
    }
    if extra:
        gap.update(extra)
    return gap


def gaps_from_routing_decisions(decisions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """review 单元 → 物化 gap（不静默丢弃，§30 检查清单）。"""
    gaps: list[dict[str, Any]] = []
    for decision in decisions:
        if str(decision.get("route") or "") != "review":
            continue
        reason_by_rule = {
            "review_weak_signal": "弱信号单元（sentence_shape/colon_spec）待专家判定",
            "review_disposition": "表格 cell 处置为 review，待提升或确认排除",
            "review_no_signal": "候选单元无可审计硬信号，待专家判定",
        }
        rule = str(decision.get("rule") or "review_no_signal")
        gaps.append(build_gap(
            unit_id=str(decision.get("unit_id") or ""),
            gate="routing_review_pending",
            reason=reason_by_rule.get(rule, f"review 路由（rule={rule}）"),
            primary_route=None,
            recommended_action="expert_review",
            blocking=False,
            source_hash=str(decision.get("source_text_hash") or ""),
            extra={"rule": rule,
                   "evidence": [e for e in decision.get("evidence") or []
                                if e.get("kind") == "weak_signal"]}))
    return gaps


def gaps_from_functional_product(product: Any, *,
                                 product_fingerprint: str = "") -> list[dict[str, Any]]:
    """守恒失败 → 块级 targeted_reextract 缺口（M5 局部升级的喂料端）。

    只有携带可定位块锚的失败（evidence_mismatches.declared_block_ids、
    duplicates.groups.block_ids）才升级为 ``targeted_reextract``；无块锚的失败
    （uncovered obligations 只有句索引）与执行状态失败标 ``needs_work``——
    不做块级猜测（宁漏勿错）。gate 名与 quality_gates 对齐。
    """
    if not isinstance(product, dict):
        return []
    gaps: list[dict[str, Any]] = []
    status = str(product.get("execution_status") or "")
    conservation = product.get("conservation") or {}
    checks = conservation.get("checks") if isinstance(conservation, dict) else None
    checks = checks if isinstance(checks, dict) else {}

    if status not in ("ok", ""):
        gaps.append(build_gap(
            unit_id="", gate="execution_status",
            reason=f"execution_status={status}——直抽不完整，不可局部升级",
            recommended_action="needs_work", blocking=True,
            source_hash=product_fingerprint))
    for mismatch in checks.get("evidence_presence", {}).get("evidence_mismatches") or []:
        block_ids = [str(b) for b in mismatch.get("declared_block_ids") or [] if b]
        if not block_ids:
            continue
        gaps.append(build_gap(
            unit_id="", gate="obligation_conservation",
            reason=(f"{mismatch.get('reason') or 'evidence_mismatch'}: "
                    f"{mismatch.get('functional_requirement_id')}"),
            recommended_action="targeted_reextract", blocking=True,
            source_hash=product_fingerprint,
            extra={"block_ids": block_ids,
                   "functional_requirement_id": mismatch.get("functional_requirement_id")}))
    for group in checks.get("duplicates", {}).get("groups") or []:
        block_ids = [str(b) for b in group.get("block_ids") or [] if b]
        if not block_ids:
            continue
        section_id = str(group.get("section_id") or "")
        gaps.append(build_gap(
            unit_id="", gate="obligation_conservation",
            reason=(f"重复条款组（{len(group.get('functional_requirement_ids') or [])} 条 FRE）"
                    f" @ {section_id}"),
            recommended_action="targeted_reextract", blocking=True,
            source_hash=product_fingerprint,
            extra={"block_ids": block_ids, "section_id": section_id}))
    for obligation in checks.get("obligation_coverage", {}).get("uncovered_obligations") or []:
        sentence = str(obligation.get("sentence") or obligation)[:100]
        gaps.append(build_gap(
            unit_id="", gate="obligation_conservation",
            reason=f"未覆盖义务（无块锚，不做块级猜测）: {sentence}",
            recommended_action="needs_work", blocking=True,
            source_hash=product_fingerprint,
            extra={"obligation": obligation}))
    return gaps


def merge_gaps(*gap_lists: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 gap_id 去重合并（后到覆盖先到），保持排序稳定。"""
    by_id: dict[str, dict[str, Any]] = {}
    for gaps in gap_lists:
        for gap in gaps:
            for field in _REQUIRED_GAP_FIELDS:
                if not gap.get(field) and field != "unit_id":
                    raise ValueError(f"gap 缺必需字段 {field}: {gap}")
            by_id[str(gap.get("gap_id"))] = gap
    return [by_id[gap_id] for gap_id in sorted(by_id)]


def summarize_gaps(gaps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    gaps = list(gaps)
    by_gate: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for gap in gaps:
        by_gate[gap["gate"]] = by_gate.get(gap["gate"], 0) + 1
        by_action[gap["recommended_action"]] = by_action.get(gap["recommended_action"], 0) + 1
    return {
        "schema": ROUTING_GAPS_SUMMARY_SCHEMA,
        "gap_count": len(gaps),
        "blocking_count": sum(1 for gap in gaps if gap.get("blocking")),
        "counts_by_gate": dict(sorted(by_gate.items())),
        "counts_by_action": dict(sorted(by_action.items())),
    }


def write_routing_gaps(out_dir, gaps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = merge_gaps(gaps)
    store = ArtifactStore(out_dir, category="pipeline")
    store.write_jsonl(ROUTING_GAPS_FILENAME, rows)
    summary = summarize_gaps(rows)
    summary["artifact"] = ROUTING_GAPS_FILENAME
    return summary


def load_routing_gaps(out_dir) -> list[dict[str, Any]]:
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, ROUTING_GAPS_FILENAME,
                                  category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []
