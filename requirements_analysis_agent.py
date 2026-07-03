import json
import re
from typing import Any


def build_analysis_prompt(requirements: list[dict[str, Any]], vocabulary: dict[str, Any]) -> dict[str, str]:
    system = "你是电表软件需求分析工程师。你的任务不是翻译原文，而是基于可追溯的抽取结果推导软件研发需求。"
    user = "\n".join(
        [
            "请基于需求 JSON 和模板词表 JSON 输出 JSON 数组。",
            "ownership 只能是 `software`、`hardware`、`co_design`。",
            "hardware 需求只做简要说明。",
            "software 需求必须给出输入/触发、处理逻辑、输出/状态变化、验收建议。",
            "co_design 需求的软件侧必须详细说明，硬件依赖只做简要说明。",
            "不能只翻译原文；必须推导可研发、可验收的软件需求。",
            "不能修改数字、OBIS、DLMS class ID、阈值、时间、访问权限。",
            "模板词表 JSON:",
            json.dumps(vocabulary, ensure_ascii=False),
            "需求 JSON:",
            json.dumps(requirements, ensure_ascii=False),
        ]
    )
    return {"system": system, "user": user}


def validate_llm_item(item: dict[str, Any], source: dict[str, Any]) -> list[str]:
    source_text = str(source.get("source_quote") or source.get("description") or source.get("requirement") or "")
    analysis_text = " ".join(
        str(item.get(field, ""))
        for field in ("requirement", "software_requirement_text", "hardware_dependency", "ownership_reason")
    )
    analysis_numbers = set(_numbers(analysis_text))

    issues = []
    for number in _numbers(source_text):
        if number not in analysis_numbers:
            issues.append(f"source number {number} missing from analysis text")
    return issues


def _numbers(text: str) -> list[str]:
    seen = set()
    numbers = []
    for match in re.findall(r"\b\d+(?:\.\d+)?\b", text):
        if match not in seen:
            seen.add(match)
            numbers.append(match)
    return numbers
