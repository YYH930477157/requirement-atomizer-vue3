"""抽取单元层（F3 拆分自 ai_extract）：块→章节→LLM 输入单元的全部确定性机器。

职责：TOC 行清洗、章节聚合、条款族/整章切分、试抽采样、跨条款/附录引用解析、
术语条目收集与定向挂载。零 LLM、零外部状态——独立可测。
"""
from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

DEFAULT_MERGE_CHARS = 2800

_TOC_LINE_END_RE = re.compile(r"\.{5,}[\s\d]*$")


_TOC_LEADER_RUN_RE = re.compile(r"\.{5,}")


def _is_toc_line(line: str) -> bool:
    if _TOC_LINE_END_RE.search(line):
        return True
    return len(_TOC_LEADER_RUN_RE.findall(line)) >= 3


def clean_block_text(block: dict[str, Any]) -> str:
    """block 文本去目录点线行；清完为空 = 纯目录块，各消费处按无内容处理。"""
    text = str(block.get("text") or "")
    lines = [line for line in text.splitlines() if not _is_toc_line(line)]
    return "\n".join(lines).strip()


# 抽取排除区：封面/印刷目录——目录条目形似需求路径,进 LLM 会抽出空壳需求
# （真实案例 EN 16314：11 条引用=目录路径、锚点兜底挂封面）。preface/introduction
# 保留（可含背景约束）；缺 doc_region 的块视为 body（旧产物/测试夹具兼容）。
_EXTRACT_EXCLUDED_REGIONS = ("front_matter", "table_of_contents")


def body_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [b for b in blocks
            if str(b.get("doc_region") or "body") not in _EXTRACT_EXCLUDED_REGIONS]


def assemble_sections(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]] | None = None,
    table_cell_items: list[dict[str, Any]] | None = None,
    table_cell_dispositions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """把已解析 blocks 按 section_path 聚合成章节单元（章节文本 + 溯源 block）。

    table-structure-v2 起消费真实 table_items/table_cell_items（权威 row/cell ID），
    不再自行拼 item ID；旧调用（None）退回兼容合成（行号含表头/标题偏移修复）。"""
    try:  # 延迟 import,避免与 ai_extract 的顶层 import 形成循环
        from ai_extract import _PARAM_ROW_MIN_CELLS, _row_render_line, classify_table_kind
    except ImportError:  # pragma: no cover - ai_extract 始终在场
        classify_table_kind = None
        _row_render_line = None
        _PARAM_ROW_MIN_CELLS = 2
    items_by_block: dict[str, list[dict[str, Any]]] = {}
    for item in table_items or []:
        items_by_block.setdefault(str(item.get("table_block_id") or ""), []).append(item)
    cells_by_block: dict[str, list[dict[str, Any]]] = {}
    for cell in table_cell_items or []:
        cells_by_block.setdefault(str(cell.get("table_block_id") or ""), []).append(cell)
    dispositions_by_cell = {
        str(row.get("cell_id") or ""): row
        for row in table_cell_dispositions or []
        if str(row.get("cell_id") or "")
    }
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for block in blocks:
        section_path = [str(s) for s in (block.get("section_path") or [])]
        key = " / ".join(section_path) or "(root)"
        unit = groups.get(key)
        if unit is None:
            unit = {"section_id": key, "section_path": section_path,
                    "heading": section_path[-1] if section_path else "",
                    "texts": [], "block_ids": []}
            groups[key] = unit
        text = clean_block_text(block)
        is_table = str(block.get("type") or "") == "table"
        if text and not is_table:
            unit["texts"].append(text)
        if block.get("block_id"):
            unit["block_ids"].append(block["block_id"])
            # section_path/noise 必须随行（guards-v12/v15）：fallback 收窄按需求所属小节
            # 过滤 span、匹配器按噪声排除——缺字段时两条规则都静默失效
            if is_table:
                table_sources = []
                for table_block in _iter_table_blocks(block):
                    source = _structured_table_source(
                        table_block,
                        block_id=str(block["block_id"]),
                        block_items=items_by_block.get(str(block["block_id"]), []),
                        block_cells=cells_by_block.get(str(block["block_id"]), []),
                        dispositions_by_cell=dispositions_by_cell,
                        classify_table_kind=classify_table_kind,
                        row_render_line=_row_render_line,
                        param_row_min_cells=_PARAM_ROW_MIN_CELLS,
                    )
                    if source is None:
                        continue
                    table_sources.append(source)
                    if source["text"]:
                        unit["texts"].append(source["text"])
                    if source.get("header_line"):
                        unit.setdefault("_table_header_lines", []).append(source["header_line"])
                    unit.setdefault("source_blocks", []).append(source["source_block"])
                if table_sources:
                    unit["table_input_mode"] = "structured_leaves"
            else:
                unit.setdefault("source_blocks", []).append({
                    "block_id": block["block_id"],
                    "text": text,
                    "section_path": list(block.get("section_path") or []),
                    "noise": bool(block.get("noise")),
                })

    sections: list[dict[str, Any]] = []
    for unit in groups.values():
        body = "\n".join(unit["texts"]).strip()
        if not body:
            continue
        sections.append({"section_id": unit["section_id"], "section_path": unit["section_path"],
                         "heading": unit["heading"], "text": body, "block_ids": unit["block_ids"],
                         "source_blocks": unit.get("source_blocks", []),
                         "_table_header_lines": unit.get("_table_header_lines", []),
                         "table_input_mode": unit.get("table_input_mode", "plain_text")})
    return sections


