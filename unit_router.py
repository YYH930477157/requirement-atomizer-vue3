"""确定性 Unit Router（quality-first 方案 §7，M2 Shadow Mode）。

对 ExtractionUnit 逐单元输出路由决策：a_track / b_track / mixed / context / review。
第一版零 LLM、零执行变化——只产 ``unit_routing_decisions.jsonl`` governed 产物，
不改变任何既有阶段；用于回放对比（M2 shadow）与后续 quality-first 主执行（M4）。

硬信号（§7.3/§7.4，全部确定性可审计）：
- A 硬：合法 COSEM class_id（cosem_object_model.CLASS_NAME_TO_ID 白名单）、格式合法
  OBIS（atomize.extract_parameters + normalize_obis_value）、attribute/method 编号、
  访问模式词、cosem_object_context（cosem_structured 角色）、COSEM/DLMS 结构表头；
- B 硬：规范性义务模态（复用 functional_extract 权威模态正则）、表结构层
  obligation_signal 的 marker/modal/pattern 强信号；
- 弱信号：sentence_shape/colon_spec（表结构层口径）→ review，不静默丢弃；
- Context：定义/引用/标题/无信号叙事/excluded 处置——永不做付费提取。

评分（§7.7）：a_score/b_score 两个独立分数，硬信号=1.0、弱信号=0.4、无=0.0；
不使用互相抵消的总分。阈值不落魔法数字：本版规则只依赖硬/弱二值判定 + 规则名
（rule 字段），真实语料标定后如引入数值阈值，必须 bump UNIT_ROUTER_VERSION。

v2 标定（2026-08-17，ABNT 真实语料 + phase2 探针）：COSEM 结构表的 row/cell 单元
在 A 硬信号 + 义务模态并存时改判 a_track（`cosem_table_a_priority`）——模态出现在
参数叙述列，归 A 轨 claim/处置权威；prose mixed 语义不变。

红线：路由不改写单元内容；决策携带 unit source_text_hash 供缓存 lineage 校验；
review 单元必须物化（shadow 阶段即写入产物，后续阶段不得静默丢弃）。
"""
from __future__ import annotations

import re
from typing import Any

from artifact_store import ArtifactStore
from extraction_units import (
    EXTRACTION_UNIT_PLANNER_VERSION,
    load_extraction_units,
    plan_extraction_units,
)
from io_utils import read_jsonl

UNIT_ROUTER_VERSION = "unit-router-v2"
UNIT_ROUTING_DECISION_SCHEMA = "unit-routing-decision/v1"
UNIT_ROUTING_DECISIONS_FILENAME = "unit_routing_decisions.jsonl"
UNIT_ROUTING_SUMMARY_SCHEMA = "unit-routing-summary/v1"

ROUTES = ("a_track", "b_track", "mixed", "context", "review")

# 证据 kind（schema 枚举的单点权威）
EVIDENCE_KINDS = (
    "obis",                 # 格式合法 OBIS 代码（A 硬）
    "class_id",             # COSEM class 编号（合法白名单内为 A 硬）
    "cosem_attribute",      # attribute/method 编号（A 硬）
    "access_mode",          # 访问模式词（A 硬）
    "cosem_context",        # cosem_object_context / COSEM 结构表头（A 硬）
    "dlms_profile",         # DLMS/COSEM 协议词 + 结构上下文（A 硬）
    "modal",                # 规范性义务模态（B 硬）
    "normative_pattern",    # 表结构层强 normative 模式（B 硬）
    "weak_signal",          # sentence_shape/colon_spec 弱信号（→ review）
)

_ATTRIBUTE_RE = re.compile(r"\b(?:attribute|attr|method)\s*(?:no\.?\s*)?(\d{1,3})\b",
                           re.IGNORECASE)
_ACCESS_MODE_RE = re.compile(r"\b(?:read[- ]only|write[- ]only|read[- ]write|readonly|"
                             r"readwrite)\b", re.IGNORECASE)
_DLMS_RE = re.compile(r"\b(?:DLMS|COSEM)\b")
_COSEM_HEADER_RE = re.compile(
    r"object\s*/\s*attribute\s*name|access\s*rights|^CL$|^#$", re.IGNORECASE)


def _evidence(kind: str, value: Any) -> dict[str, str]:
    return {"kind": kind, "value": str(value) if value is not None else ""}


