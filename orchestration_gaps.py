"""T2-1 编排环缺口信号读取层（确定性、只读、零副作用）。

把"该看哪里"的四类缺口信号聚合成统一缺口模型，供 ``orchestration_loop`` 驱动再规划。
裁决（"怎么判"）仍在专家面板——本模块只读、不改任何抽取产物或裁决状态。

四类缺口（与简报 T2-1 一一对应）：
  1. ``clarification_blocking`` —— 澄清报告里 blocker_level=blocking 的必答未答项。
     这类缺口需要人答复，编排环**不能**自动闭合，route=human。
  2. ``conservation_open`` —— functional_extract 守恒核对的未闭合条款（missing/extra/
     duplicate/evidence_mismatch）。missing 子句（条款未被任何功能需求消费）→ route=extract
     （再抽该块可能覆盖它）；extra/duplicate/mismatch 是结构性错配，route=human。
  3. ``sampling_escalate`` —— claim 账本抽检闭合率低于 floor（``claim_sampling_summary.json``
     的 ``escalate=true``）。被推迟的 claim 经 claim catalog 映射到块 → route=extract；映射
     不到块的延迟 claim 或文档级 escalate → route=human。
  4. ``weakness`` —— 澄清报告弱词/可测性扫描命中（``weakness:*`` 信号）。弱词需要人澄清意图，
     再抽同一块未必更精确，route=human（如实进 NEEDS WORK，不自动烧钱补抽）。

T2-3 的 verification 反哺（test_completed=否 / 实现偏差）单独暴露为 ``verification_candidates``，
**不**并入四类缺口——它是"进人工确认队列的修订候选"，编排环只生成不裁决、绝不自动改需求。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from result_package import governed_artifact_path

# 缺口模型版本（进 gap report / orchestration 产物指纹；与 decide-trace-v1 解耦）。
ORCHESTRATION_GAP_VERSION = "orchestration-gap-v1"
# 编排策略版本（loop summary 的 policy_version；trace 记录单独用本常量，不复用 agent-policy-v3，
# 以免把缺口驱动的编排决策错标成 Phase 1 rule/llm 决策——provenance 不伪造）。
ORCHESTRATION_POLICY_VERSION = "orchestration-policy-v1"

GAP_KINDS = (
    "clarification_blocking",
    "conservation_open",
    "sampling_escalate",
    "weakness",
)

# 严重度 → 排序权重（数字越小越先被编排环处理）。
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
_SEVERITY_RANK = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}

# kind → 排序权重（同级 severity 内的稳定次序：守恒 > 抽检 > 澄清 > 弱词）。
_KIND_RANK = {kind: index for index, kind in enumerate(GAP_KINDS)}

ROUTE_EXTRACT = "extract"
ROUTE_HUMAN = "human"

ACTION_SPOT_EXTRACT = "spot_extract"
ACTION_TARGETED_REEXTRACT = "targeted_reextract"
ACTION_HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class Gap:
    """单个缺口：编排环据此决定"该看哪里"。

    ``block_id`` 是抽取落点（spot_extract/targeted_reextract 的目标块）；route=human 的缺口
    可能为空串。``action`` 是读取层的推荐动作，编排环在实际执行时会按授权/资格做最终裁定
    （如未授权 LLM → extract 降级为 human；omission 候选块 → spot_extract 升级为 targeted_reextract）。
    """

    kind: str
    target_id: str
    severity: str
    route: str
    action: str
    block_id: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[int, int, str, str]:
        return (
            _SEVERITY_RANK.get(self.severity, 99),
            _KIND_RANK.get(self.kind, 99),
            self.target_id,
            self.kind,
        )


@dataclass(frozen=True)
class VerificationCandidate:
    """T2-3 verification 反哺候选：进人工确认队列，绝不自动改需求。

    provenance 标 orchestration 来源；requirement_id + reason 指纹做幂等键（loop 写盘去重）。
    """

    requirement_id: str
    reason: str              # "test_not_completed" | "implementation_deviation"
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GapReport:
    """一次只读缺口快照。零副作用：调用前后盘上产物不变。"""

    version: str
    gaps: tuple[Gap, ...]
    counts_by_kind: dict[str, int]
    sources_available: dict[str, bool]
    readiness: dict[str, Any]
    verification_candidates: tuple[VerificationCandidate, ...]

    @property
    def extract_gaps(self) -> tuple[Gap, ...]:
        return tuple(g for g in self.gaps if g.route == ROUTE_EXTRACT)

    @property
    def human_gaps(self) -> tuple[Gap, ...]:
        return tuple(g for g in self.gaps if g.route == ROUTE_HUMAN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "orchestration-gap-report/v1",
            "version": self.version,
            "policy_version": ORCHESTRATION_POLICY_VERSION,
            "counts_by_kind": dict(self.counts_by_kind),
            "total": len(self.gaps),
            "extract_count": len(self.extract_gaps),
            "human_count": len(self.human_gaps),
            "sources_available": dict(self.sources_available),
            "readiness": dict(self.readiness),
            "verification_candidate_count": len(self.verification_candidates),
            "gaps": [asdict(gap) for gap in self.gaps],
            "verification_candidates": [asdict(c) for c in self.verification_candidates],
        }


class OrchestrationGapInputError(ValueError):
    """输出目录缺少编排环赖以读取缺口的最小产物（blocks/ai_requirements）。"""


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------


def read_gaps(out_dir: Path) -> GapReport:
    """确定性读取四类缺口 + verification 候选。只读、零副作用。"""
    root = Path(out_dir).expanduser().resolve()
    _require_minimal_artifacts(root)

    sources: dict[str, bool] = {}
    gaps: list[Gap] = []

    # ① 澄清 blocking + ④ 弱词：同源于 clarification_report（一次 collect 复用）。
    blocking_gaps, weakness_gaps, readiness, clar_available = _clarification_gaps(root, sources)
    gaps.extend(blocking_gaps)
    gaps.extend(weakness_gaps)

    # ② 守恒未闭合条款。
    conservation_gaps = _conservation_gaps(root, sources)
    gaps.extend(conservation_gaps)

    # ③ 抽检 escalate。
    sampling_gaps = _sampling_escalate_gaps(root, sources)
    gaps.extend(sampling_gaps)

    # T2-3 verification 反哺候选（独立于四类缺口）。
    verification_candidates = _verification_candidates(root, sources)

    gaps.sort(key=Gap.sort_key)
    counts_by_kind = {kind: 0 for kind in GAP_KINDS}
    for gap in gaps:
        counts_by_kind[gap.kind] = counts_by_kind.get(gap.kind, 0) + 1

    return GapReport(
        version=ORCHESTRATION_GAP_VERSION,
        gaps=tuple(gaps),
        counts_by_kind=counts_by_kind,
        sources_available=sources,
        readiness=readiness,
        verification_candidates=tuple(verification_candidates),
    )


def gap_report_summary(report: GapReport) -> dict[str, Any]:
    """机器读摘要（decide_trace state_digest / loop summary 消费）。"""
    return {
        "counts_by_kind": dict(report.counts_by_kind),
        "total": len(report.gaps),
        "extract_count": len(report.extract_gaps),
        "human_count": len(report.human_gaps),
        "verification_candidate_count": len(report.verification_candidates),
        "ready_gate": "pass" if report.readiness.get("verdict") == "READY" else "blocked",
    }


# ---------------------------------------------------------------------------
# 各类缺口读取
# ---------------------------------------------------------------------------


def _require_minimal_artifacts(root: Path) -> None:
    blocks = root / "blocks.jsonl"
    requirements = root / "ai_requirements.jsonl"
    missing = [p.name for p in (blocks, requirements) if not p.is_file()]
    if missing:
        raise OrchestrationGapInputError(
            f"输出目录缺少编排环必需产物：{', '.join(missing)}（先跑 AI 抽取再编排）"
        )


def _clarification_gaps(
    root: Path, sources: dict[str, bool]
) -> tuple[list[Gap], list[Gap], dict[str, Any], bool]:
    """① clarification_blocking + ④ weakness，复用 clarification_report 的 collect_questions。

    返回 (blocking_gaps, weakness_gaps, readiness, available)。collect_questions 任一异常都
    如实标 available=False 并返回空缺口——编排环不伪造缺口也不静默吞错（readiness 退保守 NEEDS WORK）。
    """
    import clarification_report

    try:
        entries = clarification_report.collect_questions(root)
        unresolved, _counts = clarification_report.unresolved_hard_questions(root)
        readiness = clarification_report.readiness_verdict(root, len(unresolved))
        available = True
    except Exception:  # noqa: BLE001 — 只读层不得因 clarification 链路异常崩溃编排环
        sources["clarification_report"] = False
        return [], [], {"verdict": "NEEDS WORK", "reasons": ["clarification 读取失败"]}, False

    sources["clarification_report"] = available
    unresolved_ids = {
        str(entry.get("clarification_id") or "") for entry in unresolved
    }

    blocking: list[Gap] = []
    weakness: list[Gap] = []
    for entry in entries:
        cid = str(entry.get("clarification_id") or "")
        signal = str(entry.get("signal") or "")
        # ④ 弱词/可测性扫描命中：仅当前未解决者进编排缺口（专家已 verified_ok 的不再驱动
        # NEEDS WORK）。route=human——弱词需人澄清意图，再抽同一块未必更精确，不自动烧钱。
        if signal.startswith("weakness:") and cid and cid in unresolved_ids:
            weakness.append(Gap(
                kind="weakness",
                target_id=cid,
                severity=SEVERITY_MEDIUM,
                route=ROUTE_HUMAN,
                action=ACTION_HUMAN_REVIEW,
                evidence={
                    "signal": signal,
                    "source_id": str(entry.get("source_id") or ""),
                    "section": str(entry.get("section") or ""),
                    "question": str(entry.get("question") or "")[:200],
                    "blocker_level": str(entry.get("blocker_level") or ""),
                },
            ))
        # ① 仅"当前未解决且 blocking"的澄清项才进编排缺口（已消解的不重复驱动）。
        if cid and cid in unresolved_ids and entry.get("blocker_level") == "blocking":
            blocking.append(Gap(
                kind="clarification_blocking",
                target_id=cid,
                severity=SEVERITY_HIGH,
                route=ROUTE_HUMAN,
                action=ACTION_HUMAN_REVIEW,
                evidence={
                    "signal": signal,
                    "source_id": str(entry.get("source_id") or ""),
                    "section": str(entry.get("section") or ""),
                    "question": str(entry.get("question") or "")[:200],
                    "audience": str(entry.get("audience") or ""),
                },
            ))
    return blocking, weakness, readiness, available


def _conservation_gaps(root: Path, sources: dict[str, bool]) -> list[Gap]:
    """② functional_extract 守恒核对的未闭合条款。

    missing 子句（条款块未被功能需求消费）→ route=extract（再抽该块可能覆盖它）；
    extra/duplicate/evidence_mismatch → route=human（结构性错配，专家必须手工裁）。
    functional_requirements.json 缺席（直抽未开 / 旧路径）→ available=False，无缺口。
    """
    payload = _read_governed_json(root, "functional_requirements.json", category="pipeline")
    sources["functional_requirements"] = payload is not None
    if payload is None:
        return []
    conservation = payload.get("conservation") or {}
    if not isinstance(conservation, dict) or conservation.get("ok", True):
        return []

    gaps: list[Gap] = []
    for block_id in _str_list(conservation.get("missing_block_ids")):
        gaps.append(Gap(
            kind="conservation_open",
            target_id=block_id,
            severity=SEVERITY_HIGH,
            route=ROUTE_EXTRACT,
            action=ACTION_TARGETED_REEXTRACT,
            block_id=block_id,
            evidence={"reason": "missing", "block_id": block_id},
        ))
    for block_id in _str_list(conservation.get("extra_block_ids")):
        gaps.append(Gap(
            kind="conservation_open",
            target_id=f"extra:{block_id}",
            severity=SEVERITY_HIGH,
            route=ROUTE_HUMAN,
            action=ACTION_HUMAN_REVIEW,
            evidence={"reason": "extra", "block_id": block_id},
        ))
    for block_id in _str_list(conservation.get("duplicate_assignments")):
        gaps.append(Gap(
            kind="conservation_open",
            target_id=f"duplicate:{block_id}",
            severity=SEVERITY_MEDIUM,
            route=ROUTE_HUMAN,
            action=ACTION_HUMAN_REVIEW,
            evidence={"reason": "duplicate", "block_id": block_id},
        ))
    for mismatch in conservation.get("evidence_mismatches") or []:
        if not isinstance(mismatch, dict):
            continue
        fid = str(mismatch.get("functional_requirement_id") or "")
        gaps.append(Gap(
            kind="conservation_open",
            target_id=f"mismatch:{fid}",
            severity=SEVERITY_MEDIUM,
            route=ROUTE_HUMAN,
            action=ACTION_HUMAN_REVIEW,
            evidence={"reason": "evidence_mismatch", **mismatch},
        ))
    return gaps


def _sampling_escalate_gaps(root: Path, sources: dict[str, bool]) -> list[Gap]:
    """③ claim 账本抽检闭合率低于 floor 的 escalate 信号。

    escalate=true 时把被推迟的 claim 经 claim catalog 映射到块 → route=extract（spot_extract
    该块为专家产出覆盖证据草稿）；映射不到块 / 无延迟清单 → 文档级 route=human。escalate=false
    或采样摘要缺席 → 无缺口（claim 账本未启用不算编排缺口）。
    """
    summary = _read_governed_json(root, "claim_sampling_summary.json", category="state")
    sources["claim_sampling_summary"] = summary is not None
    if not summary or not summary.get("escalate"):
        return []

    deferred = _str_list(summary.get("deferred_claim_ids"))
    if not deferred:
        return [Gap(
            kind="sampling_escalate",
            target_id="document",
            severity=SEVERITY_HIGH,
            route=ROUTE_HUMAN,
            action=ACTION_HUMAN_REVIEW,
            evidence={
                "reason": "document_escalate_no_deferred",
                "selected_ratio": summary.get("selected_ratio"),
                "deferred_count": int(summary.get("deferred_count") or 0),
            },
        )]

    catalog_blocks = _claim_id_to_block(root, sources)
    gaps: list[Gap] = []
    for claim_id in deferred:
        block_id = catalog_blocks.get(claim_id, "")
        if block_id:
            gaps.append(Gap(
                kind="sampling_escalate",
                target_id=claim_id,
                severity=SEVERITY_HIGH,
                route=ROUTE_EXTRACT,
                action=ACTION_SPOT_EXTRACT,
                block_id=block_id,
                evidence={
                    "reason": "deferred_claim",
                    "claim_id": claim_id,
                    "block_id": block_id,
                },
            ))
        else:
            gaps.append(Gap(
                kind="sampling_escalate",
                target_id=claim_id,
                severity=SEVERITY_HIGH,
                route=ROUTE_HUMAN,
                action=ACTION_HUMAN_REVIEW,
                evidence={"reason": "deferred_claim_no_block", "claim_id": claim_id},
            ))
    return gaps


def _verification_candidates(
    root: Path, sources: dict[str, bool]
) -> list[VerificationCandidate]:
    """T2-3：verification 反哺候选（test_completed=否 / 实现偏差）→ 人工确认队列。

    只读 verification_states.jsonl；绝不修改需求。verification_states 缺席 → 无候选。
    """
    try:
        from review_state import read_verification_states
    except Exception:  # noqa: BLE001
        sources["verification_states"] = False
        return []
    try:
        states = read_verification_states(root)
    except Exception:  # noqa: BLE001 — 只读层不因状态文件异常崩溃
        sources["verification_states"] = False
        return []
    sources["verification_states"] = True

    candidates: list[VerificationCandidate] = []
    for requirement_id, state in states.items():
        verification = state.get("verification") if isinstance(state.get("verification"), dict) else {}
        implemented = str(verification.get("implemented") or state.get("implemented") or "")
        test_completed = verification.get("test_completed", state.get("test_completed"))
        reasons: list[str] = []
        detail_parts: list[str] = []
        if test_completed is False:
            reasons.append("test_not_completed")
            detail_parts.append("test_completed=False（测试未完成，需复核需求可验证性 / 测试覆盖）")
        if implemented and implemented not in {"yes", "implemented"}:
            reasons.append("implementation_deviation")
            detail_parts.append(f"implemented={implemented}（实现状态偏离，需复核需求与实现一致性）")
        if not reasons:
            continue
        candidates.append(VerificationCandidate(
            requirement_id=str(requirement_id),
            reason=";".join(reasons),
            detail="；".join(detail_parts),
            evidence={
                "implemented": implemented,
                "test_completed": test_completed,
                "lifecycle_state": str(state.get("lifecycle_state") or ""),
            },
        ))
    candidates.sort(key=lambda c: c.requirement_id)
    return candidates


# ---------------------------------------------------------------------------
# 受治理路径上的只读 JSON / JSONL 辅助
# ---------------------------------------------------------------------------


def _read_governed_json(root: Path, filename: str, *, category: str) -> dict[str, Any] | None:
    path = governed_artifact_path(root, filename, category=category, for_write=False)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _claim_id_to_block(root: Path, sources: dict[str, bool]) -> dict[str, str]:
    """claim_catalog.jsonl → {claim_id: block_id}（只读；用于 sampling_escalate 落点映射）。"""
    from io_utils import read_jsonl

    path = governed_artifact_path(root, "claim_catalog.jsonl", category="state", for_write=False)
    if not path.is_file():
        # 旧布局回退：claim_catalog.jsonl 可能直接在根（非 package_v1）。
        path = root / "claim_catalog.jsonl"
    sources["claim_catalog"] = path.is_file()
    if not path.is_file():
        return {}
    mapping: dict[str, str] = {}
    try:
        for row in read_jsonl(path):
            claim_id = str(row.get("claim_id") or "")
            if not claim_id:
                continue
            locator = row.get("locator") if isinstance(row.get("locator"), dict) else {}
            block_id = str(
                locator.get("block_id")
                or row.get("block_id")
                or row.get("table_block_id")
                or ""
            )
            if block_id:
                mapping[claim_id] = block_id
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        # 坏行/坏文件不崩溃读取层——映射不到的 claim 由调用方走 human 路由
        sources["claim_catalog"] = False
    return mapping


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