def _iter_table_blocks(block: dict[str, Any]):
    yield block
    for nested in block.get("nested_tables") or []:
        if isinstance(nested, dict):
            yield from _iter_table_blocks(nested)


def _structured_table_source(
    block: dict[str, Any],
    *,
    block_id: str,
    block_items: list[dict[str, Any]],
    block_cells: list[dict[str, Any]],
    dispositions_by_cell: dict[str, dict[str, Any]],
    classify_table_kind,
    row_render_line,
    param_row_min_cells: int,
) -> dict[str, Any] | None:
    """Build addressable table leaves; flattened ``block.text`` is audit-only."""
    from table_structure import cell_context_text, physical_data_row_indexes

    table_id = str(block.get("table_id") or block_id)
    table_kind = classify_table_kind(block) if classify_table_kind is not None else ""
    headers = [str(value or "") for value in (block.get("headers") or [])]
    title = str(block.get("table_title") or table_id)
    context_header_line = (
        f"[TABLE_CONTEXT table_id={table_id} kind={table_kind or 'other'} "
        f"title={title}] headers={' | '.join(headers)}"
    )
    repeat_header_line = " | ".join(headers) if table_kind == "parameter" else ""
    table_items = [
        row for row in block_items if str(row.get("table_id") or "") == table_id
    ]
    table_cells = [
        row for row in block_cells if str(row.get("table_id") or "") == table_id
    ]
    cells_by_row: dict[int, list[dict[str, Any]]] = {}
    for cell in table_cells:
        cells_by_row.setdefault(int(cell.get("row_index") or 0), []).append(cell)

    row_entries: list[dict[str, Any]] = []
    data_rows = list(block.get("data_rows") or [])
    physical_rows = physical_data_row_indexes(block)
    data_position = {row_index: pos for pos, row_index in enumerate(physical_rows, start=1)}
    if table_items:
        for item in sorted(table_items, key=lambda row: int(row.get("row_index") or 0)):
            if str(item.get("leaf_role") or "row") != "row":
                continue
            row_index = int(item.get("row_index") or 0)
            position = data_position.get(row_index)
            row = data_rows[position - 1] if position and position - 1 < len(data_rows) else []
            values = [str(value or "").strip() for value in row]
            non_empty = [value for value in values if value]
            if len(non_empty) < param_row_min_cells and not any(
                _is_normative_cell(value) for value in non_empty
            ):
                continue
            if _is_group_header_evidence(block, item, non_empty):
                continue
            source_text = row_render_line(headers, row) if row_render_line else str(item.get("text") or "")
            owned_cells = [
                cell for cell in cells_by_row.get(row_index, [])
                if _cell_is_extractable(cell, dispositions_by_cell)
                and str(cell.get("leaf_kind") or "") == "row"
            ]
            cell_ids = [str(cell.get("cell_id") or "") for cell in owned_cells]
            extraction_text = (
                f"[TABLE_LEAF kind=row table_id={table_id} item_id={item.get('item_id') or ''} "
                f"cell_ids={','.join(cell_ids)}] {title} | {' | '.join(headers)} | {source_text}"
            )
            row_entries.append({
                "row_index": row_index,
                "item_id": str(item.get("item_id") or ""),
                "cell_ids": cell_ids,
                "text": extraction_text,
                "source_text": source_text,
                "extraction_text": extraction_text,
            })
    elif table_kind == "parameter" and row_render_line is not None:
        for offset, row in enumerate(data_rows, start=1):
            values = [str(value or "").strip() for value in row]
            non_empty = [value for value in values if value]
            if len(non_empty) < param_row_min_cells or len(set(non_empty)) == 1:
                continue
            row_index = physical_rows[offset - 1] if offset - 1 < len(physical_rows) else offset
            item_id = f"{table_id}-R{row_index:06d}"
            source_text = row_render_line(headers, row)
            extraction_text = (
                f"[TABLE_LEAF kind=row table_id={table_id} item_id={item_id} cell_ids=] "
                f"{title} | {' | '.join(headers)} | {source_text}"
            )
            row_entries.append({
                "row_index": row_index,
                "item_id": item_id,
                "cell_ids": [],
                "text": extraction_text,
                "source_text": source_text,
                "extraction_text": extraction_text,
            })

    cell_entries: list[dict[str, Any]] = []
    for cell in sorted(
        table_cells,
        key=lambda row: (int(row.get("row_index") or 0), int(row.get("column_index") or 0)),
    ):
        if str(cell.get("leaf_kind") or "") != "cell":
            continue
        if not _cell_is_extractable(cell, dispositions_by_cell):
            continue
        context_text = cell_context_text(cell)
        cell_id = str(cell.get("cell_id") or "")
        disposition = dispositions_by_cell.get(cell_id) or {}
        extraction_text = (
            f"[TABLE_LEAF kind=cell table_id={table_id} cell_id={cell_id} "
            f"disposition={disposition.get('disposition') or 'target'}] {context_text}"
        )
        cell_entries.append({
            "cell_id": cell_id,
            "row_index": int(cell.get("row_index") or 0),
            "column_index": int(cell.get("column_index") or 0),
            "text": extraction_text,
            "source_text": str(cell.get("text") or ""),
            "extraction_text": extraction_text,
        })

    leaf_lines = [entry["extraction_text"] for entry in row_entries]
    leaf_lines.extend(entry["extraction_text"] for entry in cell_entries)
    pending_review = any(
        str(row.get("table_id") or "") == table_id
        and str(row.get("disposition") or "") == "review"
        for row in dispositions_by_cell.values()
    )
    if not leaf_lines and pending_review:
        leaf_lines.append(
            f"[TABLE_REVIEW_REQUIRED table_id={table_id}] {title}"
        )
    if not leaf_lines and data_rows:
        for offset, row in enumerate(data_rows, start=1):
            source_text = (
                row_render_line(headers, row)
                if row_render_line is not None
                else " | ".join(str(value or "") for value in row)
            )
            if source_text.strip():
                leaf_lines.append(
                    f"[TABLE_CONTEXT_ROW table_id={table_id} row={offset}] {source_text}"
                )
    if not leaf_lines:
        return None
    text = "\n".join([context_header_line, *leaf_lines])
    source_block = {
        "block_id": block_id,
        "table_id": table_id,
        "text": text,
        "section_path": list(block.get("section_path") or []),
        "noise": bool(block.get("noise")),
        "rows": row_entries,
        "cells": cell_entries,
        "table_input_mode": "structured_leaves",
    }
    return {
        "text": text,
        "header_line": repeat_header_line,
        "source_block": source_block,
    }


