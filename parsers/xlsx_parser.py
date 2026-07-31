from __future__ import annotations

import logging
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import range_boundaries

from atomize import DocumentProfile, build_table_artifacts, clean_text
from requirement_kb import KnowledgeRepository


LOGGER = logging.getLogger("requirement_atomizer")
MAX_SHEET_ROWS = 50_000


def extract_xlsx(
    input_path: Path,
    knowledge_bases: KnowledgeRepository | None = None,
    document_profile: DocumentProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    del document_profile
    knowledge_bases = knowledge_bases or KnowledgeRepository.from_paths([])
    # read_only=True 时，部分含条件格式/数据校验的 xlsx 不预填 sheet.max_row/max_column
    # （返回 None），导致所有 sheet 被误判为空。改用 read_only=False 保证维度可靠，
    # 且 _merged_fill_values 需要 sheet.cell() 随机访问（read_only 下不可用）。
    workbook = load_workbook(input_path, data_only=True, read_only=False)
    merge_ranges_by_sheet = _merged_ranges_by_sheet(input_path)
    blocks: list[dict[str, Any]] = []
    table_items: list[dict[str, Any]] = []
    table_cell_items: list[dict[str, Any]] = []
    order = 0
    table_count = 0

    try:
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            sheet_merges = merge_ranges_by_sheet.get(sheet.title, [])
            parse_audit: dict[str, Any] = {}
            regions, region_merges, region_headers = _sheet_table_regions(
                sheet, sheet_merges, audit=parse_audit
            )
            if not regions:
                continue

            order += 1
            section_path = [sheet.title]
            blocks.append(
                {
                    "block_id": f"BLK-{order:06d}",
                    "order": order,
                    "type": "heading",
                    "source_format": "xlsx",
                    "heading_level": 1,
                    "text": sheet.title,
                    "section_path": section_path,
                    "domain_tags": [],
                    "kb_matches": [],
                    "requirement_like": False,
                    "noise": False,
                }
            )

            for region_index, region in enumerate(regions):
                min_row, min_col, max_row, max_col = region
                matrix = _region_matrix(sheet, region, region_merges[region_index])
                if not matrix:
                    continue
                order += 1
                table_count += 1
                # 标题识别交给 table_structure（全宽合并证据）；sheet 名作回退标题，
                # 删除"首行一个非空格即标题"硬规则
                table_block, new_table_items, new_cell_items = build_table_artifacts(
                    matrix,
                    table_id=f"TBL-{table_count:06d}",
                    block_id=f"BLK-{order:06d}",
                    order=order,
                    table_title=sheet.title,
                    section_path=section_path,
                    knowledge_bases=knowledge_bases,
                    parse_incomplete=bool(parse_audit.get("parse_incomplete")),
                    parse_incomplete_reason=parse_audit.get("parse_incomplete_reason"),
                    merge_ranges=region_merges[region_index],
                    explicit_header_rows=region_headers[region_index] or None,
                    source_format="xlsx",
                    sheet_name=sheet.title,
                    a1_origin=(min_row, min_col),
                )
                for item in new_table_items:
                    item["source_format"] = "xlsx"
                blocks.append(table_block)
                table_items.extend(new_table_items)
                table_cell_items.extend(new_cell_items)
    finally:
        workbook.close()

    return blocks, table_items, table_cell_items


def _sheet_table_regions(
    sheet: Any,
    merge_ranges: list[tuple[int, int, int, int]],
    *,
    audit: dict[str, Any],
) -> tuple[
    list[tuple[int, int, int, int]],
    list[list[tuple[int, int, int, int]]],
    list[list[int]],
]:
    """同一 sheet 的表区域拆分：优先 Excel Table 定义，否则按非空连通区域。

    返回 (regions, per-region 相对 merge ranges, per-region 显式表头行)。
    区域保留左上角 A1 坐标（非 A1 起始区域不丢溯源）；不再把整张 sheet 强制视作一张表。
    """
    max_row = sheet.max_row or 0
    max_column = sheet.max_column or 0
    if max_row == 0 or max_column == 0:
        return [], [], []
    if max_row > MAX_SHEET_ROWS:
        LOGGER.warning("sheet %s has %s rows; truncating to %s", sheet.title, max_row, MAX_SHEET_ROWS)
        audit["parse_incomplete"] = True
        audit["parse_incomplete_reason"] = {
            "code": "xlsx_row_limit",
            "observed_rows": max_row,
            "parsed_rows": MAX_SHEET_ROWS,
            "limit": MAX_SHEET_ROWS,
        }
        max_row = MAX_SHEET_ROWS

    table_defs = _excel_table_regions(sheet, max_row=max_row)
    if table_defs:
        regions = [entry[0] for entry in table_defs]
        header_rows = [entry[1] for entry in table_defs]
    else:
        regions = _connected_regions(sheet, max_row=max_row, max_column=max_column)
        header_rows = [[] for _ in regions]
    region_merges = [
        _clip_merges_to_region(merge_ranges, region) for region in regions
    ]
    return regions, region_merges, header_rows


def _excel_table_regions(
    sheet: Any, *, max_row: int
) -> list[tuple[tuple[int, int, int, int], list[int]]]:
    """Excel Table（ListObject）定义区域 + 显式表头行（相对区域 1-based）。"""
    tables = getattr(sheet, "tables", None) or {}
    regions: list[tuple[tuple[int, int, int, int], list[int]]] = []
    for table in tables.values():
        ref = getattr(table, "ref", None)
        if not ref:
            continue
        try:
            min_col, min_row, max_col, table_max_row = range_boundaries(str(ref))
        except ValueError:
            continue
        table_max_row = min(table_max_row, max_row)
        if table_max_row < min_row:
            continue
        header_count = getattr(table, "headerRowCount", None)
        if header_count is None:
            header_count = 1
        header_rows = list(range(1, max(0, int(header_count)) + 1))
        regions.append(((min_row, min_col, table_max_row, max_col), header_rows))
    regions.sort(key=lambda entry: (entry[0][0], entry[0][1]))
    return regions


def _connected_regions(
    sheet: Any, *, max_row: int, max_column: int
) -> list[tuple[int, int, int, int]]:
    """无 Excel Table 定义时按非空连通区域拆表（保留区域左上角坐标）。

    八连通：矩阵表的角落孤格（如仅对角相邻的 X marker）仍属同一张表；
    真正分立的表之间至少隔一整行/列空白，不会被粘连。"""
    non_empty: set[tuple[int, int]] = set()
    for row_index, row in enumerate(
        sheet.iter_rows(min_row=1, max_row=max_row, max_col=max_column, values_only=True),
        start=1,
    ):
        for column_index, value in enumerate(row, start=1):
            if value is not None and str(value).strip():
                non_empty.add((row_index, column_index))
    regions: list[tuple[int, int, int, int]] = []
    remaining = set(non_empty)
    while remaining:
        seed = remaining.pop()
        stack = [seed]
        component = {seed}
        while stack:
            row_index, column_index = stack.pop()
            for d_row in (-1, 0, 1):
                for d_col in (-1, 0, 1):
                    if d_row == 0 and d_col == 0:
                        continue
                    neighbor = (row_index + d_row, column_index + d_col)
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        rows = [coord[0] for coord in component]
        columns = [coord[1] for coord in component]
        regions.append((min(rows), min(columns), max(rows), max(columns)))
    regions.sort(key=lambda region: (region[0], region[1]))
    return regions


def _clip_merges_to_region(
    merge_ranges: list[tuple[int, int, int, int]],
    region: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int]]:
    """sheet 级 merge ranges 裁剪进区域并转为区域相对（1-based）坐标。"""
    min_row, min_col, max_row, max_col = region
    clipped: list[tuple[int, int, int, int]] = []
    for merge_min_row, merge_min_col, merge_max_row, merge_max_col in merge_ranges:
        if merge_max_row < min_row or merge_min_row > max_row:
            continue
        if merge_max_col < min_col or merge_min_col > max_col:
            continue
        clipped.append(
            (
                max(merge_min_row, min_row) - min_row + 1,
                max(merge_min_col, min_col) - min_col + 1,
                min(merge_max_row, max_row) - min_row + 1,
                min(merge_max_col, max_col) - min_col + 1,
            )
        )
    return clipped


def _region_matrix(
    sheet: Any,
    region: tuple[int, int, int, int],
    merge_ranges: list[tuple[int, int, int, int]],
) -> list[list[str]]:
    min_row, min_col, max_row, max_col = region
    merged_values = _merged_fill_values(
        sheet,
        [
            (
                min_row + entry[0] - 1,
                min_col + entry[1] - 1,
                min_row + entry[2] - 1,
                min_col + entry[3] - 1,
            )
            for entry in merge_ranges
        ],
        max_row=max_row,
    )
    matrix: list[list[str]] = []
    for row_offset, row in enumerate(
        sheet.iter_rows(
            min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col,
            values_only=True,
        )
    ):
        row_index = min_row + row_offset
        matrix.append(
            [
                clean_text(
                    _stringify_cell_value(
                        merged_values.get((row_index, min_col + column_offset), value)
                    )
                )
                for column_offset, value in enumerate(row)
            ]
        )
    return matrix


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
