from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from atomic_requirement_schema import validate_atomic_requirements
from docx_table_parser import DOCX_TABLE_PHYSICAL_VERSION, ParsedDocxTable, parse_docx_table
from domain_pack import load_domain_pack
from output_writer import build_quality_report, write_json, write_jsonl, write_summary
from parsers.docx_extra_channels import extract_docx_extra_channels
from requirement_kb import KnowledgeRepository
from requirement_kb.matching import TEXT_REPLACEMENTS, compile_term_pattern, find_matched_terms, normalize_match_term
from source_spans import source_alignment_fields
from result_package import governed_artifact_path
from table_dispositions import (
    TABLE_DISPOSITION_RULE_VERSION,
    build_table_cell_dispositions,
)
from unextracted_registry import build_unextracted_registry, write_unextracted_registry
from table_pattern_engine import load_table_patterns, match_table_pattern
from table_structure import (
    TABLE_STRUCTURE_VERSION,
    _DISPOSITION_HEADER_RE,
    _MATRIX_DIMENSION_MAX_LEN,
    NOTE_HEADER_RE,
    PARAM_INDEX_CELL_RE,
    analyze_table,
    build_cell_items,
    cell_context_text,
    classify_table_kind as classify_table_kind_structure,
    effective_headers as structure_effective_headers,
    inherit_merged_text,
    is_normative_text as structure_is_normative_text,
    marker_majority_columns,
    matrix_dimension_evidence,
    matrix_fact_columns,
    merge_ranges_overlap,
    normalize_merge_ranges,
    plan_table_leaves,
    row_bears_normative_sentence,
    row_is_weak_signal,
    strip_lettered_header_prefix,
    table_geometry_context,
    validate_merge_text,
)
from table_structure import (
    TABLE_DUAL_TRACK_SWITCH,
    dual_track_enabled,
    structure_from_hypothesis,
)
from tender_table_filter import TENDER_TABLE_FILTER_VERSION, classify_tender_table_kind
from version import __version__


LOGGER = logging.getLogger("requirement_atomizer")
SUPPORTED_INPUT_FORMATS = (".docx", ".xlsx", ".pdf", ".html")

# S1-4：WS1 双轨入口（LLM 提议→几何校验签发）。开关默认 OFF；OFF 时 ``analyze_table``
# 确定性路径逐字节不变（硬判据）。``_TABLE_DUAL_TRACK_PROPOSER`` 由具备 LLM 配置的调用方
# （desktop_tasks）经 ``set_table_dual_track_proposer`` 挂载；atomize 自己只做几何校验 +
# 假设派生结构 + 签发假设落盘（确定性，零 LLM）。``_TABLE_STRUCTURE_HYPOTHESES`` 为本次
# 运行累积的签发记录，``run_atomizer_pipeline`` 在抽取后落盘 ``table_structure_hypotheses.jsonl``。
_TABLE_DUAL_TRACK_PROPOSER: Any = None
_TABLE_STRUCTURE_HYPOTHESES: list[dict[str, Any]] = []
TABLE_STRUCTURE_HYPOTHESES_FILENAME = "table_structure_hypotheses.jsonl"
SIGNED_HYPOTHESIS_SCHEMA = "signed-table-hypothesis/v1"


def set_table_dual_track_proposer(proposer: Any) -> None:
    """挂载双轨提议器（``proposer(parsed_table, *, table_id, block_id, section_path) ->
    TableUnderstandingResult | None``）。由具备 openai_compatible 配置的调用方挂载。"""
    global _TABLE_DUAL_TRACK_PROPOSER
    _TABLE_DUAL_TRACK_PROPOSER = proposer


def clear_table_dual_track_proposer() -> None:
    """卸载提议器并清空本次运行的假设累积（desktop_tasks 在 run 结束后调用）。"""
    global _TABLE_DUAL_TRACK_PROPOSER
    _TABLE_DUAL_TRACK_PROPOSER = None
    _TABLE_STRUCTURE_HYPOTHESES.clear()


def _reset_table_structure_hypotheses() -> None:
    _TABLE_STRUCTURE_HYPOTHESES.clear()


def _dual_track_docx_structure(
    parsed: ParsedDocxTable,
    *,
    table_id: str,
    block_id: str,
    section_path: list[str],
    headers_hint: list[str] | None = None,
    document_id: str = "",
) -> dict[str, Any] | None:
    """S1-4：对 docx 表跑双轨（提议→几何签发）；issued 返回假设派生结构，否则 None。

    OFF / 无提议器 / 提议失败 / 未签发 → 返回 ``None``，调用方走确定性 ``analyze_table``
    （字节不变）。签发成功的假设记入 ``_TABLE_STRUCTURE_HYPOTHESES`` 供落盘 + 角色抽审。
    """
    if not dual_track_enabled() or _TABLE_DUAL_TRACK_PROPOSER is None:
        return None
    try:
        result = _TABLE_DUAL_TRACK_PROPOSER(
            parsed, table_id=table_id, block_id=block_id, section_path=section_path
        )
    except Exception as exc:  # noqa: BLE001 — 提议器失败诚实回退确定性，不阻断解析
        LOGGER.warning("dual-track proposer 失败，回退确定性几何：%s", exc)
        return None
    if result is None:
        return None
    hypothesis = getattr(result, "hypothesis", None)
    status = str(getattr(result, "status", "") or "")
    if hypothesis is None or status != "proposed":
        return None  # unavailable（无 route / 调用失败 / 返回非法）→ fallback_no_hypothesis
    try:
        from table_geometry_validator import ISSUED, validate_table_geometry

        signed = validate_table_geometry(hypothesis, parsed)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("dual-track 几何校验失败，回退确定性几何：%s", exc)
        return None
    if str(getattr(signed, "status", "") or "") != ISSUED:
        # partial_conflict / invalidated → fallback_validation_failed（确定性兜底）。
        # 冲突集路由到人工面板留作后续；本切片不阻断，产物与 OFF 一致。
        return None
    _record_signed_hypothesis(
        parsed,
        hypothesis=hypothesis,
        table_id=table_id,
        block_id=block_id,
        section_path=section_path,
        headers_hint=headers_hint,
        family_id=str(getattr(result, "family_id", "") or ""),
        document_id=document_id,
    )
    return structure_from_hypothesis(parsed.matrix, hypothesis)


def _record_signed_hypothesis(
    parsed: ParsedDocxTable,
    *,
    hypothesis: dict[str, Any],
    table_id: str,
    block_id: str,
    section_path: list[str],
    headers_hint: list[str] | None,
    family_id: str,
    document_id: str,
) -> None:
    """把签发的假设记入本次运行累积（落盘 ``table_structure_hypotheses.jsonl`` 的单条记录）。"""
    cells_meta: list[dict[str, Any]] = []
    headers = list(headers_hint or [])
    for (row, col), cell in getattr(parsed, "cells", {}).items():
        role = ""
        for entry in hypothesis.get("cells") or []:
            coord = entry.get("coordinate")
            if isinstance(coord, (list, tuple)) and len(coord) == 2 \
                    and int(coord[0]) == int(row) and int(coord[1]) == int(col):
                role = str(entry.get("role") or "")
                break
        cells_meta.append({
            "row_index": int(row),
            "column_index": int(col),
            "text": str(getattr(cell, "text", "") or ""),
            "structural_role": role,
        })
    _TABLE_STRUCTURE_HYPOTHESES.append({
        "schema": SIGNED_HYPOTHESIS_SCHEMA,
        "document_id": document_id,
        "table_id": table_id,
        "block_id": block_id,
        "section_path": list(section_path or []),
        "family_id": family_id,
        "validator_status": "issued",
        "headers": headers,
        "hypothesis": hypothesis,
        "_cells": cells_meta,
    })


def _flush_table_structure_hypotheses(out_dir: Path, *, document_id: str = "") -> int:
    """S1-4：把本次运行签发的假设落盘到 governed ``table_structure_hypotheses.jsonl``。

    仅在双轨开 + 有签发假设时写；OFF 或无假设时不写任何文件（产物与 main 一致）。
    返回写入条数。落盘走 governed_artifact_path（legacy 布局=根目录，table_role_audit 读处；
    package_v1 布局=.ratomizer/pipeline/，由结果包登记发布）。document_id 在落盘时统一盖戳
    （run_atomizer_pipeline 知道文档身份，per-table 记录无需各自携带）。
    """
    if not dual_track_enabled() or not _TABLE_STRUCTURE_HYPOTHESES:
        return 0
    from result_package import governed_artifact_path

    records = [
        {**record, "document_id": document_id or record.get("document_id") or ""}
        for record in _TABLE_STRUCTURE_HYPOTHESES
    ]
    target = governed_artifact_path(
        out_dir, TABLE_STRUCTURE_HYPOTHESES_FILENAME, category="pipeline", for_write=True
    )
    write_jsonl(target, records)
    return len(records)





DEFAULT_MAJOR_HEADINGS = (
    "scope",
    "normative references",
    "terms and definitions",
    "architecture",
    "communication profile",
    "communication profiles",
    "security",
    "bibliography",
    "figures",
    "tables",
)

DEFAULT_NOISE_PATTERNS = (
    r"abnt 2022",
    r"all rights reserved",
)
DEFAULT_NOISE_EXACT = (
    "abnt",
    "abnt nbr",
    "abnt nbr 16968:2022",
)
DEFAULT_CAPTION_PATTERN = r"^(table|figure)\s+\d+\b"
DEFAULT_BODY_START_HEADING = "scope"

DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("communication_profile", ("communication profile", "plc", "prime", "wi-sun", "lorawan", "rf", "network", "media of communication")),
    ("security_policy", ("security", "authenticated", "authentication", "encrypted", "encryption", "hls", "password", "key agreement", "digital signature", "aes-gcm", "ecdsa", "ecdh")),
    ("association", ("association", "sap", "logical device", "client", "server application")),
    ("obis_code", ("obis", "logical name", "code obis")),
    ("cosem_object", ("cosem", "interface class", "class_id", "attribute", "method")),
    ("event", ("event", "events", "event log", "group/subgroup")),
    ("alarm", ("alarm", "alarms")),
    ("error", ("error", "errors")),
    ("register", ("register", "energy register", "demand register")),
    ("billing_profile", ("billing", "periods of billing", "billing profile")),
    ("load_profile", ("load profile", "load curve")),
    ("firmware_update", ("firmware", "update of firmware")),
    ("meter_function", ("smart electricity meter", "meter", "measurement", "measuring")),
    ("power_quality", ("power quality", "qee", "quality of energy", "voltage", "current")),
    ("data_model", ("data model", "objects", "abstract object", "object related")),
]
DOMAIN_RULE_PATTERNS = [(tag, compile_term_pattern(keywords)) for tag, keywords in DOMAIN_RULES]

OBJECT_NAME_STOPWORDS = {
    "A",
    "An",
    "For",
    "If",
    "In",
    "It",
    "Numbers",
    "O",
    "Only",
    "Table",
    "The",
    "This",
    "To",
    "You",
}

DEFAULT_ACCESS_RIGHT_CLIENTS = {
    "RC": "remote management and measurement client",
    "PC": "read client",
    "SC": "service/local or specialized client depending on table context",
    "LC": "local management and measurement client",
}


class AtomizerInputError(ValueError):
    pass


class AtomizerPipelineError(RuntimeError):
    pass


def normalize_profile_value(text: str) -> str:
    return re.sub(r"\s+", " ", clean_text(text).lower().rstrip(":")).strip()


@dataclass(frozen=True)
class DocumentProfile:
    noise_patterns: tuple[str, ...] = DEFAULT_NOISE_PATTERNS
    noise_exact: tuple[str, ...] = DEFAULT_NOISE_EXACT
    major_headings: tuple[str, ...] = DEFAULT_MAJOR_HEADINGS
    caption_pattern: str = DEFAULT_CAPTION_PATTERN
    body_start_heading: str = DEFAULT_BODY_START_HEADING

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "DocumentProfile":
        if not payload:
            return cls()
        defaults = cls()
        return cls(
            noise_patterns=tuple(str(value) for value in payload.get("noise_patterns", defaults.noise_patterns)),
            noise_exact=tuple(normalize_profile_value(str(value)) for value in payload.get("noise_exact", defaults.noise_exact)),
            major_headings=tuple(normalize_profile_value(str(value)) for value in payload.get("major_headings", defaults.major_headings)),
            caption_pattern=str(payload.get("caption_pattern", defaults.caption_pattern)),
            body_start_heading=normalize_profile_value(str(payload.get("body_start_heading", defaults.body_start_heading))),
        )

    # is_noise/detect_heading 每段正文要跑 2-3+ 次，成员判定集合一次冻结缓存
    # （cached_property 直接写实例 __dict__，frozen dataclass 的 __hash__/__eq__
    # 只看声明字段，缓存不改变等值/哈希语义）
    @cached_property
    def noise_exact_set(self) -> frozenset[str]:
        return frozenset(self.noise_exact)

    @cached_property
    def major_headings_set(self) -> frozenset[str]:
        return frozenset(self.major_headings)


DEFAULT_DOCUMENT_PROFILE = DocumentProfile()


KnowledgeBase = KnowledgeRepository


