from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from requirements_analysis_schema import (
    OWNERSHIP_CO_DESIGN,
    OWNERSHIP_HARDWARE,
    OWNERSHIP_SOFTWARE,
)

ANALYZE_RULES_VERSION = "analyze-rules-v1"

SOFTWARE_TERMS = (
    "dlms",
    "cosem",
    "obis",
    "xdmls",
    "xdlms",
    "get service",
    "set service",
    "action",
    "event",
    "事件",
    "profile",
    "曲线",
    "tariff",
    "费率",
    "billing",
    "结算",
    "prepaid",
    "预付费",
    "push",
    "p1",
    "display",
    "显示",
    "status word",
    "状态字",
    "upgrade",
    "升级",
    "clock",
    "时钟",
    "access right",
    "访问权限",
)

HARDWARE_TERMS = (
    "计量芯片",
    "芯片型号",
    "ct采样",
    "ct 采样",
    "锰铜",
    "shunt",
    "relay physical",
    "继电器物理",
    "电源",
    "电池",
    "frequency band",
    "频段",
    "mechanical",
    "结构尺寸",
    "寿命",
    "器件",
    "硬件更换",
    "manufacturer",
    "manufactures a device",
    "battery",
    "service life",
    "lifetime",
    "enclosure",
    "housing",
    "ingress protection",
    "power consumption",
    "power supply",
    "three-phase",
    "powered from all three phases",
    "va",
)

CO_DESIGN_TERMS = (
    "驱动",
    "hardware related",
    "硬件相关",
    "波特率",
    "baud",
    "dataflash",
    "存储容量",
    "flash",
    "mbus",
    "m-bus",
    "wmbus",
    "w-mbus",
    "模块适配",
    "硬件接口",
    "采样影响",
    "继电器状态",
    "mobile data concentrator",
    "concentrator function",
    "concentrator functions",
    "walk by",
    "walk-by",
    "drive by",
    "drive-by",
    "remote management center",
    "central hardware and software components",
)

SEARCH_FIELDS = ("title", "description", "requirement", "module", "source_quote", "labels")

# CJK 短词（事件/显示/时钟…）按裸子串匹配会误伤部件描述（"无事件发生"、"时钟计数器型号"）。
# 中文无词边界，难以精确分词；只检查命中附近的硬件名词，并让明确的软件动作保留该命中。
_CJK_HW_CONTEXT_TERMS = ("型号", "芯片", "器件", "物理", "结构", "材质", "规格", "封装", "引脚", "硬件")
_CJK_SOFTWARE_ACTION_TERMS = (
    "读取", "同步", "记录", "配置", "处理", "上报", "控制",
    "管理", "计算", "更新", "校准", "实现", "支持",
)
_CJK_CONTEXT_RADIUS = 12


def classify_ownership(requirement: dict[str, Any]) -> dict[str, Any]:
    text = _search_text(requirement)

    co_design_term = _first_match(text, CO_DESIGN_TERMS)
    hardware_term = _first_match(text, HARDWARE_TERMS)
    software_term = _first_match(text, SOFTWARE_TERMS)

    if co_design_term:
        return _decision(OWNERSHIP_CO_DESIGN, 0.78, co_design_term)
    if hardware_term and not software_term:
        return _decision(OWNERSHIP_HARDWARE, 0.82, hardware_term)
    if software_term:
        return _decision(OWNERSHIP_SOFTWARE, 0.80, software_term)
    return {
        "ownership": OWNERSHIP_SOFTWARE,
        "ownership_confidence": 0.55,
        "ownership_reason": "No deterministic ownership keyword matched; defaulted to software.",
        "ownership_source": "rule",
    }


