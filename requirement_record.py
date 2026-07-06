"""ai_requirements 行契约 + 产物血统戳（架构债 F2）。

行结构此前是口头契约——7 个消费者各自防御式 `.get()`，映射器 ai_req_id 缺失 bug 即此类。
本模块是**单源**：写入端逐行校验（问题只警告不丢行——校验器保护的是消费者预期，不是拦截器）；
消费端引用字段名从这里 import。

产物血统：所有 JSON 产物盖 `provenance` 块（producer/version/generated_at）——"拿 v9 旧数据
当新结果看"的事故（2026-07-06 实况）从此产物本体可自证；消费端版本不匹配时警告。
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

LOGGER = logging.getLogger("requirement_atomizer")

# 必在键（可为空值，但键必须存在——消费者可安全 [] 取）
REQUIRED_KEYS = (
    "title", "description", "type", "priority", "module", "labels",
    "source_quote", "source_section", "source_block_ids",
    "acceptance_criteria", "dev_guidance", "notes", "status",
)
_LIST_KEYS = ("labels", "source_block_ids", "acceptance_criteria", "dev_guidance")
_STR_KEYS = ("title", "description", "type", "priority", "module",
             "source_quote", "source_section", "notes", "status")


def validate_requirement_row(row: dict[str, Any]) -> list[str]:
    """返回契约问题清单；空=合格。只校验形状，不校验业务。"""
    problems: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in row:
            problems.append(f"缺键 {key}")
    for key in _LIST_KEYS:
        if key in row and not isinstance(row[key], list):
            problems.append(f"{key} 应为 list，得到 {type(row[key]).__name__}")
    for key in _STR_KEYS:
        if key in row and not isinstance(row[key], str):
            problems.append(f"{key} 应为 str，得到 {type(row[key]).__name__}")
    tt = row.get("threshold_table")
    if tt is not None and not isinstance(tt, dict):
        problems.append("threshold_table 应为 dict|None")
    subs = row.get("sub_items")
    if subs is not None:
        if not isinstance(subs, list) or any(not isinstance(x, dict) for x in subs):
            problems.append("sub_items 应为 dict 列表")
    return problems


def validate_rows(rows: list[dict[str, Any]], *, where: str) -> int:
    """批量校验并警告（不拦截）。返回问题行数。"""
    bad = 0
    for i, row in enumerate(rows):
        problems = validate_requirement_row(row)
        if problems:
            bad += 1
            LOGGER.warning("需求行契约告警 %s#%d（%s）: %s",
                           where, i, str(row.get("title") or "")[:30], "; ".join(problems[:4]))
    return bad


def provenance(producer: str, version: str) -> dict[str, str]:
    """产物血统戳：写进每个 JSON 产物顶层的 `provenance` 键。"""
    return {"producer": producer, "producer_version": version,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds")}


def check_provenance(payload: dict[str, Any], *, expect_producer: str,
                     current_version: str) -> str:
    """消费端校验：产物由旧版生成 → 返回人话警告（空串=没问题/无戳的老产物）。"""
    prov = payload.get("provenance")
    if not isinstance(prov, dict):
        return ""   # 老产物没戳，不惊扰
    version = str(prov.get("producer_version") or "")
    if prov.get("producer") == expect_producer and version and version != current_version:
        return (f"上游产物由 {expect_producer} {version} 生成（当前 {current_version}），"
                f"建议重跑上游后再消费")
    return ""