@dataclass
class SectionState:
    levels: dict[int, str] = field(default_factory=dict)

    def update(self, level: int, title: str) -> list[str]:
        self.levels[level] = title
        for old_level in list(self.levels):
            if old_level > level:
                del self.levels[old_level]
        return self.path()

    def path(self) -> list[str]:
        return [self.levels[level] for level in sorted(self.levels)]


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    for source, replacement in TEXT_REPLACEMENTS.items():
        value = value.replace(source, replacement)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def iter_body_items(document: DocxDocument) -> Iterable[Paragraph | Table]:
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def is_noise(text: str, *, document_profile: DocumentProfile | None = None) -> bool:
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    low = text.lower()
    if not text:
        return True
    if any(re.search(pattern, low, flags=re.I) for pattern in profile.noise_patterns):
        return True
    if normalize_profile_value(low) in profile.noise_exact_set:
        return True
    if re.fullmatch(r"\d+\s+pages?", low):
        return True
    if re.fullmatch(r"[ivxlcdm]+", low):
        return True
    if re.fullmatch(r"\d+", text):
        return True
    return False


def has_numbering(paragraph: Paragraph) -> bool:
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.numPr is not None


def numbering_level(paragraph: Paragraph) -> int | None:
    p_pr = paragraph._p.pPr
    num_pr = p_pr.numPr if p_pr is not None else None
    if num_pr is None:
        return None
    ilvl = num_pr.ilvl
    if ilvl is None or ilvl.val is None:
        return 0
    try:
        return int(ilvl.val)
    except (TypeError, ValueError):
        return 0


def detect_heading(
    text: str,
    style_name: str,
    is_list_item: bool = False,
    *,
    document_profile: DocumentProfile | None = None,
) -> tuple[int, str] | None:
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    if not text or is_noise(text, document_profile=profile):
        return None

    style_low = style_name.lower()
    match = re.search(r"heading\s+(\d+)", style_low)
    if match:
        return min(int(match.group(1)), 6), text

    normalized = text.strip().lower().rstrip(":")
    if normalized in profile.major_headings_set:
        return 1, text

    numbered = re.match(r"^(\d+(?:\.\d+)*)(?:\s+|\.\s+)(.{3,})$", text)
    if numbered:
        number, title = numbered.groups()
        title = title.strip()
        # A large bare integer is overwhelmingly a quantity or table value, not
        # a top-level clause number (for example, "100 litres of water ...").
        # Keep explicit Heading styles authoritative, but protect all heuristic
        # callers, including DOCX, instead of relying on the PDF-only refinement.
        if "." not in number and int(number) > 40:
            return None
        if not looks_like_toc_entry(title) and not looks_like_caption(text, document_profile=profile):
            return min(number.count(".") + 1, 6), f"{number} {title}"

    if (
        style_low == "list paragraph"
        and not is_list_item
        and len(text) <= 80
        and not text.endswith(".")
        and not looks_like_caption(text, document_profile=profile)
    ):
        if re.search(r"[A-Za-z]", text):
            return 2, text

    return None


def looks_like_toc_entry(text: str) -> bool:
    if re.search(r"\s+\d{1,3}$", text):
        return True
    if text.lower().endswith("page"):
        return True
    return False


def looks_like_caption(text: str, *, document_profile: DocumentProfile | None = None) -> bool:
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    return bool(re.match(profile.caption_pattern, text.strip(), flags=re.I))


def infer_table_title(last_caption: str | None, table_index: int) -> str:
    if last_caption:
        return last_caption
    return f"Table {table_index}"


def unique_headers(raw_headers: list[str], width: int) -> list[str]:
    headers: list[str] = []
    counts: Counter[str] = Counter()
    for index in range(width):
        base = clean_text(raw_headers[index]) if index < len(raw_headers) else ""
        if not base:
            base = f"column_{index + 1}"
        counts[base] += 1
        headers.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return headers


def table_matrix(table: Table) -> list[list[str]]:
    matrix: list[list[str]] = []
    for row in table.rows:
        matrix.append([clean_text(cell.text) for cell in row.cells])
    return matrix


def docx_table_grid_evidence(
    table: Table,
) -> tuple[list[tuple[int, int, int, int]], list[int], bool]:
    """DOCX 表 XML 级结构证据：gridSpan/vMerge 合并区域 + tblHeader 显式表头行。

    纯确定性解析 OOXML；python-docx 的 row.cells 已把合并值填充到覆盖格（扁平矩阵
    口径不变），这里只还原合并关系本身，供 table_structure 判标题/分组/canonical cell。

    vMerge 链按 anchor 归组：一次 restart 只登记一个 anchor，continue 推进该格
    gridSpan 覆盖的全部列游标所属的 anchor，关闭时每个 anchor 恰好产出一个
    range——同一逻辑合并绝不拆成重叠双份（此前逐游标存链会把二维 merge 拆成
    (1,1,1,2)+(1,1,2,2) 的重叠证据）。continue 无 anchor / 横跨多个 anchor /
    与本行普通格冲突 = 结构矛盾 → merge_conflict=True，调用方放弃全部合并证据
    （保留文本、结构标 needs_review），绝不伪造。
    """
    merge_ranges: list[tuple[int, int, int, int]] = []
    explicit_header_rows: list[int] = []
    # anchor_key=(row, col) → {"col_span": int, "last_row": int, "cursors": set[int]}
    anchors: dict[tuple[int, int], dict[str, Any]] = {}
    cursor_to_anchor: dict[int, tuple[int, int]] = {}
    merge_conflict = False

    def close_anchor(key: tuple[int, int]) -> None:
        state = anchors.pop(key, None)
        if state is None:
            return
        for cursor in state["cursors"]:
            cursor_to_anchor.pop(cursor, None)
        anchor_row, anchor_col = key
        if state["last_row"] > anchor_row or state["col_span"] > 1:
            merge_ranges.append(
                (anchor_row, anchor_col, state["last_row"], anchor_col + state["col_span"] - 1)
            )

    for row_index, tr in enumerate(table._tbl.tr_lst, start=1):
        tr_pr = tr.trPr
        if tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None:
            explicit_header_rows.append(row_index)
        column_cursor = 1
        seen_columns: set[int] = set()
        continued_this_row: set[tuple[int, int]] = set()

        def close_anchors_on(cursors: Iterable[int]) -> None:
            nonlocal merge_conflict
            keys = {cursor_to_anchor[c] for c in cursors if c in cursor_to_anchor}
            for key in keys:
                if key in continued_this_row:
                    # 同一逻辑合并在本行一部分 continue、一部分出现普通格 = 矛盾
                    merge_conflict = True
                close_anchor(key)

        for tc in tr.tc_lst:
            tc_pr = tc.tcPr
            col_span = 1
            vmerge_val: str | None = None
            has_vmerge = False
            if tc_pr is not None:
                grid_span = tc_pr.find(qn("w:gridSpan"))
                if grid_span is not None:
                    try:
                        col_span = max(1, int(grid_span.get(qn("w:val")) or 1))
                    except ValueError:
                        col_span = 1
                vmerge = tc_pr.find(qn("w:vMerge"))
                if vmerge is not None:
                    has_vmerge = True
                    vmerge_val = vmerge.get(qn("w:val")) or "continue"
            cursors = set(range(column_cursor, column_cursor + col_span))
            seen_columns |= cursors
            if has_vmerge and vmerge_val == "restart":
                close_anchors_on(cursors)
                key = (row_index, column_cursor)
                anchors[key] = {
                    "col_span": col_span,
                    "last_row": row_index,
                    "cursors": cursors,
                }
                for cursor in cursors:
                    cursor_to_anchor[cursor] = key
            elif has_vmerge:
                keys = {cursor_to_anchor.get(cursor) for cursor in cursors}
                if None in keys or len(keys) != 1:
                    # continue 无 anchor 或横跨多个 anchor = 结构矛盾
                    merge_conflict = True
                else:
                    key = next(iter(keys))
                    anchors[key]["last_row"] = max(anchors[key]["last_row"], row_index)
                    continued_this_row.add(key)
            else:
                close_anchors_on(cursors)
                if col_span > 1:
                    merge_ranges.append(
                        (row_index, column_cursor, row_index, column_cursor + col_span - 1)
                    )
            column_cursor += col_span
        # 本行未出现的列若挂着 vmerge 链 → 链在此行之前终止
        for cursor in list(cursor_to_anchor):
            if cursor not in seen_columns:
                key = cursor_to_anchor[cursor]
                if key in continued_this_row:
                    merge_conflict = True
                close_anchor(key)
    for key in list(anchors):
        close_anchor(key)
    # 去重（同一区域被不同路径各记一次的防御）并升序
    deduped = sorted(set(merge_ranges))
    return deduped, explicit_header_rows, merge_conflict


def _collapse_merged_title_row(
    row: list[str],
    row_index: int,
    merge_ranges: list[tuple[int, int, int, int]],
    width: int,
) -> list[str]:
    """标题行的合并覆盖塌缩：锚格保留文本、覆盖格清空（镜像 docx 物理网格）。

    xlsx 的 _region_matrix 把合并值扁平填充到全部覆盖格（by design）——全宽
    合并标题行照抄矩阵会把同一文本带 N 份进块载荷，全文翻译逐格拼成
    "Title | Title | Title"。标题行由全宽合并锚行检测识别（detect_title_rows），
    塌缩精确而非启发式；存活 range 已过 validate_merge_text（覆盖格为空或与
    锚逐字一致），清空绝不丢内容。仅标题行走此口径——数据/表头行的扁平填充
    是 xlsx 数据行可见性的独立行为，不在本函数范围。"""
    cells = pad_row(row, width)
    for min_row, min_col, max_row, max_col in merge_ranges:
        if not min_row <= row_index <= max_row:
            continue
        for column in range(min_col, max_col + 1):
            if (row_index, column) != (min_row, min_col) and column <= width:
                cells[column - 1] = ""
    return cells


