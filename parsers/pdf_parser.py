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
_COPYRIGHT_FOOTER_RE = re.compile(chr(0xA9) + ".{0,40}" + chr(92) + "bpage" + chr(92) + "b", re.IGNORECASE)

# --- 词内空格破碎修复（机翻 PDF 排版病，2026-07-07 真实案例 UNI 12007）--------
# Google 翻译版 PDF 会把真实空格字形嵌进词内（"Water M eters"、"UNI/TS 1 2007"），
# 27% 的块受污染——LLM 输入被污染、页脚重复行检测失配、观感稀碎。调 x_tolerance 无效
# （空格是真字符），只能后处理拼合。**文档级门控**：仅当抽样页碎片率超阈值才启用，
# 正常 PDF（ABNT/EN16314 实测低于阈值）零触碰。
_FRAG_ALPHA_RE = re.compile("(?<![0-9] )" + chr(92) + "b([B-HJ-Zb-hj-z]) ([a-z]{2,})" + chr(92) + "b")  # 排除 a/A/I/i（合法单字母词）与数字后的单位字母（"0,5 m as"）
_FRAG_CAP_RE = re.compile(r"\b([A-Z]) ([A-Z]{1,4})\b(?! [a-z])")   # "I SO"/"O NE" → ISO/ONE
_FRAG_DIGIT_RE = re.compile(r"\b(\d) (\d{2,})\b")                   # "1 2007" → 12007
_FRAG_PROBE_RE = re.compile(r"\b[A-Za-z] [a-z]{2,}\b")
DEFRAG_RATIO_THRESHOLD = 0.02   # 每词碎片数 ≥2% 判定为破碎文档


# 引用字母的前导词：这些词后面的单个大写字母是合法引用（"Annex B gives…"/"class A meters"），
# 不是碎片——拼合会把 "B gives" 腐蚀成 "Bgives"（自审实锤）
_REF_LEAD_WORDS = frozenset((
    "annex", "appendix", "class", "table", "figure", "type", "part",
    "zone", "group", "category", "clause", "section", "grade",
))