def _cell_is_extractable(
    cell: dict[str, Any], dispositions_by_cell: dict[str, dict[str, Any]]
) -> bool:
    disposition = dispositions_by_cell.get(str(cell.get("cell_id") or ""))
    if disposition is None:
        return str(cell.get("leaf_kind") or "") in {"row", "cell"}
    return str(disposition.get("disposition") or "") in {"target", "composite"}


def _is_normative_cell(text: str) -> bool:
    from table_structure import is_normative_text

    return is_normative_text(text)


def _is_group_header_evidence(
    block: dict[str, Any], item: dict[str, Any], non_empty: list[str]
) -> bool:
    """分组标题行判定（merge anchor 证据优先；无证据时退回同值启发式）。"""
    if len(set(non_empty)) != 1 or not non_empty:
        return False
    from table_structure import is_normative_text, normalize_merge_ranges, full_width_merge_row

    if is_normative_text(non_empty[0]):
        return False
    # S15（2026-08-03 清单）：merge_ranges=[] 是"已知无合并"的确切证据——
    # 同值行必须经全宽 merge anchor 判定（结果：不是分组标题）；只有键缺失
    # 或显式 None（旧产物无证据）才退回历史同值启发式
    if block.get("merge_ranges") is None:
        return True  # 旧产物无合并证据：历史同值口径
    merge_ranges = normalize_merge_ranges(block.get("merge_ranges"))
    width = int(block.get("columns") or 0)
    return full_width_merge_row(int(item.get("row_index") or 0), width, merge_ranges) is not None