def build_table_artifacts(
    matrix: list[list[str]],
    *,
    raw_matrix: list[list[str]] | None = None,
    table_id: str,
    block_id: str,
    order: int,
    table_title: str,
    section_path: list[str],
    knowledge_bases: KnowledgeRepository,
    parse_incomplete: bool = False,
    parse_incomplete_reason: dict[str, Any] | None = None,
    merge_ranges: Iterable[Iterable[int]] | None = None,
    merge_evidence_conflict: bool = False,
    explicit_header_rows: list[int] | None = None,
    source_format: str = "docx",
    sheet_name: str | None = None,
    a1_origin: tuple[int, int] | None = None,
    page_number: int | None = None,
    cell_bboxes: dict[tuple[int, int], Any] | None = None,
    geometry_kind: str | None = None,
    cell_metadata: dict[tuple[int, int], dict[str, Any]] | None = None,
    structure_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """表格三件套：block + table_items（行容器）+ table_cell_items（canonical cells）。

    table-structure-v2：标题/表头/合并/粒度全部由 table_structure 确定性识别；
    不新增顶层 block，行/格身份用 item_id/cell_id。

    S1-4：``structure_override``（非 None 时）跳过 ``analyze_table``，直接用 WS1 双轨
    签发的假设派生结构（``structure_from_hypothesis`` 形状）。``None``（默认）= 旧确定性
    ``analyze_table`` 路径逐字节不变（OFF 硬判据）。调用方仅在 ``dual_track_enabled()`` 且
    几何校验签发 issued 时才传 override。
    """
    normalized_merges = normalize_merge_ranges(merge_ranges)
    # 合并证据矛盾（上游解析冲突/面积相交）→ 放弃精确几何、保留全部文本，
    # 结构标 needs_review；绝不拿自相矛盾的 merge 照常产出（伪造合并事故）
    if merge_ranges is None:
        merge_evidence_status = "unavailable"
    elif normalized_merges:
        merge_evidence_status = "available"
    else:
        merge_evidence_status = "known_none"
    if merge_evidence_conflict or (
        normalized_merges and merge_ranges_overlap(normalized_merges)
    ):
        normalized_merges = []
        merge_evidence_status = "dropped_conflict"
    else:
        # B6：被覆盖格文本校验——covered 坐标的几何身份只是上游主张，其文本
        # 非空且与 anchor 不逐字一致时，该 range 覆盖的是另一条独立内容；
        # 照常合并会让被覆盖义务随 cell 删除消失（计数器全零的静默丢失）。
        # 冲突 range 整体拒收（全部格保留为独立 cell），结构标 needs_review
        valid_merges, text_conflicts = validate_merge_text(matrix, normalized_merges)
        if text_conflicts:
            normalized_merges = valid_merges
            merge_evidence_status = "dropped_text_conflict"
    structure = structure_override if structure_override is not None else analyze_table(
        matrix,
        # 当前解析无几何证据与确认无合并都不得授予分组标题；区别只通过
        # merge_evidence_status 如实保留，旧产物由版本迁移门处理。
        merge_ranges=normalized_merges,
        explicit_header_rows=explicit_header_rows,
    )
    width = structure["width"]
    height = structure["height"]
    title_row_indexes = structure["title_row_indexes"]
    header_row_indexes = structure["header_row_indexes"]
    data_row_indexes = structure["data_row_indexes"]
    # 歧义"表头"保留结构角色（规范性内容经 structural_row 出 cell claim），但
    # 其文本不得参与列名渲染：按行过滤——单格题注候选（ambiguous_structure_rows）
    # /义务句行（modal/pattern）/弱信号说明句行（sentence_shape）永不充当列名
    # （"Outputs selected by the operator" 类句子列名事故），列名回退 column_N；
    # 其余干净表头行仍供给列名——v4 首版只要状态 ambiguous 就整表坍缩 column_N，
    # 首行单格题注候选会把次行的真实表头（Label/Value/Formula）一并灭失
    ambiguous_row_set = set(structure.get("ambiguous_structure_rows") or [])
    naming_row_indexes = [
        row_index
        for row_index in header_row_indexes
        if row_index not in ambiguous_row_set
        and not row_bears_normative_sentence(matrix[row_index - 1])
        and not row_is_weak_signal(matrix[row_index - 1])
    ]
    header_count = len(header_row_indexes)
    header_rows = [pad_row(matrix[row_index - 1], width) for row_index in header_row_indexes]
    data_rows = [pad_row(matrix[row_index - 1], width) for row_index in data_row_indexes]
    # 全部标题行（不止提升为 table_title 的首行）进块：全文档翻译的堆叠标题/副标题行
    # 需要逐行单元，否则第二行起的标题文本不进任何翻译单元（静默丢失）。
    # 标题行同时塌缩合并覆盖（锚格保留、覆盖格清空）：xlsx 扁平填充的全宽标题行
    # 若照抄矩阵，同一文本 N 份进 title_rows → LLM 输入/账本/HTML 三处重复，
    # 且拼接串与 table_title 不同文使题注去重失效。
    title_rows = [
        _collapse_merged_title_row(matrix[row_index - 1], row_index, normalized_merges, width)
        for row_index in title_row_indexes
    ]
    # 有效矩阵（covered 坐标继承 anchor 文本）只用于分类/表头/事实列判定——
    # 与 docx 扁平填充口径对齐（纵向合并的对象名对后续行可见）；
    # 块渲染与行/格正文恒用真实矩阵
    effective_matrix = inherit_merged_text(matrix, normalized_merges)
    effective_data_rows = [
        pad_row(effective_matrix[row_index - 1], width) for row_index in data_row_indexes
    ]
    headers = effective_table_headers(
        [
            pad_row(effective_matrix[row_index - 1], width)
            for row_index in naming_row_indexes
        ],
        width,
    )
    classification_headers = headers
    if "sequential_clause_rows:headerless" in structure.get("header_detection_evidence", []):
        # A page-continuation fragment has no source header to display or send to
        # prompts, so its public headers remain honest ``column_N`` fallbacks.
        # The consecutive clause-number evidence nevertheless proves the common
        # ``clause | specification | values...`` row shape; use semantic labels
        # only inside deterministic kind classification so the rows stay atomic
        # instead of degrading into unrelated cell candidates.
        classification_headers = [
            "clause_index",
            "Specification",
            *[f"value_{index}" for index in range(1, max(1, width - 1))],
        ][:width]
    # 标题行（全宽合并）提升为表标题；无标题行时保留 caption/sheet/回退标题
    if title_row_indexes:
        first_title_row = matrix[title_row_indexes[0] - 1]
        title_text = next((clean_text(value) for value in first_title_row if clean_text(value)), "")
        if title_text:
            table_title = title_text
    table_kind = classify_table_kind_structure(
        classification_headers, effective_data_rows, section_path
    )
    # A9-1：商务/表单表识别（默认关，OFF 时逐字节不变）
    tender_table_kind = classify_tender_table_kind(
        headers=headers,
        data_rows=effective_data_rows,
        section_path=section_path,
        table_title=table_title,
    )
    # 矩阵事实列：mapping_matrix 全表取；parameter/other 组合表（DLMS 属性×服务矩阵）
    # 也取——marker 格按 cell 闭环（mixed），COSEM 行 join 与 A 轨能力事实同时保留。
    # P0-4：唯一来源是共享的正向维度证据（一次计算，分类/plan/块载荷/A 轨同消费）
    dimension_evidence = matrix_dimension_evidence(headers, effective_data_rows)
    fact_columns = set(dimension_evidence)
    rejected_marker_columns = {
        column
        for column in marker_majority_columns(headers, effective_data_rows) - fact_columns
        if not NOTE_HEADER_RE.search(str(headers[column] or ""))
    }
    # plan_table_leaves 与 build_cell_items 顺序消费同一份表格几何——归一化合并/
    # covered 集/分组标题行一次算清共享，避免大表 O(合并面积) 重复付出两遍
    geometry = table_geometry_context(
        matrix, width=width, data_rows=data_row_indexes, merge_ranges=normalized_merges
    )
    plan = plan_table_leaves(
        structure, matrix, table_kind=table_kind,
        merge_ranges=normalized_merges,
        headers=headers, fact_columns=fact_columns,
        tender_table_kind=tender_table_kind,
        geometry=geometry,
    )
    table_text_full = render_table_text(headers, data_rows)
    # 2026-07-27 起扁平文本不再截断（impl-v6 取消 [:5000]、impl-v7 render 默认全行）：
    # text 恒为完整渲染，text_truncated 恒 False；字段保留供账本与旧产物判别。
    table_text = table_text_full
    text_truncated = False
    raw_source = raw_matrix or matrix
    raw_rows = [[str(value or "") for value in row] for row in raw_source]
    raw_header_rows = [
        pad_row(raw_rows[row_index - 1], width)
        for row_index in header_row_indexes
        if row_index - 1 < len(raw_rows)
    ]
    raw_data_rows = [
        pad_row(raw_rows[row_index - 1], width)
        for row_index in data_row_indexes
        if row_index - 1 < len(raw_rows)
    ]
    raw_headers = effective_table_headers(raw_header_rows, width)
    raw_table_text = render_table_text(raw_headers, raw_data_rows)
    kb_matches = match_knowledge(knowledge_bases, table_title, table_text, " > ".join(section_path))
    domain_tags = merge_tags(tag_domains(table_title, table_text, " > ".join(section_path)), kb_domain_tags(kb_matches))
    leaf_plan_payload = {
        "mode": plan["mode"],
        "row_leaves": list(plan["row_leaves"]),
        "cell_leaves": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in plan["cell_leaves"]
        ],
        "context_cells": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in plan["context_cells"]
        ],
        "multi_duty_cells": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in (plan.get("multi_duty_cells") or [])
        ],
        "weak_signal_cells": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in (plan.get("weak_signal_cells") or [])
        ],
        "unsignaled_data_cells": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in (plan.get("unsignaled_data_cells") or [])
        ],
        # P0-5：无结构证据的单格"标题/表头"——可定位的歧义资格候选，
        # 计数进账本审计并联动 needs_review，绝不静默关闭
        "ambiguous_structure_cells": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in (plan.get("ambiguous_structure_cells") or [])
        ],
        "untyped_colon_spec_cells": [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in (plan.get("untyped_colon_spec_cells") or [])
        ],
    }
    # A9-1：商务/表单表整表受控排除候选（默认关，OFF 时 leaf_plan 不含该键）
    if plan.get("tender_commercial_cells"):
        leaf_plan_payload["tender_commercial_cells"] = [
            f"{table_id}-R{row_index:06d}-C{column_index:06d}"
            for row_index, column_index in plan["tender_commercial_cells"]
        ]
    block = {
        "block_id": block_id,
        "order": order,
        "type": "table",
        "table_id": table_id,
        "table_title": table_title,
        "section_path": section_path,
        "source_format": source_format,
        "rows": height,
        "columns": width,
        "header_row_count": header_count,
        "header_rows": header_rows,
        "title_rows": title_rows,
        "headers": headers,
        # 完整数据行进块：批注视图渲染真表格（此前只有扁平 text，画线/无画线表都糊成一坨）
        "data_rows": data_rows,
        # 完整扁平文本进块（2026-07-27 修复：初始提交的 [:5000] 截断让大参数表 88% 内容
        # 进不了抽取管线——STO/俄标类文档规范全在百行级参数表里,B 轨只看到前几行。
        # 下游章节合并本就有 ~5k 字符切分,长文本自然分 chunk;批注视图走独立 data_rows）
        "text": table_text,
        "raw_text": raw_table_text,
        **source_alignment_fields(raw_table_text, table_text),
        "text_truncated": text_truncated,
        "parse_incomplete": bool(parse_incomplete),
        "domain_tags": domain_tags,
        "kb_matches": kb_matches,
        "requirement_like": is_requirement_like(table_text),
        "noise": False,
        # table-structure-v2 结构面
        "table_structure_version": TABLE_STRUCTURE_VERSION,
        "table_kind": table_kind,
        "leaf_mode": plan["mode"],
        "title_row_indexes": title_row_indexes,
        "header_row_indexes": header_row_indexes,
        "header_detection_status": structure["header_detection_status"],
        "header_detection_evidence": structure["header_detection_evidence"],
        "merge_evidence_status": merge_evidence_status,
        "merge_ranges": [list(entry) for entry in normalized_merges],
        "matrix_fact_columns": sorted(fact_columns),
        # P0-4：正向维度证据随块下发（审核面）——{0-based 列号: operation/
        # qualified_operation/axis_member}；下游（mixed 判定/marker 句式合成）只消费本结果与
        # matrix_fact_columns，禁止另行推导事实列
        "matrix_dimension_evidence": {
            str(column): tag for column, tag in dimension_evidence.items()
        },
        # marker 占多数但被维度证据闸拒收的列（B3/B4 审核面）：X 列的表头是处置词/
        # 泛称包装词/合成列名——marker 以原文保留（行容器/cell context），但不合成
        # 自然语言义务、也不成 cell leaf；非空即结构待审证据
        "matrix_rejected_marker_columns": sorted(rejected_marker_columns),
        "leaf_plan": leaf_plan_payload,
    }
    # A9-1：tender 商务/表单表识别标记（默认关，OFF 时字段不存在以保持字节一致）
    if tender_table_kind:
        block["tender_table_kind"] = tender_table_kind
        block["tender_table_filter_version"] = TENDER_TABLE_FILTER_VERSION
    if parse_incomplete_reason:
        block["parse_incomplete_reason"] = dict(parse_incomplete_reason)

    row_leaf_set = set(plan["row_leaves"])
    table_items: list[dict[str, Any]] = []
    current_cosem_object: dict[str, Any] | None = None
    for row_offset, row in enumerate(data_rows, start=1):
        row_index = data_row_indexes[row_offset - 1]
        if not any(row):
            continue
        fields = {
            headers[col_index]: row[col_index] if col_index < len(row) else ""
            for col_index in range(width)
        }
        compact_fields = {key: value for key, value in fields.items() if value}
        raw_row = raw_data_rows[row_offset - 1] if row_offset <= len(raw_data_rows) else row
        raw_fields = {
            headers[col_index]: raw_row[col_index] if col_index < len(raw_row) else ""
            for col_index in range(width)
            if headers[col_index] in compact_fields
        }
        field_provenance = {
            key: source_alignment_fields(str(raw_fields.get(key) or ""), str(value or ""))
            for key, value in compact_fields.items()
        }
        field_alignments = {
            key: provenance["source_alignment"] for key, provenance in field_provenance.items()
        }
        field_raw_to_repaired_spans = {
            key: provenance["raw_to_repaired_spans"] for key, provenance in field_provenance.items()
        }
        canonical_row_text = " | ".join(f"{key}={value}" for key, value in compact_fields.items())
        raw_row_text = " | ".join(
            f"{key}={raw_fields.get(key, '')}" for key in compact_fields)
        row_alignment = source_alignment_fields(raw_row_text, canonical_row_text)
        item_id = f"{table_id}-R{row_index:06d}"
        if is_cosem_object_header(compact_fields):
            current_cosem_object = build_cosem_object_context(item_id, row_index, compact_fields)
        # extract_matrix_facts 只允许对有真实矩阵事实列的表执行（mapping_matrix 全表，
        # 组合表仅限事实列）——普通参数表/Note 列一律为空（堵 "1 shall support Note."）
        matrix_facts = (
            extract_matrix_facts(headers, row, fact_columns=fact_columns)
            if fact_columns
            else []
        )
        fact_text = " | ".join(f"{fact['subject']} -> {fact['predicate_header']}" for fact in matrix_facts)
        context_text = " | ".join(str(value) for value in (current_cosem_object or {}).values() if value)
        item_text = " | ".join([*compact_fields.values(), fact_text, context_text])
        item_matches = match_knowledge(knowledge_bases, table_title, item_text, " > ".join(section_path))
        item_tags = merge_tags(tag_domains(table_title, item_text, " > ".join(section_path)), kb_domain_tags(item_matches))
        table_item = {
            "item_id": item_id,
            "type": "table_row",
            "table_id": table_id,
            "table_block_id": block_id,
            "table_title": table_title,
            "section_path": section_path,
            "row_index": row_index,
            "fields": compact_fields,
            "raw_fields": raw_fields,
            "field_alignments": field_alignments,
            "field_raw_to_repaired_spans": field_raw_to_repaired_spans,
            "text": canonical_row_text,
            "raw_text": raw_row_text,
            **row_alignment,
            "matrix_facts": matrix_facts,
            "domain_tags": item_tags,
            "kb_matches": item_matches,
            "requirement_like": is_requirement_like(item_text),
            "noise": False,
            # cell/mixed 模式中行仅作容器（COSEM join 保留），不再生成重复父 claim
            "leaf_role": "row" if row_index in row_leaf_set else "container",
        }
        if current_cosem_object and (is_cosem_object_header(compact_fields) or is_cosem_attribute_row(compact_fields)):
            table_item["cosem_object_context"] = current_cosem_object
        table_items.append(table_item)

    table_cell_items = build_cell_items(
        matrix,
        raw_matrix,
        structure,
        plan,
        table_id=table_id,
        block_id=block_id,
        table_title=table_title,
        section_path=section_path,
        headers=headers,
        table_kind=table_kind,
        source_format=source_format,
        merge_ranges=normalized_merges,
        sheet_name=sheet_name,
        a1_origin=a1_origin,
        page_number=page_number,
        cell_bboxes=cell_bboxes,
        geometry_kind=geometry_kind,
        fact_columns=fact_columns,
        cell_metadata=cell_metadata,
        geometry=geometry,
    )

    return block, table_items, table_cell_items


