"""Faithful DOCX table-grid parsing before semantic table classification.

This module intentionally knows nothing about requirement roles. It restores the
OOXML grid, canonical merge anchors, direct cell paragraphs, nested tables, and
style evidence so ``table_structure`` can make deterministic decisions later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph


DOCX_TABLE_PHYSICAL_VERSION = "docx-table-physical-v1"


@dataclass(frozen=True)
class ParsedParagraph:
    text: str
    style_name: str
    list_level: int | None
    manual_break_count: int


@dataclass(frozen=True)
class ParsedCellContent:
    paragraphs: tuple[ParsedParagraph, ...]
    nested_table_count: int


@dataclass
class ParsedCell:
    row_index: int
    column_index: int
    text: str
    raw_text: str
    row_span: int = 1
    column_span: int = 1
    covered_coordinates: tuple[tuple[int, int], ...] = ()
    content: ParsedCellContent = field(
        default_factory=lambda: ParsedCellContent((), 0)
    )
    style_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NestedTableRef:
    parent_coordinate: tuple[int, int]
    ordinal: int
    table: "ParsedDocxTable"


@dataclass
class ParsedDocxTable:
    width: int
    matrix: list[list[str]]
    raw_matrix: list[list[str]]
    cells: dict[tuple[int, int], ParsedCell]
    merge_ranges: list[tuple[int, int, int, int]]
    explicit_header_rows: list[int]
    nested_tables: list[NestedTableRef]
    parse_incomplete: bool
    parse_incomplete_reason: dict[str, Any]
    raw_text: str
    version: str = DOCX_TABLE_PHYSICAL_VERSION


def _integer_child(parent: Any, tag: str, default: int = 0) -> int:
    if parent is None:
        return default
    node = parent.find(qn(tag))
    if node is None:
        return default
    try:
        return max(0, int(node.get(qn("w:val")) or default))
    except (TypeError, ValueError):
        return default


def _span_and_vmerge(tc: Any) -> tuple[int, str | None]:
    tc_pr = tc.tcPr
    span = max(1, _integer_child(tc_pr, "w:gridSpan", 1))
    if tc_pr is None:
        return span, None
    node = tc_pr.find(qn("w:vMerge"))
    if node is None:
        return span, None
    return span, str(node.get(qn("w:val")) or "continue")


def _paragraph_list_level(paragraph: Paragraph) -> int | None:
    p_pr = paragraph._p.pPr
    num_pr = p_pr.numPr if p_pr is not None else None
    if num_pr is not None:
        ilvl = num_pr.ilvl
        if ilvl is None or ilvl.val is None:
            return 0
        try:
            return int(ilvl.val)
        except (TypeError, ValueError):
            return 0
    style_name = paragraph.style.name if paragraph.style is not None else ""
    if style_name.lower().startswith("list"):
        return 0
    return None


def _normalize_paragraph_text(value: str) -> str:
    lines = []
    for line in str(value or "").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[\t\f\v ]+", " ", line).strip()
        lines.append(cleaned)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _cell_style_evidence(tc: Any, paragraphs: list[Paragraph]) -> dict[str, Any]:
    tc_pr = tc.tcPr
    shading = ""
    borders = False
    vertical_alignment = ""
    if tc_pr is not None:
        shd = tc_pr.find(qn("w:shd"))
        if shd is not None:
            shading = str(shd.get(qn("w:fill")) or "")
        borders = tc_pr.find(qn("w:tcBorders")) is not None
        valign = tc_pr.find(qn("w:vAlign"))
        if valign is not None:
            vertical_alignment = str(valign.get(qn("w:val")) or "")
    alignments = sorted({
        str(paragraph.alignment)
        for paragraph in paragraphs
        if paragraph.alignment is not None
    })
    return {
        "bold": any(run.bold is True for paragraph in paragraphs for run in paragraph.runs),
        "shading": shading,
        "borders": borders,
        "paragraph_alignments": alignments,
        "vertical_alignment": vertical_alignment,
    }


def _parse_cell_content(tc: Any, parent_table: Table) -> tuple[
    ParsedCellContent, str, str, list[ParsedDocxTable]
]:
    cell_parent = _Cell(tc, parent_table)
    parsed_paragraphs: list[ParsedParagraph] = []
    paragraph_objects: list[Paragraph] = []
    nested_tables: list[ParsedDocxTable] = []
    raw_parts: list[str] = []
    normalized_parts: list[str] = []
    for child in tc.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, cell_parent)
            paragraph_objects.append(paragraph)
            raw = str(paragraph.text or "")
            normalized = _normalize_paragraph_text(raw)
            parsed_paragraphs.append(ParsedParagraph(
                text=normalized,
                style_name=paragraph.style.name if paragraph.style is not None else "",
                list_level=_paragraph_list_level(paragraph),
                manual_break_count=raw.count("\n"),
            ))
            if raw:
                raw_parts.append(raw)
            if normalized:
                normalized_parts.append(normalized)
        elif isinstance(child, CT_Tbl):
            nested_tables.append(parse_docx_table(Table(child, cell_parent)))
    content = ParsedCellContent(
        paragraphs=tuple(parsed_paragraphs),
        nested_table_count=len(nested_tables),
    )
    return (
        content,
        "\n".join(normalized_parts),
        "\n".join(raw_parts),
        nested_tables,
    )


def _declared_grid_width(table: Table) -> int:
    grid = table._tbl.tblGrid
    if grid is None:
        return 0
    return len(grid.gridCol_lst)


def parse_docx_table(table: Table) -> ParsedDocxTable:
    """Restore a DOCX table's physical grid without semantic role guesses."""
    declared_width = _declared_grid_width(table)
    rows_payload: list[dict[int, tuple[str, str]]] = []
    cells: dict[tuple[int, int], ParsedCell] = {}
    explicit_header_rows: list[int] = []
    nested_refs: list[NestedTableRef] = []
    merge_ranges: list[tuple[int, int, int, int]] = []
    active_by_column: dict[int, tuple[int, int]] = {}
    active_state: dict[tuple[int, int], dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    observed_width = 0

    def close_anchor(key: tuple[int, int]) -> None:
        state = active_state.pop(key, None)
        if state is None:
            return
        for column in state["columns"]:
            if active_by_column.get(column) == key:
                active_by_column.pop(column, None)
        start_row, start_column = key
        end_row = int(state["last_row"])
        end_column = start_column + int(state["column_span"]) - 1
        anchor = cells.get(key)
        if anchor is not None:
            anchor.row_span = end_row - start_row + 1
            covered = [
                (row, column)
                for row in range(start_row, end_row + 1)
                for column in range(start_column, end_column + 1)
                if (row, column) != key
            ]
            anchor.covered_coordinates = tuple(covered)
        if end_row > start_row or end_column > start_column:
            merge_ranges.append((start_row, start_column, end_row, end_column))

    for row_index, tr in enumerate(table._tbl.tr_lst, start=1):
        tr_pr = tr.trPr
        if tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None:
            explicit_header_rows.append(row_index)
        grid_before = _integer_child(tr_pr, "w:gridBefore", 0)
        grid_after = _integer_child(tr_pr, "w:gridAfter", 0)
        cursor = 1 + grid_before
        row_values: dict[int, tuple[str, str]] = {}
        continued: set[tuple[int, int]] = set()

        for tc in tr.tc_lst:
            column_span, vmerge = _span_and_vmerge(tc)
            columns = set(range(cursor, cursor + column_span))
            content, text, raw_text, nested_tables = _parse_cell_content(tc, table)
            if vmerge == "continue":
                keys = {active_by_column.get(column) for column in columns}
                if None in keys or len(keys) != 1:
                    issues.append({
                        "code": "merge_conflict",
                        "row_index": row_index,
                        "column_index": cursor,
                        "detail": "vertical continuation lacks one canonical anchor",
                    })
                    key = (row_index, cursor)
                    cells[key] = ParsedCell(
                        row_index=row_index,
                        column_index=cursor,
                        text=text,
                        raw_text=raw_text,
                        column_span=column_span,
                        content=content,
                        style_evidence={},
                    )
                    row_values[cursor] = (text, raw_text)
                else:
                    key = next(iter(keys))
                    state = active_state[key]
                    state["last_row"] = row_index
                    continued.add(key)
                    if text and text != cells[key].text:
                        issues.append({
                            "code": "merge_text_conflict",
                            "row_index": row_index,
                            "column_index": cursor,
                            "text": text,
                        })
            else:
                overlapping = {
                    active_by_column[column]
                    for column in columns
                    if column in active_by_column
                }
                for key in overlapping:
                    close_anchor(key)
                key = (row_index, cursor)
                paragraph_objects = [
                    Paragraph(child, _Cell(tc, table))
                    for child in tc.iterchildren()
                    if isinstance(child, CT_P)
                ]
                cells[key] = ParsedCell(
                    row_index=row_index,
                    column_index=cursor,
                    text=text,
                    raw_text=raw_text,
                    column_span=column_span,
                    covered_coordinates=tuple(
                        (row_index, column)
                        for column in range(cursor + 1, cursor + column_span)
                    ),
                    content=content,
                    style_evidence=_cell_style_evidence(tc, paragraph_objects),
                )
                row_values[cursor] = (text, raw_text)
                for ordinal, nested_table in enumerate(nested_tables, start=1):
                    nested_refs.append(NestedTableRef(key, ordinal, nested_table))
                if vmerge == "restart":
                    state = {
                        "last_row": row_index,
                        "column_span": column_span,
                        "columns": columns,
                    }
                    active_state[key] = state
                    for column in columns:
                        active_by_column[column] = key
                elif column_span > 1:
                    merge_ranges.append(
                        (row_index, cursor, row_index, cursor + column_span - 1)
                    )
            cursor += column_span

        row_width = cursor - 1 + grid_after
        observed_width = max(observed_width, row_width)
        if declared_width and row_width != declared_width:
            issues.append({
                "code": "row_width_conflict",
                "row_index": row_index,
                "declared_width": declared_width,
                "observed_width": row_width,
            })
        for key in list(active_state):
            if key not in continued and key[0] < row_index:
                close_anchor(key)
        rows_payload.append(row_values)

    for key in list(active_state):
        close_anchor(key)

    width = declared_width or observed_width
    if observed_width > width:
        width = observed_width
    matrix: list[list[str]] = []
    raw_matrix: list[list[str]] = []
    for row_values in rows_payload:
        normalized_row = [""] * width
        raw_row = [""] * width
        for column, (text, raw_text) in row_values.items():
            if 1 <= column <= width:
                normalized_row[column - 1] = text
                raw_row[column - 1] = raw_text
        matrix.append(normalized_row)
        raw_matrix.append(raw_row)

    ordered_ranges = sorted(set(merge_ranges))
    raw_text = "\n".join(
        value
        for row in raw_matrix
        for value in row
        if value
    )
    primary_issue = issues[0] if issues else {}
    reason = dict(primary_issue)
    if issues:
        reason["issues"] = issues
        reason["version"] = DOCX_TABLE_PHYSICAL_VERSION
    # 嵌套表序号按表级全局唯一分配（2026-08-05 Kimi 高危 #2）：原 ordinal 由各单元格
    # enumerate(..., start=1) 产生——两个单元格各含一个嵌套表会都得 N001，atomize 据此
    # 生成 {table_id}-N001 嵌套表 ID 与其 cell ID 全部碰撞，conservation 审计 hard-fail
    # 致整次 atomize 失败。按文档序（行/列遍历顺序）统一重编号，确保 N001/N002/... 唯一。
    nested_refs = [
        NestedTableRef(ref.parent_coordinate, ordinal, ref.table)
        for ordinal, ref in enumerate(nested_refs, start=1)
    ]
    return ParsedDocxTable(
        width=width,
        matrix=matrix,
        raw_matrix=raw_matrix,
        cells=cells,
        merge_ranges=ordered_ranges,
        explicit_header_rows=explicit_header_rows,
        nested_tables=nested_refs,
        parse_incomplete=bool(issues),
        parse_incomplete_reason=reason,
        raw_text=raw_text,
    )
