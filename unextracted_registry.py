"""未抽取内容登记册（A7）。

汇总解析层主动放弃或无法进入需求管线的内容：noise 块、隐藏 sheet、跳过 sheet、
textbox/header/footer 收容前后差额等。默认开启，纯登记不改行为。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from output_writer import write_json
from result_package import governed_artifact_path

UNEXTRACTED_REGISTRY_VERSION = "unextracted-registry/v1"
REGISTRY_FILENAME = "unextracted_registry.json"

# A9-3：疑似流程图页开关（默认关）
_FIGURE_PAGE_FILTER_ENV = "RATOMIZER_TENDER_FIGURE_PAGE_FILTER"
# 页面文本字符阈值：低于此值 + 存在图标题信号 → 疑似流程图页
_FIGURE_PAGE_CHAR_THRESHOLD = 200
# 图/流程图标题信号
_FIGURE_SIGNAL_RE = re.compile(
    r"\b(?:figure|diagram|flow\s*(?:chart|diagram)?|chart|process\s*(?:flow|diagram)|"
    r"schematic|illustration|drawing|image|picture|photo|"
    r"图|流程图|示意图|框图|线路图|照片)"
    r"|\b(?:flow\s+diagram|flow\s+chart|process\s+flow\s+diagram|process\s+flow\s+chart|"
    r"credit\s+transfer\s+process)\b",
    re.IGNORECASE,
)

# 与 requirements_analysis_template.py 保持一致，避免循环依赖
_SKIPPED_SHEET_TITLES = {
    "需求模版Release notes",
    "原始需求对应表",
    "需求变更管理",
}


KIND_NOISE_BLOCK = "noise_block"
KIND_HIDDEN_SHEET = "hidden_sheet"
KIND_SKIPPED_SHEET = "skipped_sheet"
KIND_TEXTBOX_CHANNEL = "textbox_channel"
KIND_HEADER_CHANNEL = "header_channel"
KIND_FOOTER_CHANNEL = "footer_channel"
KIND_FRONT_MATTER_BLOCK = "front_matter_block"
KIND_NON_PRODUCT_REFERENCE_BLOCK = "non_product_reference_block"
KIND_FIGURE_PAGE = "figure_page"


def _entry(
    kind: str,
    reason: str,
    *,
    source_id: str = "",
    section: str = "",
    text_preview: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preview = str(text_preview or "").strip()
    return {
        "kind": kind,
        "reason": reason,
        "source_id": str(source_id or ""),
        "section": str(section or ""),
        "text_preview": preview[:300],
        "evidence": evidence or {},
    }


def _collect_noise_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for block in blocks:
        if not block.get("noise"):
            continue
        bid = str(block.get("block_id") or "")
        entries.append(_entry(
            KIND_NOISE_BLOCK,
            "解析层标为页眉页脚/噪声，未进入抽取管线",
            source_id=bid,
            section=" > ".join(str(p) for p in (block.get("section_path") or [])),
            text_preview=str(block.get("text") or ""),
            evidence={"block_id": bid, "section_path": block.get("section_path")},
        ))
    return entries


def _collect_region_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """正文区之前的 front_matter 块（除 noise 外）登记为未抽取，供复核是否误伤正文。"""
    entries: list[dict[str, Any]] = []
    for block in blocks:
        region = str(block.get("doc_region") or "body")
        if region in {"body", "noise"} or block.get("noise"):
            continue
        bid = str(block.get("block_id") or "")
        kind = KIND_NON_PRODUCT_REFERENCE_BLOCK if region == "non_product_reference" else KIND_FRONT_MATTER_BLOCK
        reason = (
            f"文档区域标为 {region}，默认不进入 body 抽取"
            if region != "non_product_reference"
            else "招标程序性/商务附件区域，按参考类处理，不进功能需求"
        )
        entries.append(_entry(
            kind,
            reason,
            source_id=bid,
            section=" > ".join(str(p) for p in (block.get("section_path") or [])),
            text_preview=str(block.get("text") or ""),
            evidence={"block_id": bid, "doc_region": region, "section_path": block.get("section_path")},
        ))
    return entries


def _collect_xlsx_sheets(input_path: Path) -> list[dict[str, Any]]:
    """从 xlsx 输入读取隐藏 sheet 与跳过 sheet，每条带原因。"""
    entries: list[dict[str, Any]] = []
    suffix = input_path.suffix.lower()
    if suffix != ".xlsx":
        return entries
    try:
        workbook = load_workbook(input_path, data_only=True, read_only=True)
    except Exception:
        return entries
    try:
        for sheet in workbook.worksheets:
            title = str(sheet.title or "").strip()
            if not title:
                continue
            state = str(getattr(sheet, "sheet_state", "visible")).strip()
            if state != "visible":
                entries.append(_entry(
                    KIND_HIDDEN_SHEET,
                    f"sheet 状态为 {state}，未进入解析",
                    source_id=title,
                    text_preview=title,
                    evidence={"sheet_title": title, "sheet_state": state},
                ))
            elif title in _SKIPPED_SHEET_TITLES:
                entries.append(_entry(
                    KIND_SKIPPED_SHEET,
                    "sheet 标题命中已知非内容清单（Release notes/变更管理/对应表），未进入解析",
                    source_id=title,
                    text_preview=title,
                    evidence={"sheet_title": title, "sheet_state": state},
                ))
    finally:
        workbook.close()
    return entries


def _collect_content_channel_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A5② 收容的 textbox/header/footer 内容，登记为未进入正文流。"""
    entries: list[dict[str, Any]] = []
    for block in blocks:
        channel = str(block.get("content_channel") or "body")
        if channel == "body":
            continue
        kind = {
            "textbox": KIND_TEXTBOX_CHANNEL,
            "header": KIND_HEADER_CHANNEL,
            "footer": KIND_FOOTER_CHANNEL,
        }.get(channel, f"{channel}_channel")
        bid = str(block.get("block_id") or "")
        entries.append(_entry(
            kind,
            f"内容来自 {channel} 通道，未按正文块参与需求抽取",
            source_id=bid,
            section=" > ".join(str(p) for p in (block.get("section_path") or [])),
            text_preview=str(block.get("text") or ""),
            evidence={"block_id": bid, "content_channel": channel},
        ))
    return entries


