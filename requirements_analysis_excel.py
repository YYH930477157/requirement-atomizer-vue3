from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from requirements_analysis_schema import OWNERSHIP_CO_DESIGN, OWNERSHIP_SOFTWARE
from text_normalize import formula_safe


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
# openpyxl 会对控制字符抛 IllegalCharacterError（PDF 文本层常带 \x0b 等）——写入前剥离
_ILLEGAL_XLSX_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _safe_cell(value: Any) -> Any:
    """单元格防护：控制字符剥离 + 公式注入中和（formula_safe，与 spec_excel 同一纪律）。

    没有这层，'=HYPERLINK(...)' 开头的抽取文本会以活公式落进交付给研发的工作簿——
    这是 spec-data-integrity 阶段修掉的同类漏洞，此处必须同样设防。
    """
    if isinstance(value, str):
        value = _ILLEGAL_XLSX_CHARS.sub("", value)
    return formula_safe(value)


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
            ws.append([_safe_cell(value) for value in _excel_row(index, item)])

    from xlsx_io import safe_save_workbook
    return safe_save_workbook(wb, output_path)
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
    objective = str(item.get("objective") or "").strip()
    if objective:
        notes.append(f"功能目标：{objective}")
    notes.extend(f"功能行为：{value}" for value in item.get("behaviors") or [])
    role_labels = {
        "configure": "配置", "detect": "检测/触发", "execute": "执行/控制",
        "store": "存储/归档", "query": "查询/读取", "report": "上报/传输",
        "access": "权限/访问", "recover": "恢复/重试", "behavior": "其它行为",
    }
    for entry in item.get("lifecycle_behaviors") or []:
        if isinstance(entry, dict):
            role = role_labels.get(str(entry.get("role") or "behavior"), str(entry.get("role") or "其它行为"))
            behavior = str(entry.get("behavior") or "").strip()
            if behavior:
                notes.append(f"生命周期-{role}：{behavior}")
    source_modules = [str(value).strip() for value in item.get("source_modules") or [] if str(value).strip()]
    if len(source_modules) > 1:
        notes.append("跨模块来源：" + "、".join(source_modules))
    notes.extend(f"前置条件：{value}" for value in item.get("preconditions") or [])
    notes.extend(f"数据约束：{value}" for value in item.get("data_constraints") or [])
    for variant in item.get("variants") or []:
        if isinstance(variant, dict):
            name = str(variant.get("name") or "变体").strip()
            behavior = str(variant.get("behavior") or "").strip()
            notes.append(f"功能变体 {name}：{behavior}" if behavior else f"功能变体：{name}")
    notes.extend(f"异常处理：{value}" for value in item.get("exceptions") or [])
    related = [str(value).strip() for value in item.get("related_dlms_objects") or [] if str(value).strip()]
    if related:
        notes.append("关联 DLMS 对象：" + "、".join(related))
    notes.extend(f"待澄清冲突：{value}" for value in item.get("conflict_flags") or [])
    # 富化软标随交付物同行：编造数字/遗漏漂移必须在研发看的列里可见（2026-07-08 审计 B1）
    notes.extend(f"⚠ 富化待核：{value}" for value in item.get("enrichment_warnings") or [])
    # 参数表优先（数值是研发的命根子：粒径/成分/限值清单必须出现在交付物里，不能只留在中间产物）
    table = item.get("threshold_table")
    if isinstance(table, dict) and table.get("rows"):
        columns = [str(c) for c in table.get("columns") or []]
        if columns:
            notes.append("参数表：" + " | ".join(columns))
        for row in table.get("rows") or []:
            notes.append("  " + " | ".join(str(cell) for cell in (row if isinstance(row, list) else [row])))
    notes.extend(str(value) for value in item.get("developer_guidance") or [])
    notes.extend(f"设计候选（非规范约束）：{value}" for value in item.get("design_options") or [])
    notes.extend(f"假设：{value}" for value in item.get("assumptions") or [])
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
    title_key = base.casefold()
    if title_key not in used_titles:
        used_titles.add(title_key)
        return base

    index = 2
    while True:
        suffix = f"~{index}"
        title = f"{base[:31 - len(suffix)]}{suffix}"
        title_key = title.casefold()
        if title_key not in used_titles:
            used_titles.add(title_key)
            return title
        index += 1
