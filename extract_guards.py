"""抽取护栏层（F3 拆分自 ai_extract）：确定性质量信号，只标不拦。

漏值检测（数值清单没进交付物）、模糊验收检测（"符合要求"式空话）、去重键、文本归一。
"""
from __future__ import annotations

import json
import re
from typing import Any

from cosem_behavior_spec import extract_codes, extract_ints

_LEFT_BEHIND_MIN = 4      # 引句附近 ≥N 个数值没被带走才标（避免零星页码/序号误报）


_LEFT_BEHIND_WINDOW = 800  # 引句起往后看的窗口（枚举清单/成分表通常紧跟引句）


def _values_left_behind(req: dict[str, Any], source: str) -> int:
    """确定性漏值检测：引句附近的数值清单没进需求（真实案例：粉尘粒径/成分百分比全被
    "规定的范围"指代吞掉，threshold_table=None——研发拿不到数值等于没写）。只标记不拦截。"""
    quote = str(req.get("source_quote") or "")
    if not quote:
        return 0
    pos = source.find(quote)
    if pos < 0:
        return 0
    window = source[pos:pos + max(len(quote), _LEFT_BEHIND_WINDOW)]
    captured = extract_ints(" ".join([
        _produced_text(req), json.dumps(req.get("threshold_table") or {}),
    ]))
    left = extract_ints(window) - captured
    return len(left) if len(left) >= _LEFT_BEHIND_MIN else 0


_VAGUE_PHRASES = ("符合要求", "满足要求", "正常工作", "工作正常", "运行正常", "表现良好",
                  "适当", "合理", "正确处理", "妥善处理", "gracefully", "properly",
                  "reasonable", "as expected", "correctly", "appropriately")


_TESTABLE_HINT_RE = re.compile(r"[0-9０-９]|≥|≤|>|<|＝|=|不超过|不少于|不小于|不大于|之内|以内|以上|以下")


def _vague_acceptance(req: dict[str, Any]) -> list[str]:
    """返回不可测的验收条目（命中空话且无任何可判定判据）。只标不拦。"""
    vague: list[str] = []
    for item in (req.get("acceptance_criteria") or []):
        text = str(item)
        low = text.lower()
        if any(p in low for p in _VAGUE_PHRASES) and not _TESTABLE_HINT_RE.search(text) \
                and not extract_codes(text):
            vague.append(text[:80])
    return vague


def _req_key(req: dict[str, Any]) -> str:
    """去重键：source_quote（归一）→ title → description 前 80 字。

    三级回退保证过了护栏的条目（必有 description 或 quote）键恒非空——否则"有描述但
    无引用无标题"的自检补充项会因空键被静默丢弃（与初抽路径不对称）。
    """
    q = re.sub(r"\s+", " ", str(req.get("source_quote") or "")).strip().lower()
    if q:
        return q
    title = str(req.get("title") or "").strip().lower()
    if title:
        return title
    return str(req.get("description") or "").strip().lower()[:80]


def _norm_ws(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _produced_text(requirement: dict[str, Any]) -> str:
    # sub_items 与 threshold_table 此前不在漂移扫描内（2026-07-08 审计 B3/B4）：
    # 参数表被注释为"数值是研发的命根子"却是校验最弱的字段——编造/换算的数值零检测。
    # 纳入后：编造编码走硬拦（draft+拦截注），无据数字走软标（批注视图 suspicion 徽章）。
    sub_texts = " ".join(
        str(s.get("text") or "") for s in requirement.get("sub_items") or [] if isinstance(s, dict))
    table = requirement.get("threshold_table") or {}
    table_cells: list[str] = []
    if isinstance(table, dict):
        table_cells.extend(str(c) for c in table.get("columns") or [])
        for row in table.get("rows") or []:
            table_cells.extend(str(c) for c in (row if isinstance(row, list) else [row]))
    return " ".join([
        str(requirement.get("title") or ""),
        str(requirement.get("description") or ""),
        str(requirement.get("source_quote") or ""),
        " ".join(str(a) for a in requirement.get("acceptance_criteria") or []),
        sub_texts,
        " ".join(table_cells),
    ])


