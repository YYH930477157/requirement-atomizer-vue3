"""HTML 输入解析器（A5①）。

把 HTML 文档解析为 DocumentIR：标题/段落/表格结构提取，表格走既有表格工件路径。
默认关闭；开关见 config.py / RATOMIZER_ENABLE_HTML_PARSER（或调用方显式启用）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lxml import html

from atomize import build_table_artifacts, clean_text
from doc_ir import DocumentIR, blocks_to_doc_ir
from parsers.base import DocumentParser
from requirement_kb import KnowledgeRepository


HTML_PARSER_VERSION = "html-parser-v1"


def _node_text(node: Any) -> str:
    """提取节点下全部文本，按空白规范化。"""
    text = str(node.text_content() or "").strip()
    return clean_text(text)


def _is_heading_tag(tag: str) -> tuple[bool, int]:
    m = re.fullmatch(r"h([1-6])", tag.lower())
    if m:
        return True, int(m.group(1))
    return False, 0


def _parse_table(
    table_node: Any,
    *,
    table_id: str,
    block_id: str,
    order: int,
    section_path: list[str],
    knowledge_bases: KnowledgeRepository,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """把 <table> 节点转成三件套。"""
    rows: list[list[str]] = []
    for tr in table_node.findall(".//tr"):
        row_cells: list[str] = []
        for cell in tr.findall(".//td") + tr.findall(".//th"):
            row_cells.append(_node_text(cell))
        if any(row_cells):
            rows.append(row_cells)
    if not rows:
        return {}, [], []
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return build_table_artifacts(
        padded,
        table_id=table_id,
        block_id=block_id,
        order=order,
        table_title="HTML table",
        section_path=section_path,
        knowledge_bases=knowledge_bases,
        source_format="html",
    )


def extract_html(
    input_path: Path,
    knowledge_bases: KnowledgeRepository | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """HTML 抽取入口：返回 (blocks, table_items, table_cell_items)。"""
    knowledge_bases = knowledge_bases or KnowledgeRepository.from_paths([])
    text = Path(input_path).expanduser().resolve().read_text(encoding="utf-8")
    doc = html.fromstring(text)
    blocks: list[dict[str, Any]] = []
    table_items: list[dict[str, Any]] = []
    table_cell_items: list[dict[str, Any]] = []
    order = 0
    table_count = 0

    sections: dict[int, str] = {}

    def section_path() -> list[str]:
        return [sections[level] for level in sorted(sections)]

    for node in doc.iter():
        tag = str(node.tag).lower()
        if tag in ("script", "style", "noscript"):
            continue
        is_heading, level = _is_heading_tag(tag)
        if is_heading:
            title = _node_text(node)
            if not title:
                continue
            sections[level] = title
            for old in list(sections):
                if old > level:
                    del sections[old]
            order += 1
            blocks.append({
                "block_id": f"BLK-{order:06d}",
                "order": order,
                "type": "heading",
                "source_format": "html",
                "heading_level": level,
                "text": title,
                "section_path": section_path(),
                "domain_tags": [],
                "kb_matches": [],
                "requirement_like": False,
                "noise": False,
            })
            continue
        if tag == "p":
            text = _node_text(node)
            if not text:
                continue
            order += 1
            blocks.append({
                "block_id": f"BLK-{order:06d}",
                "order": order,
                "type": "paragraph",
                "source_format": "html",
                "text": text,
                "section_path": section_path(),
                "domain_tags": [],
                "kb_matches": [],
                "requirement_like": False,
                "noise": False,
            })
            continue
        if tag == "table":
            table_count += 1
            order += 1
            table_id = f"TBL-{table_count:06d}"
            block_id = f"BLK-{order:06d}"
            table_block, new_items, new_cells = _parse_table(
                node,
                table_id=table_id,
                block_id=block_id,
                order=order,
                section_path=section_path(),
                knowledge_bases=knowledge_bases,
            )
            if table_block:
                blocks.append(table_block)
                table_items.extend(new_items)
                table_cell_items.extend(new_cells)

    return blocks, table_items, table_cell_items


class HtmlParser(DocumentParser):
    source_format = "html"

    def parse(self, path: Path) -> DocumentIR:
        input_path = path.expanduser().resolve()
        blocks, table_items, table_cell_items = extract_html(input_path)
        return blocks_to_doc_ir(
            blocks=blocks,
            table_items=table_items,
            source_path=input_path,
            doc_id=input_path.stem,
        )