def clause_key(section: dict[str, Any]) -> str | None:
    """两级条款族键：4.6.1 Requirements / 4.6.2 Test → "4.6"；4.15 → "4.15"；无编号 → None。

    标准文档的天然语义单元是条款族——X.Y 是一个需求整体，X.Y.1 是要求、X.Y.2 是对应测试
    （a↔a、b↔b 对应）。按字数贪心切分会把要求和测试拆进不同 LLM 单元（真实反馈："分段乱乱的"）。
    """
    m = re.match(r"^(\d+(?:\.\d+)*)", str(section.get("heading") or section.get("section_id") or "").strip())
    if not m:
        return None
    parts = m.group(1).split(".")
    return ".".join(parts[:2])


# --- 目录子树打包（0715 抽取质量重构,通用规则非章节号硬编码）---------------------
# 双线对比实证:两级族键 + 族内纯字数贪心会把深层 Requirements/Test 兄弟节切进不同
# 单元(EN 16314:4.12.3.2 Test/7.18.3.2.2 Test 成了孤立单元 → 模型对孤立测试片段
# 过度演绎,附录/测试章节内容缺陷率 58% vs 主体 18%)。改为:沿编号层级树自底向上装箱,
# 整子树能装就整体一单元;装不下才下钻;"要求+测试"语义兄弟(标题词面分类,任意语言的
# 标准文档通用结构)绑成原子,允许放宽到 2×target 也不拆。

_OUTLINE_NUM_RE = re.compile(r"^(?:Annex\s+([A-Z])\b|([A-Z])\.(\d+(?:\.\d+)*)|(\d+(?:\.\d+)*))",
                             re.IGNORECASE)
# 标题语义分类（通用词面）:测试/验证类标题绑到前一个兄弟(其要求节)
_TEST_HEADING_RE = re.compile(
    r"\btests?\b|\btest\s+methods?\b|\bverifications?\b|试验|测试|验证|检验", re.IGNORECASE)


def outline_path(section: dict[str, Any]) -> tuple | None:
    """标题 → 层级路径元组："7.13.4.3.1 Test"→(7,13,4,3,1);"A.1.2"→('A',1,2);
    "Annex A"→('A',);无编号 → None(走旧贪心,兼容散文/标题乱码文档)。"""
    heading = str(section.get("heading") or section.get("section_id") or "").strip()
    m = _OUTLINE_NUM_RE.match(heading)
    if not m:
        return None
    if m.group(1):
        return (m.group(1).upper(),)
    if m.group(2):
        return (m.group(2).upper(), *(int(x) for x in m.group(3).split(".")))
    return tuple(int(x) for x in m.group(4).split("."))


def _is_test_heading(section: dict[str, Any]) -> bool:
    return bool(_TEST_HEADING_RE.search(str(section.get("heading") or "")))


def _piece_len(section: dict[str, Any]) -> int:
    return len(section.get("text") or "") + len(section.get("heading") or "") + 4


def _pack_outline_run(run: list[tuple[tuple, dict[str, Any]]], depth: int,
                      target_chars: int) -> list[list[dict[str, Any]]]:
    """一段连续同前缀章节 → 原子序列(每个原子=必须同单元的章节列表)。

    规则(按序):①整段 ≤2×target → 整体一个原子(整子树优先);②按 depth+1 前缀切子组,
    测试类子组绑到前一子组(要求+测试原子);③原子仍超 2×target → 递归下钻;
    ④相邻小原子在同一父下贪心并到 ≤target(装箱经济性,不跨父)。"""
    total = sum(_piece_len(s) for _p, s in run)
    if total <= target_chars * CLAUSE_FAMILY_MAX_FACTOR:
        return [[s for _p, s in run]]

    child_groups: list[list[tuple[tuple, dict[str, Any]]]] = []
    for item in run:
        path, _sec = item
        key = path[:depth + 1]
        if child_groups and child_groups[-1][0][0][:depth + 1] == key:
            child_groups[-1].append(item)
        else:
            child_groups.append([item])

    # 测试类子组绑前一子组:整组标题全为测试/验证类 → 与其要求节同原子
    bound: list[list[tuple[tuple, dict[str, Any]]]] = []
    for group in child_groups:
        heads = [s for _p, s in group]
        if bound and heads and all(_is_test_heading(s) for s in heads):
            bound[-1].extend(group)
        else:
            bound.append(group)

    atoms: list[list[dict[str, Any]]] = []
    for group in bound:
        gsize = sum(_piece_len(s) for _p, s in group)
        deeper = any(len(p) > depth + 1 for p, _s in group)
        if gsize <= target_chars * CLAUSE_FAMILY_MAX_FACTOR or not deeper or len(group) == 1:
            atoms.append([s for _p, s in group])
        else:
            atoms.extend(_pack_outline_run(group, depth + 1, target_chars))

    # 相邻原子贪心并箱(≤target;超大原子单独成箱,交给 _pack_sections 内部拆)
    coalesced: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_len = 0
    for atom in atoms:
        asize = sum(_piece_len(s) for s in atom)
        if cur and cur_len + asize > target_chars:
            coalesced.append(cur)
            cur, cur_len = [], 0
        cur.extend(atom)
        cur_len += asize
    if cur:
        coalesced.append(cur)
    return coalesced