def interpret_table_matrix(matrix: list[list[str]]) -> dict[str, Any]:
    width = max((len(row) for row in matrix), default=0)
    # S1-4：双轨分支（xlsx/pdf 的轻量结构预览）。OFF → analyze_table 逐字节不变；
    # ON → analyze_table_dual_track（无 parsed_table 几何 → mode=fallback_no_hypothesis，
    # 结构与确定性一致，仅多一块 dual_track 审计标记；假设签发只发生在 docx 主路径）。
    if dual_track_enabled():
        from table_structure import analyze_table_dual_track

        structure = analyze_table_dual_track(matrix)
    else:
        structure = analyze_table(matrix)
    header_rows = [pad_row(matrix[row_index - 1], width) for row_index in structure["header_row_indexes"]]
    data_rows = [pad_row(matrix[row_index - 1], width) for row_index in structure["data_row_indexes"]]
    headers = effective_table_headers(header_rows, width)
    return {
        "width": width,
        "height": len(matrix),
        "header_row_count": structure["header_row_count"],
        "header_rows": header_rows,
        "headers": headers,
        "data_rows": data_rows,
    }


def pad_row(row: list[str], width: int) -> list[str]:
    return [row[index] if index < len(row) else "" for index in range(width)]


def row_has_data_markers(row: list[str]) -> bool:
    return any(is_positive_marker(value) for value in row)


def effective_table_headers(header_rows: list[list[str]], width: int) -> list[str]:
    if not header_rows:
        return unique_headers([], width)

    headers: list[str] = []
    for column_index in range(width):
        parts: list[str] = []
        seen: set[str] = set()
        for row in header_rows:
            value = clean_text(strip_lettered_header_prefix(
                row[column_index] if column_index < len(row) else ""
            ))
            key = normalize_header_part(value)
            if not value or key in seen:
                continue
            parts.append(value)
            seen.add(key)
        headers.append(" / ".join(parts) if parts else f"column_{column_index + 1}")
    return unique_headers(headers, width)


def normalize_header_part(value: str | None) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[_/\\-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_positive_marker(value: str | None) -> bool:
    normalized = normalize_header_part(value)
    return normalized in {"x", "yes", "true", "required", "mandatory", "applicable"}


def extract_matrix_facts(
    headers: list[str],
    row: list[str],
    *,
    fact_columns: set[int] | None = None,
) -> list[dict[str, Any]]:
    """矩阵事实抽取。

    fact_columns 为 None 时是遗留口径（所有非 subject 的 marker 格）；传入时（mapping_matrix
    专用）只有矩阵事实列的 marker 才算事实，subject 恒为行头（首列）——Note 列保持原文，
    不再产生 "1 shall support Note." 类伪句式。"""
    if fact_columns is not None:
        subject = clean_text(row[0]) if row else ""
        if not subject or is_positive_marker(subject):
            return []
        subject_header = headers[0] if headers else "column_1"
        facts = []
        for column_index in sorted(fact_columns):
            if column_index >= len(row):
                continue
            marker = clean_text(row[column_index])
            if not is_positive_marker(marker):
                continue
            facts.append(
                {
                    "subject_header": subject_header,
                    "subject": subject,
                    "predicate_header": headers[column_index] if column_index < len(headers) else f"column_{column_index + 1}",
                    "marker": marker,
                    "value": True,
                    "relation": "allowed",
                }
            )
        return facts
    subject_header, subject, subject_index = primary_row_subject(headers, row)
    if not subject:
        return []

    facts: list[dict[str, Any]] = []
    for column_index, value in enumerate(row):
        marker = clean_text(value)
        if column_index == subject_index or not is_positive_marker(marker):
            continue
        facts.append(
            {
                "subject_header": subject_header,
                "subject": subject,
                "predicate_header": headers[column_index] if column_index < len(headers) else f"column_{column_index + 1}",
                "marker": marker,
                "value": True,
                "relation": "allowed",
            }
        )
    return facts


def primary_row_subject(headers: list[str], row: list[str]) -> tuple[str, str, int]:
    for index, value in enumerate(row):
        cleaned = clean_text(value)
        if cleaned and not is_positive_marker(cleaned):
            header = headers[index] if index < len(headers) else f"column_{index + 1}"
            return header, cleaned, index
    return "", "", -1


def is_cosem_object_header(fields: dict[str, Any]) -> bool:
    return bool(first_field_value(fields, "Object/attribute name") and first_field_value(fields, "CL"))


def is_cosem_attribute_row(fields: dict[str, Any]) -> bool:
    return bool(first_field_value(fields, "#") and first_field_value(fields, "Object/attribute name"))


def build_cosem_object_context(item_id: str, row_index: int, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_item_id": item_id,
        "row_index": row_index,
        "object_name": first_field_value(fields, "Object/attribute name"),
        "class_id": parse_intish(first_field_value(fields, "CL")),
        "obis": first_field_value(fields, "Value"),
        "meaning": first_field_value(fields, "Meaning"),
        "comment": first_field_value(fields, "Comment"),
    }


def parse_intish(value: Any) -> int | str | None:
    if value is None:
        return None
    text = clean_text(str(value)).lower()
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    if text in words:
        return words[text]
    if text.isdigit():
        return int(text)
    return clean_text(str(value))


def tag_domains(*texts: str) -> list[str]:
    haystack = normalize_match_term(" ".join(t for t in texts if t))
    tags: list[str] = []
    for tag, pattern in DOMAIN_RULE_PATTERNS:
        if find_matched_terms(pattern, haystack, normalized=True):
            tags.append(tag)
    return tags


def load_knowledge_bases(paths: list[Path]) -> KnowledgeRepository:
    return KnowledgeRepository.from_paths(paths)


def stable_requirement_id(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("source_id") or ""),
        str(row.get("requirement_type") or ""),
        normalize_match_term(row.get("requirement", "")),
    ]
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16].upper()
    return f"SREQ-{digest}"


def match_knowledge(knowledge_bases: KnowledgeRepository | None, *texts: str) -> list[dict[str, Any]]:
    if not knowledge_bases or not knowledge_bases.entries:
        return []

    haystack = normalize_match_term(" ".join(t for t in texts if t))
    if not haystack:
        return []

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in knowledge_bases.entries:
        matched_terms = find_matched_terms(entry.match_pattern, haystack, normalized=True)
        if not matched_terms:
            continue
        key = (entry.kb_id, entry.entry_id)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "kb_id": entry.kb_id,
                "entry_id": entry.entry_id,
                "type": entry.entry_type,
                "layer": entry.layer,
                "name": entry.name,
                "matched_terms": matched_terms[:8],
                "domain_tags": list(entry.domain_tags),
                "definition": entry.definition,
                "relations": list(entry.relations),
                "metadata": entry.metadata,
            }
        )
    matches.sort(key=lambda row: (row["type"], row["name"]))
    return matches


