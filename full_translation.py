"""Whole-document bilingual delivery backed by the annotation translation cache."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

from ai_extract import _row_render_line as _shared_row_render_line
from api_server import ANNOTATION_TRANSLATION_GUARDS_VERSION, translation_key
from io_utils import read_jsonl
from process_file_lock import process_file_lock
from result_package import governed_artifact_path
from table_structure import (
    inherit_merged_text,
    merge_ranges_overlap,
    normalize_merge_ranges,
    physical_data_row_indexes,
)


FULL_TRANSLATION_VERSION = "full-translation-v3"
DOCUMENT_TRANSLATION_SCHEMA_VERSION = "document-translation/v3"
FULL_TRANSLATION_ENV = "RATOMIZER_FULL_TRANSLATION"
DOCUMENT_TRANSLATIONS = "document_translations.jsonl"
DOCUMENT_TRANSLATION_HTML = "document_translation.html"
CLARIFICATION_BILINGUAL_HTML = "clarification_questions_bilingual.html"
_REPLACE_ATTEMPTS = 5
_LETTER_RE = re.compile(r"[^\W\d_]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SYNTHETIC_HEADER_RE = re.compile(r"^column_\d+(?:_\d+)?$", re.IGNORECASE)
# 与 table_structure._LETTERED_HEADER_CELL_RE 同口径：(a)..(z) 前缀一律剥离——第 11 列
# (k) 起同样清理。"序列必须从 (a) 起连续"的识别约束归 table_structure 管，这里只做显示清理。
_LETTERED_HEADER_RE = re.compile(r"^\s*\([a-zA-Z]\)\s*")
# 共享行渲染契约（ai_extract 不依赖 full_translation，无导入环；tests 里有环回归检测）。
_row_render_line = _shared_row_render_line


def full_translation_enabled(value: str | None = None) -> bool:
    raw = os.environ.get(FULL_TRANSLATION_ENV, "1") if value is None else value
    enabled = str(raw or "").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return False
    # 翻译交付模式（方案 §12.1，M6）：off/markers 明确不需要全文双语——全文翻译
    # 阶段不跑（chain 的 stage config 已含 enabled 布尔，指纹随配置变化）。
    # 默认 full = 既有行为。
    from config import get_env

    if str(get_env("RATOMIZER_TRANSLATION_MODE")).strip().lower() in {"off", "markers"}:
        return False
    return True


def _block_text(block: dict[str, Any]) -> str:
    return str(block.get("text") or block.get("raw_text") or "").strip()


def _looks_translatable(text: str) -> bool:
    # 目标语是中文：非 CJK 字母文字（拉丁/西里尔/希腊等）需要翻译，且必须构成
    # 主体——非 CJK 字母 ≥3 且 ≥ CJK 字符数（旧拉丁版 latin>=3 and latin>=cjk
    # 的文种广义化，比率约束一直都在）。俄文等整段外文（CJK≈0）照译；中文为主、
    # 只夹少量缩写（"电压ABC等级"）的文本跳过——目标语已是中文，进管线只是
    # 白付 LLM 成本；纯数字/符号无字母，天然不可译。
    letters = len(_LETTER_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    non_cjk = letters - cjk
    return non_cjk >= 3 and non_cjk >= cjk


def _clarification_texts(report: dict[str, Any]) -> Iterable[str]:
    fields = ("source_text", "source_quote", "original_text", "evidence", "context")
    for entry in report.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for field in fields:
            value = str(entry.get(field) or "").strip()
            if value and _looks_translatable(value):
                yield value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt + 1 >= _REPLACE_ATTEMPTS:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def _clean_header(value: Any) -> str:
    text = str(value or "").strip()
    if _SYNTHETIC_HEADER_RE.fullmatch(text):
        return ""
    return _LETTERED_HEADER_RE.sub("", text).strip()


def _padded_cells(row: Any, width: int) -> list[str]:
    cells = [str(cell or "") for cell in (row if isinstance(row, (list, tuple)) else [row])]
    return (cells + [""] * max(0, width - len(cells)))[:width]


def _table_row_lists(block: dict[str, Any], key: str) -> list[list[str]]:
    return [row for row in (block.get(key) or []) if isinstance(row, (list, tuple))]


def _finalize_unit(unit: dict[str, Any]) -> dict[str, Any]:
    """单元落位：规范化 source_text 并一次算好内容键/摘要（后续收集与处置只复用）。"""
    text = str(unit.get("source_text") or "").strip()
    unit["source_text"] = text
    unit["translation_key"] = translation_key(text) if text else ""
    unit["source_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return unit


def _fallback_header(block: dict[str, Any], headers: list[str]) -> bool:
    status = str(block.get("header_detection_status") or "").lower()
    non_empty = [str(value or "").strip() for value in headers if str(value or "").strip()]
    return status == "fallback" or bool(
        non_empty and all(_SYNTHETIC_HEADER_RE.fullmatch(value) for value in non_empty)
    )


def _physical_matrix(
    block: dict[str, Any],
    *,
    width: int,
    header_indexes: list[int],
    data_indexes: list[int],
) -> list[list[str]] | None:
    """从块载荷重建物理行矩阵（1..rows）；放置证据不完整时返回 None（调用方按块列表渲染）。

    标题行单元格来自块的 ``title_rows`` 载荷（atomize 结构化路径写入，与
    ``title_row_indexes`` 对齐）；无载荷时标题行为占位空行，绝不伪造内容。"""
    total = int(block.get("rows") or 0)
    if total <= 0:
        return None
    header_rows = _table_row_lists(block, "header_rows")
    data_rows = _table_row_lists(block, "data_rows")
    if len(header_rows) != len(header_indexes) or len(data_rows) != len(data_indexes):
        return None
    title_indexes = [int(value) for value in (block.get("title_row_indexes") or [])]
    title_payload = _table_row_lists(block, "title_rows")
    title_cells = (
        title_payload if len(title_payload) == len(title_indexes)
        else [[] for _ in title_indexes]
    )
    placed: dict[int, list[str]] = {}
    for row_index, row in zip(title_indexes, title_cells):
        if row_index in placed or not 1 <= row_index <= total:
            return None
        placed[row_index] = list(row)
    for row_index, row in zip(header_indexes, header_rows):
        if row_index in placed or not 1 <= row_index <= total:
            return None
        placed[row_index] = list(row)
    for row_index, row in zip(data_indexes, data_rows):
        if row_index in placed or not 1 <= row_index <= total:
            return None
        placed[row_index] = list(row)
    if not (set(range(1, total + 1)) - set(title_indexes)) <= set(placed):
        return None  # 存在既非标题也无放置证据的物理行 —— 矩阵不可信
    return [_padded_cells(placed.get(row, []), width) for row in range(1, total + 1)]


def _regular_table_plan(block: dict[str, Any]) -> dict[str, Any] | None:
    if str(block.get("type") or block.get("block_type") or "") != "table":
        return None
    if block.get("nested_tables"):
        return None
    merge_ranges = normalize_merge_ranges(block.get("merge_ranges") or [])
    # 复杂表兜底只剩：嵌套表 + 几何自相矛盾的合并（面积相交）。纵向合并保持结构化
    # （v3：此前任何纵向合并都把整表降为 complex_table——扁平文本超批上限、逐句重试、
    # 逐行双语 UI 恰好在最大的表上丢失）。
    if merge_ranges_overlap(merge_ranges):
        return None
    raw_headers = [str(value or "").strip() for value in (block.get("headers") or [])]
    raw_header_rows = _table_row_lists(block, "header_rows")
    data_rows = _table_row_lists(block, "data_rows")
    width = max(
        [len(raw_headers), *(len(row) for row in raw_header_rows), *(len(row) for row in data_rows)],
        default=0,
    )
    if width <= 0:
        return None
    headers = _padded_cells(raw_headers, width)
    display_headers = [_clean_header(value) for value in headers]
    fallback = _fallback_header(block, headers)
    header_indexes = [int(value) for value in (block.get("header_row_indexes") or [])]
    data_indexes = physical_data_row_indexes(block)
    matrix = _physical_matrix(
        block, width=width, header_indexes=header_indexes, data_indexes=data_indexes
    )
    # 有效矩阵：纵向合并的锚文本向续行传播（复用 table_structure.inherit_merged_text）。
    # 只喂纵向分量——横向合并的覆盖格保持空、由 colspan 表达，不在行内复制翻译
    # 文本。2D 合并（跨行且跨列）分解为锚列的纵向条带：只有锚列向续行继承锚
    # 文本；锚行的横向覆盖（锚列+1..max_col）保持为空，与纯横向合并"文本只在
    # 最左格出现一次"同口径——否则继承会把锚行横向铺满锚文本（"A B | A B | x"
    # 进 LLM 输入与账本）。
    vertical_ranges = [
        (min_row, min_col, max_row, min_col)
        for min_row, min_col, max_row, _max_col in merge_ranges
        if min_row != max_row
    ]
    effective = inherit_merged_text(matrix, vertical_ranges) if matrix is not None else None

    def row_cells(row_index: int | None, fallback_row: Any) -> list[str]:
        if effective is not None and row_index is not None and 1 <= row_index <= len(effective):
            return list(effective[row_index - 1])
        return _padded_cells(fallback_row, width)

    units: list[dict[str, Any]] = []
    table_id = str(block.get("table_id") or "")
    block_id = str(block.get("block_id") or "")
    title = str(block.get("table_title") or "").strip()
    if title:
        units.append(_finalize_unit({
            "unit_id": f"{block_id}:title",
            "role": "title",
            "row_index": None,
            "source_cells": [title],
            "source_text": title,
        }))
    # 每个物理标题行一个 title 单元（v3：此前只有 table_title 一个单元，堆叠标题的
    # 副标题行不出现在任何单元）。单元格只在 title_rows 载荷可得时渲染——不伪造。
    for row_index in [int(value) for value in (block.get("title_row_indexes") or [])]:
        cells = row_cells(row_index, [])
        cell_texts = [str(cell or "").strip() for cell in cells]
        if not any(cell_texts):
            continue
        units.append(_finalize_unit({
            "unit_id": f"{block_id}:title-row:{row_index}",
            "role": "title",
            "row_index": row_index,
            "source_cells": cells,
            "source_text": " | ".join(text for text in cell_texts if text),
        }))
    if not fallback:
        for offset, raw_row in enumerate(raw_header_rows, start=1):
            row_index = header_indexes[offset - 1] if offset <= len(header_indexes) else None
            cells = [_clean_header(cell) for cell in row_cells(row_index, raw_row)]
            if not any(cells):
                continue
            units.append(_finalize_unit({
                "unit_id": f"{block_id}:header:{offset}",
                "role": "header",
                "row_index": int(row_index) if row_index is not None else offset,
                "source_cells": cells,
                "source_text": _row_render_line(display_headers, cells),
            }))
        if not raw_header_rows and any(display_headers):
            units.append(_finalize_unit({
                "unit_id": f"{block_id}:header:1",
                "role": "header",
                "row_index": 1,
                "source_cells": display_headers,
                "source_text": _row_render_line(display_headers, display_headers),
            }))
    else:
        for offset, raw_row in enumerate(raw_header_rows, start=1):
            row_index = header_indexes[offset - 1] if offset <= len(header_indexes) else None
            cells = row_cells(row_index, raw_row)
            if not any(cell.strip() for cell in cells):
                continue
            units.append(_finalize_unit({
                "unit_id": f"{block_id}:data:fallback-header:{offset}",
                "role": "data",
                "row_index": int(row_index) if row_index is not None else offset,
                "source_cells": cells,
                "source_text": _row_render_line(display_headers, cells),
            }))
    for offset, raw_row in enumerate(data_rows, start=1):
        placed_index = int(data_indexes[offset - 1]) if offset <= len(data_indexes) else None
        cells = row_cells(placed_index, raw_row)
        if not any(cell.strip() for cell in cells):
            continue  # 全空行不成翻译单元（v3：此前照发 "|  |" 空行给 LLM）
        units.append(_finalize_unit({
            "unit_id": f"{block_id}:data:{offset}",
            "role": "data",
            "row_index": placed_index if placed_index is not None else offset,
            "source_cells": cells,
            "source_text": _row_render_line(display_headers, cells),
        }))
    return {
        "table_id": table_id,
        "title": title,
        "column_count": width,
        "headers": display_headers,
        "header_detection_status": str(block.get("header_detection_status") or ""),
        "header_fallback": fallback,
        "rebuilt": block.get("table_source") == "text_layout",
        "merge_ranges": [list(entry) for entry in merge_ranges],
        "units": units,
    }


def _unit_disposition(
    unit: dict[str, Any],
    *,
    enabled: bool,
    sidecar: dict[str, dict[str, Any]],
    translation_summary: dict[str, Any],
) -> dict[str, Any]:
    source = str(unit.get("source_text") or "").strip()
    key = str(unit.get("translation_key") or "") or (translation_key(source) if source else "")
    entry = sidecar.get(key, {}) if key else {}
    translation = str(entry.get("translation") or "").strip()
    guards_current = entry.get("guards_version") == ANNOTATION_TRANSLATION_GUARDS_VERSION
    if not source:
        status, reason = "skipped", "empty_text"
    elif not enabled:
        status, reason = "skipped", "feature_disabled"
    elif not _looks_translatable(source):
        # 纯数字/标记（或已是中文）的行不值得 LLM：跳过且不计入 eligible
        # （与 empty_text 同口径的受控跳过，v3 前它们照常占批位）。
        status, reason = "skipped", "nothing_translatable"
    elif translation and not entry.get("rejected") and guards_current:
        status, reason = "translated", ""
    else:
        status = "failed"
        if translation and not entry.get("rejected"):
            # 缓存条目未过当前护栏版本 —— 顺序无关地按失败处置（与 api_server
            # load_annotation_translations 的 guards_version 闸同口径）。
            reason = "guards_version_mismatch"
        else:
            reason = str(entry.get("status") or entry.get("reason") or "")
            if not reason:
                reason = (
                    "llm_unavailable"
                    if translation_summary.get("route") == "stub"
                    else "missing_cache_entry"
                )
    return {
        **unit,
        "status": status,
        "reason": reason,
        "translation": translation if status == "translated" else "",
        "translation_key": key,
        "source_sha256": str(unit.get("source_sha256") or "")
        or hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "model": entry.get("model") or translation_summary.get("model") or "",
        "strategy_version": entry.get("strategy_version") or "",
    }


def _status_target(value: dict[str, Any]) -> str:
    translation = html.escape(str(value.get("translation") or ""))
    if translation:
        return translation
    status = html.escape(str(value.get("status") or ""))
    reason = html.escape(str(value.get("reason") or ""))
    return f'<span class="translation-failure">[{status}] {reason}</span>'


def _vertical_inheritance_map(
    units: list[dict[str, Any]],
    merge_ranges: list[list[int]],
) -> dict[tuple[int, int], str]:
    """纵向合并 (锚行, 锚列) → 锚行单元的锚列格文本（渲染续行时的兜底继承表）。

    计划侧在矩阵可信时已把有效矩阵（锚文本向续行传播）写进续行单元；矩阵
    重建失败（放置证据不完整）的兜底路径里续行格可能为空——这里只从既有
    单元数据取锚文本，绝不伪造。2D 合并只登记锚列（纵向分量），锚行横向
    覆盖列不继承——与计划侧 _regular_table_plan 的纵向分解同口径。"""
    by_row: dict[int, dict[str, Any]] = {}
    for unit in units:
        index = unit.get("row_index")
        if index is not None:
            by_row.setdefault(int(index), unit)
    texts: dict[tuple[int, int], str] = {}
    for min_row, min_col, max_row, max_col in merge_ranges:
        if int(min_row) == int(max_row):
            continue  # 纯横向合并不跨行，续行继承不适用
        anchor_unit = by_row.get(int(min_row))
        if anchor_unit is None:
            continue
        # 2D 合并只按锚列兜底继承（与计划侧的纵向分解同口径）：续行锚列继承
        # 锚文本，锚行的横向覆盖列保持空——不再向每个覆盖列铺锚文本。
        anchor_cells = _padded_cells(anchor_unit.get("source_cells") or [], int(min_col))
        texts[(int(min_row), int(min_col))] = str(anchor_cells[-1] or "").strip()
    return texts


def _render_source_cells(
    unit: dict[str, Any],
    *,
    width: int,
    tag: str,
    merge_ranges: list[list[int]],
    inherited_texts: dict[tuple[int, int], str] | None = None,
) -> str:
    """源文行单元格（网格安全渲染：双语表内禁用 rowspan/colspan）。

    交错双语布局里每个源文行后紧跟整行译文行——物理 rowspan 会吞掉译文行的
    格槽、其后的源文行又省略被覆盖列，合并以下每一行都错位；跨 thead/tbody
    的 rowspan 也不是合法 HTML。因此每行恒渲染完整列集（列数恒等于表宽）：
    - 纵向合并续行：被覆盖列渲染继承的锚文本（单元已带有效矩阵文本，缺失时
      从锚行单元兜底继承），标 ``data-inherited="1"`` 留证；
    - 横向单行合并：合并文本只在最左格渲染一次，同行被覆盖列渲染空格并标
      ``data-merge-covered="1"``——译文行是整行级条幅、无法逐格镜像同一
      colspan 结构，网格有效优先于 colspan 视觉；
    - 被覆盖格里与锚不同的事实文本（上游校验冲突的防御路径）原样渲染，
      绝不丢内容。"""
    cells = _padded_cells(unit.get("source_cells") or [], width)
    row_index = unit.get("row_index")
    horizontal_covered: dict[int, int] = {}   # 列 → 横向合并锚列（同行被覆盖）
    vertical_continuation: dict[int, int] = {}  # 列 → 纵向合并锚行（续行继承）
    if row_index is not None:
        row = int(row_index)
        for min_row, min_col, max_row, max_col in merge_ranges:
            if not int(min_row) <= row <= int(max_row):
                continue
            for column in range(int(min_col), int(max_col) + 1):
                if row == int(min_row):
                    if column > int(min_col):
                        horizontal_covered[column] = int(min_col)
                else:
                    vertical_continuation[column] = int(min_row)
    inherited_texts = inherited_texts or {}
    rendered: list[str] = []
    for column in range(1, width + 1):
        text = str(cells[column - 1] or "").strip()
        if column in vertical_continuation:
            anchor_row = vertical_continuation[column]
            if not text:
                text = inherited_texts.get((anchor_row, column), "")
            rendered.append(f'<{tag} data-inherited="1">{html.escape(text)}</{tag}>')
            continue
        if column in horizontal_covered:
            anchor_text = str(cells[horizontal_covered[column] - 1] or "").strip()
            if text and text != anchor_text:
                # 防御：被覆盖格里是与锚不同的事实文本——原样渲染，绝不丢内容。
                rendered.append(f"<{tag}>{html.escape(text)}</{tag}>")
            else:
                rendered.append(f'<{tag} data-merge-covered="1"></{tag}>')
            continue
        rendered.append(f"<{tag}>{html.escape(text)}</{tag}>")
    return "".join(rendered)


def _normalize_title_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _render_full_width_pair(unit: dict[str, Any], *, width: int, tag: str) -> str:
    """物理标题行：全宽合并行（源文 + 译文成对，每行网格覆盖恒为表宽）。"""
    source = html.escape(str(unit.get("source_text") or ""))
    return (
        f'<tr class="source-row"><{tag} colspan="{width}">{source}</{tag}></tr>'
        f'<tr class="translation-row"><{tag} colspan="{width}">{_status_target(unit)}</{tag}></tr>'
    )


def _render_table_html(row: dict[str, Any]) -> str:
    table = dict(row.get("table") or {})
    width = max(1, int(table.get("column_count") or 1))
    units = [unit for unit in (table.get("rows") or []) if isinstance(unit, dict)]
    title_units = [unit for unit in units if unit.get("role") == "title"]
    caption_unit = next(
        (unit for unit in title_units if unit.get("row_index") is None),
        next(iter(title_units), None),
    )
    title_row_units = sorted(
        (unit for unit in title_units if unit.get("row_index") is not None),
        key=lambda unit: int(unit["row_index"]),
    )
    headers = [unit for unit in units if unit.get("role") == "header"]
    data_rows = [unit for unit in units if unit.get("role") == "data"]
    merge_ranges = [
        list(entry) for entry in (table.get("merge_ranges") or [])
        if isinstance(entry, (list, tuple)) and len(entry) == 4
    ]
    inherited_texts = _vertical_inheritance_map(units, merge_ranges)
    caption_source = html.escape(str((caption_unit or {}).get("source_text") or table.get("title") or ""))
    caption_translation = _status_target(caption_unit) if caption_unit else ""
    badge = '<span class="table-badge">无画线重建</span>' if table.get("rebuilt") else ""
    fallback = '<span class="table-note">无表头（结构未识别）</span>' if table.get("header_fallback") else ""
    caption = (
        f"<figcaption><span>{caption_source}</span>"
        f"<span class=\"caption-translation\">{caption_translation}</span>{badge}{fallback}</figcaption>"
        if caption_source or badge or fallback else ""
    )
    # 题注去重：与题注同文的物理标题行只在 figcaption 出现一次（此前题注 +
    # 正文首行双渲染）；不同文的堆叠标题（副标题）保留正文渲染。
    normalized_caption = _normalize_title_text(
        (caption_unit or {}).get("source_text") or table.get("title") or ""
    )
    visible_title_rows = [
        unit for unit in title_row_units
        if not normalized_caption
        or _normalize_title_text(unit.get("source_text")) != normalized_caption
    ]
    # 结构边界：首个表头物理行（无表头单元的 fallback 表以首个数据行承载）。
    # 边界前的标题行置顶 thead（文档序），边界起的标题行落 tbody 原位；
    # 无边界证据（既无表头也无数据行）时标题行全部进 thead。
    boundary_rows = [
        int(unit["row_index"]) for unit in headers if unit.get("row_index") is not None
    ] or [
        int(unit["row_index"]) for unit in data_rows if unit.get("row_index") is not None
    ]
    boundary = min(boundary_rows) if boundary_rows else None
    head_title_units = [
        unit for unit in visible_title_rows
        if boundary is None or int(unit["row_index"]) < boundary
    ]
    body_title_units = [
        unit for unit in visible_title_rows
        if boundary is not None and int(unit["row_index"]) >= boundary
    ]
    head_parts: list[str] = []
    for unit in head_title_units:
        head_parts.append(_render_full_width_pair(unit, width=width, tag="th"))
    for unit in headers:
        head_parts.append(
            '<tr class="source-row">'
            + _render_source_cells(
                unit, width=width, tag="th", merge_ranges=merge_ranges,
                inherited_texts=inherited_texts,
            )
            + "</tr>"
        )
        head_parts.append(
            f'<tr class="translation-row"><th colspan="{width}">{_status_target(unit)}</th></tr>'
        )
    body_parts: list[str] = []
    # 表头起的标题行与数据行按物理行序穿插（标题行全宽渲染，数据行走格渲染）。
    body_units = sorted(
        [*body_title_units, *data_rows],
        key=lambda unit: (
            unit.get("row_index") is None,
            int(unit.get("row_index") or 0),
        ),
    )
    for unit in body_units:
        if unit.get("role") == "title":
            body_parts.append(_render_full_width_pair(unit, width=width, tag="td"))
            continue
        body_parts.append(
            '<tr class="source-row">'
            + _render_source_cells(
                unit, width=width, tag="td", merge_ranges=merge_ranges,
                inherited_texts=inherited_texts,
            )
            + "</tr>"
        )
        body_parts.append(
            f'<tr class="translation-row"><td colspan="{width}">{_status_target(unit)}</td></tr>'
        )
    anchor = html.escape(str(row.get("block_id") or ""), quote=True)
    thead = f"<thead>{''.join(head_parts)}</thead>" if head_parts else ""
    return (
        f'<section class="table-pair" id="pair-{anchor}"><header>{anchor} · 表格中英对照</header>'
        f'<figure class="doc-table">{caption}<div class="table-scroll"><table>{thead}'
        f"<tbody>{''.join(body_parts)}</tbody></table></div></figure></section>"
    )


def _render_document_html(rows: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for row in rows:
        if row.get("record_kind") == "table":
            sections.append(_render_table_html(row))
            continue
        block_id = str(row.get("block_id") or "")
        source = html.escape(str(row.get("source_text") or ""))
        target = _status_target(row)
        anchor = html.escape(block_id, quote=True)
        extra = ""
        if row.get("record_kind") == "complex_table":
            extra = '<div class="table-note">复杂表按原文展示</div>'
        sections.append(
            f'<section class="pair" id="pair-{anchor}">'
            f'<article id="src-{anchor}"><header>{anchor} · EN '
            f'<a href="#zh-{anchor}">中文</a></header>{extra}<p>{source}</p></article>'
            f'<article id="zh-{anchor}" class="translation"><header>{anchor} · 中文 '
            f'<a href="#src-{anchor}">EN</a></header><p>{target}</p></article></section>'
        )
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>全文中英对照</title>
<style>body{margin:0;font:15px/1.65 system-ui,sans-serif;color:#17202a;background:#f5f7f8}
main{max-width:1280px;margin:auto;padding:24px}.pair{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #cbd3d8;background:white}
article{padding:16px 20px;min-width:0}.translation{background:#f7fbf8;border-left:1px solid #d7dfdc}header{font-size:12px;color:#53636d}
p{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#176b4d}.table-pair{border-top:1px solid #cbd3d8;background:#fff;padding:16px 20px}
.doc-table{margin:8px 0 0}.doc-table figcaption{font-size:13px;font-weight:650;color:#344252;margin-bottom:8px}.caption-translation{display:block;color:#176b4d;font-weight:500}
.table-badge,.table-note{display:inline-block;margin-left:8px;color:#6b7280;font-size:11px;font-weight:500}.table-scroll{overflow-x:auto;border:1px solid #dfe5e8;border-radius:6px}
.doc-table table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.5}.doc-table th,.doc-table td{padding:8px 10px;border-right:1px solid #edf0f2;border-bottom:1px solid #e6eaed;text-align:left;vertical-align:top;overflow-wrap:anywhere}
.doc-table th:last-child,.doc-table td:last-child{border-right:0}.source-row:nth-of-type(4n+1) td{background:#fafbfd}.translation-row th,.translation-row td{background:#f3faf6;color:#176b4d;font-size:12px;padding-top:6px;padding-bottom:9px}.translation-failure{color:#9a3412}
@media(max-width:720px){main{padding:12px}.pair{grid-template-columns:1fr}.translation{border-left:0;border-top:1px solid #d7dfdc}.table-pair{padding:14px 12px}}</style>
</head><body><main><h1>全文中英对照</h1>""" + "".join(sections) + "</main></body></html>\n"