def _collect_figure_pages(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A9-3：疑似流程图页强制高亮（默认关）。

    判据：页面文本字符数低于阈值，且存在图/流程图标题信号；或页面块数极少（≤2）
    且文本极低。基于现有解析期几何/文本证据，不做 VLM 识别。
    """
    value = os.environ.get(_FIGURE_PAGE_FILTER_ENV, "0").strip().lower()
    if value in {"0", "false", "off", ""}:
        return []

    pages: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        page_number = block.get("page_number")
        if page_number is None:
            continue
        pages.setdefault(int(page_number), []).append(block)

    entries: list[dict[str, Any]] = []
    for page_number, page_blocks in sorted(pages.items()):
        text_blocks = [b for b in page_blocks if str(b.get("type") or "") in {"paragraph", "heading", "caption"}]
        total_chars = sum(len(str(b.get("text") or "")) for b in text_blocks)
        if total_chars >= _FIGURE_PAGE_CHAR_THRESHOLD:
            continue
        # 图/流程图标题信号
        has_figure_signal = any(
            _FIGURE_SIGNAL_RE.search(str(b.get("text") or ""))
            for b in page_blocks
        )
        # 极低文本 + 块数极少（无段落或仅标题）
        sparse_page = len(text_blocks) <= 2 and total_chars <= 120
        if not has_figure_signal and not sparse_page:
            continue
        title_block = next(
            (b for b in page_blocks if str(b.get("type") or "") == "heading"),
            None,
        )
        title_text = str(title_block.get("text") or "") if title_block else ""
        entries.append(_entry(
            KIND_FIGURE_PAGE,
            "整页文本极少且疑似含图/流程图，请专家人工核对是否含规范性内容",
            source_id=f"PAGE-{page_number}",
            section=" > ".join(str(p) for p in (title_block.get("section_path") or []) if title_block),
            text_preview=title_text,
            evidence={
                "page_number": page_number,
                "page_text_char_count": total_chars,
                "text_block_count": len(text_blocks),
                "has_figure_signal": has_figure_signal,
                "sparse_page": sparse_page,
                "title": title_text,
            },
        ))
    return entries


def build_unextracted_registry(
    input_path: Path,
    blocks: list[dict[str, Any]],
    *_unused: Any,
) -> dict[str, Any]:
    """构建未抽取内容登记册。默认开启，纯登记不改行为。

    返回字典可直接写为 unextracted_registry.json；同时可被 quality_report /
    clarification_report 读取汇总。
    """
    input_path = Path(input_path).expanduser().resolve()
    entries: list[dict[str, Any]] = []
    entries.extend(_collect_noise_blocks(blocks))
    entries.extend(_collect_region_blocks(blocks))
    entries.extend(_collect_content_channel_blocks(blocks))
    entries.extend(_collect_figure_pages(blocks))
    entries.extend(_collect_xlsx_sheets(input_path))

    by_kind: dict[str, int] = {}
    for entry in entries:
        kind = entry["kind"]
        by_kind[kind] = by_kind.get(kind, 0) + 1

    return {
        "schema": UNEXTRACTED_REGISTRY_VERSION,
        "total": len(entries),
        "by_kind": by_kind,
        "entries": entries,
    }


def load_unextracted_registry(out_dir: Path) -> dict[str, Any] | None:
    """读取已写入的登记册；缺失或损坏返回 None，调用方 fail-closed 按无登记处理。"""
    path = Path(out_dir).expanduser().resolve() / REGISTRY_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_unextracted_registry(
    out_dir: Path,
    registry: dict[str, Any],
    *,
    use_governed_path: bool = True,
) -> Path:
    """写登记册到输出目录。默认走 governed_artifact_path（package_v1 兼容）。"""
    out_dir = Path(out_dir).expanduser().resolve()
    if use_governed_path:
        path = governed_artifact_path(out_dir, REGISTRY_FILENAME, category="pipeline", for_write=True)
    else:
        path = out_dir / REGISTRY_FILENAME
    write_json(path, registry)
    return path


def summarize_unextracted_counts(out_dir: Path) -> dict[str, Any]:
    """供 quality_report 调用的轻量摘要。"""
    payload = load_unextracted_registry(out_dir)
    if payload is None:
        return {"available": False, "total": 0, "by_kind": {}}
    return {
        "available": True,
        "total": int(payload.get("total") or 0),
        "by_kind": dict(payload.get("by_kind") or {}),
    }


def collect_unextracted_clarification_entries(out_dir: Path) -> list[dict[str, Any]]:
    """供 clarification_report 调用的入口：把可能含需求的未抽取项转为参考级清单。

    噪声块/front_matter/隐藏 sheet 本身是有意排除，但登记后 reviewer 可抽查是否误伤。
    所有条目返回为"参考"（非阻塞），避免直接打爆就绪门。
    """
    payload = load_unextracted_registry(out_dir)
    if payload is None:
        return []
    entries: list[dict[str, Any]] = []
    for entry in (payload.get("entries") or []):
        kind = entry.get("kind", "")
        # 只把可能含真实需求的项暴露给澄清报告；隐藏/跳过 sheet 是结构性排除
        if kind in {
            KIND_NOISE_BLOCK,
            KIND_FRONT_MATTER_BLOCK,
            KIND_TEXTBOX_CHANNEL,
            KIND_NON_PRODUCT_REFERENCE_BLOCK,
            KIND_FIGURE_PAGE,
        }:
            entries.append(entry)
    return entries
