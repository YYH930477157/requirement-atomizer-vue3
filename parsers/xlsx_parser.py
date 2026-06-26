from __future__ import annotations

import logging
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from atomize import DocumentProfile, build_table_artifacts, clean_text
from requirement_kb import KnowledgeRepository


LOGGER = logging.getLogger("requirement_atomizer")
MAX_SHEET_ROWS = 50_000


def extract_xlsx(
    input_path: Path,
    knowledge_bases: KnowledgeRepository | None = None,
    document_profile: DocumentProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del document_profile
    knowledge_bases = knowledge_bases or KnowledgeRepository.from_paths([])
    # read_only=True 时，部分含条件格式/数据校验的 xlsx 不预填 sheet.max_row/max_column
    # （返回 None），导致所有 sheet 被误判为空。改用 read_only=False 保证维度可靠，
    # 且 _merged_fill_values 需要 sheet.cell() 随机访问（read_only 下不可用）。
    workbook = load_workbook(input_path, data_only=True, read_only=False)
    merge_ranges_by_sheet = _merged_ranges_by_sheet(input_path)
    blocks: list[dict[str, Any]] = []
    table_items: list[dict[str, Any]] = []
    order = 0
    table_count = 0

    try:
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            matrix = _sheet_matrix(sheet, merge_ranges_by_sheet.get(sheet.title, []))
            if not matrix:
                continue

            order += 1
            section_path = [sheet.title]
            blocks.append(
                {
                    "block_id": f"BLK-{order:06d}",
                    "order": order,
                    "type": "heading",
                    "heading_level": 1,
                    "text": sheet.title,
                    "section_path": section_path,
                    "domain_tags": [],
                    "kb_matches": [],
                    "requirement_like": False,
                    "noise": False,
                }
            )

            table_title = sheet.title
            if _single_cell_title_row(matrix[0]):
                table_title = next(value for value in matrix[0] if value)
                matrix = matrix[1:]
            if not matrix:
                continue

            order += 1
            table_count += 1
            table_block, new_table_items = build_table_artifacts(
                matrix,
                table_id=f"TBL-{table_count:06d}",
                block_id=f"BLK-{order:06d}",
                order=order,
                table_title=table_title,
                section_path=section_path,
                knowledge_bases=knowledge_bases,
            )
            blocks.append(table_block)
            table_items.extend(new_table_items)
    finally:
        workbook.close()

    return blocks, table_items


def _merged_ranges_by_sheet(input_path: Path) -> dict[str, list[tuple[int, int, int, int]]]:
    workbook = load_workbook(input_path, data_only=True, read_only=False)
    try:
        return {
            sheet.title: [
                (cell_range.min_row, cell_range.min_col, cell_range.max_row, cell_range.max_col)
                for cell_range in sheet.merged_cells.ranges
            ]
            for sheet in workbook.worksheets
        }
    finally:
        workbook.close()


def _sheet_matrix(sheet: Any, merge_ranges: list[tuple[int, int, int, int]]) -> list[list[str]]:
    max_row = sheet.max_row or 0
    max_column = sheet.max_column or 0
    if max_row == 0 or max_column == 0:
        return []
    if max_row > MAX_SHEET_ROWS:
        LOGGER.warning("sheet %s has %s rows; truncating to %s", sheet.title, max_row, MAX_SHEET_ROWS)
        max_row = MAX_SHEET_ROWS

    merged_values = _merged_fill_values(sheet, merge_ranges, max_row=max_row)
    matrix: list[list[str]] = []
    for row_index, row in enumerate(
        sheet.iter_rows(min_row=1, max_row=max_row, max_col=max_column, values_only=True),
        start=1,
    ):
        values = [
            clean_text(_stringify_cell_value(merged_values.get((row_index, column_index), value)))
            for column_index, value in enumerate(row, start=1)
        ]
        matrix.append(values)

    return _trim_empty_edges(matrix)


def _merged_fill_values(
    sheet: Any,
    merge_ranges: list[tuple[int, int, int, int]],
    *,
    max_row: int,
) -> dict[tuple[int, int], Any]:
    values: dict[tuple[int, int], Any] = {}
    for min_row, min_col, range_max_row, max_col in merge_ranges:
        if min_row > max_row:
            continue
        top_left = sheet.cell(row=min_row, column=min_col).value
        for row_index in range(min_row, min(range_max_row, max_row) + 1):
            for column_index in range(min_col, max_col + 1):
                values[(row_index, column_index)] = top_left
    return values


def _trim_empty_edges(matrix: list[list[str]]) -> list[list[str]]:
    while matrix and not any(matrix[-1]):
        matrix.pop()
    while matrix and not any(matrix[0]):
        matrix.pop(0)
    if not matrix:
        return []

    last_non_empty_column = -1
    for row in matrix:
        for index, value in enumerate(row):
            if value:
                last_non_empty_column = max(last_non_empty_column, index)
    if last_non_empty_column < 0:
        return []
    return [row[: last_non_empty_column + 1] for row in matrix]


def _single_cell_title_row(row: list[str]) -> bool:
    return sum(1 for value in row if value) == 1


def _stringify_cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if value.time() == time.min:
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return str(int(value))
    return str(value)
