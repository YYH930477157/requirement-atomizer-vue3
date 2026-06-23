from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber

from atomize import (
    DEFAULT_DOCUMENT_PROFILE,
    AtomizerInputError,
    DocumentProfile,
    SectionState,
    build_table_artifacts,
    clean_text,
    detect_heading,
    infer_table_title,
    is_noise,
    is_requirement_like,
    kb_domain_tags,
    looks_like_caption,
    match_knowledge,
    merge_tags,
    tag_domains,
)
from requirement_kb import KnowledgeRepository


LOGGER = logging.getLogger("requirement_atomizer")
TEXT_LAYER_SAMPLE_PAGES = 5
MIN_AVERAGE_EXTRACTED_CHARS = 100
HEADER_FOOTER_BAND_RATIO = 0.12


def extract_pdf(
    input_path: Path,
    knowledge_bases: KnowledgeRepository | None = None,
    document_profile: DocumentProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    knowledge_bases = knowledge_bases or KnowledgeRepository.from_paths([])
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    with pdfplumber.open(input_path) as pdf:
        _assert_text_layer(pdf)
        repeated_noise = _detect_repeated_margin_lines(pdf)

        sections = SectionState()
        blocks: list[dict[str, Any]] = []
        table_items: list[dict[str, Any]] = []
        order = 0
        table_count = 0
        last_caption: str | None = None

        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            table_bboxes = [table.bbox for table in tables]
            page_paragraphs = _paragraphs_outside_tables(page, table_bboxes, document_profile=profile)
            paragraph_index = 0

            for table in tables:
                while paragraph_index < len(page_paragraphs) and page_paragraphs[paragraph_index]["bottom"] <= table.bbox[1]:
                    order, last_caption = _append_text_block(
                        blocks,
                        page_paragraphs[paragraph_index]["text"],
                        order=order,
                        page_number=page_number,
                        sections=sections,
                        knowledge_bases=knowledge_bases,
                        repeated_noise=repeated_noise,
                        last_caption=last_caption,
                        profile=profile,
                    )
                    paragraph_index += 1

                matrix = _clean_table_matrix(table.extract())
                if _skip_table_matrix(matrix):
                    continue
                table_count += 1
                order += 1
                table_id = f"TBL-{table_count:06d}"
                block_id = f"BLK-{order:06d}"
                table_block, new_table_items = build_table_artifacts(
                    matrix,
                    table_id=table_id,
                    block_id=block_id,
                    order=order,
                    table_title=infer_table_title(last_caption, table_count),
                    section_path=sections.path(),
                    knowledge_bases=knowledge_bases,
                )
                table_block["page_number"] = page_number
                for item in new_table_items:
                    item["page_number"] = page_number
                blocks.append(table_block)
                table_items.extend(new_table_items)
                last_caption = None

            while paragraph_index < len(page_paragraphs):
                order, last_caption = _append_text_block(
                    blocks,
                    page_paragraphs[paragraph_index]["text"],
                    order=order,
                    page_number=page_number,
                    sections=sections,
                    knowledge_bases=knowledge_bases,
                    repeated_noise=repeated_noise,
                    last_caption=last_caption,
                    profile=profile,
                )
                paragraph_index += 1

    return blocks, table_items


def _assert_text_layer(pdf: Any) -> None:
    sample = pdf.pages[:TEXT_LAYER_SAMPLE_PAGES]
    if not sample:
        raise AtomizerInputError("该 PDF 无文字层（疑似扫描件），当前版本不支持；可用 Word 打开该 PDF 另存为 .docx 后重试。")
    chars = [len(page.extract_text() or "") for page in sample]
    if sum(chars) / len(chars) < MIN_AVERAGE_EXTRACTED_CHARS:
        raise AtomizerInputError("该 PDF 无文字层（疑似扫描件），当前版本不支持；可用 Word 打开该 PDF 另存为 .docx 后重试。")


def _detect_repeated_margin_lines(pdf: Any) -> set[str]:
    threshold = max(2, int(len(pdf.pages) * 0.6 + 0.999))
    counts: Counter[str] = Counter()
    for page in pdf.pages:
        top_limit = page.height * HEADER_FOOTER_BAND_RATIO
        bottom_limit = page.height * (1 - HEADER_FOOTER_BAND_RATIO)
        for line in _word_lines(page.extract_words()):
            if line["top"] <= top_limit or line["bottom"] >= bottom_limit:
                normalized = _normalize_repeated_line(line["text"])
                if normalized:
                    counts[normalized] += 1
    return {text for text, count in counts.items() if count >= threshold}


def _paragraphs_outside_tables(
    page: Any,
    table_bboxes: list[tuple[float, float, float, float]],
    *,
    document_profile: DocumentProfile,
) -> list[dict[str, Any]]:
    words = [
        word
        for word in page.extract_words()
        if not any(_word_intersects_bbox(word, bbox) for bbox in table_bboxes)
    ]
    lines = _word_lines(words)
    if not lines:
        return []

    paragraphs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for line in lines:
        if previous is not None and _starts_new_paragraph(
            previous,
            line,
            page_height=page.height,
            document_profile=document_profile,
        ):
            paragraphs.append(_merge_lines(current))
            current = []
        current.append(line)
        previous = line
    if current:
        paragraphs.append(_merge_lines(current))
    return [paragraph for paragraph in paragraphs if paragraph["text"]]


def _word_lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda word: (round(float(word["top"]), 1), float(word["x0"])))
    lines: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_top: float | None = None
    for word in sorted_words:
        top = float(word["top"])
        if current_top is None or abs(top - current_top) <= 3:
            current.append(word)
            current_top = top if current_top is None else (current_top + top) / 2
            continue
        lines.append(_merge_words(current))
        current = [word]
        current_top = top
    if current:
        lines.append(_merge_words(current))
    return lines


