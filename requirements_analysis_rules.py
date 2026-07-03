from __future__ import annotations

from typing import Any

from requirements_analysis_schema import (
    OWNERSHIP_CO_DESIGN,
    OWNERSHIP_HARDWARE,
    OWNERSHIP_SOFTWARE,
)

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
)

SEARCH_FIELDS = ("title", "description", "requirement", "module", "source_quote", "labels")


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
    return " ".join(parts).casefold()


def _first_match(text: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        if term.casefold() in text:
            return term
    return None


def _decision(ownership: str, confidence: float, term: str) -> dict[str, Any]:
    return {
        "ownership": ownership,
        "ownership_confidence": confidence,
        "ownership_reason": f"Matched {ownership} rule term: {term}",
        "ownership_source": "rule",
    }