# 插入伪标题免疫:脚注/图例/水印行被解析成"标题"会打断章节 run 与兄弟相邻
# (实证:水印行成"16 章"插在 4.12.2.1/4.12.2.2 之间 → Test 孤立)。三明治判据:
# 断点处向前看 ≤LOOKAHEAD 节,若能回到当前顶层前缀且夹层各节都小 → 夹层随前节吸收。
_INTERLOPER_MAX_CHARS = 400
_INTERLOPER_LOOKAHEAD = 3
# 微单元折叠:打包尾部残留的孤立小单元(伪标题/空壳章节头)并入前一单元,减少碎单元
_MIN_UNIT_CHARS = 120


def _absorb_interlopers(sections: list[dict[str, Any]], start: int,
                        top: tuple) -> tuple[list[tuple[tuple, dict[str, Any]]], int]:
    """从 start 收集同顶层前缀 run,夹层伪标题按三明治判据随前节吸收(挂前节 path)。"""
    run: list[tuple[tuple, dict[str, Any]]] = []
    j = start
    while j < len(sections):
        p = outline_path(sections[j])
        if p is not None and p[:1] == top:
            run.append((p, sections[j]))
            j += 1
            continue
        # 断点:向前看能否回到 top,且夹层各节都足够小
        k = j
        small = True
        while k < len(sections) and k - j < _INTERLOPER_LOOKAHEAD:
            pk = outline_path(sections[k])
            if pk is not None and pk[:1] == top:
                break
            if _piece_len(sections[k]) > _INTERLOPER_MAX_CHARS:
                small = False
                break
            k += 1
        resumed = (small and k < len(sections) and k - j < _INTERLOPER_LOOKAHEAD
                   and run)
        if not resumed:
            break
        anchor_path = run[-1][0]
        for m in range(j, k):
            run.append((anchor_path, sections[m]))   # 夹层挂前节 path,内容原位保留
        j = k
    return run, j


