"""DOCX 额外内容通道抽取（A5②）：文本框与页眉页脚。

由 ``RATOMIZER_DOCX_EXTRA_CHANNELS`` 控制（默认关闭）。开启后 extract_docx
在正文段落/表格之后追加这些通道内容，块上标记 ``content_channel=textbox|header|footer``，
不改变既有正文块内容；关闭时 blocks.jsonl 与未引入该功能前逐字节一致。
"""
from __future__ import annotations

from typing import Any

from docx import Document
from docx.enum.section import WD_HEADER_FOOTER
from docx.oxml.ns import qn


def _paragraph_texts_from_xml(element: Any) -> list[str]:
    """从任意 w:p 容器（body/hdr/ftr/txbxContent）按段落提取文本。"""
    texts: list[str] = []
    for p in element.findall(qn("w:p")):
        parts = p.findall(f".//{qn('w:t')}")
        if not parts:
            continue
        text = "".join(part.text or "" for part in parts).strip()
        if text:
            texts.append(text)
    return texts


def extract_textbox_texts(document: Document) -> list[str]:
    """扫描 body 内所有 w:txbxContent 文本框，返回非空段落文本列表。"""
    body = document.element.body
    texts: list[str] = []
    for txbx in body.findall(f".//{qn('w:txbxContent')}"):
        texts.extend(_paragraph_texts_from_xml(txbx))
    # 去重（同一文本框可能在多个占位 shape 中重复出现）
    seen: set[str] = set()
    result: list[str] = []
    for text in texts:
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _header_footer_parts(document: Document) -> list[tuple[str, Any]]:
    """返回 (channel, part) 列表，channel 为 header/footer；覆盖 default/first/even。"""
    parts: list[tuple[str, Any]] = []
    for section in document.sections:
        # default
        parts.append(("header", section.header))
        parts.append(("footer", section.footer))
        # first page
        if getattr(section, "different_first_page_header_footer", False):
            try:
                first_header = section.first_page_header
                first_footer = section.first_page_footer
            except Exception:
                first_header = first_footer = None
            if first_header is not None:
                parts.append(("header", first_header))
            if first_footer is not None:
                parts.append(("footer", first_footer))
        # even page
        if getattr(section, "odd_and_even_pages_header_footer", False):
            try:
                even_header = section.even_page_header
                even_footer = section.even_page_footer
            except Exception:
                even_header = even_footer = None
            if even_header is not None:
                parts.append(("header", even_header))
            if even_footer is not None:
                parts.append(("footer", even_footer))
    return parts


def extract_header_footer_texts(document: Document) -> dict[str, list[str]]:
    """返回 {"header": [...], "footer": [...]}。按 part 去重，避免多节引用同一 part 重复。"""
    result: dict[str, list[str]] = {"header": [], "footer": []}
    seen_partnames: set[str] = set()
    for channel, part in _header_footer_parts(document):
        partname = ""
        if hasattr(part, "part") and part.part is not None:
            partname = str(getattr(part.part, "partname", "") or "")
        if partname in seen_partnames:
            continue
        seen_partnames.add(partname)
        # Header/Footer 对象通过 ._element 暴露 XML 根
        element = getattr(part, "_element", None)
        if element is None:
            continue
        texts = _paragraph_texts_from_xml(element)
        for text in texts:
            if text not in result[channel]:
                result[channel].append(text)
    return result


def extract_docx_extra_channels(document: Document) -> dict[str, list[str]]:
    """统一入口：返回三种通道的非空文本。"""
    hf = extract_header_footer_texts(document)
    return {
        "textbox": extract_textbox_texts(document),
        "header": hf["header"],
        "footer": hf["footer"],
    }