def _merge_words(words: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(words, key=lambda word: float(word["x0"]))
    return {
        "text": clean_text(" ".join(str(word["text"]) for word in ordered)),
        "top": min(float(word["top"]) for word in ordered),
        "bottom": max(float(word["bottom"]) for word in ordered),
        "x0": min(float(word["x0"]) for word in ordered),
        "x1": max(float(word["x1"]) for word in ordered),
    }


def _merge_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "text": clean_text(" ".join(line["text"] for line in lines)),
        "top": min(line["top"] for line in lines),
        "bottom": max(line["bottom"] for line in lines),
    }


def _starts_new_paragraph(
    previous: dict[str, Any],
    line: dict[str, Any],
    *,
    page_height: float,
    document_profile: DocumentProfile,
) -> bool:
    if _is_margin_line(previous, page_height) or _is_margin_line(line, page_height):
        return True
    gap = float(line["top"]) - float(previous["bottom"])
    if gap >= 12:
        return True
    if detect_heading(line["text"], "", document_profile=document_profile):
        return True
    if looks_like_caption(line["text"], document_profile=document_profile):
        return True
    return False


def _is_margin_line(line: dict[str, Any], page_height: float) -> bool:
    margin = 55
    return float(line["top"]) <= margin or float(line["bottom"]) >= page_height - margin


def _append_text_block(
    blocks: list[dict[str, Any]],
    text: str,
    *,
    order: int,
    page_number: int,
    sections: SectionState,
    knowledge_bases: KnowledgeRepository,
    repeated_noise: set[str],
    last_caption: str | None,
    profile: DocumentProfile,
) -> tuple[int, str | None]:
    text = clean_text(text)
    if not text:
        return order, last_caption

    heading = detect_heading(text, "", document_profile=profile)
    block_type = "paragraph"
    if heading:
        section_path = sections.update(heading[0], heading[1])
        block_type = "heading"
    else:
        section_path = sections.path()

    order += 1
    kb_matches = match_knowledge(knowledge_bases, text, " > ".join(section_path))
    domain_tags = merge_tags(tag_domains(text, " > ".join(section_path)), kb_domain_tags(kb_matches))
    normalized = _normalize_repeated_line(text)
    noise = is_noise(text, document_profile=profile) or normalized in repeated_noise
    block: dict[str, Any] = {
        "block_id": f"BLK-{order:06d}",
        "order": order,
        "type": block_type,
        "style": "",
        "text": text,
        "section_path": section_path,
        "page_number": page_number,
        "domain_tags": domain_tags,
        "kb_matches": kb_matches,
        "requirement_like": is_requirement_like(text),
        "noise": noise,
    }
    if heading:
        block["heading_level"] = heading[0]
    blocks.append(block)

    if looks_like_caption(text, document_profile=profile):
        last_caption = text
    elif block_type != "heading" and not noise:
        if last_caption and len(text) > 120:
            last_caption = None
    return order, last_caption


def _clean_table_matrix(raw_matrix: list[list[Any]] | None) -> list[list[str]]:
    matrix: list[list[str]] = []
    for row in raw_matrix or []:
        cleaned = [clean_text("" if value is None else str(value)) for value in row]
        if any(cleaned):
            matrix.append(cleaned)
    return matrix


def _skip_table_matrix(matrix: list[list[str]]) -> bool:
    if not matrix:
        return True
    non_empty_cells = sum(1 for row in matrix for value in row if value)
    return non_empty_cells <= 1


def _word_intersects_bbox(word: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    return not (
        float(word["x1"]) <= x0
        or float(word["x0"]) >= x1
        or float(word["bottom"]) <= top
        or float(word["top"]) >= bottom
    )


def _normalize_repeated_line(text: str) -> str:
    text = clean_text(text).lower()
    text = re.sub(r"\bpage\s+\d+\b", "page", text)
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