def _fold_tiny_units(units: list[dict[str, Any]], target_chars: int) -> list[dict[str, Any]]:
    # 阈值随 target 缩放:小 target(测试夹具/特殊配置)下不误折正常单元
    threshold = min(_MIN_UNIT_CHARS, max(1, target_chars // 4))
    folded: list[dict[str, Any]] = []
    for u in units:
        if folded and len(u.get("text") or "") < threshold:
            prev = folded[-1]
            prev["text"] = (prev.get("text") or "") + "\n\n" + (u.get("text") or "")
            prev["block_ids"] = list(prev.get("block_ids") or []) + list(u.get("block_ids") or [])
            prev["source_blocks"] = list(prev.get("source_blocks") or []) + list(u.get("source_blocks") or [])
            prev["drift_source"] = (prev.get("drift_source") or prev["text"]) + "\n" + \
                (u.get("drift_source") or u.get("text") or "")
            prev["table_input_mode"] = _combine_table_input_mode(
                prev.get("table_input_mode", "plain_text"),
                u.get("table_input_mode", "plain_text"))
            continue
        folded.append(u)
    return folded


def pack_by_outline(sections: list[dict[str, Any]], *,
                    target_chars: int = DEFAULT_MERGE_CHARS) -> list[dict[str, Any]]:
    """章节 → LLM 输入单元(目录子树打包)。编号章节走层级树装箱;无编号连续段落
    沿用旧贪心(_pack_sections)。输出结构/顺序契约与 merge_sections 一致。"""
    units: list[dict[str, Any]] = []
    i = 0
    while i < len(sections):
        path = outline_path(sections[i])
        if path is None:
            j = i
            while j < len(sections) and outline_path(sections[j]) is None:
                j += 1
            units.extend(_pack_sections(sections[i:j], target_chars=target_chars,
                                        split_chars=target_chars))
            i = j
            continue
        run, j = _absorb_interlopers(sections, i, path[:1])
        for atom in _pack_outline_run(run, 1, target_chars):
            # 原子内可能仍超限(单节超大):交给 _pack_sections,其 target 放宽到族上限,
            # 单节超限走原 _split_text 拆分(drift_source 保整章语义不变)
            units.extend(_pack_sections(atom, target_chars=target_chars * CLAUSE_FAMILY_MAX_FACTOR,
                                        split_chars=target_chars))
        i = j
    return _fold_tiny_units(units, target_chars)


CLAUSE_FAMILY_MAX_FACTOR = 2


UNIT_MODE_ENV = "RATOMIZER_AI_UNIT_MODE"   # clause(默认) | chapter


CHAPTER_MAX_CHARS = 24000


CHAPTER_MIN_MAX_TOKENS = 16384  # 整章几十条需求的 JSON 输出预算（推理模型思维链之外）


def merge_sections(sections: list[dict[str, Any]], *, target_chars: int = DEFAULT_MERGE_CHARS,
                   unit_mode: str = "clause") -> list[dict[str, Any]]:
    """章节 → LLM 输入单元：**先按条款族分组（语义边界），族内再按字数规整（经济边界）**。

    同族（如 4.6.1/4.6.2）保持同单元、上限放宽到 2×target；**不同条款族绝不合并**——此前的
    纯字数贪心会把 4.5 尾巴和 4.6 开头拼在一起（真实反馈"分段乱乱的"的根源）。无编号章节沿用
    旧贪心合并（向后兼容散文/标题乱码文档）。
    """
    chapter_mode = unit_mode == "chapter"
    if not chapter_mode:
        # 0715 重构:clause 模式改目录子树打包——整子树优先、要求/测试语义绑定、
        # 下钻不跨父贪心。旧两级族键+族内纯字数贪心会把深层 Requirements/Test 拆开
        # (双线对比实证:孤立 Test 单元 → 内容缺陷率 58%)。
        return pack_by_outline(sections, target_chars=target_chars)

    groups: list[tuple[str | None, list[dict[str, Any]]]] = []
    for sec in sections:
        key = clause_key(sec)
        if key is not None:
            key = key.split(".")[0]   # 整章：4.14.1 → "4"（同章条款全部同单元）
        if groups and groups[-1][0] == key and key is not None:
            groups[-1][1].append(sec)      # 同章 → 同组
        elif groups and groups[-1][0] is None and key is None:
            groups[-1][1].append(sec)      # 连续无编号 → 同组（旧贪心处理）
        else:
            groups.append((key, [sec]))

    units: list[dict[str, Any]] = []
    for key, group in groups:
        limit = CHAPTER_MAX_CHARS if key is not None else target_chars
        units.extend(_pack_sections(group, target_chars=limit, split_chars=limit if key is not None else target_chars))
    return units


def _combine_table_input_mode(*modes: str) -> str:
    """合并后单元的表格输入模式：只要含一个结构化表段即按 ``structured_leaves`` 对待。

    结构化硬约束（build_section_prompt 的「不得新增/修改数值、单位、型号、代码」块）宁可
    多覆盖——混入散文也安全，约束只对 [TABLE_LEAF] 段起作用；绝不可漏，否则纯表段经合并后
    模式回落 plain_text，硬约束生产上从不注入（2026-08-05 Kimi 审核发现的高危 #1）。
    """
    return "structured_leaves" if any(m == "structured_leaves" for m in modes) else "plain_text"


def _pack_sections(sections: list[dict[str, Any]], *, target_chars: int,
                   split_chars: int) -> list[dict[str, Any]]:
    """组内按字数规整（原贪心逻辑）：小节拼接 ≤target；超大单节按 split_chars 拆。"""
    merged: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and cur["texts"]:
            merged.append(_finalize_merged(cur))
        cur = None

    for sec in sections:
        piece = f"## {sec['heading']}\n{sec['text']}" if sec.get("heading") else sec["text"]
        block_ids = list(sec.get("block_ids") or [])
        source_blocks = list(sec.get("source_blocks") or [])
        if len(piece) > target_chars:
            # 超大源章节：拆成 ≤split 的多块，各自独立成段（同段 block_ids 全量保留以便溯源）。
            # drift_source 保留完整原文：漂移护栏须以整章为 baseline，否则 LLM 合理引用同章
            # 其它片段里的 OBIS/事件码会被误判为"原文未见的结构漂移"（假阳性误伤）。
            # 封堵一：parameter 表被切多 chunk 时,第 2 个起每个 chunk 首行注入表头渲染行
            # （第 1 chunk 已含原始表头;后续 chunk 无表头会让 LLM 看无列名裸数据)
            flush()
            header_lines = list(sec.get("_table_header_lines") or [])
            header_prefix = ("\n".join(header_lines) + "\n") if header_lines else ""
            chunks = _split_text(piece, split_chars)
            for idx, chunk in enumerate(chunks):
                if idx > 0 and header_prefix and chunk.strip():
                    chunk = header_prefix + chunk
                merged.append(_finalize_merged({
                    "section_id": sec["section_id"], "heading": sec.get("heading", ""),
                    "texts": [chunk], "block_ids": block_ids, "source_blocks": source_blocks,
                    "drift_source": piece,
                    "table_input_mode": sec.get("table_input_mode", "plain_text")}))
            continue
        if cur is None:
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": block_ids, "source_blocks": source_blocks, "len": len(piece),
                   "table_input_mode": sec.get("table_input_mode", "plain_text")}
        elif cur["len"] + len(piece) > target_chars and cur["texts"]:
            flush()
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": block_ids, "source_blocks": source_blocks, "len": len(piece),
                   "table_input_mode": sec.get("table_input_mode", "plain_text")}
        else:
            cur["texts"].append(piece)
            cur["block_ids"].extend(block_ids)
            cur.setdefault("source_blocks", []).extend(source_blocks)
            cur["table_input_mode"] = _combine_table_input_mode(
                cur.get("table_input_mode", "plain_text"),
                sec.get("table_input_mode", "plain_text"))
            cur["len"] += len(piece)
    flush()
    return merged


