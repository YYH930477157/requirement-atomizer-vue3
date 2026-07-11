from __future__ import annotations

import re
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
    "manufacturer",
    "manufactures a device",
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
# 中文无词边界，难以精确分词；务实护栏：当短 CJK 软件词命中时，若上下文出现这些"硬件/部件"
# 修饰词，则视为假朋友、撤销该命中（宁可漏判软件→走默认 software，也不把硬件件误判归类）。
_CJK_HW_CONTEXT_TERMS = ("型号", "芯片", "器件", "物理", "结构", "材质", "规格", "封装", "引脚", "硬件")


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
        normalized_term = term.casefold()
        if _contains_cjk(normalized_term):
            if normalized_term in text and not _is_cjk_false_friend(text, normalized_term):
                return term
            continue
        if _matches_ascii_term(text, normalized_term):
            return term
    return None


def _is_cjk_false_friend(text: str, term: str) -> bool:
    """短 CJK 软件词（≤2 字）若出现在硬件/部件上下文里，判为假朋友（0711 评审）。

    例如 term="时钟" 命中 "时钟计数器型号"、term="事件" 命中 "事件计数器芯片"——
    这些是硬件件描述里的字面词，不是功能域信号。长 CJK 词（≥3 字，如"访问权限"）
    语义已足够明确，不撤。
    """
    if len(term) > 2:
        return False
    return any(hw in text for hw in _CJK_HW_CONTEXT_TERMS)


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