def _a_signals(unit: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """返回 (evidence, hard)。hard = 可验证结构证据（A 硬信号）。"""
    from atomize import extract_parameters
    from cosem_object_model import CLASS_NAME_TO_ID, class_name_for_id

    text = str(unit.get("source_text") or "")
    evidence: list[dict[str, str]] = []
    parameters = extract_parameters(text)
    for code in (parameters.get("obis_codes") or [])[:4]:
        evidence.append(_evidence("obis", code))
    for class_id in (parameters.get("class_ids") or [])[:4]:
        name = class_name_for_id(str(class_id))
        evidence.append(_evidence(
            "class_id", f"{class_id} ({name})" if name else f"{class_id} (unverified)"))
    match = _ATTRIBUTE_RE.search(text)
    if match:
        evidence.append(_evidence("cosem_attribute", match.group(0).strip()))
    match = _ACCESS_MODE_RE.search(text)
    if match:
        evidence.append(_evidence("access_mode", match.group(0)))
    roles = {str(role) for role in unit.get("roles") or []}
    headers = [str(header) for header in
               (unit.get("table_context") or {}).get("headers") or []]
    cosem_headers = [header for header in headers if _COSEM_HEADER_RE.search(header)]
    if "cosem_structured" in roles or cosem_headers:
        evidence.append(_evidence(
            "cosem_context",
            "cosem_object_context" if "cosem_structured" in roles
            else " | ".join(cosem_headers)))
    dlms = _DLMS_RE.search(text)
    if dlms and (cosem_headers or "cosem_structured" in roles):
        evidence.append(_evidence("dlms_profile", dlms.group(0)))
    # 命名 COSEM 类词命中（如 "Profile Generic"）仅在 COSEM 表格语境下算合法 class
    # 证据——白名单含 "Data"/"Clock" 等普通名词，在正文里命中全是假阳性
    if "cosem_structured" in roles or cosem_headers:
        for name, class_id in CLASS_NAME_TO_ID.items():
            if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                evidence.append(_evidence("class_id", f"{name} ({class_id})"))
                break

    # 核心硬信号：OBIS / 合法 class / COSEM 上下文；attribute/access 词只有在核心
    # 证据或 COSEM 表格语境下才升硬——否则普通义务句里的 "read-only access" 会把
    # b_track 误判成 mixed（§7.6 要求强 A 信号才算 Mixed）
    core_kinds = {"obis", "cosem_context", "dlms_profile"}
    core_hard = [item for item in evidence
                 if item["kind"] in core_kinds
                 or (item["kind"] == "class_id" and "unverified" not in item["value"])]
    structural_table = "cosem_structured" in roles or bool(cosem_headers)
    hard = list(core_hard)
    if core_hard or structural_table:
        hard.extend(item for item in evidence
                    if item["kind"] in ("cosem_attribute", "access_mode"))
    return evidence, hard


def _b_signals(unit: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """返回 (evidence, hard, weak)。"""
    from functional_extract import _EN_MODAL_PHRASE_RE, _EN_MODAL_RE, _ZH_MODAL_RE
    from table_structure import obligation_signal

    text = str(unit.get("source_text") or "")
    evidence: list[dict[str, str]] = []
    hard: list[dict[str, str]] = []
    weak: list[dict[str, str]] = []
    for match in list(_EN_MODAL_RE.finditer(text))[:3]:
        evidence.append(_evidence("modal", match.group(0).lower()))
    phrase = _EN_MODAL_PHRASE_RE.search(text)
    if phrase:
        evidence.append(_evidence("modal", phrase.group(0).lower()))
    zh = _ZH_MODAL_RE.search(text)
    if zh:
        evidence.append(_evidence("modal", zh.group(0)))
    if evidence:
        hard.extend(item for item in evidence if item["kind"] == "modal")
    signal = obligation_signal(text)
    if signal in ("modal", "marker", "pattern"):
        entry = _evidence("normative_pattern", signal)
        evidence.append(entry)
        hard.append(entry)
    elif signal in ("sentence_shape", "colon_spec"):
        entry = _evidence("weak_signal", signal)
        evidence.append(entry)
        weak.append(entry)
    return evidence, hard, weak


def route_unit(unit: dict[str, Any]) -> dict[str, Any]:
    """单单元确定性路由（纯函数）。"""
    a_evidence, a_hard = _a_signals(unit)
    b_evidence, b_hard, weak = _b_signals(unit)
    evidence = a_evidence + b_evidence
    roles = {str(role) for role in unit.get("roles") or []}
    kind = str(unit.get("unit_kind") or "")

    def _score(hard: list[dict[str, str]], weak_evidence: list[dict[str, str]]) -> float:
        if hard:
            return 1.0
        if weak_evidence:
            return 0.4
        return 0.0

    a_score = _score(a_hard, [])
    b_score = _score(b_hard, weak)

    # 定义/引用/标题是结构性上下文（§7.5）：引用文本内嵌的 shall 属于被引条款自己的
    # 义务，由该条款单元承载——这里再路由只会双重抽取
    headers = [str(header) for header in
               (unit.get("table_context") or {}).get("headers") or []]
    cosem_table = kind in ("table_row", "table_cell") and (
        "cosem_structured" in roles
        or any(_COSEM_HEADER_RE.search(header) for header in headers))
    if kind in ("definition", "reference", "heading"):
        route, primary, rule, confidence = "context", None, "context_by_kind", 0.9
    elif cosem_table and (a_hard or b_hard):
        # v2（2026-08-17 真实语料标定，phase2 探针实证）：COSEM 结构表（cosem 语境的
        # row/cell 单元）出现义务模态时，模态几乎总在参数叙述列（Meaning/Value 对
        # 默认值/缓冲行为的说明——同一行其他格携带 OBIS/class，本格文本可能只有模态），
        # 属 §7.5「仅用于限定邻近需求的参数说明」——整表归 A 轨 claim/处置权威，
        # flash 直抽此类表确定性守恒失败（引文改写/数字丢失）。prose 单元的
        # mixed/b_track 语义不变（§8/§9.1：B 提义务 + A 确定性补结构字段）。
        route, primary, rule, confidence = "a_track", "a_track", "cosem_table_a_priority", 0.9
    elif a_hard and b_hard:
        route, primary, rule, confidence = "mixed", "b_track", "hard_ab_mixed", 0.95
    elif a_hard:
        route, primary, rule, confidence = "a_track", "a_track", "hard_a_only", 1.0
    elif b_hard:
        route, primary, rule, confidence = "b_track", "b_track", "hard_b_only", 1.0
    elif kind == "narrative" or "excluded" in roles:
        route, primary, rule, confidence = "context", None, "context_by_kind", 0.9
    elif "review_candidate" in roles:
        route, primary, rule, confidence = "review", None, "review_disposition", 0.4
    elif weak:
        route, primary, rule, confidence = "review", None, "review_weak_signal", 0.4
    elif "context" in roles or (unit.get("table_context") or {}).get("disposition") == "context":
        route, primary, rule, confidence = "context", None, "context_by_disposition", 0.9
    else:
        # planner 认为是候选但路由器找不到任何可审计信号——弱信号进 review，
        # 不静默丢弃（§2.2 红线）
        route, primary, rule, confidence = "review", None, "review_no_signal", 0.4

    return {
        "schema": UNIT_ROUTING_DECISION_SCHEMA,
        "unit_id": str(unit.get("unit_id") or ""),
        "unit_kind": kind,
        "route": route,
        "primary_route": primary,
        "a_score": a_score,
        "b_score": b_score,
        "confidence": confidence,
        "rule": rule,
        "evidence": evidence,
        "source_text_hash": str(unit.get("source_text_hash") or ""),
        "router_version": UNIT_ROUTER_VERSION,
        "planner_version": str(unit.get("planner_version") or EXTRACTION_UNIT_PLANNER_VERSION),
        "decision_basis": "deterministic",
    }


def route_units(units: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decisions = [route_unit(unit) for unit in units]
    counts: dict[str, int] = {route: 0 for route in ROUTES}
    rules: dict[str, int] = {}
    kinds_by_route: dict[str, dict[str, int]] = {}
    for decision in decisions:
        counts[decision["route"]] += 1
        rules[decision["rule"]] = rules.get(decision["rule"], 0) + 1
        kinds_by_route.setdefault(decision["route"], {})
        kinds_by_route[decision["route"]][decision["unit_kind"]] = (
            kinds_by_route[decision["route"]].get(decision["unit_kind"], 0) + 1)
    summary = {
        "schema": UNIT_ROUTING_SUMMARY_SCHEMA,
        "router_version": UNIT_ROUTER_VERSION,
        "shadow_mode": True,
        "unit_count": len(units),
        "counts_by_route": counts,
        "counts_by_rule": dict(sorted(rules.items())),
        "counts_by_route_and_kind": kinds_by_route,
        "review_rate": round(counts["review"] / len(units), 4) if units else 0.0,
        "context_rate": round(counts["context"] / len(units), 4) if units else 0.0,
    }
    return decisions, summary


def route_document(out_dir, *, plan_if_missing: bool = True) -> dict[str, Any]:
    """Shadow 入口：规划（如缺）→ 路由 → 写 governed 产物。不改变执行链。"""
    units = load_extraction_units(out_dir)
    if not units and plan_if_missing:
        plan_extraction_units(out_dir)
        units = load_extraction_units(out_dir)
    decisions, summary = route_units(units)
    store = ArtifactStore(out_dir, category="pipeline")
    store.write_jsonl(UNIT_ROUTING_DECISIONS_FILENAME, decisions)
    summary["artifact"] = UNIT_ROUTING_DECISIONS_FILENAME
    summary["unit_count_planned"] = len(units)
    return summary


def load_routing_decisions(out_dir) -> list[dict[str, Any]]:
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, UNIT_ROUTING_DECISIONS_FILENAME,
                                  category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []
