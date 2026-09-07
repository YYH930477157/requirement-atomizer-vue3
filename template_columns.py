"""Shared template column contracts and header resolution.

The writer and the A/B gate both inspect the same V2.3.x workbooks.  Keeping
the aliases and fixed-column fallback in one module prevents a template change
from making the producer and verifier disagree about where the requirement
body lives.  The helpers are deliberately dependency-free so they can be used
by CLI tooling and packaging smoke tests alike.
"""
from __future__ import annotations

import re
from typing import Any, Mapping


# Template-wide fixed positions used when a sheet has no complete semantic
# header row.  These are the positions written by template_writer.
WRITER_COLUMN_CONTRACT: dict[str, int] = {
    "module": 3,
    "body": 6,
    "notes": 7,
    "section": 9,
}
REQUIREMENT_SHEET_SIGNATURE = ("序号", "子模块")


# Header aliases used by template_writer.  The writer also emits fields that
# are not needed by the A/B reader; retaining them here keeps its public
# ``_HEADER_ALIASES`` compatibility surface unchanged.
WRITER_HEADER_ALIASES: dict[tuple[str, ...], str] = {
    ("序号",): "seq",
    ("子模块",): "submodule",
    ("描述",): "question",
    ("需求模版", "需求模板"): "template",
    ("需求",): "answer",
    ("说明、示例、注意事项", "说明、示例和注意事项"): "notes",
    ("是否客户需求",): "is_customer",
    ("客户需求章节",): "section",
    ("驱动/硬件相关", "驱动／硬件相关"): "hw",
}


# Header aliases used by final-XLSX quality gates and truth-set tooling.
# Keep the tuple ordering stable: diagnostics display the first few aliases.
XLSX_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "body": ("需求", "需求正文", "需求内容", "需求文本", "需求描述", "软件需求",
             "requirement", "requirement text", "requirement description",
             "software requirement", "software requirement text"),
    "section": ("客户需求章节", "需求章节", "源文章节", "源章节", "章节", "条款",
                "section", "source section", "clause", "chapter"),
    "module": ("模块", "子模块", "功能模块", "module", "submodule", "sub-module",
               "function module"),
    "condition": ("条件", "前置条件", "前提条件", "适用条件", "前提",
                  "condition", "conditions", "precondition", "pre-condition"),
    "acceptance": ("验收标准", "验收准则", "验证标准", "验收",
                   "acceptance", "acceptance criteria", "acceptance criterion",
                   "verification criteria", "verify criteria"),
    "notes": ("说明、示例、注意事项", "说明", "说明示例注意事项", "说明与示例",
              "示例、注意事项", "备注", "notes", "note", "remarks", "remark"),
    "description": ("描述", "问题描述", "description", "problem description"),
}


def normalize_header(value: Any) -> str:
    """Normalize a workbook header using the gate's historical semantics."""
    return re.sub(r"\s+", "", str(value or "").strip().casefold())


def locate_columns(
    header_row: tuple[Any, ...],
    aliases: Mapping[str, tuple[str, ...]] = XLSX_COLUMN_ALIASES,
) -> dict[str, int]:
    """Map logical fields to 1-based columns, taking the first matching cell."""
    normalized_aliases = {
        logical: {normalize_header(alias) for alias in names}
        for logical, names in aliases.items()
    }
    mapping: dict[str, int] = {}
    for column_index, raw in enumerate(header_row, 1):
        header = normalize_header(raw)
        if not header:
            continue
        for logical, accepted in normalized_aliases.items():
            if logical not in mapping and header in accepted:
                mapping[logical] = column_index
                break
    return mapping


def writer_contract_columns(
    header_row: tuple[Any, ...],
    *,
    signature: tuple[str, ...] = REQUIREMENT_SHEET_SIGNATURE,
    contract: Mapping[str, int] = WRITER_COLUMN_CONTRACT,
) -> dict[str, int] | None:
    """Return the fixed writer contract for a signed requirement sheet."""
    headers = {normalize_header(cell) for cell in header_row}
    if not all(normalize_header(cell) in headers for cell in signature):
        return None
    if len(header_row) < contract["body"]:
        return None
    return dict(contract)


def resolve_writer_sheet_columns(header_row: tuple[Any, ...]) -> dict[str, int] | None:
    """Resolve a writer sheet's semantic columns, or return ``None`` to fallback."""
    grouped: dict[str, list[str]] = {}
    for aliases, semantic in WRITER_HEADER_ALIASES.items():
        grouped.setdefault(semantic, []).extend(aliases)
    resolved = locate_columns(header_row, {
        semantic: tuple(headers) for semantic, headers in grouped.items()
    })
    if all(key in resolved for key in ("seq", "submodule", "answer", "notes")):
        return resolved
    return None


__all__ = [
    "REQUIREMENT_SHEET_SIGNATURE", "WRITER_COLUMN_CONTRACT",
    "WRITER_HEADER_ALIASES", "XLSX_COLUMN_ALIASES", "normalize_header",
    "locate_columns", "writer_contract_columns", "resolve_writer_sheet_columns",
]
