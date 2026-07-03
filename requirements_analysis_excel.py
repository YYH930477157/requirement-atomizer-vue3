from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from requirements_analysis_schema import OWNERSHIP_CO_DESIGN, OWNERSHIP_SOFTWARE


HEADERS = [
    "关闭",
    "序号",
    "子模块",
    "描述",
    "需求模版",
    "需求",
    "说明、示例、注意事项",
    "是否客户需求",
    "客户需求章节",
    "驱动/硬件相关",
    "项目负责人确认",
    "测试负责人确认",
    "研发测试确认",
    "功能是否实现",
    "测试用例号",
    "测试是否完成",
]

_SOFTWARE_OWNERSHIPS = {OWNERSHIP_SOFTWARE, OWNERSHIP_CO_DESIGN}
_INVALID_SHEET_TITLE_CHARS = re.compile(r"[\[\]:*?/\\]")


def write_software_requirements_xlsx(items: list[dict[str, Any]], output_path: Path) -> Path:
    output_path = Path(output_path)
    wb = Workbook()
    wb.remove(wb.active)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item.get("ownership") not in _SOFTWARE_OWNERSHIPS:
            continue
        module = str(item.get("module") or "unmapped")
        grouped.setdefault(module, []).append(item)

    if not grouped:
        grouped["软件需求"] = []

    used_titles: set[str] = set()
    for module, rows in grouped.items():
        ws = wb.create_sheet(_unique_sheet_title(module, used_titles))
        ws.append(HEADERS)
        _style_header(ws)
        ws.freeze_panes = "A2"
        for index, item in enumerate(rows, start=1):
            ws.append(_excel_row(index, item))

    wb.save(output_path)
    return output_path


def _excel_row(index: int, item: dict[str, Any]) -> list[Any]:
    source_chapter = str(item.get("source_section") or "").strip()
    if not source_chapter:
        source_chapter = ",".join(str(value) for value in item.get("source_requirement_ids") or [])

    return [
        "",
        index,
        item.get("submodule") or "",
        item.get("description") or "",
        "",
        item.get("software_requirement_text") or item.get("requirement") or "",
        _notes_text(item),
        "是",
        source_chapter,
        "是" if item.get("ownership") == OWNERSHIP_CO_DESIGN else "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]


def _notes_text(item: dict[str, Any]) -> str:
    notes: list[str] = []
    notes.extend(str(value) for value in item.get("developer_guidance") or [])
    source_quote = str(item.get("source_quote") or "").strip()
    if source_quote:
        notes.append(f"原文：{source_quote}")
    notes.extend(f"待确认：{value}" for value in item.get("open_questions") or [])
    return "\n".join(notes)


def _style_header(ws: Any) -> None:
    fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill


def _safe_sheet_title(value: str) -> str:
    title = _INVALID_SHEET_TITLE_CHARS.sub("", value).strip()[:31]
    return title or "软件需求"


def _unique_sheet_title(value: str, used_titles: set[str]) -> str:
    base = _safe_sheet_title(value)
    if base not in used_titles:
        used_titles.add(base)
        return base

    index = 2
    while True:
        suffix = f"~{index}"
        title = f"{base[:31 - len(suffix)]}{suffix}"
        if title not in used_titles:
            used_titles.add(title)
            return title
        index += 1