def _search_text(requirement: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in SEARCH_FIELDS:
        value = requirement.get(field)
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    # Keep local CJK context windows inside one source field/value.
    return (" " * (_CJK_CONTEXT_RADIUS + 1)).join(parts).casefold()


def _first_match(text: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        normalized_term = term.casefold()
        if _contains_cjk(normalized_term):
            if normalized_term in text and not _is_cjk_false_friend(text, normalized_term):
                return term
            continue
        if _matches_ascii_term(text, normalized_term):
            return term
    return None


def _is_cjk_false_friend(text: str, term: str) -> bool:
    """短 CJK 软件词仅在局部硬件名词上下文且无软件动作时判为假朋友。

    例如 term="时钟" 命中 "时钟计数器型号"、term="事件" 命中 "事件计数器芯片"——
    这些是硬件件描述里的字面词，不是功能域信号。长 CJK 词（≥3 字，如"访问权限"）
    语义已足够明确，不撤。
    """
    if len(term) > 2:
        return False
    positions = [match.start() for match in re.finditer(re.escape(term), text)]
    if not positions:
        return False
    for position in positions:
        start = max(0, position - _CJK_CONTEXT_RADIUS)
        end = min(len(text), position + len(term) + _CJK_CONTEXT_RADIUS)
        context = text[start:end]
        hardware_context = any(value in context for value in _CJK_HW_CONTEXT_TERMS)
        software_action = any(value in context for value in _CJK_SOFTWARE_ACTION_TERMS)
        if not hardware_context or software_action:
            return False
    return True


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _matches_ascii_term(text: str, term: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


def _decision(ownership: str, confidence: float, term: str) -> dict[str, Any]:
    return {
        "ownership": ownership,
        "ownership_confidence": confidence,
        "ownership_reason": f"Matched {ownership} rule term: {term}",
        "ownership_source": "rule",
    }


# ===========================================================================
# WS4：verification 人工覆盖通道 + 四态状态机 + 手工入口 + 依赖裁决（策略层）
# ---------------------------------------------------------------------------
# 共享状态 I/O（锁 + 原子替换）在 review_state.py；纯域契约在 requirement_schema.py。
# 本模块只做策略：CAS 校验、生命周期前进/回退规则、reviewer_override 来源标记、
# 候选接受才写库。全程确定性、零 LLM 调用。
# ===========================================================================
def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_functional_requirements_payload(root: Path) -> dict[str, Any]:
    """读 functional_requirements.json——双路径探测（governed 优先、根目录兜底）。

    functional_synthesis 走裸根写、functional_extract 走 governed 写，两个写入器并存是
    现状（见 result_package._ARTIFACTS 的 functional_requirements 登记 + legacy_path）。
    package_v1 下 governed 解析到 .ratomizer/pipeline/，但裸根写入仍可能落根目录，
    故逐候选 stat 命中即读，与桌面端 readGovernedArtifact 同口径（for_write=False 不建目录）。
    """
    from result_package import governed_artifact_path

    candidates = [
        governed_artifact_path(root, "functional_requirements.json",
                               category="pipeline", for_write=False),
        root / "functional_requirements.json",
    ]
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def read_functional_requirements(out_dir: Path) -> list[dict[str, Any]]:
    """读 functional_requirements.json 的 items 列表（governed 双路径探测）。

    供 GET /functional-requirements 只读端点：缺失/坏 JSON → 空列表（如实，不伪造）。
    """
    root = Path(out_dir).expanduser().resolve()
    items = _read_functional_requirements_payload(root).get("items")
    return [item for item in (items or []) if isinstance(item, dict)]


def load_requirement_index(out_dir: Path) -> dict[str, dict[str, Any]]:
    """构建 {requirement_id: {item, fingerprint}} 索引（分析项 + 功能需求 + 手工需求）。

    供 verification CAS、xlsx 回灌按行定位使用——需求重新生成后内容指纹漂移即失配。
    functional_requirements.json 必须纳入：FRE-* 功能抽取条目只在此文件，旧实现漏读导致
    其 CAS 形同虚设（current_fingerprint 恒 ""，任何 expected 都“匹配”）。
    """
    from requirement_schema import requirement_content_fingerprint, requirement_identity
    from review_state import read_manual_requirements

    root = Path(out_dir).expanduser().resolve()
    index: dict[str, dict[str, Any]] = {}
    analysis_path = root / "engineering_analysis.json"
    if analysis_path.exists():
        try:
            payload = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        items = payload.get("items") if isinstance(payload, dict) else None
        for item in items or []:
            if isinstance(item, dict):
                rid = requirement_identity(item)
                index[rid] = {"item": item, "fingerprint": requirement_content_fingerprint(item)}
    # FRE-* 功能抽取条目（functional_extract 直抽）：只落 functional_requirements.json，
    # 不纳入索引则 verification CAS 对它们恒放行（F1 修复）。
    functional_items = _read_functional_requirements_payload(root).get("items")
    for item in functional_items or []:
        if isinstance(item, dict):
            rid = requirement_identity(item)
            index[rid] = {"item": item, "fingerprint": requirement_content_fingerprint(item)}
    for item in read_manual_requirements(root):
        rid = requirement_identity(item)
        index[rid] = {"item": item, "fingerprint": requirement_content_fingerprint(item)}
    return index


def apply_verification_override(
    out_dir: Path,
    requirement_id: str,
    verification: Any,
    *,
    actor: str = "",
    evidence_fingerprint: str | None = None,
    expected_evidence_fingerprint: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """CAS 校验后写入 verification 覆盖（reviewer_override 来源），并前进迁移生命周期。

    前进迁移全部由 verification 字段驱动（advance_lifecycle 取当前态与派生态较高者）；
    自动降级不存在——派生值低于当前态时保留当前态。CAS 失配抛 VerificationStateConflict
    （evidence fingerprint 失配拒绝自动合入转人工）。
    """
    from requirement_schema import (
        VERIFICATION_SOURCE,
        advance_lifecycle,
        lifecycle_rank,
        normalize_verification,
    )
    from review_state import (
        VerificationStateConflict,
        append_lifecycle_event,
        read_verification_states,
        upsert_verification_state,
    )

    root = Path(out_dir).expanduser().resolve()
    rid = str(requirement_id or "").strip()
    if not rid:
        raise ValueError("requirement_id is required for verification override")
    normalized = normalize_verification(verification)
    index = load_requirement_index(root)
    entry = index.get(rid)
    current_fingerprint = str(entry["fingerprint"]) if entry else ""
    if expected_evidence_fingerprint is not None and \
            str(expected_evidence_fingerprint) != current_fingerprint:
        raise VerificationStateConflict(
            f"需求 {rid} 内容已变化（CAS 失配），verification 拒绝自动合入，转人工核对",
            requirement_id=rid, current_fingerprint=current_fingerprint)
    existing = read_verification_states(root).get(rid, {})
    current_state = str(existing.get("lifecycle_state") or "draft")
    new_state = advance_lifecycle(current_state, normalized)
    when = str(timestamp or _now_iso())
    record = {
        "requirement_id": rid,
        "verification": normalized,
        "lifecycle_state": new_state,
        "lifecycle_max": max(
            int(existing.get("lifecycle_max") or lifecycle_rank(current_state)),
            lifecycle_rank(new_state),
        ),
        "evidence_fingerprint": current_fingerprint or str(evidence_fingerprint or ""),
        "source": VERIFICATION_SOURCE,
        "actor": str(actor or ""),
        "timestamp": when,
        "schema": "verification-state/v1",
    }
    persisted = upsert_verification_state(root, rid, record)
    # S1-10a：前进迁移同样 append 事件（与回退事件同构同流）。
    # 仅在生命周期严格升态时追加——重复保存（无升态）不污染 append-only 审计流
    # （S1-6 三连保存不应堆积重复事件）。upsert 已先落盘，事件是同流投影。
    if lifecycle_rank(new_state) > lifecycle_rank(current_state):
        append_lifecycle_event(root, {
            "requirement_id": rid,
            "from_state": current_state,
            "to_state": new_state,
            "kind": "advance",
            "trigger": "verification-driven",
            "actor": str(actor or ""),
            "reason": "",
            "timestamp": when,
        })
    return persisted


def apply_requirement_library_adoption(
    out_dir: Path,
    requirement_id: str,
    *,
    ownership: str = "",
    module: str = "",
    actor: str = "",
    reason: str = "",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """把需求库历史条目的归属/模块初值套用到目标功能需求。

    经既有 reviewer_override 通道（verification_states.jsonl，source=reviewer_override）留痕——
    复用 upsert_verification_state 的锁 + 原子替换写路径，不新造写文件。actor/reason 必填
    （审计可追溯：谁采纳了哪个历史条目、为什么）。ownership/module 任一为空则跳过该字段，
    不清空既有覆盖。
    """
    from review_state import upsert_verification_state

    root = Path(out_dir).expanduser().resolve()
    rid = str(requirement_id or "").strip()
    actor_s = str(actor or "").strip()
    reason_s = str(reason or "").strip()
    if not rid:
        raise ValueError("requirement_id is required for library adoption")
    if not actor_s or not reason_s:
        raise ValueError("actor and reason are required for library adoption (reviewer_override 留痕)")
    ownership_s = str(ownership or "").strip()
    module_s = str(module or "").strip()
    record: dict[str, Any] = {
        "requirement_id": rid,
        "schema": "verification-state/v1",
        "adopt_source": "requirement_library",
        "adopt_actor": actor_s,
        "adopt_reason": reason_s,
        "adopt_timestamp": str(timestamp or _now_iso()),
    }
    if ownership_s:
        record["ownership_override"] = ownership_s
    if module_s:
        record["module_override"] = module_s
    return upsert_verification_state(root, rid, record)


def rollback_requirement_lifecycle(
    out_dir: Path,
    requirement_id: str,
    target_state: str,
    *,
    actor: str,
    reason: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """人工回退生命周期（唯一使状态下落的路径）。回退事件 append-only 留痕。

    回退不清 verification 字段（自动降级不存在，状态机下降不等于数据倒退）。
    """
    from requirement_schema import LIFECYCLE_DRAFT, LIFECYCLE_VALUES, lifecycle_rank
    from review_state import (
        VerificationStateConflict,
        append_lifecycle_event,
        read_verification_states,
        upsert_verification_state,
    )

    root = Path(out_dir).expanduser().resolve()
    rid = str(requirement_id or "").strip()
    target = str(target_state or "").strip()
    if target not in LIFECYCLE_VALUES:
        raise ValueError(f"非法生命周期目标态：{target_state}")
    existing = read_verification_states(root).get(rid, {})
    current = str(existing.get("lifecycle_state") or LIFECYCLE_DRAFT)
    if lifecycle_rank(target) >= lifecycle_rank(current):
        raise ValueError(
            f"回退目标必须低于当前态（当前 {current} → 目标 {target} 不是回退）")
    when = str(timestamp or _now_iso())
    existing["lifecycle_state"] = target
    existing["lifecycle_max"] = max(
        int(existing.get("lifecycle_max") or lifecycle_rank(current)),
        lifecycle_rank(current),
    )
    existing["requirement_id"] = rid
    record = upsert_verification_state(root, rid, existing)
    append_lifecycle_event(root, {
        "requirement_id": rid,
        "from_state": current,
        "to_state": target,
        "kind": "rollback",
        "trigger": "manual",
        "actor": str(actor or ""),
        "reason": str(reason or ""),
        "timestamp": when,
    })
    return record


def current_lifecycle(out_dir: Path, requirement_id: str) -> str:
    """读当前生命周期态（无覆盖记录=未参与状态机，按 draft 计）。"""
    from requirement_schema import LIFECYCLE_DRAFT
    from review_state import read_verification_states

    rid = str(requirement_id or "").strip()
    record = read_verification_states(Path(out_dir).expanduser().resolve()).get(rid)
    return str((record or {}).get("lifecycle_state") or LIFECYCLE_DRAFT)


def record_manual_requirement(
    out_dir: Path,
    *,
    objective: str,
    behaviors: Any = None,
    module: str = "",
    ownership: str = "",
    priority: str = "P1",
    notes: str = "",
    actor: str = "",
    requirement_id: str = "",
) -> dict[str, Any]:
    """构造并持久化一条手工需求（provenance=manual，追溯列留空不伪引）。

    手工条目走完全相同下游（归属/澄清/导出/状态机）——归属由下游 classify_ownership 在
    导出时按其文本确定性分类（默认 software）。
    """
    from requirement_schema import build_manual_requirement
    from review_state import append_manual_requirement

    record = build_manual_requirement(
        objective=objective, behaviors=behaviors, module=module, ownership=ownership,
        priority=priority, notes=notes, actor=actor, requirement_id=requirement_id,
    )
    append_manual_requirement(Path(out_dir).expanduser().resolve(), record)
    return record


def apply_dependency_decision(
    out_dir: Path,
    candidate: dict[str, Any],
    *,
    accepted: bool,
    actor: str = "",
    reason: str = "",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """依赖/父子候选裁决：接受才写库；拒绝不落库（返回 written=False）。"""
    from review_state import upsert_dependency_decision

    if not accepted:
        return {"accepted": False, "written": False, "candidate": candidate}
    decision = dict(candidate)
    decision.update({
        "status": "accepted",
        "actor": str(actor or ""),
        "reason": str(reason or ""),
        "timestamp": str(timestamp or _now_iso()),
    })
    record = upsert_dependency_decision(Path(out_dir).expanduser().resolve(), decision)
    return {"accepted": True, "written": True, "decision": record}


def dependency_candidates_for_project(out_dir: Path) -> list[dict[str, Any]]:
    """对当前项目的功能需求跑确定性依赖/父子候选推荐（只生产值，不动 schema）。"""
    from requirement_schema import recommend_dependency_candidates
    from review_state import read_manual_requirements

    root = Path(out_dir).expanduser().resolve()
    # S1-10c：改 governed 双路径探测（.ratomizer/pipeline 优先、根兜底，for_write=False 不建目录）。
    # 旧实现裸拼 root/"functional_requirements.json"——package_v1 下该文件不在根目录，
    # 候选恒空（B1 类寻址失守的重现，与 load_requirement_index 同族）。复用既有双路径读取器。
    requirements: list[dict[str, Any]] = [
        item for item in (_read_functional_requirements_payload(root).get("items") or [])
        if isinstance(item, dict)
    ]
    requirements.extend(read_manual_requirements(root))
    return recommend_dependency_candidates(requirements)
