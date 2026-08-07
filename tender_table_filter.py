"""招标文件商务/表单表识别过滤器（A9-1）。

默认关闭；开启后，命中表在 table_cell_dispositions.jsonl 标记为 excluded（reason=
tender_commercial_table），并在 claim catalog 中生成可审阅的默认排除候选，不进入
功能聚类/需求候选。
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable

TENDER_TABLE_FILTER_VERSION = "tender-table-filter-v1"
TENDER_COMMERCIAL_REASON = "tender_commercial_table"

# --- 商务/表单信号词表 -----------------------------------------------------------
# 价格/币种/数量/签名栏等栏目标记
_COMMERCIAL_HEADER_WORDS = {
    "price", "prices", "pricing", "amount", "amounts", "total", "totals", "sum",
    "subtotal", "vat", "tax", "currency", "currencies", "usd", "zar", "euro",
    "euros", "gbp", "yen", "rand", "dollar", "dollars", "quantity", "quantities",
    "qty", "unit price", "unit prices", "unit cost", "unit costs", "cost", "costs",
    "bid price", "bid amount", "tender price", "contract price", "lump sum",
    "signature", "signatures", "signed", "sign", "date", "dates", "place",
    "bidder", "bidders", "vendor", "vendors", "supplier", "suppliers", "contractor",
    "contractors", "company", "companies", "firm", "firms", "manufacturer",
    "authorised signatory", "authorized signatory", "witness", "witnesses",
    "page", "pages", "item no", "item number", "line item", "line no", "s/no",
    "serial no", "serial number",
}

# 金额/数量模式（保守：要求含数字 + 单位/币种符号，避免误伤技术参数中的纯数字）
_PRICE_LIKE_RE = re.compile(
    r"(?:^|\s)\d[\d,\s]*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|ZAR|Rand|\$|€|£)"
    r"|(?:^|\s)(?:USD|EUR|GBP|ZAR|Rand|\$|€|£)\s*\d[\d,\s]*(?:\.\d{1,2})?",
    re.IGNORECASE,
)
_QUANTITY_LIKE_RE = re.compile(
    r"\b\d[\d,\s]*\s*(?:pcs|pieces|sets|units|ea|nos|no\.|m\s*\.\s*|km|kg|tons?|meters?|metres?)\b",
    re.IGNORECASE,
)

# 规范性模态词——商务/表单表应缺失
_NORMATIVE_MODAL_RE = re.compile(
    r"\b(?:shall|must|should|required|mandatory)\b|"
    r"(?:应当|必须|不得|应满足|应支持|须符合)",
    re.IGNORECASE,
)

# 技术参数表常见表头词——命中则降低商务判定权重
_TECHNICAL_HEADER_WORDS = {
    "requirement", "requirements", "technical", "characteristic", "characteristics",
    "value", "values", "specification", "specifications", "min", "max", "minimum",
    "maximum", "limit", "rating", "nominal", "tolerance", "range", "unit", "parameter",
    "test", "tests", "standard", "standards", "clause", "clauses", "frequency",
    "voltage", "current", "power", "temperature", "humidity", "accuracy", "class",
    "protection", "ip", "obis", "cosem", "dlms", "sts", "plc", "rf", "dcu",
}


def _normalize(value: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(value or "").strip().lower())


def _header_word_hits(headers: Iterable[str]) -> set[str]:
    hits: set[str] = set()
    for header in headers:
        text = _normalize(header)
        if not text:
            continue
        for word in _COMMERCIAL_HEADER_WORDS:
            if word in text:
                hits.add(word)
    return hits


def _technical_header_hits(headers: Iterable[str]) -> set[str]:
    hits: set[str] = set()
    for header in headers:
        text = _normalize(header)
        if not text:
            continue
        for word in _TECHNICAL_HEADER_WORDS:
            if word in text:
                hits.add(word)
    return hits


def _count_pattern_matches(data_rows: list[list[str]], pattern: re.Pattern[str]) -> int:
    count = 0
    for row in data_rows:
        for cell in row:
            if pattern.search(str(cell or "")):
                count += 1
    return count


def _count_modal_matches(data_rows: list[list[str]]) -> int:
    return _count_pattern_matches(data_rows, _NORMATIVE_MODAL_RE)


def _count_nonempty_cells(data_rows: list[list[str]]) -> int:
    return sum(
        1 for row in data_rows for cell in row if str(cell or "").strip()
    )


def tender_table_filter_enabled() -> bool:
    """A9-1 开关：默认关闭。"""
    value = os.environ.get("RATOMIZER_TENDER_TABLE_FILTER", "0").strip().lower()
    return value not in {"0", "false", "off", ""}


def is_tender_commercial_table(
    *,
    headers: list[str],
    data_rows: list[list[str]],
    section_path: list[str] | None = None,
    table_title: str = "",
) -> bool:
    """确定性识别商务/表单表。

    判据（必须同时满足）：
    1. 表头命中商务信号词（价格/币种/数量/签名栏等）或数据行含显著金额/数量模式；
    2. 全表无规范性模态词（shall/must/required 等）——技术规范表必然含 modal；
    3. 技术参数信号词不占优（避免误伤价格列旁带技术参数的混合表）。

    返回 True 表示该表应归入 tender_commercial_table 受控排除。
    """
    if not data_rows:
        return False

    # 1. 商务信号
    header_hits = _header_word_hits(headers)
    price_matches = _count_pattern_matches(data_rows, _PRICE_LIKE_RE)
    quantity_matches = _count_pattern_matches(data_rows, _QUANTITY_LIKE_RE)
    has_commercial_signal = bool(header_hits) or price_matches >= 2 or quantity_matches >= 3
    if not has_commercial_signal:
        # 标题兜底：明确的价格表/资质表标题
        title = _normalize(table_title)
        if any(word in title for word in {"price", "pricing", "bid form", "tender form",
                                           "qualification", "declaration", "signature"}):
            has_commercial_signal = True
        else:
            return False

    # 2. 无规范性 modal 词
    modal_matches = _count_modal_matches(data_rows)
    if modal_matches > 0:
        return False

    # 3. 技术参数信号不占优
    technical_hits = _technical_header_hits(headers)
    if technical_hits and not header_hits:
        # 只有技术信号、没有商务信号 → 更可能是技术表
        return False

    nonempty = _count_nonempty_cells(data_rows)
    if nonempty == 0:
        return False

    # 金额/数量模式占比足够高，或表头有明确商务词
    if header_hits:
        return True
    commercial_pattern_ratio = (price_matches + quantity_matches) / nonempty
    return commercial_pattern_ratio >= 0.15


def classify_tender_table_kind(
    *,
    headers: list[str],
    data_rows: list[list[str]],
    section_path: list[str] | None = None,
    table_title: str = "",
) -> str | None:
    """返回 tender 表类型，当前仅识别 commercial；未命中返回 None。"""
    if not tender_table_filter_enabled():
        return None
    if is_tender_commercial_table(
        headers=headers,
        data_rows=data_rows,
        section_path=section_path,
        table_title=table_title,
    ):
        return "commercial"
    return None