def kb_domain_tags(matches: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for match in matches:
        for tag in match.get("domain_tags", []):
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return tags


def is_requirement_like(text: str) -> bool:
    low = text.lower()
    if low.strip().startswith("summary"):
        return False
    signals = (
        "shall",
        "must",
        "should",
        "required",
        "requirement",
        "not used, must",
        "is required",
        "are required",
        "only",
        "mandatory",
    )
    if any(signal in low for signal in signals):
        return True
    definition_constraints = (
        r"\balways\s+begins\b",
        r"\balways\s+ends\b",
        r"\bends\s+on\b",
        r"\bcan\s+be\s+valid\s+for\b",
    )
    if any(re.search(pattern, low) for pattern in definition_constraints):
        return True
    if re.search(r"\bvalid for\b[^.;:]*\b\d+\b[^.;:]*\b(day|days|month|months|year|years|hour|hours)\b", low):
        return True
    if re.search(r"\b(?:default|factory)\s+value\s+of\b", low):
        return True
    if re.search(r"\bcan\s+be\s+one\s+of\b", low):
        return True
    if re.search(r"\b(?:profile|protocol|channel|medium|media)\b[^.;:]{0,120}\bcan\s+be\s+used\s+for\s+(?:the\s+)?communication\b", low):
        return True
    if re.search(r"\bat\s+least\b[^.;:]{0,80}\b(?:highlight|record|report|transmit|store)s?\b[^.;:]{0,120}\bif\b", low):
        return True
    return False


def is_atomic_requirement_like(text: str) -> bool:
    low = text.lower()
    strong_signals = (
        "shall",
        "must",
        "not used, must",
        "is required",
        "are required",
        "access is required",
        "mandatory",
        "required by",
        "required for",
        "set to",
    )
    return any(signal in low for signal in strong_signals)


def extract_docx(
    input_path: Path,
    knowledge_bases: KnowledgeRepository | None = None,
    document_profile: DocumentProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    knowledge_bases = knowledge_bases or KnowledgeRepository.from_paths([])
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    document = Document(input_path)
    sections = SectionState()
    blocks: list[dict[str, Any]] = []
    table_items: list[dict[str, Any]] = []
    table_cell_items: list[dict[str, Any]] = []
    last_caption: str | None = None
    table_count = 0
    order = 0

    for item in iter_body_items(document):
        if isinstance(item, Paragraph):
            raw_text = str(item.text or "")
            text = clean_text(raw_text)
            if not text:
                continue

            style_name = item.style.name if item.style is not None else ""
            list_level = numbering_level(item)
            is_list_item = list_level is not None
            heading = detect_heading(text, style_name, is_list_item=is_list_item, document_profile=profile)
            block_type = "paragraph"
            if heading:
                level, title = heading
                section_path = sections.update(level, title)
                block_type = "heading"
            else:
                section_path = sections.path()

            order += 1
            block_id = f"BLK-{order:06d}"
            kb_matches = match_knowledge(knowledge_bases, text, " > ".join(section_path))
            domain_tags = merge_tags(tag_domains(text, " > ".join(section_path)), kb_domain_tags(kb_matches))
            block = {
                "block_id": block_id,
                "order": order,
                "type": block_type,
                "style": style_name,
                "text": text,
                "raw_text": raw_text,
                **source_alignment_fields(raw_text, text),
                "is_list_item": is_list_item,
                "list_level": list_level,
                "section_path": section_path,
                "domain_tags": domain_tags,
                "kb_matches": kb_matches,
                "requirement_like": is_requirement_like(text),
                "noise": is_noise(text, document_profile=profile),
            }
            if heading:
                block["heading_level"] = heading[0]
            blocks.append(block)

            if looks_like_caption(text, document_profile=profile):
                last_caption = text
            elif block_type != "heading" and not is_noise(text, document_profile=profile):
                # Keep captions available across short spacer paragraphs, but avoid
                # accidentally attaching a distant caption to a later table.
                if last_caption and len(text) > 120:
                    last_caption = None

        elif isinstance(item, Table):
            parsed = parse_docx_table(item)
            if not parsed.matrix:
                continue
            table_count += 1
            table_id = f"TBL-{table_count:06d}"
            table_title = infer_table_title(last_caption, table_count)
            section_path = sections.path()
            order += 1
            block_id = f"BLK-{order:06d}"
            table_block, new_table_items, new_cell_items = _build_docx_table_tree(
                parsed,
                table_id=table_id,
                block_id=block_id,
                order=order,
                table_title=table_title,
                section_path=section_path,
                knowledge_bases=knowledge_bases,
            )
            blocks.append(table_block)
            table_items.extend(new_table_items)
            table_cell_items.extend(new_cell_items)
            last_caption = None

    # A5②：收容文本框/页眉页脚内容（默认关闭，避免 golden blocks.jsonl 漂移）
    if os.environ.get("RATOMIZER_DOCX_EXTRA_CHANNELS", "0").strip().lower() in {"1", "true", "yes", "on"}:
        extra_channels = extract_docx_extra_channels(document)
        for channel, texts in extra_channels.items():
            for text in texts:
                text = clean_text(text)
                if not text:
                    continue
                order += 1
                block_id = f"BLK-{order:06d}"
                section_path = sections.path()
                kb_matches = match_knowledge(knowledge_bases, text, " > ".join(section_path))
                domain_tags = merge_tags(tag_domains(text, " > ".join(section_path)), kb_domain_tags(kb_matches))
                blocks.append({
                    "block_id": block_id,
                    "order": order,
                    "type": "paragraph",
                    "source_format": "docx",
                    "content_channel": channel,
                    "text": text,
                    "raw_text": text,
                    "section_path": section_path,
                    "domain_tags": domain_tags,
                    "kb_matches": kb_matches,
                    "requirement_like": is_requirement_like(text),
                    "noise": False,
                })

    return blocks, table_items, table_cell_items


def _docx_cell_metadata(
    parsed: ParsedDocxTable,
    *,
    table_id: str,
) -> dict[tuple[int, int], dict[str, Any]]:
    nested_by_coordinate: dict[tuple[int, int], list[str]] = defaultdict(list)
    for ref in parsed.nested_tables:
        nested_by_coordinate[ref.parent_coordinate].append(
            f"{table_id}-N{ref.ordinal:03d}"
        )
    metadata: dict[tuple[int, int], dict[str, Any]] = {}
    for coordinate, cell in parsed.cells.items():
        metadata[coordinate] = {
            "content_paragraphs": [
                {
                    "text": paragraph.text,
                    "style_name": paragraph.style_name,
                    "list_level": paragraph.list_level,
                    "manual_break_count": paragraph.manual_break_count,
                }
                for paragraph in cell.content.paragraphs
            ],
            "style_evidence": dict(cell.style_evidence),
            "nested_table_ids": nested_by_coordinate.get(coordinate, []),
            "docx_table_physical_version": DOCX_TABLE_PHYSICAL_VERSION,
        }
    return metadata


def _build_docx_table_tree(
    parsed: ParsedDocxTable,
    *,
    table_id: str,
    block_id: str,
    order: int,
    table_title: str,
    section_path: list[str],
    knowledge_bases: KnowledgeRepository,
    parent_table_id: str | None = None,
    parent_cell_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one top-level block plus recursively governed nested table sources.

    Nested tables receive independent table IDs but deliberately share the parent
    top-level block ID. This preserves the stable ``BLK-*`` sequence while keeping
    every nested row/cell independently addressable.
    """
    # S1-4：WS1 双轨——LLM 提议→几何校验签发；issued 时用假设派生结构，否则 None（确定性兜底）。
    # OFF / 无提议器 / 未签发 → override=None，build_table_artifacts 走 analyze_table 逐字节不变。
    header_row_hint = next(
        (row for row in (parsed.matrix or []) if any(str(c or "").strip() for c in row)), [],
    )
    structure_override = _dual_track_docx_structure(
        parsed, table_id=table_id, block_id=block_id,
        section_path=section_path, headers_hint=[str(c or "") for c in header_row_hint],
    )
    block, items, cells = build_table_artifacts(
        parsed.matrix,
        raw_matrix=parsed.raw_matrix,
        table_id=table_id,
        block_id=block_id,
        order=order,
        table_title=table_title,
        section_path=section_path,
        knowledge_bases=knowledge_bases,
        parse_incomplete=parsed.parse_incomplete,
        parse_incomplete_reason=parsed.parse_incomplete_reason or None,
        merge_ranges=parsed.merge_ranges,
        explicit_header_rows=parsed.explicit_header_rows or None,
        source_format="docx",
        cell_metadata=_docx_cell_metadata(parsed, table_id=table_id),
        structure_override=structure_override,
    )
    block["docx_table_physical_version"] = DOCX_TABLE_PHYSICAL_VERSION
    block["nested_tables"] = []
    if parent_table_id:
        block["parent_table_id"] = parent_table_id
    if parent_cell_id:
        block["parent_cell_id"] = parent_cell_id
    for row in [*items, *cells]:
        row["docx_table_physical_version"] = DOCX_TABLE_PHYSICAL_VERSION
        if parent_table_id:
            row["parent_table_id"] = parent_table_id
        if parent_cell_id:
            row["parent_cell_id"] = parent_cell_id

    for ref in parsed.nested_tables:
        nested_id = f"{table_id}-N{ref.ordinal:03d}"
        owner_cell_id = (
            f"{table_id}-R{ref.parent_coordinate[0]:06d}"
            f"-C{ref.parent_coordinate[1]:06d}"
        )
        nested_block, nested_items, nested_cells = _build_docx_table_tree(
            ref.table,
            table_id=nested_id,
            block_id=block_id,
            order=order,
            table_title=f"{table_title} / nested table {ref.ordinal}",
            section_path=section_path,
            knowledge_bases=knowledge_bases,
            parent_table_id=table_id,
            parent_cell_id=owner_cell_id,
        )
        block["nested_tables"].append(nested_block)
        items.extend(nested_items)
        cells.extend(nested_cells)
    return block, items, cells


def merge_tags(*tag_lists: Iterable[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag_list in tag_lists:
        for tag in tag_list:
            if tag and tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return tags


def mark_doc_regions(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    document_profile: DocumentProfile | None = None,
    table_cell_items: list[dict[str, Any]] | None = None,
) -> None:
    """Mark blocks as body/front matter so model tasks ignore cover and TOC pages."""
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    body_start_indexes: list[int] = []
    preface_index: int | None = None
    introduction_index: int | None = None

    for index, block in enumerate(blocks):
        text = normalize_title(block.get("text", ""))
        # 容忍条款号前缀（真实案例 EN 16314）："1 Scope" 精确匹配不上 "scope" →
        # body_start=0 → 封面/目录全标 body，目录条目混进抽取单元变成空壳需求。
        stripped = re.sub(r"^\d+(?:\.\d+)*[.)]?\s+", "", text)
        if block.get("type") == "heading" and profile.body_start_heading in (text, stripped):
            body_start_indexes.append(index)
        if block.get("type") == "heading" and text == "preface" and preface_index is None:
            preface_index = index
        if block.get("type") == "heading" and text == "introduction" and introduction_index is None:
            introduction_index = index

    # Standards often include "The Scope in English..." in the preface before the
    # real normative body. If multiple Scope headings exist, the last one is the
    # safer body start.
    # 只认前 60% 里的 Scope（2026-07-08 审计 H1）：文档后部的裸 "Scope" 标题（双语对照页/
    # 附录引述被判一级标题）若被当 body 起点，其前的全部正文会标成 front_matter 静默退出
    # A 轨候选。后部候选全无时回退第一个（宁多收不静默丢）。
    cutoff = int(len(blocks) * 0.6)
    early = [i for i in body_start_indexes if i <= cutoff]
    if early:
        body_start = early[-1]
    elif body_start_indexes:
        body_start = body_start_indexes[0]
    else:
        body_start = 0

    for index, block in enumerate(blocks):
        if index >= body_start:
            region = "body"
        elif preface_index is not None and index >= preface_index:
            region = "preface"
        elif introduction_index is not None and index >= introduction_index:
            region = "introduction"
        elif block.get("section_path") and any(normalize_title(p) in {"tables", "figures"} for p in block["section_path"]):
            region = "table_of_contents"
        else:
            region = "front_matter"
        block["doc_region"] = region

    block_region_by_id = {block["block_id"]: block.get("doc_region", "body") for block in blocks}
    for item in table_items:
        item["doc_region"] = block_region_by_id.get(item.get("table_block_id"), "body")
    for cell in table_cell_items or []:
        cell["doc_region"] = block_region_by_id.get(cell.get("table_block_id"), "body")
    # A9-2：tender 区域识别（默认关，OFF 时本段不执行以保持字节一致）
    if os.environ.get("RATOMIZER_TENDER_REGION_FILTER", "0").strip().lower() not in {"0", "false", "off"}:
        from tender_regions import apply_tender_regions

        apply_tender_regions(blocks)
        # 表格/单元格跟随其所属块
        block_region_by_id = {block["block_id"]: block.get("doc_region", "body") for block in blocks}
        for item in table_items:
            item["doc_region"] = block_region_by_id.get(item.get("table_block_id"), "body")
        for cell in table_cell_items or []:
            cell["doc_region"] = block_region_by_id.get(cell.get("table_block_id"), "body")


def normalize_title(text: str) -> str:
    text = clean_text(text).lower().rstrip(":")
    text = re.sub(r"\s+", " ", text)
    return text


def apply_table_pattern_shadow(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    domain_pack_dir: Path,
) -> dict[str, Any]:
    patterns_path = domain_pack_dir.expanduser().resolve() / "table_patterns.yaml"
    if not patterns_path.exists():
        raise AtomizerInputError(f"Missing table_patterns.yaml: {patterns_path}")
    patterns = load_table_patterns(patterns_path)
    table_items_by_block: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in table_items:
        table_items_by_block[str(item.get("table_block_id") or "")].append(item)

    by_pattern_id: Counter[str] = Counter()
    tables_total = 0
    tables_with_pattern = 0
    for block in blocks:
        if block.get("type") != "table":
            continue
        tables_total += 1
        matches = match_table_pattern(block, patterns)[:3]
        if not matches:
            continue
        block["pattern_matches"] = matches
        tables_with_pattern += 1
        by_pattern_id.update(match["pattern_id"] for match in matches)
        for item in table_items_by_block.get(str(block.get("block_id") or ""), []):
            item["pattern_matches"] = matches

    return {
        "tables_total": tables_total,
        "tables_with_pattern": tables_with_pattern,
        "by_pattern_id": dict(by_pattern_id.most_common()),
    }


def load_document_profile_from_domain_pack(domain_pack_dir: Path | None) -> DocumentProfile:
    if domain_pack_dir is None:
        return DEFAULT_DOCUMENT_PROFILE
    pack_path = domain_pack_dir.expanduser().resolve() / "pack.yaml"
    if not pack_path.exists():
        return DEFAULT_DOCUMENT_PROFILE
    pack = load_domain_pack(pack_path)
    return DocumentProfile.from_payload(pack.payload.get("document_profile"))


def render_table_text(headers: list[str], rows: list[list[str]], max_rows: int | None = None) -> str:
    """扁平渲染整张表。2026-07-27 起默认渲染全部数据行——此前的 max_rows=20 截断
    （初始提交遗留）让大参数表第 21 行起的内容进不了抽取管线（STO 实证：143 行参数表
    扁平文本尾部只有 '... 123 more rows'）；调用方需要截断时显式传 max_rows。"""
    lines = [" | ".join(headers)]
    limit = len(rows) if max_rows is None else max_rows
    for row in rows[:limit]:
        padded = row + [""] * max(0, len(headers) - len(row))
        lines.append(" | ".join(padded[: len(headers)]))
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows")
    return "\n".join(lines)


def build_chunks(
    blocks: list[dict[str, Any]],
    target_chars: int = 3500,
    include_regions: set[str] | None = None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    current_section: tuple[str, ...] = tuple()

    def flush() -> None:
        nonlocal current, current_chars, current_section
        if not current:
            return
        chunk_index = len(chunks) + 1
        text_parts: list[str] = []
        source_ids: list[str] = []
        domain_counter: Counter[str] = Counter()
        kb_matches_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        req_like = False
        for block in current:
            source_ids.append(block["block_id"])
            domain_counter.update(block.get("domain_tags", []))
            for match in block.get("kb_matches", []):
                key = (match.get("kb_id", ""), match.get("entry_id", ""))
                if key not in kb_matches_by_key:
                    kb_matches_by_key[key] = match
            req_like = req_like or bool(block.get("requirement_like"))
            if block["type"] == "heading":
                text_parts.append(f"# {block['text']}")
            elif block["type"] == "table":
                text_parts.append(f"[{block.get('table_id')}] {block.get('table_title')}\n{block.get('text', '')}")
            else:
                text_parts.append(block["text"])
        chunks.append(
            {
                "chunk_id": f"CH-{chunk_index:06d}",
                "order": chunk_index,
                "section_path": list(current_section),
                "source_block_ids": source_ids,
                "text": "\n\n".join(text_parts),
                "domain_tags": [tag for tag, _ in domain_counter.most_common()],
                "kb_matches": list(kb_matches_by_key.values())[:40],
                "requirement_like": req_like,
            }
        )
        current = []
        current_chars = 0
        current_section = tuple()

    for block in blocks:
        if include_regions is not None and block.get("doc_region") not in include_regions:
            continue
        if block.get("noise"):
            continue

        block_section = tuple(block.get("section_path") or [])
        block_text = block.get("text") or ""
        block_size = len(block_text)

        if block["type"] == "heading":
            if current and current_chars >= target_chars * 0.35:
                flush()

        if block["type"] == "table" and current:
            flush()

        if current and block_section != current_section and current_chars >= target_chars * 0.5:
            flush()

        if current and current_chars + block_size > target_chars:
            flush()

        if not current:
            current_section = block_section
        current.append(block)
        current_chars += block_size

        if block["type"] == "table":
            flush()

    flush()
    return chunks


def build_llm_tasks(chunks: list[dict[str, Any]], table_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    for chunk in chunks:
        if not chunk.get("requirement_like") and not chunk.get("domain_tags"):
            continue
        task_id = f"TASK-{len(tasks) + 1:06d}"
        tasks.append(
            {
                "task_id": task_id,
                "task_type": "extract_atomic_requirements",
                "source_type": "chunk",
                "source_id": chunk["chunk_id"],
                "source_refs": chunk["source_block_ids"],
                "section_path": chunk.get("section_path", []),
                "domain_tags": chunk.get("domain_tags", []),
                "kb_matches": chunk.get("kb_matches", []),
                "instruction": atomic_requirement_instruction(),
                "input": chunk["text"],
                "expected_output_schema": atomic_requirement_schema(),
            }
        )

    for item in table_items:
        if not item.get("domain_tags") and not item.get("requirement_like"):
            continue
        task_id = f"TASK-{len(tasks) + 1:06d}"
        tasks.append(
            {
                "task_id": task_id,
                "task_type": "classify_table_atom",
                "source_type": "table_row",
                "source_id": item["item_id"],
                "source_refs": [item["table_block_id"]],
                "section_path": item.get("section_path", []),
                "domain_tags": item.get("domain_tags", []),
                "kb_matches": item.get("kb_matches", []),
                "instruction": table_atom_instruction(),
                "input": {
                    "table_title": item["table_title"],
                    "row_index": item["row_index"],
                    "fields": item["fields"],
                    "matrix_facts": item.get("matrix_facts", []),
                },
                "expected_output_schema": atomic_requirement_schema(),
            }
        )

    return tasks


def build_atomic_candidates(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    *,
    include_regions: set[str] | None = None,
    table_cell_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    blocks_by_id = {str(block.get("block_id") or ""): block for block in blocks}
    # cell/mixed 模式表的行仅作容器：A 轨候选按 leaf plan 消费，禁止父子双份
    cell_mode_blocks = {
        block_id
        for block_id, block in blocks_by_id.items()
        if str(block.get("table_kind") or "") in {"mapping_matrix", "prose_grid"}
    }
    # 组合表（parameter + 真实矩阵事实列）：行候选保留（COSEM 行级化），矩阵事实
    # 改由 marker cell 产出——同一物理事实不重复成 atom。
    # P0-4：只消费块载荷里构建期算好的 matrix_fact_columns（共享正向维度证据），
    # 禁止下游用别的口径重新推导事实列；旧产物无该字段即无事实列（重解析后才有）
    mixed_fact_blocks = {
        block_id
        for block_id, block in blocks_by_id.items()
        if block_id not in cell_mode_blocks
        and str(block.get("table_kind") or "")
        and block.get("matrix_fact_columns")
    }

    def add(row: dict[str, Any]) -> None:
        key = (
            row.get("source_id", ""),
            row.get("requirement_type", ""),
            normalize_match_term(row.get("requirement", "")),
        )
        if key in seen:
            return
        seen.add(key)
        row["req_id"] = f"AREQ-{len(candidates) + 1:06d}"
        row["stable_req_id"] = stable_requirement_id(row)
        candidates.append(row)

    for block in blocks:
        if include_regions is not None and block.get("doc_region") not in include_regions:
            continue
        if block.get("type") != "paragraph" or block.get("noise"):
            continue
        paragraph_text = clean_text(block.get("text", ""))
        for context in paragraph_requirement_contexts(paragraph_text):
            sentence = context["sentence"]
            if not is_atomic_requirement_like(sentence):
                continue
            add(
                atomic_row(
                    source_id=block["block_id"],
                    source_type="paragraph",
                    source_refs=[block["block_id"]],
                    section_path=block.get("section_path", []),
                    domain_tags=block.get("domain_tags", []),
                    kb_matches=block.get("kb_matches", []),
                    requirement_type=classify_requirement_type(sentence, block.get("domain_tags", [])),
                    requirement=sentence,
                    object_name=infer_object_name(block.get("kb_matches", []), sentence),
                    parameters=extract_parameters(sentence),
                    verification_method=verification_method_for(block.get("domain_tags", []), sentence),
                    confidence=0.68,
                    ambiguity=is_ambiguous_text(sentence),
                    condition=condition_from_previous_sentence(context.get("prev_sentence")),
                    source_context={
                        "paragraph_text": truncate_text(paragraph_text, 600),
                        "prev_sentence": context.get("prev_sentence"),
                    },
                )
            )

    for item in table_items:
        if include_regions is not None and item.get("doc_region") not in include_regions:
            continue
        if str(item.get("table_block_id") or "") in cell_mode_blocks:
            # cell/mixed 模式：行只是容器（COSEM join 仍直接读 table_items.jsonl），
            # A 轨候选由下方 cell 层按 leaf plan 产出，禁止父子双份
            continue
        if str(item.get("table_block_id") or "") in mixed_fact_blocks:
            # 组合表：矩阵事实由 marker cell 产出（见下方 cell 循环），行不再复述
            matrix_facts = []
        else:
            matrix_facts = item.get("matrix_facts", [])
        for fact in matrix_facts:
            predicate = clean_table_header(fact.get("predicate_header", ""))
            subject = clean_text(fact.get("subject"))
            if not subject or not predicate:
                continue
            add(
                atomic_row(
                    source_id=item["item_id"],
                    source_type="table_matrix_fact",
                    source_refs=[item["table_block_id"], item["item_id"]],
                    section_path=item.get("section_path", []),
                    domain_tags=item.get("domain_tags", []),
                    kb_matches=item.get("kb_matches", []),
                    requirement_type="capability_matrix",
                    requirement=f"{subject} shall support {predicate}.",
                    object_name=subject,
                    parameters={
                        "table_title": item.get("table_title"),
                        "row_index": item.get("row_index"),
                        "subject_header": fact.get("subject_header"),
                        "predicate_header": fact.get("predicate_header"),
                        "marker": fact.get("marker"),
                    },
                    verification_method="configuration_check",
                    confidence=0.82,
                    ambiguity=False,
                )
            )

        fields = item.get("fields", {})
        for valued_fact in extract_valued_matrix_facts(fields):
            add(valued_matrix_candidate(item, valued_fact))

        object_candidate = cosem_object_candidate(item, fields)
        if object_candidate:
            add(object_candidate)

        cosem_candidate = cosem_attribute_candidate(item, fields)
        if cosem_candidate:
            add(cosem_candidate)

        event_candidate = event_definition_candidate(item, fields)
        if event_candidate:
            add(event_candidate)

        event_group_candidate = event_group_candidate_from_fields(item, fields)
        if event_group_candidate:
            add(event_group_candidate)

        for candidate in [
            security_suite_candidate(item, fields),
            security_policy_bit_candidate(item, fields),
            security_policy_state_candidate(item, fields),
            measurement_quantity_candidate(item, fields),
            flag_definition_candidate(item, fields),
        ]:
            if candidate:
                add(candidate)

        row_requirement = table_row_requirement_candidate(item, fields)
        if row_requirement:
            add(row_requirement)

    fact_columns_by_block: dict[str, set[int]] = {}
    for cell in table_cell_items or []:
        if cell.get("leaf_kind") != "cell":
            continue
        if include_regions is not None and cell.get("doc_region") not in include_regions:
            continue
        block_id = str(cell.get("table_block_id") or "")
        parent = blocks_by_id.get(block_id) or {}
        table_kind = str(parent.get("table_kind") or "")
        section_path = list(cell.get("section_path") or parent.get("section_path") or [])
        domain_tags = list(parent.get("domain_tags") or [])
        kb_matches = list(parent.get("kb_matches") or [])
        cell_text = clean_text(cell.get("text") or "")
        if not cell_text:
            continue
        column_index = int(cell.get("column_index") or 0)
        marker_cell = table_kind == "mapping_matrix" or block_id in mixed_fact_blocks
        if marker_cell and is_positive_marker(cell_text):
            # 结构角色闸：只有数据区格的 marker 才参与句式合成——表头/标题位的
            # marker 词永不合成（"Item shall support Required." 幻觉事故）
            if str(cell.get("structural_role") or "") != "data":
                continue
            if block_id not in fact_columns_by_block:
                stored_fact_columns = parent.get("matrix_fact_columns")
                if stored_fact_columns is not None:
                    fact_columns_by_block[block_id] = {
                        int(value) for value in stored_fact_columns
                    }
                else:
                    # P0-4：旧产物无共享维度证据时不重新推导——无事实列即不合成
                    # （重解析后由构建期的 matrix_dimension_evidence 统一供给）
                    fact_columns_by_block[block_id] = set()
            if column_index - 1 not in fact_columns_by_block[block_id]:
                continue  # 非矩阵事实列的 marker 只是原文，不成句式
            subject = ""
            subject_header = ""
            # subject 取标识条目的纯值（结构化 row_header_entries），不反解析
            # "Header=Value" 显示串（row_header_context 是 claim 上下文形态）
            identity_entries = cell.get("row_header_entries")
            if identity_entries:
                last_entry = identity_entries[-1]
                subject = clean_text(last_entry.get("value"))
                subject_header = str(last_entry.get("header") or "")
            elif cell.get("row_header_context"):
                subject = clean_text(cell["row_header_context"][-1])
            predicate = ""
            if cell.get("header_path"):
                predicate = clean_table_header(str(cell["header_path"][-1] or ""))
            # subject/predicate 真实性闸：空值、marker 词、纯数字、规范性句子
            # （被误判为行头的义务句）都不是对象名/能力名——证据不全时保留原始
            # cell（B 轨闭环），不合成自然语言义务
            if (
                not subject
                or not predicate
                or is_positive_marker(subject)
                or is_positive_marker(predicate)
                or re.fullmatch(r"[\d.,/\-\s]+", subject)
                or len(subject) > _MATRIX_DIMENSION_MAX_LEN
                or structure_is_normative_text(subject)
            ):
                continue
            add(
                atomic_row(
                    source_id=str(cell["cell_id"]),
                    source_type="table_cell",
                    source_refs=[block_id, str(cell["cell_id"])],
                    section_path=section_path,
                    domain_tags=domain_tags,
                    kb_matches=kb_matches,
                    requirement_type="capability_matrix",
                    requirement=f"{subject} shall support {predicate}.",
                    object_name=subject,
                    parameters={
                        "table_title": cell.get("table_title"),
                        "row_index": cell.get("row_index"),
                        "column_index": column_index,
                        "subject_header": subject_header,
                        "predicate_header": (cell.get("header_path") or [""])[-1],
                        "marker": cell_text,
                    },
                    verification_method="configuration_check",
                    confidence=0.82,
                    ambiguity=False,
                )
            )
            continue
        if not cell.get("requirement_like"):
            continue
        # 单格规范性文本直接使用逐字原文，不改写为矩阵句式
        add(
            atomic_row(
                source_id=str(cell["cell_id"]),
                source_type="table_cell",
                source_refs=[block_id, str(cell["cell_id"])],
                section_path=section_path,
                domain_tags=domain_tags,
                kb_matches=kb_matches,
                requirement_type=classify_requirement_type(cell_text, domain_tags),
                requirement=cell_text,
                object_name=infer_object_name(kb_matches, cell_text),
                parameters={
                    "table_title": cell.get("table_title"),
                    "row_index": cell.get("row_index"),
                    "column_index": column_index,
                    "header_path": list(cell.get("header_path") or []),
                    "row_header_context": list(cell.get("row_header_context") or []),
                },
                verification_method=verification_method_for(domain_tags, cell_text),
                confidence=0.7,
                ambiguity=is_ambiguous_text(cell_text),
                source_context={"cell_context": cell_context_text(cell)},
            )
        )

    return candidates


def atomic_row(
    *,
    source_id: str,
    source_type: str,
    source_refs: list[str],
    section_path: list[str],
    domain_tags: list[str],
    kb_matches: list[dict[str, Any]],
    requirement_type: str,
    requirement: str,
    object_name: str,
    parameters: dict[str, Any],
    verification_method: str,
    confidence: float,
    ambiguity: bool,
    condition: str | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "source_id": source_id,
        "source_type": source_type,
        "source_refs": source_refs,
        "section_path": section_path,
        "domain": primary_domain(domain_tags),
        "domain_tags": domain_tags,
        "object": object_name,
        "requirement_type": requirement_type,
        "requirement": clean_text(requirement),
        "condition": condition,
        "parameters": parameters,
        "verification_method": verification_method,
        "ambiguity": ambiguity,
        "review_questions": review_questions_for(requirement, ambiguity),
        "confidence": confidence,
        "kb_matches": compact_kb_matches(kb_matches),
        "generated_by": "rule_based_atomizer_v1",
    }
    if source_context is not None:
        row["source_context"] = source_context
    return row


def paragraph_requirement_contexts(text: str) -> list[dict[str, str | None]]:
    sentences = split_paragraph_sentences(text)
    contexts: list[dict[str, str | None]] = []
    for index, sentence in enumerate(sentences):
        contexts.append(
            {
                "sentence": sentence,
                "prev_sentence": sentences[index - 1] if index > 0 else None,
            }
        )
    return contexts


def split_paragraph_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    return [clean_text(part) for part in re.split(r"(?<=[.;!?])\s+", text) if clean_text(part)]


def condition_from_previous_sentence(prev_sentence: str | None) -> str | None:
    if not prev_sentence:
        return None
    if is_atomic_requirement_like(prev_sentence):
        return None
    return prev_sentence if re.match(r"^(if|when|where|in case|unless)\b", prev_sentence, flags=re.I) else None


def truncate_text(text: str, max_chars: int) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def classify_requirement_type(text: str, domain_tags: list[str]) -> str:
    low = text.lower()
    if "security" in domain_tags or any(term in low for term in ("hls", "lls", "password", "encrypt", "authenticat")):
        return "security"
    if "access_control" in domain_tags or any(term in low for term in ("read", "write", "access", "association")):
        return "access_control"
    if "communication_profile" in domain_tags or any(term in low for term in ("dlms", "xdlms", "communication", "push")):
        return "communication"
    if "cosem_object" in domain_tags or any(term in low for term in ("cosem", "obis", "logical_name", "attribute")):
        return "cosem_object"
    if "event" in domain_tags:
        return "event"
    return "functional"


def verification_method_for(domain_tags: list[str], text: str) -> str:
    low = text.lower()
    if "configuration_check" in domain_tags or any(term in low for term in ("set to", "access rights", "configured", "password", "hls", "lls")):
        return "configuration_check"
    if any(term in low for term in ("shall support", "must support", "service", "push", "notification")):
        return "test"
    if "security_policy" in domain_tags:
        return "test"
    return "inspection"


def infer_object_name(kb_matches: list[dict[str, Any]], text: str) -> str:
    preferred_types = {
        "cosem_interface_class",
        "cosem_object_instance",
        "object",
        "client_role",
        "logical_device",
        "service_set",
        "security_level",
    }
    for match in kb_matches:
        if match.get("type") in preferred_types and match.get("name"):
            return str(match["name"])
    text = clean_text(text)
    match = re.search(r"\b([A-Z][A-Za-z0-9_/-]*(?:\s+[A-Z][A-Za-z0-9_/-]*){0,4})\b", text)
    if not match:
        return ""
    candidate = match.group(1).strip()
    first_word = candidate.split()[0]
    return "" if first_word in OBJECT_NAME_STOPWORDS else candidate


def extract_parameters(text: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    obis_codes = re.findall(r"\b\d+-\d+:\d+(?:\.\d+|\.x){3}\b", text)
    if obis_codes:
        params["obis_codes"] = list(dict.fromkeys(obis_codes))
    sap_values = re.findall(r"\bSAP\s*=\s*0x[0-9A-Fa-f]+\b", text)
    if sap_values:
        params["sap_values"] = list(dict.fromkeys(sap_values))
    class_ids = re.findall(r"\b(?:class|CL)\s*=?\s*(\d{1,3})\b", text, flags=re.I)
    if class_ids:
        params["class_ids"] = list(dict.fromkeys(class_ids))
    return params


def is_ambiguous_text(text: str) -> bool:
    low = text.lower()
    return any(signal in low for signal in ("if necessary", "can be", "may be", "where applicable", "reserved"))


def review_questions_for(requirement: str, ambiguity: bool) -> list[str]:
    if not ambiguity:
        return []
    return [f"Confirm whether this source text is normative: {requirement[:140]}"]


def primary_domain(domain_tags: list[str]) -> str:
    return domain_tags[0] if domain_tags else "general"


def compact_kb_matches(kb_matches: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for match in kb_matches[:limit]:
        compact.append(
            {
                "kb_id": match.get("kb_id"),
                "entry_id": match.get("entry_id"),
                "type": match.get("type"),
                "name": match.get("name"),
                "matched_terms": match.get("matched_terms", [])[:5],
            }
        )
    return compact


def clean_table_header(value: str | None) -> str:
    value = clean_text(value)
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        if len(parts) >= 2:
            top = parts[0]
            leaf = parts[-1]
            if normalize_header_part(top) in normalize_header_part(leaf):
                return leaf
            return f"{top}: {leaf}"
    return value


def extract_valued_matrix_facts(fields: dict[str, Any]) -> list[dict[str, Any]]:
    if len(fields) < 3:
        return []
    if looks_like_non_matrix_row(fields):
        return []
    first_key = next(iter(fields), "")
    subject = clean_text(fields.get(first_key))
    if not subject:
        return []
    # 索引号 subject（"1"/"2."）不是对象名——"1 shall have Requirement set to …"
    # 与 "1 shall support Note." 同族伪句式，一律不产
    if PARAM_INDEX_CELL_RE.match(subject):
        return []

    facts: list[dict[str, Any]] = []
    for key, value in list(fields.items())[1:]:
        cleaned_value = clean_text(str(value))
        if not cleaned_value or is_positive_marker(cleaned_value):
            continue
        if NOTE_HEADER_RE.search(str(key)):
            continue  # Note 列保持原文，永远不是 valued 事实
        if _DISPOSITION_HEADER_RE.search(str(key)):
            # 处置/泛称包装列（Status/Result/Requirement/Value…）不是能力维度——
            # "Voltage shall have Status set to ok." 伪句式（B4）：值保持原文在
            # 行容器与 cell claim 中，不合成自然语言义务
            continue
        facts.append(
            {
                "subject_header": first_key,
                "subject": subject,
                "predicate_header": key,
                "value": cleaned_value,
                "relation": "has_value",
            }
        )
    return facts


def looks_like_non_matrix_row(fields: dict[str, Any]) -> bool:
    normalized_keys = {normalize_header_part(key) for key in fields}
    non_matrix_markers = {
        "id",
        "name",
        "#",
        "object attribute name",
        "cl",
        "type",
        "value",
        "meaning",
        "comment",
        "unit",
        "flag",
        "description",
        "state",
        "security policy",
        "bit",
        "security policy security states",
        "access rights rc pc sc lc",
        "description of the event",
        "event number",
        "number of event",
        "group number",
        "subgroup number",
    }
    return bool(normalized_keys & non_matrix_markers)


def valued_matrix_candidate(item: dict[str, Any], fact: dict[str, Any]) -> dict[str, Any]:
    subject = clean_text(fact.get("subject"))
    predicate = clean_table_header(fact.get("predicate_header"))
    value = clean_text(fact.get("value"))
    requirement = f"{subject} shall have {predicate} set to {value}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="table_valued_matrix_fact",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type=classify_valued_matrix_type(item, fact),
        requirement=requirement,
        object_name=subject,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "subject_header": fact.get("subject_header"),
            "predicate_header": fact.get("predicate_header"),
            "value": value,
        },
        verification_method="configuration_check",
        confidence=0.8,
        ambiguity=is_ambiguous_text(value),
    )


def classify_valued_matrix_type(item: dict[str, Any], fact: dict[str, Any]) -> str:
    text = normalize_match_term(" ".join([item.get("table_title", ""), fact.get("predicate_header", ""), fact.get("value", "")]))
    if any(term in text for term in ("hls", "lls", "without security", "security")):
        return "association_security_matrix"
    return "table_value_matrix"


def cosem_attribute_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    attr_no = first_field_value(fields, "#")
    attr_name = first_field_value(fields, "Object/attribute name")
    access_rights = first_field_value(fields, "Access rights RC/PC/SC/LC")
    if not attr_no or not attr_name or not access_rights:
        return None

    object_context = item.get("cosem_object_context") or {}
    object_name = clean_text(object_context.get("object_name")) or infer_object_name(item.get("kb_matches", []), attr_name)
    qualified_attr_name = f"{object_name}.{attr_name}" if object_name else attr_name
    parsed_access_rights = parse_access_rights(access_rights)
    class_id = object_context.get("class_id")
    obis = clean_text(object_context.get("obis"))
    object_bits = []
    if object_name:
        object_bits.append(object_name)
    if class_id not in {None, ""}:
        object_bits.append(f"CL {class_id}")
    if obis:
        object_bits.append(f"OBIS {obis}")
    object_phrase = f" for {' / '.join(object_bits)}" if object_bits else ""
    requirement = f"COSEM attribute {qualified_attr_name}{object_phrase} shall use access rights {access_rights}."
    params = {
        "table_title": item.get("table_title"),
        "row_index": item.get("row_index"),
        "cosem_object": object_context,
        "attribute_id": attr_no,
        "attribute_name": attr_name,
        "type": first_field_value(fields, "Type"),
        "value": first_field_value(fields, "Value"),
        "meaning": first_field_value(fields, "Meaning"),
        "comment": first_field_value(fields, "Comment"),
        "access_rights": access_rights,
        "access_rights_by_client": parsed_access_rights,
    }
    return atomic_row(
        source_id=item["item_id"],
        source_type="cosem_attribute_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type="cosem_attribute_access",
        requirement=requirement,
        object_name=qualified_attr_name,
        parameters={key: value for key, value in params.items() if value},
        verification_method="configuration_check",
        confidence=0.9 if object_name else 0.82,
        ambiguity=False,
    )


def table_row_requirement_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    field_text = " | ".join(str(value) for value in fields.values() if value)
    if not is_atomic_requirement_like(field_text):
        return None
    return atomic_row(
        source_id=item["item_id"],
        source_type="table_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type=classify_requirement_type(field_text, item.get("domain_tags", [])),
        requirement=field_text,
        object_name=infer_object_name(item.get("kb_matches", []), field_text),
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "fields": fields,
        },
        verification_method=verification_method_for(item.get("domain_tags", []), field_text),
        confidence=0.74,
        ambiguity=is_ambiguous_text(field_text),
    )


def cosem_object_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    if not is_cosem_object_header(fields):
        return None

    context = item.get("cosem_object_context") or build_cosem_object_context(item["item_id"], item.get("row_index", 0), fields)
    object_name = clean_text(context.get("object_name"))
    class_id = context.get("class_id")
    obis = clean_text(context.get("obis"))
    if not object_name or not obis:
        return None

    object_bits = [object_name]
    if class_id not in {None, ""}:
        object_bits.append(f"CL {class_id}")
    object_bits.append(f"OBIS {obis}")
    requirement = f"COSEM object {' / '.join(object_bits)} shall be defined by the profile."
    return atomic_row(
        source_id=item["item_id"],
        source_type="cosem_object_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type="cosem_object_instance",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "cosem_object": context,
        },
        verification_method="configuration_check",
        confidence=0.88,
        ambiguity=False,
    )


def event_definition_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    group = first_field_value(fields, "Group number")
    subgroup = first_field_value(fields, "Subgroup number")
    event_number = first_field_value(fields, "Event number") or first_field_value(fields, "Number of event")
    description = (
        first_field_value(fields, "Description of the event")
        or first_field_value(fields, "Event description")
        or first_field_value(fields, "Event subgroup description")
    )
    if not event_number or not description:
        return None
    if not group and not subgroup and "event" not in item.get("table_title", "").lower():
        return None

    subgroup_description = (
        first_field_value(fields, "Event subgroup description")
        or first_field_value(fields, "Description of the subgroup of events")
    )
    object_name = "Event"
    if group or subgroup or event_number:
        object_name = f"Event G{group or '?'}-SG{subgroup or '?'}-E{event_number}"
    requirement = f"{object_name} shall be defined as: {description}."
    parameters = {
        "table_title": item.get("table_title"),
        "row_index": item.get("row_index"),
        "group_number": group,
        "subgroup_number": subgroup,
        "subgroup_description": subgroup_description,
        "event_number": parse_intish(event_number),
        "event_description": description,
    }
    return atomic_row(
        source_id=item["item_id"],
        source_type="event_table_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["event", "log"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="event_definition",
        requirement=requirement,
        object_name=object_name,
        parameters={key: value for key, value in parameters.items() if value not in {"", None}},
        verification_method="document_review",
        confidence=0.84,
        ambiguity=is_ambiguous_text(description),
    )


def event_group_candidate_from_fields(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    group = first_field_value(fields, "Group number")
    subgroup = first_field_value(fields, "Subgroup number")
    minimum_records = first_field_value(fields, "Minimum records")
    description = first_field_value(fields, "Description of the event") or first_field_value(fields, "Event subgroup description")
    subgroup_description = first_field_value(fields, "Event subgroup description")
    if not group or not subgroup or not minimum_records:
        return None
    object_name = f"Event subgroup G{group}-SG{subgroup}"
    requirement = f"{object_name} shall keep at least {minimum_records} records for {description}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="event_group_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["event", "log"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="event_group_retention",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "group_number": group,
            "subgroup_number": subgroup,
            "subgroup_description": subgroup_description,
            "minimum_records": parse_intish(minimum_records),
            "description": description,
        },
        verification_method="configuration_check",
        confidence=0.86,
        ambiguity=is_ambiguous_text(description),
    )


def security_suite_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    suite_id = first_field_value(fields, "ID")
    name = first_field_value(fields, "Name")
    if not suite_id or not name or "security" not in item.get("table_title", "").lower():
        return None
    params = {
        "table_title": item.get("table_title"),
        "row_index": item.get("row_index"),
        "id": parse_intish(suite_id),
        "name": name,
        "authenticated_encryption": first_field_value(fields, "Authenticated encryption"),
        "digital_signature": first_field_value(fields, "Digital signature"),
        "key_agreement": first_field_value(fields, "Key Agreement"),
        "hash": first_field_value(fields, '"Hash"') or first_field_value(fields, "Hash"),
        "transport_key": first_field_value(fields, "Transport key"),
        "compression": first_field_value(fields, "Compression"),
    }
    requirement = f"Security suite {suite_id} shall be defined as {name}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="security_suite_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["security_policy"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="security_suite_definition",
        requirement=requirement,
        object_name=f"Security suite {suite_id}",
        parameters={key: value for key, value in params.items() if value not in {"", None}},
        verification_method="document_review",
        confidence=0.86,
        ambiguity=False,
    )


def security_policy_bit_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    bit = first_field_value(fields, "bit")
    policy = first_field_value(fields, "Security Policy - Security States")
    if not bit or not policy:
        return None
    object_name = f"Security policy bit {bit}"
    requirement = f"{object_name} shall be defined as: {policy}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="security_policy_bit_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["security_policy"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="security_policy_bit",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "bit": parse_intish(bit),
            "definition": policy,
        },
        verification_method="configuration_check",
        confidence=0.86,
        ambiguity=is_ambiguous_text(policy),
    )


def security_policy_state_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    state = first_field_value(fields, "State")
    policy = first_field_value(fields, "Security policy")
    if not state or not policy:
        return None
    object_name = f"Security policy state {state}"
    requirement = f"{object_name} shall be defined as: {policy}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="security_policy_state_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["security_policy"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="security_policy_state",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "state": parse_intish(state),
            "policy": policy,
        },
        verification_method="configuration_check",
        confidence=0.84,
        ambiguity=is_ambiguous_text(policy),
    )


def measurement_quantity_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    quantity_group = first_field_value(fields, "Greatness")
    quantity = first_field_value(fields, "Greatness_2")
    unit = first_field_value(fields, "Unit")
    if not quantity_group or not quantity or not unit:
        return None
    object_name = quantity
    requirement = f"Measurement quantity {quantity} shall use unit {unit}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="measurement_quantity_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=merge_tags(item.get("domain_tags", []), ["measurement_quantity"]),
        kb_matches=item.get("kb_matches", []),
        requirement_type="measurement_quantity_unit",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": item.get("table_title"),
            "row_index": item.get("row_index"),
            "quantity_group": quantity_group,
            "quantity": quantity,
            "unit": unit,
        },
        verification_method="document_review",
        confidence=0.82,
        ambiguity=False,
    )


def flag_definition_candidate(item: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any] | None:
    flag = first_field_value(fields, "Flag")
    description = first_field_value(fields, "Description")
    if not flag or not description:
        return None
    title = item.get("table_title", "")
    object_name = f"{title}: {flag}" if title else flag
    requirement = f"{object_name} shall be defined as: {description}."
    return atomic_row(
        source_id=item["item_id"],
        source_type="flag_definition_row",
        source_refs=[item["table_block_id"], item["item_id"]],
        section_path=item.get("section_path", []),
        domain_tags=item.get("domain_tags", []),
        kb_matches=item.get("kb_matches", []),
        requirement_type="flag_definition",
        requirement=requirement,
        object_name=object_name,
        parameters={
            "table_title": title,
            "row_index": item.get("row_index"),
            "flag": flag,
            "description": description,
        },
        verification_method="document_review",
        confidence=0.8,
        ambiguity=is_ambiguous_text(description),
    )


def parse_access_rights(value: str | None, client_map: dict[str, str] | None = None) -> dict[str, Any]:
    text = clean_text(value)
    if not text:
        return {}
    clients = list((client_map or DEFAULT_ACCESS_RIGHT_CLIENTS).items())
    parts = [part.strip().upper() for part in text.split("/")]
    parsed_clients: list[dict[str, Any]] = []
    for index, (client_code, client_name) in enumerate(clients):
        code = parts[index] if index < len(parts) else ""
        parsed_clients.append(
            {
                "client": client_code,
                "client_name": client_name,
                "code": code,
                "read": "R" in code,
                "write": "W" in code,
                "allowed": code not in {"", "--"},
            }
        )
    return {
        "raw": text,
        "clients": parsed_clients,
    }


def first_field_value(fields: dict[str, Any], expected_header: str) -> str:
    expected = normalize_header_part(expected_header)
    for key, value in fields.items():
        if normalize_header_part(key) == expected:
            return clean_text(str(value))
    squashed = expected.replace(" ", "")
    for key, value in fields.items():
        if normalize_header_part(key).replace(" ", "") == squashed:
            return clean_text(str(value))
    return ""


def atomic_requirement_instruction() -> str:
    return (
        "Extract atomic requirements from this source. Keep each requirement independently testable. "
        "Preserve technical terms such as DLMS/COSEM, OBIS, SAP, HLS, firmware, register, event, alarm, "
        "and measurement units. If the source is contextual rather than normative, mark ambiguity=true "
        "or return an empty requirements list."
    )


def table_atom_instruction() -> str:
    return (
        "Convert this table row into one atomic technical item or requirement. Preserve all codes, group "
        "numbers, event numbers, object names, units, and descriptions exactly enough for traceability. "
        "Classify the domain and suggest a verification method."
    )


def atomic_requirement_schema() -> dict[str, Any]:
    return {
        "requirements": [
            {
                "req_id": "string",
                "stable_req_id": "string",
                "source_id": "string",
                "source_refs": ["string"],
                "domain": "string",
                "object": "string",
                "requirement_type": "string",
                "requirement": "string",
                "condition": "string|null",
                "parameters": {},
                "verification_method": "inspection|test|configuration_check|document_review|analysis",
                "ambiguity": "boolean",
                "review_questions": ["string"],
                "confidence": "number",
            }
        ]
    }


def assert_valid_atomic_requirements(rows: list[dict[str, Any]]) -> None:
    issues = validate_atomic_requirements(rows)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        preview = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise ValueError(f"invalid atomic requirements: {preview}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atomize a technical standard document for LLM requirement analysis.")
    parser.add_argument("input", type=Path, help="Input .docx, .xlsx, .pdf, or .html file")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    parser.add_argument("--chunk-chars", type=int, default=3500, help="Target character size per retrieval chunk")
    parser.add_argument(
        "--kb",
        type=Path,
        action="append",
        default=[],
        help="External knowledge base JSON file. Can be provided multiple times.",
    )
    parser.add_argument("--domain-pack", type=Path, default=None, help="Optional domain pack directory for shadow table matching.")
    return parser.parse_args()


def run_atomizer_pipeline(
    input_path: Path,
    out_dir: Path,
    *,
    chunk_chars: int = 3500,
    kb_paths: list[Path] | None = None,
    domain_pack_dir: Path | None = None,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    if not input_path.exists():
        raise AtomizerInputError(f"Input file does not exist: {input_path}")
    input_format = input_path.suffix.lower()
    if input_format == ".xls":
        raise AtomizerInputError("Legacy .xls input is not supported; save it as .xlsx. Supported formats: .docx, .xlsx, .pdf, .html.")
    if input_format == ".html":
        if os.environ.get("RATOMIZER_ENABLE_HTML_PARSER", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            raise AtomizerInputError("HTML input is disabled by default; set RATOMIZER_ENABLE_HTML_PARSER=1 to enable.")
    if input_format not in SUPPORTED_INPUT_FORMATS:
        raise AtomizerInputError(f"Unsupported input format: {input_format or '<none>'}. Supported formats: .docx, .xlsx, .pdf, .html.")

    out_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("loading knowledge bases (%s files)", len(kb_paths or []))
    knowledge_bases = load_knowledge_bases(kb_paths or [])
    document_profile = load_document_profile_from_domain_pack(domain_pack_dir)

    LOGGER.info("extracting %s", input_format.lstrip("."))
    _reset_table_structure_hypotheses()  # S1-4：双轨假设累积按本次运行隔离
    xlsx_requirement_list_candidates: int | None = None
    if input_format == ".docx":
        blocks, table_items, table_cell_items = extract_docx(input_path, knowledge_bases=knowledge_bases, document_profile=document_profile)
    elif input_format == ".xlsx":
        from parsers.xlsx_parser import extract_xlsx

        blocks, table_items, table_cell_items = extract_xlsx(input_path, knowledge_bases=knowledge_bases, document_profile=document_profile)
        # A6：需求清单型 xlsx 行映射分流（默认关）
        if os.environ.get("RATOMIZER_XLSX_REQUIREMENT_LIST", "").strip().lower() in {"1", "true", "yes", "on"}:
            from xlsx_requirement_list import extract_requirement_list_candidates, write_base_library_candidates
            xlsx_candidates = extract_requirement_list_candidates(input_path)
            if xlsx_candidates:
                write_base_library_candidates(out_dir, xlsx_candidates)
                xlsx_requirement_list_candidates = len(xlsx_candidates)
    elif input_format == ".html":
        from parsers.html_parser import extract_html

        blocks, table_items, table_cell_items = extract_html(input_path, knowledge_bases=knowledge_bases)
    else:
        from parsers.pdf_parser import extract_pdf

        blocks, table_items, table_cell_items = extract_pdf(input_path, knowledge_bases=knowledge_bases, document_profile=document_profile)
    LOGGER.info("extracted %s blocks, %s table rows, %s table cells", len(blocks), len(table_items), len(table_cell_items))
    # S1-4：双轨签发的表格结构假设落盘（OFF / 无假设 → 不写任何文件，产物与 main 一致）。
    hypothesis_count = _flush_table_structure_hypotheses(out_dir, document_id=input_path.stem)
    pattern_shadow = None
    if domain_pack_dir is not None:
        pattern_shadow = apply_table_pattern_shadow(blocks, table_items, domain_pack_dir)
    mark_doc_regions(blocks, table_items, document_profile=document_profile, table_cell_items=table_cell_items)
    # A7：未抽取内容登记册（默认开启，纯登记不改行为）
    unextracted_registry: dict[str, Any] | None = None
    if os.environ.get("RATOMIZER_UNEXTRACTED_REGISTRY", "1").strip().lower() not in {"0", "false", "off"}:
        unextracted_registry = build_unextracted_registry(input_path, blocks)
        write_unextracted_registry(out_dir, unextracted_registry)
    table_cell_dispositions = build_table_cell_dispositions(blocks, table_cell_items)
    LOGGER.info("building chunks")
    chunks = build_chunks(blocks, target_chars=chunk_chars, include_regions={"body"})
    body_table_items = [item for item in table_items if item.get("doc_region") == "body"]
    body_table_cells = [cell for cell in table_cell_items if cell.get("doc_region") == "body"]
    LOGGER.info("building candidates")
    atomic_candidates = build_atomic_candidates(
        blocks,
        body_table_items,
        include_regions={"body"},
        table_cell_items=body_table_cells,
    )
    try:
        assert_valid_atomic_requirements(atomic_candidates)
    except ValueError as exc:
        raise AtomizerPipelineError(str(exc)) from exc
    llm_tasks = build_llm_tasks(chunks, body_table_items)
    quality_report = build_quality_report(blocks, table_items, atomic_candidates, llm_tasks, pattern_shadow=pattern_shadow, out_dir=out_dir)

    LOGGER.info("writing outputs")
    block_count = write_jsonl(out_dir / "blocks.jsonl", blocks)
    chunk_count = write_jsonl(out_dir / "chunks.jsonl", chunks)
    table_count = write_jsonl(out_dir / "table_items.jsonl", table_items)
    table_cell_count = write_jsonl(out_dir / "table_cell_items.jsonl", table_cell_items)
    disposition_count = write_jsonl(
        governed_artifact_path(out_dir, "table_cell_dispositions.jsonl"),
        table_cell_dispositions,
    )
    atomic_count = write_jsonl(out_dir / "atomic_requirements.jsonl", atomic_candidates)
    task_count = write_jsonl(out_dir / "llm_tasks.jsonl", llm_tasks)
    write_json(out_dir / "quality_report.json", quality_report)

    domain_counts: Counter[str] = Counter()
    kb_counts: Counter[str] = Counter()
    for row in blocks:
        domain_counts.update(row.get("domain_tags", []))
        kb_counts.update(match.get("name", match.get("entry_id", "")) for match in row.get("kb_matches", []))
    for row in table_items:
        domain_counts.update(row.get("domain_tags", []))
        kb_counts.update(match.get("name", match.get("entry_id", "")) for match in row.get("kb_matches", []))

    manifest = {
        "tool": "requirement-atomizer",
        "version": __version__,
        "table_structure_version": TABLE_STRUCTURE_VERSION,
        "table_disposition_rule_version": TABLE_DISPOSITION_RULE_VERSION,
        "input": str(input_path),
        "input_format": input_format.lstrip("."),
        "output_dir": str(out_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_bases": [
            {
                "kb_id": info.kb_id,
                "name": info.name,
                "version": info.version,
                "entries": info.entries,
            }
            for info in knowledge_bases.infos
        ],
        "domain_pack": str(domain_pack_dir.expanduser().resolve()) if domain_pack_dir else None,
        "counts": {
            "blocks": block_count,
            "chunks": chunk_count,
            "table_items": table_count,
            "table_cell_items": table_cell_count,
            "table_cell_dispositions": disposition_count,
            "body_table_items": len(body_table_items),
            "atomic_requirements": atomic_count,
            "llm_tasks": task_count,
        },
        "files": {
            "blocks": "blocks.jsonl",
            "chunks": "chunks.jsonl",
            "table_items": "table_items.jsonl",
            "table_cell_items": "table_cell_items.jsonl",
            "table_cell_dispositions": "table_cell_dispositions.jsonl",
            "atomic_requirements": "atomic_requirements.jsonl",
            "llm_tasks": "llm_tasks.jsonl",
            "quality_report": "quality_report.json",
            "unextracted_registry": "unextracted_registry.json",
            "summary": "summary.md",
        },
    }
    # S1-4：双轨开且有签发假设时，登记到 manifest 计数/文件（OFF 或无假设 → manifest 不变）。
    if hypothesis_count:
        manifest["counts"]["table_structure_hypotheses"] = hypothesis_count
        manifest["files"]["table_structure_hypotheses"] = TABLE_STRUCTURE_HYPOTHESES_FILENAME
        manifest["table_dual_track"] = {
            "switch": TABLE_DUAL_TRACK_SWITCH,
            "issued_count": hypothesis_count,
        }
    # A7：登记册写入后同步登记 manifest
    if unextracted_registry is not None:
        manifest["counts"]["unextracted_entries"] = unextracted_registry.get("total", 0)
        manifest["unextracted_registry"] = {
            "version": unextracted_registry.get("schema", ""),
            "total": unextracted_registry.get("total", 0),
            "by_kind": unextracted_registry.get("by_kind", {}),
        }
    # A6：需求清单候选写入后同步登记 manifest
    if xlsx_requirement_list_candidates is not None:
        manifest["counts"]["xlsx_requirement_list_candidates"] = xlsx_requirement_list_candidates
        manifest["files"]["base_library_candidates"] = "base_library_candidates.jsonl"
    write_json(out_dir / "manifest.json", manifest)
    write_summary(out_dir / "summary.md", manifest, domain_counts, kb_counts, quality_report=quality_report)

    return manifest


def main() -> int:
    args = parse_args()
    try:
        manifest = run_atomizer_pipeline(
            args.input,
            args.out,
            chunk_chars=args.chunk_chars,
            kb_paths=args.kb,
            domain_pack_dir=args.domain_pack,
        )
    except AtomizerInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
