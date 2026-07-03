from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


DEFAULT_MODULES = (
    "系统需求",
    "计量需求",
    "时钟需求",
    "费率需求",
    "显示需求",
    "需量需求",
    "结算需求",
    "负荷曲线",
    "报警窃电需求",
    "电网质量需求",
    "升级需求",
    "负控需求",
    "状态字需求",
    "事件需求",
    "协议栈需求",
    "push需求",
    "P1需求",
    "MBUS需求",
    "预付费需求",
)

_SKIPPED_SHEET_TITLES = {
    "需求模版Release notes",
    "原始需求对应表",
    "需求变更管理",
}


def fallback_template_vocabulary() -> dict[str, Any]:
    modules = list(DEFAULT_MODULES)
    return {
        "modules": modules,
        "submodules_by_module": {module: [] for module in modules},
    }


def extract_template_vocabulary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return fallback_template_vocabulary()

    workbook = load_workbook(path, data_only=True, read_only=True)
    modules: list[str] = []
    submodules_by_module: dict[str, list[str]] = {}

    try:
        for worksheet in workbook.worksheets:
            module = worksheet.title.strip()
            if not module or module.endswith("列表") or module in _SKIPPED_SHEET_TITLES:
                continue

            modules.append(module)
            submodules_by_module[module] = _extract_submodules(worksheet)
    finally:
        workbook.close()

    return {
        "modules": modules,
        "submodules_by_module": submodules_by_module,
    }


def _extract_submodules(worksheet: Worksheet) -> list[str]:
    header_column: int | None = None
    header_row: int | None = None

    for row_number, row in enumerate(
        worksheet.iter_rows(min_row=1, max_row=5, values_only=True),
        start=1,
    ):
        for column_index, cell_value in enumerate(row):
            if _normalize_cell_value(cell_value) == "子模块":
                header_column = column_index
                header_row = row_number
                break
        if header_column is not None:
            break

    if header_column is None or header_row is None:
        return []

    submodules: list[str] = []
    seen: set[str] = set()
    for row in worksheet.iter_rows(min_row=header_row + 1, values_only=True):
        if header_column >= len(row):
            continue
        value = _normalize_cell_value(row[header_column])
        if not value or value in seen:
            continue
        seen.add(value)
        submodules.append(value)

    return submodules


def _normalize_cell_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