def _render_clarification_html(report: dict[str, Any], translations: dict[str, str]) -> str:
    entries = report.get("entries") or []
    items: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        question = html.escape(str(entry.get("question") or entry.get("text") or ""))
        source = next((str(entry.get(key) or "").strip() for key in
                       ("source_text", "source_quote", "original_text", "evidence", "context")
                       if str(entry.get(key) or "").strip()), "")
        translated = translations.get(translation_key(source), "") if source else ""
        items.append(
            f'<section><h2>{index}. {question}</h2><p class="source">{html.escape(source)}</p>'
            f'<p class="translation">{html.escape(translated)}</p></section>'
        )
    note = "" if entries else "<p>澄清报告尚未生成；运行澄清阶段后重跑全文翻译即可增量补齐。</p>"
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>双语澄清报告</title><style>body{max-width:960px;margin:auto;padding:24px;font:15px/1.65 system-ui,sans-serif;color:#17202a}
section{border-top:1px solid #ccd5da;padding:14px 0}.source{white-space:pre-wrap}.translation{white-space:pre-wrap;color:#176b4d}</style></head>
<body><h1>双语澄清报告</h1>""" + note + "".join(items) + "</body></html>\n"


def _update_quality_report(out_dir: Path, summary: dict[str, Any]) -> None:
    path = governed_artifact_path(out_dir, "quality_report.json", category="pipeline")
    lock = governed_artifact_path(out_dir, "full_translation.lock", category="state")
    with process_file_lock(lock, timeout_s=15.0, label="full translation quality report lock"):
        report = _read_json(path)
        report["full_translation"] = summary
        _atomic_write(path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def _aggregate_status(dispositions: list[dict[str, Any]]) -> tuple[str, str]:
    if not dispositions or all(row["status"] == "skipped" for row in dispositions):
        reason = next((str(row.get("reason") or "") for row in dispositions if row.get("reason")), "empty_table")
        return "skipped", reason
    failures = sum(row["status"] == "failed" for row in dispositions)
    if failures:
        return "failed", f"table_rows_failed:{failures}"
    return "translated", ""


def run_full_translation(
    out_dir: Path,
    *,
    route: str | None = "openai_compatible",
    chat: Any = None,
) -> dict[str, Any]:
    from doc_annotation_export import (
        _active_translation_strategy_version,
        _read_translation_sidecar,
        generate_annotation_translations,
    )

    root = Path(out_dir).expanduser().resolve()
    blocks_path = governed_artifact_path(root, "blocks.jsonl", category="pipeline", for_write=False)
    blocks = [row for row in read_jsonl(blocks_path) if isinstance(row, dict)]
    report_path = governed_artifact_path(root, "clarification_report.json", category="pipeline", for_write=False)
    clarification_report = _read_json(report_path)
    enabled = full_translation_enabled()
    plans: dict[str, dict[str, Any]] = {}
    texts: dict[str, tuple[str, str]] = {}
    block_units: dict[int, dict[str, Any]] = {}
    for index, block in enumerate(blocks):
        block_id = str(block.get("block_id") or "")
        plan = _regular_table_plan(block)
        if plan is not None:
            plans[block_id] = plan
            for unit in plan["units"]:
                text = str(unit.get("source_text") or "").strip()
                if text and _looks_translatable(text):
                    key = str(unit.get("translation_key") or "") or translation_key(text)
                    texts[key] = (f"table_{unit['role']}", text)
            continue
        text = _block_text(block)
        if text and _looks_translatable(text):
            unit = _finalize_unit({
                "unit_id": f"{block_id or f'block-{index + 1}'}:block",
                "role": "block",
                "row_index": None,
                "source_cells": [text],
                "source_text": text,
            })
            block_units[index] = unit
            texts[unit["translation_key"]] = (str(block.get("block_type") or "block"), text)
    for text in _clarification_texts(clarification_report):
        texts[translation_key(text)] = ("clarification", text)

    translation_summary: dict[str, Any] = {
        "route": "stub", "model": "", "cached": 0, "translated": 0,
        "rejected": 0, "unresolved": len(texts), "batch_calls": 0, "failed_calls": 0,
    }
    if enabled and texts:
        translation_summary = generate_annotation_translations(
            root, route=route, texts=texts, chat=chat
        )
    sidecar = _read_translation_sidecar(root)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    strategy = _active_translation_strategy_version()
    rows: list[dict[str, Any]] = []
    block_counts = {"translated": 0, "failed": 0, "skipped": 0}
    table_row_counts = {"translated": 0, "failed": 0, "skipped": 0}
    fallback_tables = 0
    for index, block in enumerate(blocks):
        block_id = str(block.get("block_id") or f"block-{index + 1}")
        source = _block_text(block)
        plan = plans.get(block_id)
        record_kind = "block"
        table_payload: dict[str, Any] | None = None
        if plan is not None:
            dispositions = [
                _unit_disposition(
                    unit, enabled=enabled, sidecar=sidecar,
                    translation_summary=translation_summary,
                )
                for unit in plan["units"]
            ]
            status, reason = _aggregate_status(dispositions)
            if plan["header_fallback"]:
                fallback_tables += 1
            for disposition in dispositions:
                if disposition.get("role") in {"header", "data"}:
                    table_row_counts[disposition["status"]] += 1
            record_kind = "table"
            table_payload = {
                key: value for key, value in plan.items() if key != "units"
            }
            table_payload["rows"] = dispositions
            key = ""
            source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
            translation = ""
            model = translation_summary.get("model") or ""
            strategy_value = strategy
        else:
            # 非表格块走与表格单元同一处置语义（v3 前此处内联重写一份，语义会漂移）。
            unit = block_units.get(index) or _finalize_unit({
                "unit_id": f"{block_id}:block",
                "role": "block",
                "row_index": None,
                "source_cells": [source] if source else [],
                "source_text": source,
            })
            disposition = _unit_disposition(
                unit, enabled=enabled, sidecar=sidecar,
                translation_summary=translation_summary,
            )
            status, reason = disposition["status"], disposition["reason"]
            key = disposition["translation_key"]
            translation = disposition["translation"]
            source_sha = disposition["source_sha256"]
            model = disposition["model"]
            strategy_value = disposition.get("strategy_version") or strategy
            if str(block.get("type") or block.get("block_type") or "") == "table":
                record_kind = "complex_table"
        block_counts[status] += 1
        record = {
            "schema_version": DOCUMENT_TRANSLATION_SCHEMA_VERSION,
            "record_kind": record_kind,
            "block_id": block_id,
            "block_index": index,
            "status": status,
            "reason": reason,
            "source_text": source,
            "translation": translation if record_kind != "table" else "",
            "provenance": {
                "producer": FULL_TRANSLATION_VERSION,
                "source_sha256": source_sha,
                "translation_key": key,
                "route": translation_summary.get("route") or "stub",
                "model": model,
                "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
                "strategy_version": strategy_value,
                "generated_at": generated_at,
            },
        }
        if table_payload is not None:
            record["table"] = table_payload
        rows.append(record)

    ledger_path = governed_artifact_path(root, DOCUMENT_TRANSLATIONS, category="pipeline")
    document_html_path = governed_artifact_path(root, DOCUMENT_TRANSLATION_HTML, category="pipeline")
    clarification_html_path = governed_artifact_path(root, CLARIFICATION_BILINGUAL_HTML, category="pipeline")
    _atomic_write(ledger_path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _atomic_write(document_html_path, _render_document_html(rows))
    accepted = {
        key: str(entry.get("translation") or "").strip()
        for key, entry in sidecar.items()
        if str(entry.get("translation") or "").strip() and not entry.get("rejected")
    }
    _atomic_write(
        clarification_html_path,
        _render_clarification_html(clarification_report, accepted),
    )
    eligible = block_counts["translated"] + block_counts["failed"]
    coverage = round(block_counts["translated"] / eligible, 6) if eligible else 1.0
    table_eligible = table_row_counts["translated"] + table_row_counts["failed"]
    table_coverage = (
        round(table_row_counts["translated"] / table_eligible, 6)
        if table_eligible else 1.0
    )
    quality = {
        "version": FULL_TRANSLATION_VERSION,
        "enabled": enabled,
        "total_blocks": len(rows),
        "counts": block_counts,
        "eligible_blocks": eligible,
        "coverage": coverage,
        "coverage_percent": round(coverage * 100, 2),
        "meets_99_percent": coverage >= 0.99,
        "table_rows": {
            "counts": table_row_counts,
            "eligible_rows": table_eligible,
            "coverage": table_coverage,
            "coverage_percent": round(table_coverage * 100, 2),
            "header_fallback_tables": fallback_tables,
        },
        "translation_calls": {
            key: translation_summary.get(key, 0)
            for key in ("cached", "translated", "rejected", "unresolved", "batch_calls", "failed_calls")
        },
        "route": translation_summary.get("route") or "stub",
        "model": translation_summary.get("model") or "",
    }
    _update_quality_report(root, quality)
    return {
        "kind": "full_translation",
        "out_dir": str(root),
        "route": quality["route"],
        "quality": quality,
        "translations": translation_summary,
        "written": [str(ledger_path), str(document_html_path), str(clarification_html_path)],
    }