def _finalize_merged(cur: dict[str, Any]) -> dict[str, Any]:
    text = "\n\n".join(cur["texts"]).strip()
    # 漂移护栏 baseline：拆分片段用整章原文，其余默认用自身文本（无跨片段码）
    drift_source = cur.get("drift_source") or text
    return {"section_id": cur["section_id"], "heading": cur["heading"],
            "section_path": [cur["heading"]] if cur["heading"] else [],
            "text": text, "block_ids": cur["block_ids"], "source_blocks": cur.get("source_blocks", []),
            "drift_source": drift_source,
            "table_input_mode": cur.get("table_input_mode", "plain_text")}


def _split_text(text: str, target_chars: int) -> list[str]:
    """把超长文本按行贪心切成 ≤target 的块；单行超长则硬切。保证每次 LLM 输入有界。"""
    if len(text) <= target_chars:
        return [text]
    units: list[str] = []
    for line in text.split("\n"):
        if len(line) <= target_chars:
            units.append(line)
        else:  # 单行超长（如无换行的长表格）：硬切
            units.extend(line[i:i + target_chars] for i in range(0, len(line), target_chars))
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for unit in units:
        add = len(unit) + 1
        if cur and cur_len + add > target_chars:
            chunks.append("\n".join(cur))
            cur, cur_len = [unit], add
        else:
            cur.append(unit)
            cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c.strip()]


def sample_sections(sections: list[dict[str, Any]], limit: int | None) -> tuple[list[dict[str, Any]], bool]:
    """试抽样本：均匀取 N 章（确定性步长，非"前 N 章"——文档开头是范围/术语，需求密度最低，
    前 N 章会给出误导性的质量样本）。缓存指纹按章节内容算，样本章节的缓存全量跑时原样复用。"""
    if not limit or limit <= 0 or limit >= len(sections):
        return sections, False
    stride = len(sections) / limit
    picked = [sections[min(int(i * stride), len(sections) - 1)] for i in range(limit)]
    return picked, True


_CLAUSE_REF_RE = re.compile(
    r"\b(?:given in|specified in|according to|defined in|listed in|in accordance with|see)\s+"
    r"(Annex\s+[A-Z]\b|[A-Z]\.\d+(?:\.\d+)*\b|\d+(?:\.\d+){1,5})", re.IGNORECASE)