def _guarded_sub(pattern: re.Pattern[str], text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        head = text[: m.start()].rstrip()
        lead = head.rsplit(None, 1)[-1] if head else ""
        # 引用字母保护：前词是 Annex/Class/Table 等，或前词本身是单个大写字母（引用链
        # "Annex A B"——A 的前词是 Annex，B 的前词是 A）；and/or 后的单个大写字母同理
        # （"classes A and B look…"），小写不豁免（"and b ecomes" 是真碎片）
        if lead.lower() in _REF_LEAD_WORDS or (len(lead) == 1 and lead.isupper()):
            return m.group(0)
        if lead.lower() in ("and", "or") and m.group(1).isupper():
            return m.group(0)
        return m.group(1) + m.group(2)
    return pattern.sub(repl, text)


_PAIR_RE = re.compile(r"(.)\1")


def _collapse_pairs(word: str) -> str | None:
    """相邻等对折半（"TThhiiss"→"This"，"002255.."→"025."）。几乎全部字符成对才算
    双写词（允许 1 个落单残字,容纳粘尾标点/奇数长度）,否则返回 None（"book" 折成
    "bok" 会损失信息——必须整词自证是双写才动）。"""
    collapsed = _PAIR_RE.sub(r"\1", word)
    if 2 * len(collapsed) - len(word) in (0, 1):
        return collapsed
    return None


def dedouble_text(text: str) -> str:
    """PDF 假粗体去双写（真实案例 UNI 12007 前言：粗体=同字形画两遍→"TThhiiss tteecchh…"）。

    两级门控：长词(≥4)完全成对即自证双写、无条件收（正常英文不存在全双写长词）；
    短词（"ww"/"11"/"aa"合法存在）只在同文本另有 ≥2 个长双写词佐证时才收。
    """
    words = text.split(" ")
    long_doubles = sum(1 for w in words if len(w) >= 4 and _collapse_pairs(w) is not None)
    if long_doubles == 0:
        return text
    out: list[str] = []
    for w in words:
        collapsed = _collapse_pairs(w) if len(w) >= 2 else None
        if collapsed is not None and (len(w) >= 4 or long_doubles >= 2):
            out.append(collapsed)
        else:
            out.append(w)
    return " ".join(out)


def defragment_text(text: str) -> str:
    """拼合词内空格碎片；迭代到稳定（"V a lue" 两轮收敛）。引用字母（Annex B 等）受保护。
    假粗体双写先收缩（"TThhiiss"→"This"），再走碎片拼合（"D eevveellooppeedd"→"d eveloped"→"developed"）。"""
    text = dedouble_text(text)
    prev = None
    while prev != text:
        prev = text
        text = _guarded_sub(_FRAG_ALPHA_RE, text)
        text = _guarded_sub(_FRAG_CAP_RE, text)
        text = _FRAG_DIGIT_RE.sub(r"\1\2", text)
    return text


def _fragmentation_ratio(pdf: Any, sample_pages: int = 8) -> float:
    frags = words = 0
    for page in pdf.pages[:sample_pages]:
        text = page.extract_text() or ""
        words += max(1, len(text.split()))
        frags += len(_FRAG_PROBE_RE.findall(text))
    return frags / max(1, words)


# --- 无画线表格重建（2026-07-07，真实案例 UNI 12007：page.lines/rects=0，find_tables=0）----
# pdfplumber 原生 text 策略实测不可用（整页吞成 100×14 伪表，且在去碎前推断列界），
# 自研：在已去碎的词行上按大间隙切格 → 列起点跨行聚类成网格 → 逻辑行组装（首列有内容=新行，
# 包裹续行按列归并）。伪表代价极高（表块 noise:False 且逐行进需求候选），守卫全过才产表；
# ABNT（画线表文档）零新增表块是验收门。
CELL_GAP_PT = 6.0            # 行内词间隙超过此值视为列界（第 88 页实测列距远大于此）
CELL_GAP_RELAXED_PT = 12.0   # 去碎模式下左词为单字符时的放宽阈值（防 "1 2007" 碎片跨格）
COLUMN_ALIGN_TOLERANCE = 4.0
_DOT_LEADER_RE = re.compile(r"\.{4,}\s*\d+\s*$")
_LIST_MARKER_CELL_RE = re.compile(r"^(?:[a-z0-9]{1,3}\)(\s|$)|\[\d+\](\s|$)|[—–•-](\s|$)|NOTE\b)")
_PURE_INT_RE = re.compile(r"^\d{1,4}$")


def _split_line_cells(words: list[dict[str, Any]], *, defrag: bool = False) -> list[dict[str, Any]]:
    """把一行的词按大间隙切成单元格；返回 [{text, x0, x1}]。

    阈值自适应：真表格的词距是双峰（格内小、格间大），固定 6pt 即可切准；宽词距排版的
    prose（ABNT 前言页实测词距普遍 7-12pt）会被固定阈值切碎成伪列——对 ≥6 词的行，
    阈值抬到 max(6pt, 2.2×中位间隙)，均匀大词距的行就整行归一格。
    """
    ordered = sorted(words, key=lambda w: float(w["x0"]))
    gaps = [float(b["x0"]) - float(a["x1"]) for a, b in zip(ordered, ordered[1:])]
    base_threshold = CELL_GAP_PT
    if len(ordered) >= 6 and gaps:
        median_gap = sorted(gaps)[len(gaps) // 2]
        base_threshold = max(CELL_GAP_PT, 2.2 * median_gap)
    groups: list[list[dict[str, Any]]] = [[ordered[0]]]
    for left, right in zip(ordered, ordered[1:]):
        threshold = base_threshold
        if defrag and len(str(left["text"]).strip()) <= 1:
            threshold = max(threshold, CELL_GAP_RELAXED_PT)
        if float(right["x0"]) - float(left["x1"]) > threshold:
            groups.append([right])
        else:
            groups[-1].append(right)
    cells = []
    for group in groups:
        text = clean_text(" ".join(str(w["text"]) for w in group))
        if defrag:
            text = defragment_text(text)
        cells.append({"text": text, "x0": float(group[0]["x0"]), "x1": float(group[-1]["x1"])})
    return cells


def _cluster_starts(values: list[float]) -> list[float]:
    """x0 聚类（容差内合并取均值），返回升序列起点。"""
    clusters: list[list[float]] = []
    for v in sorted(values):
        if clusters and v - clusters[-1][-1] <= COLUMN_ALIGN_TOLERANCE:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [sum(c) / len(c) for c in clusters]


def _nearest_column(x0: float, columns: list[float]) -> int | None:
    best, best_dist = None, None
    for idx, col in enumerate(columns):
        dist = abs(x0 - col)
        if best_dist is None or dist < best_dist:
            best, best_dist = idx, dist
    if best is None or best_dist is None:
        return None
    return best if best_dist <= COLUMN_ALIGN_TOLERANCE * 2 else None


def _assemble_rows(region: list[dict[str, Any]], columns: list[float]) -> list[list[str]]:
    """逻辑行组装：首列有内容且当前行已有首列 → 新行；否则并入当前行（包裹续行/后补列）。

    0711 评审修复：单元格距最近列锚点 >2×容差时旧逻辑直接丢弃（机翻 PDF 列漂移的
    OBIS/访问权限单元格会静默丢内容）。现在改为兜底：找不到列的单元格按 x0 落到最近列
    （位置可能不精确，但内容不丢——OBIS 错一位是严重缺陷，丢失单元格更严重）。
    """
    rows: list[dict[int, list[str]]] = []
    current: dict[int, list[str]] | None = None
    for line in region:
        assigned: list[tuple[int, str]] = []
        for cell in line["cells"]:
            if not cell["text"]:
                continue
            col = _nearest_column(cell["x0"], columns)
            if col is None and columns:
                # 兜底：容差外不丢，归到 x0 最近的列（保内容；列归属可能粗，但不静默丢）
                col = min(range(len(columns)), key=lambda i: abs(columns[i] - cell["x0"]))
            if col is not None:
                assigned.append((col, cell["text"]))
        if not assigned:
            continue
        has_col0 = any(col == 0 for col, _ in assigned)
        if current is None or (has_col0 and 0 in current):
            if current:
                rows.append(current)
            current = {}
        for col, text in assigned:
            current.setdefault(col, []).append(text)
    if current:
        rows.append(current)
    return [[" ".join(row.get(i, [])) for i in range(len(columns))] for row in rows]


def _validate_text_table(matrix: list[list[str]], *, region_lines: int, page_candidate_lines: int) -> list[list[str]] | None:
    """守卫链：全过才产表；任一不过返回 None（行回流段落）。"""
    if len(matrix) < 2:
        return None
    ncols = max(len(row) for row in matrix)
    # 列占用率：非首列须在 ≥2 行有内容，幽灵列删掉后重验
    keep = [0] + [j for j in range(1, ncols)
                  if sum(1 for row in matrix if j < len(row) and row[j]) >= 2]
    dropped = [j for j in range(1, ncols) if j not in keep]
    # 偏移单元格可能自成单例锚点；删幽灵列前并回最近保留列，保证内容守恒。
    for row in matrix:
        for column in dropped:
            if column >= len(row) or not row[column]:
                continue
            target = min(keep, key=lambda candidate: abs(candidate - column))
            row[target] = " ".join(part for part in (row[target], row[column]) if part)
    matrix = [[row[j] if j < len(row) else "" for j in keep] for row in matrix]
    ncols = len(keep)
    if ncols < 2:
        return None
    first_col = [row[0] for row in matrix if row[0]]
    # 首列列表标记 veto：枚举列表/参考文献/图例
    if first_col and sum(1 for v in first_col if _LIST_MARKER_CELL_RE.match(v)) * 2 >= len(first_col):
        return None
    # TOC veto 泛化：2-4 列且末列多为纯整数（页码），不依赖点引导线
    last_col = [row[-1] for row in matrix if row[-1]]
    if 2 <= ncols <= 4 and last_col and sum(1 for v in last_col if _PURE_INT_RE.match(v)) > 0.7 * len(last_col):
        return None
    # 整页双栏 veto：双语对照页（2 列覆盖该页大部分行）
    if ncols == 2 and page_candidate_lines and region_lines > 0.6 * page_candidate_lines:
        return None
    # 列长中位：真表须有 ≥2 个短列（键类列——符号/编码/字节数）；伪表（正文劈半/双语页）两边都长
    short_cols = 0
    for j in range(ncols):
        lens = sorted(len(row[j]) for row in matrix if row[j])
        if not lens:
            continue
        median = lens[len(lens) // 2]
        if median > 200:
            return None
        if median <= 40:
            short_cols += 1
    if short_cols < 2:
        return None
    # 单词格占比：宽列数 + 几乎全单词格 = 松排 prose 被切碎（真表格的格多为多词字段值）
    filled = [cell for row in matrix for cell in row if cell]
    if ncols >= 6 and filled:
        single_word = sum(1 for cell in filled if len(cell.split()) == 1)
        if single_word > 0.8 * len(filled):
            return None
    return matrix


def _attach_header_lines(region: list[dict[str, Any]], preceding: list[dict[str, Any]], columns: list[float]) -> list[dict[str, Any]]:
    """表头附着：区域上方 1-2 行若有 ≥2 格与列网格按 x 跨度重叠（容居中表头），并入区域头部。"""
    attach: list[dict[str, Any]] = []
    for line in reversed(preceding[-2:]):
        cells = line["cells"]
        if len(cells) < 2:
            break
        spans = 0
        for cell in cells:
            for idx, col in enumerate(columns):
                col_end = columns[idx + 1] if idx + 1 < len(columns) else float("inf")
                if cell["x0"] < col_end and cell["x1"] > col - COLUMN_ALIGN_TOLERANCE:
                    spans += 1
                    break
        if spans >= 2:
            attach.insert(0, line)
        else:
            break
    return attach + region


def _detect_text_tables(
    lines: list[dict[str, Any]],
    *,
    page_height: float,
    document_profile: DocumentProfile,
    defrag: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """无画线表格检测。返回 (tables, remaining_lines)；table = {top, bottom, matrix}。

    行先验排除（永不进区域）：标题行（防 section_path 被表格吞掉腐蚀）、点引导线（TOC）、
    页眉页脚带。被消费的行按身份从段落流移除。
    """
    if len(lines) < 3:
        return [], lines
    enriched = []
    for line in lines:
        candidate = (
            not _is_margin_line(line, page_height)
            and not _DOT_LEADER_RE.search(line["text"])
            and not _LIST_ITEM_RE.match(line["text"])   # 破折号/枚举列表行永不进表格区域（真实误报 p22）
            and not detect_heading(line["text"], "", document_profile=document_profile)
        )
        cells = _split_line_cells(line["words"], defrag=defrag) if candidate else []
        enriched.append({**line, "cells": cells, "candidate": candidate})
    page_candidate_lines = sum(1 for e in enriched if e["candidate"])

    tables: list[dict[str, Any]] = []
    consumed: set[int] = set()
    i = 0
    while i < len(enriched):
        line = enriched[i]
        if not line["candidate"] or len(line["cells"]) < 2:
            i += 1
            continue
        # 试着从 i 起扩一个区域（按索引追踪，消费行以身份移除）
        region_idx = [i]
        starts = [c["x0"] for c in line["cells"]]
        j = i + 1
        while j < len(enriched):
            nxt = enriched[j]
            if not nxt["candidate"] or not nxt["cells"]:
                break
            columns_now = _cluster_starts(starts)
            hits = sum(1 for c in nxt["cells"] if _nearest_column(c["x0"], columns_now) is not None)
            if len(nxt["cells"]) >= 2 and hits >= 2:
                region_idx.append(j)
                starts.extend(c["x0"] for c in nxt["cells"])
            elif len(nxt["cells"]) == 1 and hits == 1:
                region_idx.append(j)   # 包裹续行（单格且对齐已知列）
            else:
                break
            j += 1
        region = [enriched[k] for k in region_idx]
        anchors = [ln for ln in region if len(ln["cells"]) >= 2]
        columns = _cluster_starts([c["x0"] for ln in region for c in ln["cells"]])
        # 内部列对齐：最左列是免费对齐（左边距），至少 1 个内部列须跨 ≥3 行命中
        internal_hits = 0
        if len(columns) >= 2:
            for idx in range(1, len(columns)):
                col_hits = sum(
                    1 for ln in region
                    if any(_nearest_column(c["x0"], columns) == idx for c in ln["cells"])
                )
                internal_hits = max(internal_hits, col_hits)
        if len(region) >= 3 and len(anchors) >= 2 and internal_hits >= 3:
            header_idx = [k for k in range(max(0, i - 2), i)
                          if enriched[k]["candidate"] and k not in consumed]
            full_region = _attach_header_lines(region, [enriched[k] for k in header_idx], columns)
            matrix = _assemble_rows(full_region, columns)
            matrix = _validate_text_table(
                matrix, region_lines=len(full_region), page_candidate_lines=page_candidate_lines)
            if matrix is not None:
                attached = len(full_region) - len(region)
                tables.append({
                    "top": min(ln["top"] for ln in full_region),
                    "bottom": max(ln["bottom"] for ln in full_region),
                    "x0": min(ln["x0"] for ln in full_region),
                    "x1": max(ln["x1"] for ln in full_region),
                    "matrix": matrix,
                })
                consumed.update(region_idx)
                consumed.update(header_idx[len(header_idx) - attached:])
                i = j
                continue
        i += 1
    remaining = [
        {k: v for k, v in e.items() if k not in ("cells", "candidate")}
        for idx, e in enumerate(enriched) if idx not in consumed
    ]
    return tables, remaining


def extract_pdf(
    input_path: Path,
    knowledge_bases: KnowledgeRepository | None = None,
    document_profile: DocumentProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    knowledge_bases = knowledge_bases or KnowledgeRepository.from_paths([])
    profile = document_profile or DEFAULT_DOCUMENT_PROFILE
    with pdfplumber.open(input_path) as pdf:
        _assert_text_layer(pdf)
        defrag = _fragmentation_ratio(pdf) >= DEFRAG_RATIO_THRESHOLD
        if defrag:
            LOGGER.info("检测到词内空格破碎文档（机翻 PDF），启用去碎修复")
        repeated_noise = _detect_repeated_margin_lines(pdf, defrag=defrag)

        sections = SectionState()
        blocks: list[dict[str, Any]] = []
        table_items: list[dict[str, Any]] = []
        order = 0
        table_count = 0
        last_caption: str | None = None

        empty_pages = 0
        for page_number, page in enumerate(pdf.pages, start=1):
            # 画线表先验收再决定排除范围（2026-07-08 审计 C2）：此前 bbox 内的词无条件从
            # 段落流剔除，若该表随后被 _skip_table_matrix 丢弃（如 extract 拆格失败的框），
            # 词既不进表也不回段落——内容静默蒸发。现在只有验收通过的表才占用 bbox。
            kept_ruled: list[tuple[Any, list[list[str]]]] = []
            for table in page.find_tables():
                matrix = _clean_table_matrix(table.extract())
                if defrag:
                    matrix = [[defragment_text(cell) for cell in row] for row in matrix]
                if _skip_table_matrix(matrix):
                    LOGGER.info("第 %d 页画线表拆格近空，内容回流段落（bbox=%s）",
                                page_number, [round(v) for v in table.bbox])
                    continue
                kept_ruled.append((table, matrix))
            table_bboxes = [table.bbox for table, _ in kept_ruled]
            lines = _page_lines(page, table_bboxes, defrag=defrag)
            if not lines and not kept_ruled:
                empty_pages += 1
            text_tables, prose_lines = _detect_text_tables(
                lines, page_height=page.height, document_profile=profile, defrag=defrag)
            page_paragraphs = _group_paragraphs(prose_lines, page_height=page.height, document_profile=profile)

            # 画线表 + 文本重建表 + 段落按 top 统一排序，保阅读顺序
            events: list[tuple[float, str, Any]] = (
                [(float(t.bbox[1]), "ruled", (t, m)) for t, m in kept_ruled]
                + [(t["top"], "text_table", t) for t in text_tables]
                + [(p["top"], "paragraph", p) for p in page_paragraphs]
            )
            events.sort(key=lambda e: e[0])

            for _, kind, payload in events:
                if kind == "paragraph":
                    order, last_caption = _append_text_block(
                        blocks,
                        payload["text"],
                        order=order,
                        page_number=page_number,
                        pdf_region=_pdf_region(
                            page_number,
                            (payload["x0"], payload["top"], payload["x1"], payload["bottom"]),
                            page.width,
                            page.height,
                        ),
                        sections=sections,
                        knowledge_bases=knowledge_bases,
                        repeated_noise=repeated_noise,
                        last_caption=last_caption,
                        profile=profile,
                    )
                    continue
                if kind == "ruled":
                    matrix = payload[1]
                    table_bbox = payload[0].bbox
                else:
                    matrix = _clean_table_matrix(payload["matrix"])
                    if _skip_table_matrix(matrix):
                        continue
                    table_bbox = (payload["x0"], payload["top"], payload["x1"], payload["bottom"])
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
                table_block["pdf_regions"] = [
                    _pdf_region(page_number, table_bbox, page.width, page.height)]
                if kind == "text_table":
                    table_block["table_source"] = "text_layout"   # 溯源：无画线重建
                for item in new_table_items:
                    item["page_number"] = page_number
                    item["pdf_regions"] = list(table_block["pdf_regions"])
                blocks.append(table_block)
                table_items.extend(new_table_items)
                last_caption = None

        # 混合扫描 PDF 审计（2026-07-08 审计 H3）：_assert_text_layer 只采样前 5 页，
        # 正文后半是扫描页时零块产出且下游全部指标不可见——至少要在日志里喊出来
        if empty_pages > max(3, len(pdf.pages) * 0.3):
            LOGGER.warning("共 %d/%d 页无文字层（疑似扫描页混排），这些页内容未进入解析",
                           empty_pages, len(pdf.pages))

    blocks = _merge_continuation_blocks(blocks, knowledge_bases)
    return blocks, table_items


def _merge_continuation_blocks(
    blocks: list[dict[str, Any]],
    knowledge_bases: KnowledgeRepository,
) -> list[dict[str, Any]]:
    """块级续行合并：跨页断句（页内 gap 豁免够不着）——前段无句终标点 + 后段小写开头 →
    并成一段。中间隔着的页眉/页脚噪声块不挡合并（保留原位，视图本来就隐藏）。"""
    merged: list[dict[str, Any]] = []
    for block in blocks:
        target = None
        if block.get("type") == "paragraph" and not block.get("noise") and block.get("text"):
            for prev in reversed(merged):
                if prev.get("noise"):
                    continue   # 跳过页脚/页眉找真正的前文
                if prev.get("type") == "paragraph" and prev.get("text"):
                    target = prev
                break
        if (target is not None
                and target.get("page_number") is not None
                and block.get("page_number") is not None
                and target.get("page_number") == block.get("page_number")):
            target = None
        if target is not None:
            prev_text = str(target["text"]).rstrip()
            cur_text = str(block["text"])
            if (prev_text and prev_text[-1] not in _SENTENCE_TERMINALS
                    and cur_text[:1].islower()
                    and not _LIST_ITEM_RE.match(cur_text)
                    and not _DOT_LEADER_RE.search(prev_text)
                    and not _DOT_LEADER_RE.search(cur_text)
                    and len(prev_text) + len(cur_text) < 4000):
                if prev_text.endswith("-"):
                    joined = prev_text[:-1] + cur_text   # 跨页连字断词
                else:
                    joined = f"{prev_text} {cur_text}"
                target["text"] = joined
                target["requirement_like"] = is_requirement_like(joined)
                section = " > ".join(target.get("section_path") or [])
                target["kb_matches"] = match_knowledge(knowledge_bases, joined, section)
                target["domain_tags"] = merge_tags(
                    tag_domains(joined, section), kb_domain_tags(target["kb_matches"]))
                target.setdefault("pdf_regions", []).extend(block.get("pdf_regions") or [])
                continue
        merged.append(block)
    return merged


def _assert_text_layer(pdf: Any) -> None:
    sample = pdf.pages[:TEXT_LAYER_SAMPLE_PAGES]
    if not sample:
        raise AtomizerInputError("该 PDF 无文字层（疑似扫描件），当前版本不支持；可用 Word 打开该 PDF 另存为 .docx 后重试。")
    chars = [len(page.extract_text() or "") for page in sample]
    if sum(chars) / len(chars) < MIN_AVERAGE_EXTRACTED_CHARS:
        raise AtomizerInputError("该 PDF 无文字层（疑似扫描件），当前版本不支持；可用 Word 打开该 PDF 另存为 .docx 后重试。")


def _detect_repeated_margin_lines(pdf: Any, *, defrag: bool = False) -> set[str]:
    threshold = max(2, int(len(pdf.pages) * 0.6 + 0.999))
    counts: Counter[str] = Counter()
    for page in pdf.pages:
        top_limit = page.height * HEADER_FOOTER_BAND_RATIO
        bottom_limit = page.height * (1 - HEADER_FOOTER_BAND_RATIO)
        for line in _word_lines(page.extract_words(), defrag=defrag):
            if line["top"] <= top_limit or line["bottom"] >= bottom_limit:
                normalized = _normalize_repeated_line(line["text"])
                if normalized:
                    counts[normalized] += 1
    return {text for text, count in counts.items() if count >= threshold}


def _page_lines(
    page: Any,
    table_bboxes: list[tuple[float, float, float, float]],
    *,
    defrag: bool = False,
) -> list[dict[str, Any]]:
    """页面词 →（排除画线表 bbox 内的）→ 词行。"""
    words = [
        word
        for word in page.extract_words()
        if not any(_word_intersects_bbox(word, bbox) for bbox in table_bboxes)
    ]
    return _word_lines(words, defrag=defrag)


def _group_paragraphs(
    lines: list[dict[str, Any]],
    *,
    page_height: float,
    document_profile: DocumentProfile,
) -> list[dict[str, Any]]:
    if not lines:
        return []
    paragraphs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    previous_is_heading = False
    for line in lines:
        # 标题行独占一块：否则标题吞下随后的正文行，整段被判 heading（渲染成大字整段，
        # 条款锚点失真——真实案例 UNI 12007 共 372 个"标题"块全是标题+正文粘连）
        if previous is not None and (previous_is_heading or _starts_new_paragraph(
            previous,
            line,
            page_height=page_height,
            document_profile=document_profile,
        )):
            paragraphs.append(_merge_lines(current))
            current = []
        current.append(line)
        previous = line
        previous_is_heading = bool(detect_heading(line["text"], "", document_profile=document_profile))
    if current:
        paragraphs.append(_merge_lines(current))
    return [paragraph for paragraph in paragraphs if paragraph["text"]]


def _word_lines(words: list[dict[str, Any]], *, defrag: bool = False) -> list[dict[str, Any]]:
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
        lines.append(_merge_words(current, defrag=defrag))
        current = [word]
        current_top = top
    if current:
        lines.append(_merge_words(current, defrag=defrag))
    return lines


def _merge_words(words: list[dict[str, Any]], *, defrag: bool = False) -> dict[str, Any]:
    ordered = sorted(words, key=lambda word: float(word["x0"]))
    text = clean_text(" ".join(str(word["text"]) for word in ordered))
    if defrag:
        text = defragment_text(text)
    return {
        "text": text,
        "top": min(float(word["top"]) for word in ordered),
        "bottom": max(float(word["bottom"]) for word in ordered),
        "x0": min(float(word["x0"]) for word in ordered),
        "x1": max(float(word["x1"]) for word in ordered),
        "words": ordered,   # 词级坐标保留给无画线表格检测（切格用）
    }


_LIST_ITEM_RE = re.compile(r"^(?:[a-z]|\d{1,2}|[ivx]{1,4})[).]\s|^[•▪]\s|^[—–-]\s")
_SENTENCE_TERMINALS = ".:;!?…"
# 需求标志词（0711 评审）：两行都像独立需求（都含 shall/must/should/要求/应当）时，
# 即便前行无句终标点 + 下行小写开头，也判为新段——防止两条需求被误并成一条而丢一条。
_REQ_KEYWORD_RE = re.compile(r"\b(?:shall|must|should|required)\b|要求|应当|应支持|应能", re.IGNORECASE)


def _merge_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    # 去连字断词：行尾 "-" 且下行小写开头 → 去连字符无空格拼接（"require-" + "ments"）
    text = ""
    for line in lines:
        part = line["text"]
        if text.endswith("-") and part and part[0].islower():
            text = text[:-1] + part
        else:
            text = f"{text} {part}" if text else part
    return {
        "text": clean_text(text),
        "top": min(line["top"] for line in lines),
        "bottom": max(line["bottom"] for line in lines),
        "x0": min(line["x0"] for line in lines),
        "x1": max(line["x1"] for line in lines),
    }


def _pdf_region(page_number: int, bbox: Any, page_width: float, page_height: float) -> dict[str, Any]:
    return {
        "page_number": page_number,
        "bbox": [round(float(value), 3) for value in bbox],
        "page_width": round(float(page_width), 3),
        "page_height": round(float(page_height), 3),
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
    if detect_heading(line["text"], "", document_profile=document_profile):
        return True
    if looks_like_caption(line["text"], document_profile=document_profile):
        return True
    if _LIST_ITEM_RE.match(line["text"]):
        return True   # 列表项必自成段（不论行距）
    if _DOT_LEADER_RE.search(line["text"]) or _DOT_LEADER_RE.search(previous["text"]):
        return True   # 目录条目（点引导线）永不与相邻行黏段——黏了会把整屏点串塞进正文
    gap = float(line["top"]) - float(previous["bottom"])
    if gap >= 12:
        # 续行豁免：机翻 PDF 行距不齐会把一句话切成两块（真实取证 22% 段落块小写开头）。
        # 前行无句终标点 + 当前行小写开头 + 间距未大到换节 → 仍是同一段。
        # 0711 评审护栏：但若两行都像独立需求（都含 shall/must/should 等标志词），
        # 则判为新段——两条需求不应被误并成一条（会丢一条需求）。
        prev_text = previous["text"].rstrip()
        previous_x0 = float(previous.get("x0", 0.0))
        current_x0 = float(line.get("x0", previous_x0))
        current_is_outdented = previous_x0 - current_x0 >= 8
        previous_is_list_item = bool(_LIST_ITEM_RE.match(prev_text))
        current_is_list_continuation = current_x0 - previous_x0 >= 8
        if current_is_outdented or (previous_is_list_item and not current_is_list_continuation):
            return True
        if (gap < 26 and prev_text and prev_text[-1] not in _SENTENCE_TERMINALS
                and line["text"][:1].islower()
                and not (_REQ_KEYWORD_RE.search(prev_text) and _REQ_KEYWORD_RE.search(line["text"]))):
            return False
        return True
    return False


def _is_margin_line(line: dict[str, Any], page_height: float) -> bool:
    margin = 55
    return float(line["top"]) <= margin or float(line["bottom"]) >= page_height - margin


# PDF 标题归位（2026-07-07）：数字开头正则会把表格行/数值句误判成标题（"100 litres…"
# 腐蚀 section_path），机翻 PDF 还常见标题与正文粘在同一视觉行。只在 PDF 文本路径包装，
# 不动 DOCX 共享的 detect_heading。
_BARE_INT_HEADING_RE = re.compile(r"^(\d+)(?:\s|$)")
_SENTENCE_START_RE = re.compile(
    r"\s(?=(?:The|This|It|If|When|Where|Each|All|Any|Every)\s+\S"
    r"|(?:In|For|A|An|On|At)\s+[a-z(])"
)
MAX_HEADING_CHARS = 90        # 短标题直接放行
MAX_UNSPLIT_HEADING_CHARS = 160   # 超长且拆不开 → 降级段落
BARE_INT_HEADING_MAX = 40     # 单段编号超过此值不可能是章节号（"100 litres"）


def _refine_pdf_heading(
    heading: tuple[int, str],
    text: str,
    profile: DocumentProfile,
) -> tuple[tuple[int, str] | None, str, str | None]:
    """返回 (heading|None, 标题文本, 拆出的正文|None)。heading=None 表示降级段落。"""
    first_token = text.split(None, 1)[0] if text.split() else ""
    m = _BARE_INT_HEADING_RE.match(text)
    if m and "." not in first_token and int(m.group(1)) > BARE_INT_HEADING_MAX:
        return None, text, None
    if len(text) <= MAX_HEADING_CHARS:
        return heading, text, None
    # 粘连拆分：编号+首词之后找第一个句首模式（"… Software Update The service must …"）
    parts = text.split(None, 2)
    search_from = len(parts[0]) + 1 + len(parts[1]) if len(parts) >= 2 else 0
    split = _SENTENCE_START_RE.search(text, pos=search_from)
    if split:
        title = text[: split.start()].rstrip()
        body = text[split.start():].strip()
        refined = detect_heading(title, "", document_profile=profile)
        if refined and len(title) <= MAX_UNSPLIT_HEADING_CHARS and body:
            return refined, title, body
    if len(text) > MAX_UNSPLIT_HEADING_CHARS:
        return None, text, None
    return heading, text, None


def _append_text_block(
    blocks: list[dict[str, Any]],
    text: str,
    *,
    order: int,
    page_number: int,
    pdf_region: dict[str, Any] | None = None,
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
    trailing_body: str | None = None
    if heading:
        heading, text, trailing_body = _refine_pdf_heading(heading, text, profile)
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
    # 长度帽（2026-07-08 审计 M2/M3）：重复行/©页脚判定只适用于短行——页眉页脚都是短的；
    # 不设帽时，正文段落含 "© …, see page 12" 或与页眉同形的句子会整段标噪静默退出抽取
    short_enough = len(text) <= 120
    noise = (is_noise(text, document_profile=profile)
             or (short_enough and normalized in repeated_noise)
             or (short_enough and bool(_COPYRIGHT_FOOTER_RE.search(text))))
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
    if pdf_region:
        block["pdf_regions"] = [pdf_region]
    if heading:
        block["heading_level"] = heading[0]
    blocks.append(block)

    if looks_like_caption(text, document_profile=profile):
        last_caption = text
    elif block_type != "heading" and not noise:
        if last_caption and len(text) > 120:
            last_caption = None
    if trailing_body:
        # 粘连标题拆出的正文，紧随标题追加为独立段落块
        return _append_text_block(
            blocks, trailing_body, order=order, page_number=page_number,
            pdf_region=pdf_region,
            sections=sections, knowledge_bases=knowledge_bases,
            repeated_noise=repeated_noise, last_caption=last_caption, profile=profile)
    return order, last_caption


def _clean_table_matrix(raw_matrix: list[list[Any]] | None) -> list[list[str]]:
    matrix: list[list[str]] = []
    for row in raw_matrix or []:
        cleaned = [clean_text("" if value is None else str(value)) for value in row]
        if any(cleaned):
            matrix.append(cleaned)
    return matrix


_TOC_CELL_RE = re.compile(r"[.·…]{4,}\s*\d{1,3}\s*$")


def _skip_table_matrix(matrix: list[list[str]]) -> bool:
    if not matrix:
        return True
    non_empty_cells = sum(1 for row in matrix for value in row if value)
    if non_empty_cells <= 1:
        return True
    # 目录页画线表否决（真实案例 EN 16314）：pdfplumber 把印刷目录抽成"真表"——所有
    # 文本表守卫都不经过这条路径。多数行含点引导线+页码 = TOC 不是数据表，整表回流段落
    # （C2 验收：未通过的表不占 bbox，内容不蒸发），下游按目录行规则清洁/折叠。
    rows = [row for row in matrix if any(str(value).strip() for value in row)]
    leader_rows = sum(1 for row in rows
                      if any(_TOC_CELL_RE.search(str(value)) for value in row if value))
    if rows and leader_rows * 2 >= len(rows):
        return True
    return False


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
    text = re.sub(r"\bpage\s+[ivxlcdm]+\b", "page", text)   # 前言罗马页码（Page III 等）
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
