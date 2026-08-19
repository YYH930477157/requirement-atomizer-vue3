"""Routed Execution：Mixed 字段协作合并核心（quality-first 方案 §8，M3）。

Mixed ≠ 完整双跑（§8.1）：同一 unit_id + obligation identity 只产生**一条**
authoritative requirement——B 型义务语义为主干，A 型结构字段（class/OBIS/
attribute/access）经确定性解析并入 implementation_constraints，全部带
route_provenance。A/B 临时候选只留在审计产物，不同时进最终交付物。

本模块 M3 只交付确定性合并核心（零 LLM、零执行变化）：
- ``implementation_constraints(unit, decision)``：从 A 证据确定性解析结构字段
  （白名单校验 class，normalize OBIS——绝不采信模型编造值）；
- ``obligation_identity(unit)``：去重键 = source_unit_id + 规范化义务文本
  （复用 functional_extract 义务切分权威）+ 结构目标标识；
- ``shape_mixed_requirement(...)``：§8.2 输出形态。

M4/M5 在此之上接 processor dispatch 与局部升级（复用 claim queue/CAS/WAL）。
"""
from __future__ import annotations

import re
from typing import Any

ROUTED_MERGE_VERSION = "routed-merge-v1"
AUTHORITATIVE_REQUIREMENT_SCHEMA = "authoritative-requirement/v1"

_ACCESS_MODE_MAP = {
    "read only": "read_only", "read-only": "read_only", "readonly": "read_only",
    "write only": "write_only", "write-only": "write_only", "writeonly": "write_only",
    "read write": "read_write", "read-write": "read_write", "readwrite": "read_write",
}


def implementation_constraints(unit: dict[str, Any],
                               decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """从单元/路由证据确定性解析 A 型结构字段。

    只接受可验证值：class 必须在 COSEM 白名单；OBIS 经 normalize 校验；
    attribute/method 编号限 1-3 位；access 归一化枚举。解析不出就缺省——
    "宁漏勿错"，绝不从 LLM 输出回填结构字段（红线）。
    """
    from atomize import extract_parameters
    from cosem_object_model import class_name_for_id, normalize_obis_value

    text = str(unit.get("source_text") or "")
    constraints: dict[str, Any] = {}
    parameters = extract_parameters(text)
    obis = parameters.get("obis_codes") or []
    if obis:
        normalized = normalize_obis_value(str(obis[0]))
        # normalize 只归一不校验——格式必须完整（\d-\d:A.B.C[.D]）才采信
        if re.fullmatch(r"\d+-\d+:[0-9A-Za-z*]+(?:\.[0-9A-Za-z*]+){2,3}", normalized):
            constraints["obis"] = normalized
    for class_id in parameters.get("class_ids") or []:
        name = class_name_for_id(str(class_id))
        if name:
            constraints["class_id"] = int(class_id)
            constraints["class_name"] = name
            break
    match = re.search(r"\battribute\s*(?:no\.?\s*)?(\d{1,3})\b", text, re.IGNORECASE)
    if match:
        constraints["attribute_id"] = int(match.group(1))
    match = re.search(r"\bmethod\s*(?:no\.?\s*)?(\d{1,3})\b", text, re.IGNORECASE)
    if match:
        constraints["method_id"] = int(match.group(1))
    lowered = text.lower()
    for phrase, value in _ACCESS_MODE_MAP.items():
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            constraints["access"] = value
            break
    return constraints


def obligation_identity(unit: dict[str, Any]) -> str:
    """稳定去重键（§8.3）：source_unit_id + 规范化义务文本 + 结构目标。

    同一单元的同一义务（模态/空白差异归一后）得到同一 identity——Mixed 合并
    与 B 轨抽取的结果按此键去重，不会产生重复 authoritative requirement。
    """
    from claim_artifacts import sha256_bytes
    from functional_extract import _obligation_units

    text = str(unit.get("source_text") or "")
    units = _obligation_units(text)
    canonical = " ".join(part.strip().lower() for part in units) if units else text.strip().lower()
    canonical = re.sub(r"\s+", " ", canonical)
    context = unit.get("table_context") or {}
    target = "|".join(str(context.get(key) or "")
                     for key in ("table_id", "cell_id", "item_id"))
    payload = f"{unit.get('unit_id')}::{canonical}::{target}"
    return "OBL-" + sha256_bytes(payload.encode("utf-8"))[len("sha256:"):][:20]


def shape_mixed_requirement(unit: dict[str, Any],
                            decision: dict[str, Any],
                            *, narrative: str | None = None) -> dict[str, Any]:
    """§8.2 输出形态：B 义务主干 + A 确定性结构约束 + route_provenance。

    ``narrative`` 是 B 轨产出的义务叙述（M4 由 B processor 提供）；缺省时用
    单元原文句段占位（标记 ``narrative_source=unit_text``——绝不冒充 LLM 产出）。
    """
    text = narrative if narrative is not None else str(unit.get("source_text") or "")
    constraints = implementation_constraints(unit, decision)
    return {
        "schema": AUTHORITATIVE_REQUIREMENT_SCHEMA,
        "source_unit_id": str(unit.get("unit_id") or ""),
        "obligation_id": obligation_identity(unit),
        "software_requirement_text": text,
        "implementation_constraints": constraints,
        "route_provenance": {
            "route": str(decision.get("route") or "mixed"),
            "behavior": "b_track",
            "structured_fields": "deterministic_a_join" if constraints else "none",
            "router_version": str(decision.get("router_version") or ""),
            "merge_version": ROUTED_MERGE_VERSION,
            **({"narrative_source": "unit_text"}
               if narrative is None else {"narrative_source": "b_track_processor"}),
        },
        "clause_path": [str(part) for part in unit.get("clause_path") or []],
        "source_block_ids": [str(bid) for bid in unit.get("source_block_ids") or []],
        "source_text_hash": str(unit.get("source_text_hash") or ""),
    }


def dedupe_authoritative(requirements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 obligation_id 去重：每键只保留一条 authoritative，其余降为审计候选。"""
    authoritative: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for requirement in requirements:
        key = str(requirement.get("obligation_id") or "")
        if not key:
            duplicates.append(requirement)
            continue
        if key in authoritative:
            duplicates.append(requirement)
        else:
            authoritative[key] = requirement
    return list(authoritative.values()), duplicates