_CLAUSE_HEADING_RE = re.compile(r"(?m)^(?:Annex\s+([A-Z])\b|([A-Z]\.\d+(?:\.\d+)*)\b|(\d+(?:\.\d+){1,5})\b)")


MAX_REFS_PER_SECTION = 2      # 控 token 成本


REF_EXCERPT_CHARS = 1200


def _normalize_clause_ref(raw: str) -> str:
    """引用 token 归一：\"Annex A\"→\"A\"（与标题索引键一致）；其余原样。"""
    token = raw.strip()
    if token.lower().startswith("annex"):
        return token.split()[-1].upper()
    return token


def resolve_section_refs(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """就地给含内部引用的 section 挂 ref_texts + drift_source。必须对**全文**单元表跑
    （试抽采样前），被引条款可能在未被抽样的单元里。确定性、零 LLM。

    覆盖数字条款与**附录**（EN 系标准的测试程序全在 Annex——\"see A.1.4.6\"/\"in accordance
    with Annex A\" 此前是瞎的，真实反馈）。"""
    clause_pos: dict[str, tuple[int, int]] = {}
    for idx, s in enumerate(sections):
        for m in _CLAUSE_HEADING_RE.finditer(s["text"]):
            key = m.group(1) or m.group(2) or m.group(3)
            clause_pos.setdefault(key, (idx, m.start()))
    for idx, s in enumerate(sections):
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        for m in _CLAUSE_REF_RE.finditer(s["text"]):
            clause = _normalize_clause_ref(m.group(1))
            if clause in seen:
                continue
            seen.add(clause)
            target = clause_pos.get(clause)
            if not target or target[0] == idx:   # 找不到 or 就在本单元 → 无需注入
                continue
            t_idx, start = target
            refs.append({"clause": clause,
                         "text": sections[t_idx]["text"][start:start + REF_EXCERPT_CHARS]})
            if len(refs) >= MAX_REFS_PER_SECTION:
                break
        if refs:
            s["ref_texts"] = refs
            drift_source = s.get("drift_source") or s["text"]
            for ref in refs:
                if ref["text"] not in drift_source:
                    drift_source += "\n" + ref["text"]
            s["drift_source"] = drift_source
    return sections


TERM_DEFS_MAX = 4


TERM_DEF_CHARS = 240


_TERM_NAME_RE = re.compile(r"^\d+(?:\.\d+)*\s+(.{4,60}?)\s*$")


def collect_term_entries(sections: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """从术语小节收集 (术语名, 定义文本)。术语名取子节标题去编号；名太短/太泛的丢弃。"""
    entries: list[tuple[str, str]] = []
    for s in sections:
        path = " / ".join([str(x) for x in (s.get("section_path") or [])] + [str(s.get("heading") or "")])
        if not _TERMS_HEADING_RE.search(path):
            continue
        heading = str(s.get("heading") or "").strip()
        m = _TERM_NAME_RE.match(heading)
        if not m:
            continue
        term = m.group(1).strip()
        if len(term) < 8 and " " not in term:
            continue   # 单个短词（如 "AFD"）在正文中到处出现，注入价值低且刷屏
        if _TERMS_HEADING_RE.search(term):
            continue   # 术语章自身的结构标题（"Terms and definitions"/"Abbreviated terms"）
                       # 不是术语——真实产物里混进对照表浪费槽位（v11 实检）
        entries.append((term, s.get("text", "")[:TERM_DEF_CHARS]))
    return entries


def attach_term_definitions(sections: list[dict[str, Any]],
                            entries: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """就地给正文单元挂 term_defs（本单元用到的术语定义）。定义并入漂移基线（定义里的
    数字=有据）。与 ref_texts 同折进缓存指纹。"""
    if not entries:
        return sections
    lowered = [(term, term.casefold(), text) for term, text in entries]
    for s in sections:
        path = " / ".join(str(x) for x in (s.get("section_path") or []))
        if _TERMS_HEADING_RE.search(path):
            continue   # 术语小节自身不注入
        body = s.get("text", "").casefold()
        hits = [{"term": term, "text": text}
                for term, low, text in lowered if low in body][:TERM_DEFS_MAX]
        if hits:
            s["term_defs"] = hits
            s["drift_source"] = (s.get("drift_source") or s["text"]) + "\n" + \
                "\n".join(h["text"] for h in hits)
    return sections


_TERMS_HEADING_RE = re.compile(r"term|definition|abbreviat|glossary|术语|定义|符号", re.IGNORECASE)


