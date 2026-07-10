"""把"文档批注审核"导出成一个自包含 HTML 文件（Notion 清爽文档风）。

完全独立：文档原文 + AI 抽取需求数据直接嵌进 HTML，内联 CSS/JS，任意浏览器双击即开、
不需 app/服务器。需求像批注挂在原文对应小段上（anchor_block_id 精确锚点），点开看
模块/需求分析/测试指引/原文引用；裁决（接受/拒绝/讨论/改模块/写意见）静默存浏览器
localStorage（按 doc 命名空间隔离），一键「导出裁决 JSON」可回灌 app 合进交付物。
未覆盖的 requirement_like 段标「未覆盖」，顶部给疑似遗漏计数。

排版（Notion 风）：三栏（左大纲 / 中文档窄列居中 / 右批注卡片）；前言/目录/引言默认
折叠；noise 块灰显；leader-dots 与纯框线乱码在渲染层清洁（不触及抽取层）。

数据组装复用 api_server.build_document_blocks / build_ai_requirements（含锚点）。
"""
from __future__ import annotations

import datetime
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

from api_server import build_ai_requirements, build_document_blocks

ANNOTATION_HTML = "document_annotation.html"

# 非正文区：折叠显示（不删除，研发可展开核查）
_COLLAPSIBLE_REGIONS = {"front_matter", "table_of_contents", "preface", "introduction"}
# leader-dots：目录条目末尾的点连线 + 页码（Foreword .......... 3 → Foreword）
_LEADER_DOTS_RE = re.compile(r"\s*[.·…]{3,}\s*\d*\s*$")
# 段内嵌的框线乱码片段：连续符号串（可能含数字/字母前缀如 '2 --,--' 或 '--``,``--'），
# 至少 6 个符号字符、字母数字占比 <20%。剥离段内嵌入的表格框线噪声。
# 注意：不含 . （点），让 _LEADER_DOTS_RE 独占处理目录点连线。
_INLINE_GARBAGE_RE = re.compile(r"(?:\d+\s+)?[,`'=\-*_~|+…]{6,}")
# 纯符号行：PDF 框线/制表符被误读成符号串
_SYMBOL_ONLY_RE = re.compile(r"^[,\-`'=*_~|+.…\s]+$")
_OWNER_LABELS = {"software": "软件", "hardware": "硬件", "co_design": "协同", "software_term": "术语"}
_UNANALYZED_HARDWARE_TERMS = (
    "manufacturer",
    "manufactures",
    "manufactured",
    "trademark",
    "places it on the market",
    "puts it into service",
    "mechanical",
    "battery",
    "valve",
    "physical",
    "mobile data concentrator",
    "concentrator function",
    "concentrator functions",
    "walk by",
    "walk-by",
    "drive by",
    "drive-by",
)
_UNANALYZED_CO_DESIGN_TERMS = (
    "hardware and software components",
    "central hardware and software components",
    "hardware related",
    "driver",
    "interface",
    "dataflash",
    "m-bus",
    "wmbus",
)
_UNANALYZED_SOFTWARE_TERM_TERMS = (
    "significant event",
    "event or report",
    "affect its functioning",
    "alter its data",
    "data in its contents",
)
# 以上三个词表按具体语料调优（2026-07-09 UNI 水表文档），只影响视图层回退标记。
# 换语料可不改代码覆盖：out_dir/annotation_terms.json 优先，其次 manifest 里 domain_pack
# 目录下的 annotation_terms.json；格式 {"hardware": [...], "co_design": [...], "software_term": [...]}，
# 缺键回落内置默认。
_UNANALYZED_TERM_DEFAULTS: dict[str, tuple[str, ...]] = {
    "hardware": _UNANALYZED_HARDWARE_TERMS,
    "co_design": _UNANALYZED_CO_DESIGN_TERMS,
    "software_term": _UNANALYZED_SOFTWARE_TERM_TERMS,
}
_active_unanalyzed_terms: dict[str, tuple[str, ...]] = dict(_UNANALYZED_TERM_DEFAULTS)


def _load_annotation_terms(out_dir: Path) -> dict[str, tuple[str, ...]]:
    merged = dict(_UNANALYZED_TERM_DEFAULTS)
    candidates: list[Path] = []
    try:
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        pack_dir = str(manifest.get("domain_pack") or "")
        if pack_dir:
            candidates.append(Path(pack_dir) / "annotation_terms.json")
    except (OSError, json.JSONDecodeError):
        pass
    candidates.append(out_dir / "annotation_terms.json")   # out_dir 覆盖最后应用=优先级最高
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in _UNANALYZED_TERM_DEFAULTS:
            values = data.get(key)
            if isinstance(values, list):
                merged[key] = tuple(str(v).casefold() for v in values if str(v).strip())
    return merged


def _module_vocab() -> list[str]:
    try:
        from ai_extract import MODULE_VOCAB
        return list(MODULE_VOCAB)
    except Exception:  # pragma: no cover - 兜底
        return ["其它"]


def _doc_id(out_dir: Path) -> str:
    return hashlib.sha1(str(out_dir).encode("utf-8")).hexdigest()[:10]


def _covered_blocks(requirements: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for req in requirements:
        for bid in req.get("source_block_ids") or []:
            covered.add(str(bid))
    return covered


def _clean_block_text(text: str) -> str:
    """渲染层文本清洁：剥离段内框线乱码片段、去 leader-dots/页码、折叠空白。纯符号行返回空。"""
    # 剥离段内嵌的框线乱码（正文 + 句末框线噪声，如 'When --``,``-- tested' → 'When tested'）
    text = _INLINE_GARBAGE_RE.sub(" ", text)
    text = _LEADER_DOTS_RE.sub("", text)
    # 行中长点串（目录行被段落合并黏进正文时,点引导线出现在行中——真实截图:整屏点溢出）
    text = re.sub(r"[.·…]{4,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_symbol_only(text: str) -> bool:
    """True 当文本去掉字母数字后剩余符号占比 >80%（PDF 框线乱码，可能含数字编号如 '2 --,--'）。"""
    stripped = text.strip()
    if not stripped:
        return False
    alnum = sum(1 for c in stripped if c.isalnum())
    return alnum / len(stripped) < 0.2


def _block_heading_level(block: dict[str, Any]) -> int:
    """推断标题层级（1-3）。heading_level 优先，否则 section_path 深度，兜底 2。"""
    hl = block.get("heading_level")
    if isinstance(hl, int) and 1 <= hl <= 6:
        return min(hl, 3)
    path = block.get("section_path") or []
    if isinstance(path, list) and len(path) >= 1:
        return min(len(path), 3)
    return 2


def _block_region_label(region: str) -> str:
    return {"front_matter": "前言", "table_of_contents": "目录",
            "preface": "前言", "introduction": "引言"}.get(region, region)


def _render_blocks(blocks: list[dict[str, Any]], anchor_map: dict[str, list[dict[str, Any]]],
                   covered: set[str],
                   req_numbers: dict[str, int] | None = None,
                   sub_anchor_map: dict[str, list] | None = None) -> str:
    """渲染文档块：正文正常，非正文区折叠，noise 灰显，纯符号行跳过。"""
    parts: list[str] = []
    collapse_open = False
    collapse_count = 0
    collapse_label = ""
    collapse_buf: list[str] = []

    def flush_collapse() -> None:
        nonlocal collapse_open, collapse_count, collapse_buf
        if collapse_open and collapse_buf:
            parts.append(
                f'<details class="region-collapse"><summary>'
                f'{_block_region_label(collapse_label)}（{collapse_count} 段）</summary>'
                f'<div class="collapse-body">{"".join(collapse_buf)}</div></details>'
            )
        collapse_open = False
        collapse_count = 0
        collapse_buf = []

    prev_page: int | None = None
    marker_state: dict[str, Any] = {"next": 1, "req_numbers": {}}
    outline_map = _build_outline_map(blocks)
    for b in blocks:
        bid = str(b.get("block_id") or "")
        text = str(b.get("text") or "")
        # 清洁 + 跳过纯符号乱码
        text = _clean_block_text(text)
        if _is_symbol_only(text):
            continue
        if b.get("noise"):
            continue   # 页眉/页脚/水印等噪声不渲染（灰显仍占版面——排版保真，2026-07-07）
        path = b.get("section_path") or []
        region = str(b.get("doc_region") or "body")
        page_no = b.get("page_number")
        # 分页线只在正文区画：折叠区（封面/目录）攒 buffer 时直插外层会喷散落分页线
        if (region not in _COLLAPSIBLE_REGIONS and isinstance(page_no, int)
                and prev_page is not None and page_no != prev_page):
            parts.append(f'<div class="page-break"><span>第 {page_no} 页</span></div>')
        if isinstance(page_no, int):
            prev_page = page_no
        is_heading = b.get("type") == "heading" or (bool(path) and text == str(path[-1]))
        is_noise = bool(b.get("noise"))
        is_omission = bool(b.get("requirement_like")) and not is_noise and bid not in covered
        anchored = anchor_map.get(bid) or []

        # 渲染单个 block 的 HTML（表格块带 data_rows 时渲染真表格，旧 out_dir 无该字段回退扁平文字）
        block_html = _render_one_block(bid, text, path, region, is_heading, is_noise, is_omission, anchored,
                                       req_numbers or {}, (sub_anchor_map or {}).get(bid) or [],
                                       block=b, marker_state=marker_state,
                                       outline_level=outline_map.get(bid))

        # 非正文区：攒进折叠缓冲（region 变化时先 flush 旧组，开新组）
        if region in _COLLAPSIBLE_REGIONS:
            if not collapse_open or collapse_label != region:
                flush_collapse()
                collapse_open = True
                collapse_label = region
            collapse_count += 1
            collapse_buf.append(block_html)
        else:
            flush_collapse()
            parts.append(block_html)
    flush_collapse()
    return "\n".join(parts)


_LIST_TEXT_RE = re.compile(r"^(?:[a-z0-9]{1,3}[).]|[•▪—–-])\s")


def _normalize_with_char_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    normalized: list[str] = []
    char_map: list[tuple[int, int]] = []
    in_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_space:
                normalized.append(" ")
                char_map.append((i, i + 1))
                in_space = True
            else:
                start, _ = char_map[-1]
                char_map[-1] = (start, i + 1)
        else:
            normalized.append(ch)
            char_map.append((i, i + 1))
            in_space = False
    return "".join(normalized), char_map


def _find_quote_span(text: str, quote: str) -> tuple[int, int] | None:
    quote = quote.strip()
    if not quote:
        return None
    pos = text.find(quote)
    if pos >= 0:
        return pos, pos + len(quote)

    normalized_text, char_map = _normalize_with_char_map(text)
    normalized_quote = re.sub(r"\s+", " ", quote).strip()
    pos = normalized_text.find(normalized_quote)
    if pos < 0:
        return None
    end_pos = pos + len(normalized_quote) - 1
    if pos >= len(char_map) or end_pos >= len(char_map):
        return None
    return char_map[pos][0], char_map[end_pos][1]


def _annotation_chip(req: dict[str, Any], number: int, *,
                     fallback_index: int = 1, sub_label: str | None = None) -> str:
    rid = html.escape(str(req.get("ai_req_id") or ""))
    if sub_label is not None:
        return (
            f'<button class="chip annotation-index sub" data-req="{rid}" '
            f'title="{html.escape(str(req.get("title") or ""))} · 子项 {html.escape(sub_label)}" '
            f'aria-label="子项 {html.escape(sub_label)}">'
            f'<span class="annotation-number">{number:02d}.{html.escape(sub_label)}</span></button>'
        )
    owner = _OWNER_LABELS.get(str(req.get("ownership_effective") or req.get("ownership") or "software"), "软件")
    return (
        f'<button class="chip annotation-index" data-req="{rid}" data-inline-marker="1" '
        f'title="{html.escape(str(req.get("module_effective") or ""))} · {html.escape(str(req.get("title") or ""))}" '
        f'aria-label="{html.escape(str(req.get("title") or "需求批注"))}">'
        f'<span class="annotation-dot"></span>'
        f'<span class="annotation-number">{number or fallback_index:02d}</span>'
        f'<span class="annotation-owner">{html.escape(owner)}</span></button>'
    )


def _marker_number_for_req(req: dict[str, Any], marker_state: dict[str, Any] | None,
                           fallback_index: int = 1,
                           req_numbers: dict[str, int] | None = None) -> int:
    rid = str(req.get("ai_req_id") or "")
    if marker_state is None:
        return (req_numbers or {}).get(rid, fallback_index)
    assigned = marker_state.setdefault("req_numbers", {})
    if rid:
        if rid not in assigned:
            number = int(marker_state.get("next", fallback_index))
            assigned[rid] = number
            marker_state["next"] = number + 1
        return int(assigned[rid])
    number = int(marker_state.get("next", fallback_index))
    marker_state["next"] = number + 1
    return number


def _render_text_with_quote_markers(text: str, anchored: list[dict[str, Any]],
                                    req_numbers: dict[str, int],
                                    placed_ids: set[str] | None = None,
                                    marker_state: dict[str, Any] | None = None) -> tuple[str, set[str]]:
    placed = placed_ids if placed_ids is not None else set()
    matches: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]] = {}
    for fallback_index, req in enumerate(anchored, start=1):
        rid = str(req.get("ai_req_id") or "")
        if not rid or rid in placed:
            continue
        span = _find_quote_span(text, str(req.get("source_quote") or ""))
        if span:
            matches.setdefault(span, []).append((fallback_index, req))
    if not matches:
        return html.escape(text), set()

    rendered: list[str] = []
    cursor = 0
    newly_placed: set[str] = set()
    for (start, end), reqs in sorted(matches.items(), key=lambda item: (item[0][0], item[0][1])):
        if start < cursor:
            continue
        rendered.append(html.escape(text[cursor:end]))
        for fallback_index, req in reqs:
            rid = str(req.get("ai_req_id") or "")
            if rid in placed:
                continue
            number = _marker_number_for_req(req, marker_state, fallback_index, req_numbers)
            rendered.append(_annotation_chip(req, number, fallback_index=fallback_index))
            placed.add(rid)
            newly_placed.add(rid)
        cursor = end
    rendered.append(html.escape(text[cursor:]))
    return "".join(rendered), newly_placed


def _render_fallback_chips(anchored: list[dict[str, Any]], req_numbers: dict[str, int],
                           placed_ids: set[str], marker_state: dict[str, Any] | None = None) -> str:
    chips: list[str] = []
    for fallback_index, req in enumerate(anchored, start=1):
        rid = str(req.get("ai_req_id") or "")
        if rid and rid not in placed_ids:
            number = _marker_number_for_req(req, marker_state, fallback_index, req_numbers)
            chips.append(_annotation_chip(req, number, fallback_index=fallback_index))
    return "".join(chips)


def _render_sub_anchor_chips(sub_anchors: list | None, req_numbers: dict[str, int],
                             marker_state: dict[str, Any] | None = None) -> str:
    return "".join(
        _annotation_chip(
            req,
            _marker_number_for_req(req, marker_state, req_numbers.get(str(req.get("ai_req_id") or ""), 0), req_numbers),
            sub_label=str(label),
        )
        for req, label in (sub_anchors or [])
    )


def _unanalyzed_owner_for_text(text: str) -> str | None:
    if not text.strip():
        return None
    probe = text.casefold()
    terms = _active_unanalyzed_terms
    if any(term in probe for term in terms["co_design"]):
        return "co_design"
    if any(term in probe for term in terms["hardware"]):
        return "hardware"
    if any(term in probe for term in terms["software_term"]):
        return "software_term"
    return None


def _source_classification_marker(owner: str, marker_state: dict[str, Any], text: str = "") -> str:
    label = _OWNER_LABELS.get(owner, owner)
    number = marker_state.get("next", 1)
    marker_state["next"] = number + 1
    return (
        f'<button class="source-classification source-classification-{html.escape(owner)}" '
        f'data-source-classification="{html.escape(owner)}" '
        f'data-source-text="{html.escape(text)}" '
        f'title="该原文已归类为{html.escape(label)}，点击查看原因">'
        f'<span class="annotation-number">{number:02d}</span>'
        f'<span class="annotation-owner">{html.escape(label)}</span></button>'
    )


def _render_table_inner(block: dict, anchored: list[dict[str, Any]] | None = None,
                        req_numbers: dict[str, int] | None = None,
                        marker_state: dict[str, Any] | None = None) -> tuple[str, set[str]]:
    """表格块渲染成真 <table>（题注 + 表头 + 斑马纹数据行 + 横向滚动容器）。"""
    header_rows = block.get("header_rows") or []
    data_rows = block.get("data_rows") or []
    ncols = max((len(r) for r in header_rows + data_rows), default=0)
    if not data_rows and not header_rows:
        return "", set()
    anchored_rows = anchored or []
    numbers = req_numbers or {}
    state = marker_state if marker_state is not None else {"next": 1}
    placed: set[str] = set()
    title = str(block.get("table_title") or "")
    rebuilt = block.get("table_source") == "text_layout"
    caption = ""
    if title:
        badge = '<span class="table-badge">无画线重建</span>' if rebuilt else ""
        caption = f'<figcaption>{html.escape(title)}{badge}</figcaption>'
    head = "".join(
        "<tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in list(row) + [""] * (ncols - len(row))) + "</tr>"
        for row in header_rows
    )
    body_rows: list[str] = []
    for row in data_rows:
        cells: list[str] = []
        for c in list(row) + [""] * (ncols - len(row)):
            cell_text = str(c)
            rendered_cell, newly_placed = _render_text_with_quote_markers(
                cell_text, anchored_rows, numbers, placed, state
            )
            if not newly_placed:
                owner = _unanalyzed_owner_for_text(cell_text)
                if owner:
                    rendered_cell += _source_classification_marker(owner, state, cell_text)
            cells.append(f"<td>{rendered_cell}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    body = "".join(body_rows)
    thead = f"<thead>{head}</thead>" if head else ""
    return (f'<figure class="doc-table">{caption}<div class="table-scroll">'
            f'<table>{thead}<tbody>{body}</tbody></table></div></figure>'), placed


_TOC_ENTRY_SHAPE_RE = re.compile(r"^\d+(?:\.\d+)*\s+.+\s\d{1,3}$")
_TRAILING_PAGE_RE = re.compile(r"\s+\d{1,3}$")


_ANNEX_HEADING_RE = re.compile(r"^(annex|appendix|附录)\s+[A-Z0-9]", re.IGNORECASE)
_LEADING_NUM_RE = re.compile(r"^(\d+)(?:\.(\d+))?\b")
# 印刷目录条目：编号 + 标题 + （点引导线）+ 页码
_PRINTED_TOC_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.{3,}?)[\s.·…]*?(\d{1,3})?\s*$")


def _norm_outline(text: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", text.casefold())


def _parse_printed_toc(blocks: list[dict[str, Any]]) -> tuple[list[tuple[str, str, int]], int]:
    """从文档自带的印刷目录（INDEX/Contents 区,点引导线条目）解析 (编号, 标题, 级别)。
    只认前 40% 的块里、点引导线/尾页码形态的条目——这是文档结构的权威来源。
    返回 (条目, 目录最后一块的下标)——回链搜索从目录之后开始。"""
    entries: list[tuple[str, str, int]] = []
    last_index = 0
    limit = max(30, int(len(blocks) * 0.4))   # 小文档全扫（40% 窗口在测试级夹具上会饿死）
    for index, b in enumerate(blocks[:limit]):
        raw = str(b.get("text") or "")
        if not (re.search(r"[.·…]{4,}", raw) or _TOC_ENTRY_SHAPE_RE.match(_clean_block_text(raw))):
            continue
        cleaned = _clean_block_text(raw)
        m = _PRINTED_TOC_RE.match(cleaned)
        if not m:
            continue
        numbering, title = m.group(1), m.group(2).strip()
        level = min(numbering.count(".") + 1, 2)
        if numbering.count(".") >= 2 or len(title) < 3:
            continue   # 只收章/节两级
        entries.append((numbering, title, level))
        last_index = index
    return entries, last_index


def _build_outline_map(blocks: list[dict[str, Any]]) -> dict[str, int]:
    """左栏=文件目录（真实反馈 2026-07-10）：以文档**自带印刷目录**为权威源——把目录
    条目回链到正文对应标题块。启发式（标题块序列）在无印刷目录的文档上兜底。
    序列法教训：事件码表行本身就是连续编号（1..40），任何"递增即是章"的启发式都会
    把大表吞进目录。"""
    entries, toc_end = _parse_printed_toc(blocks)
    if len(entries) >= 5:
        toc_end = toc_end + 1
        picked: dict[str, int] = {}
        used: set[str] = set()
        for numbering, title, level in entries:
            want_prefix = _norm_outline(f"{numbering} {title[:16]}")
            for b in blocks[toc_end:] if len(blocks) > toc_end else blocks:
                if b.get("type") != "heading" or b.get("noise"):
                    continue
                bid = str(b.get("block_id") or "")
                if not bid or bid in used:
                    continue
                text = _clean_block_text(str(b.get("text") or ""))
                if _norm_outline(text)[:len(want_prefix)] == want_prefix:
                    picked[bid] = level
                    used.add(bid)
                    break
        if len(picked) >= 3:
            return picked
    # 兜底：无印刷目录 → 标题块直接进目录（章/节两级,印刷目录形态与超深层剔除）
    picked = {}
    seen: dict[str, str] = {}
    for b in blocks:
        if b.get("type") != "heading" or b.get("noise"):
            continue
        text = _clean_block_text(str(b.get("text") or ""))
        if not text or _TOC_ENTRY_SHAPE_RE.match(text):
            continue
        level = _block_heading_level(b)
        if level >= 3:
            continue
        key = _TRAILING_PAGE_RE.sub("", text).casefold()
        prev = seen.get(key)
        if prev:
            picked.pop(prev, None)
        bid = str(b.get("block_id") or "")
        if bid:
            picked[bid] = level
            seen[key] = bid
    return picked


def _render_one_block(bid: str, text: str, path: list, region: str,
                      is_heading: bool, is_noise: bool, is_omission: bool,
                      anchored: list, req_numbers: dict[str, int] | None = None,
                      sub_anchors: list | None = None, block: dict | None = None,
                      marker_state: dict[str, Any] | None = None,
                      outline_level: int | None = None) -> str:
    cls = ["doc-block"]
    if is_heading:
        cls.append("heading")
        cls.append(f"h{_block_heading_level({'section_path': path, 'heading_level': None})}")
    if is_noise:
        cls.append("noise")
    if is_omission:
        cls.append("omission")
    if anchored:
        cls.append("anchored")
    is_table = bool(block and block.get("type") == "table")
    if is_table:
        cls.append("is-table")
    elif _LIST_TEXT_RE.match(text):
        cls.append("list-item")   # 悬挂缩进
    if len(text) < 160:
        cls.append("short")   # 短行不 justify（目录条目/落款,拉词距很丑——真实截图反馈）
    depth = min(len(path), 4) if path else 0

    numbers = req_numbers or {}
    state = marker_state if marker_state is not None else {"next": 1, "req_numbers": {}}
    omission_html = ('<div class="omission-flag"><span class="omission-tag">未覆盖</span></div>'
                     if is_omission else "")
    if is_table and block is not None:
        table_html, placed_ids = _render_table_inner(block, anchored, numbers, state)
        fallback = _render_fallback_chips(anchored, numbers, placed_ids, state)
        sub_chips = _render_sub_anchor_chips(sub_anchors, numbers, state)
        trailing = f'<span class="chips inline-chips">{fallback}{sub_chips}</span>' if fallback or sub_chips else ""
        content = f'{table_html}{trailing}'
    else:
        text_html, placed_ids = _render_text_with_quote_markers(text, anchored, numbers, marker_state=state)
        fallback = _render_fallback_chips(anchored, numbers, placed_ids, state)
        if not placed_ids and not fallback:
            owner = _unanalyzed_owner_for_text(text)
            if owner:
                text_html += _source_classification_marker(owner, state, text)
        sub_chips = _render_sub_anchor_chips(sub_anchors, numbers, state)
        content = (f'<p class="text" data-block-id="{html.escape(bid)}">'
                   f'{text_html}{fallback}{sub_chips}</p>')
    return (
        f'<div class="{" ".join(cls)}" data-block-id="{html.escape(bid)}"'
        f'{f" data-outline={outline_level}" if outline_level else ""} style="--depth:{depth}">'
        f'<div class="block-inner">'
        f'{omission_html}'
        f'{content}'
        f'</div></div>'
    )


def render_annotation_html(out_dir: Path) -> str:
    global _active_unanalyzed_terms
    out_dir = Path(out_dir).expanduser().resolve()
    _active_unanalyzed_terms = _load_annotation_terms(out_dir)   # 语料词表可覆盖（默认=内置）
    doc = build_document_blocks(out_dir)
    blocks = doc.get("blocks") or []
    requirements = build_ai_requirements(out_dir)
    covered = _covered_blocks(requirements)

    anchor_map: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        anchor = str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")
        if anchor:
            anchor_map.setdefault(anchor, []).append(req)

    # 全文连续编号（按锚点块在文档中的出现顺序）——此前每块内部从 01 重数，满屏"01"无层级感。
    # 子项锚：需求带 sub_items 时，把各子项挂到其 source_block_ids 里以 "a)" 开头的段落
    # （二级批注 01.a/01.b…，与一级条款需求同色同点击目标）。
    block_order = {str(b.get("block_id") or ""): i for i, b in enumerate(blocks)}
    ordered = sorted(
        (req for req in requirements
         if str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")),
        key=lambda r: block_order.get(
            str(r.get("anchor_block_id") or (r.get("source_block_ids") or [""])[0] or ""), 1 << 30))
    req_numbers = {str(r.get("ai_req_id")): i for i, r in enumerate(ordered, start=1)}
    sub_anchor_map: dict[str, list[tuple[dict[str, Any], str]]] = {}
    text_by_block = {str(b.get("block_id") or ""): str(b.get("text") or "") for b in blocks}
    for req in requirements:
        labels = {str(item.get("label") or "").strip().lower()
                  for item in (req.get("sub_items") or []) if item.get("label")}
        if not labels:
            continue
        for bid in (req.get("source_block_ids") or []):
            m = re.match(r"^\s*([a-z])\)", text_by_block.get(str(bid), ""))
            if m and m.group(1) in labels:
                sub_anchor_map.setdefault(str(bid), []).append((req, m.group(1)))

    omissions = sum(
        1 for b in blocks
        if b.get("requirement_like") and not b.get("noise") and str(b.get("block_id")) not in covered
    )
    blocks_html = _render_blocks(blocks, anchor_map, covered, req_numbers, sub_anchor_map)
    reqs_json = json.dumps(requirements, ensure_ascii=False).replace("</", "<\\/")
    vocab_json = json.dumps(_module_vocab(), ensure_ascii=False).replace("</", "<\\/")
    generated_at = datetime.datetime.now().isoformat(timespec="seconds")

    return _TEMPLATE.format(
        doc_id=_doc_id(out_dir),
        source=html.escape(out_dir.name),
        generated_at=html.escape(generated_at),
        req_count=len(requirements),
        omission_count=omissions,
        blocks_html=blocks_html,
        requirements_json=reqs_json,
        module_vocab_json=vocab_json,
    )


def export_annotation_html(out_dir: Path) -> Path:
    out_dir = out_dir.expanduser().resolve()
    target = out_dir / ANNOTATION_HTML
    target.write_text(render_annotation_html(out_dir), encoding="utf-8")
    return target


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>文档批注审核 · {source}</title>
<style>
:root {{
  --page: #f5f3ee;
  --paper: #fbfaf7;
  --panel: #ffffff;
  --line: #e4e0d8;
  --line-strong: #d7d1c6;
  --ink: #171717;
  --muted: #707070;
  --faint: #a4a09a;
  --accent: #0f766e;
  --accent-soft: #dff4ef;
  --accent-quiet: #4d9a92;
  --highlight: #fff1a8;
  --serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", serif;
  --sans: Inter, system-ui, -apple-system, "Microsoft YaHei", sans-serif;
  --st-accepted: #e6f0e8; --st-accepted-tx: #2f6842;
  --st-rejected: #f4e7e3; --st-rejected-tx: #9b3b32;
  --st-discussion: #f6efd8; --st-discussion-tx: #8a6417;
  --omission-bg: #f8efd9;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: var(--sans);
  color: var(--ink); background: var(--page); font-size: 14px; line-height: 1.7; }}
.reader-shell {{ min-height: 100vh; background:
  linear-gradient(90deg, rgba(255,255,255,.62), rgba(255,255,255,0) 18%, rgba(255,255,255,0) 82%, rgba(255,255,255,.5)),
  var(--page); }}

/* --- 顶栏 --- */
.topbar {{ position: sticky; top: 0; z-index: 10; display: flex; justify-content: space-between; align-items: center;
  padding: 0 28px; height: 56px; background: rgba(253,251,246,.86); border-bottom: 1px solid var(--line);
  backdrop-filter: blur(18px); }}
.topbar .brand {{ font-weight: 600; font-size: 14px; color: var(--ink); letter-spacing: .01em; }}
.topbar .stats {{ display: flex; gap: 22px; font-size: 12px; color: var(--muted); }}
.topbar .stats strong {{ color: var(--ink); font-weight: 600; }}
.topbar .stats .warn strong {{ color: var(--st-discussion-tx); }}
.topbar button {{ background: var(--ink); color: #ffffff; border: 1px solid var(--ink); border-radius: 8px;
  padding: 7px 14px; cursor: pointer; font-size: 12px; font-weight: 600; font-family: var(--sans); }}
.topbar button:hover {{ background: #333333; border-color: #333333; }}

/* --- 三栏布局 --- */
.layout {{ display: grid; grid-template-columns: 264px minmax(0, 1fr) 336px; height: calc(100vh - 56px); }}

/* 阅读进度条（Instapaper 式细条） */
.read-progress {{ position: sticky; top: 56px; z-index: 9; height: 3px; background: transparent; }}
.read-progress i {{ display: block; height: 100%; width: 0; background: var(--accent); transition: width .1s linear; }}

/* --- 左：大纲 --- */
/* --- 左侧大纲：树形可折叠 --- */
.outline {{ border-right: 1px solid var(--line); overflow-y: auto; padding: 22px 14px;
  background: rgba(250,248,242,.62); font-size: 13px; }}
.outline .outline-title {{ font-size: 11px; text-transform: uppercase; color: var(--faint);
  letter-spacing: 0.08em; margin: 0 0 12px 8px; }}
.outline .nav-item {{ display: flex; align-items: center; padding: 3px 8px; border-radius: 4px;
  color: var(--muted); cursor: pointer; line-height: 1.5; text-decoration: none; }}
.outline .nav-item:hover {{ background: rgba(49,95,114,.07); color: var(--ink); }}
.outline .nav-item.active {{ background: var(--accent-soft); color: var(--accent); }}
.outline .nav-item .toggle {{ width: 14px; font-size: 10px; color: var(--faint); flex-shrink: 0;
  transition: transform .15s; text-align: center; }}
.outline .nav-item.collapsed .toggle {{ transform: rotate(-90deg); }}
.outline .nav-item .label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.outline .nav-children {{ overflow: hidden; }}
.outline .nav-children.collapsed {{ display: none; }}
.outline .h1-item {{ font-weight: 600; }}
.outline .h2-item {{ padding-left: 28px; font-size: 12px; }}
.outline .h3-item {{ padding-left: 44px; font-size: 12px; color: var(--faint); }}
.outline .h2-item .toggle, .outline .h3-item .toggle {{ visibility: hidden; }}

/* --- 中：文档 --- */
.paper {{ overflow-y: auto; padding: 46px 0 72px; }}
.doc-content {{ max-width: 720px; margin: 0 auto; padding: 56px 64px 72px; background: var(--paper);
  border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 18px 50px rgba(23, 23, 23, 0.08);
  font-family: var(--serif); font-size: 18px; line-height: 2.0; }}

.doc-block {{ margin-bottom: 10px; }}
.block-inner {{ position: relative; padding-left: calc(var(--depth, 0) * 16px); }}
.doc-block .text {{ margin: 0; padding: 2px 0; }}
.doc-block.heading .text {{ font-weight: 600; margin-top: 20px; }}
.doc-block.heading .text {{ line-height: 1.3; }}
.doc-block.h1 .text {{ font-size: 32px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }}
.doc-block.h2 .text {{ font-size: 23px; }}
.doc-block.h2 .block-inner {{ border-left: 2px solid var(--accent-quiet); padding-left: 12px; margin-left: -14px; }}
.doc-block.h3 .text {{ font-size: 19px; color: #3d3d3d; }}
.doc-block.noise .text {{ opacity: 0.3; font-size: 13px; }}
.doc-block.omission {{ background: linear-gradient(90deg, var(--omission-bg), rgba(248,239,217,.35)); border-radius: 4px; padding: 4px 8px; margin: 5px 0; }}
.doc-block.omission .text {{ border-left: 2px solid #cda85c; padding-left: 9px; }}
.doc-block.anchored {{ cursor: pointer; border-radius: 4px; }}
.doc-block.anchored:hover {{ background: var(--accent-soft); }}
.doc-block.in-span {{ background: var(--accent-soft); border-radius: 4px; }}
.text mark {{ background: linear-gradient(transparent 44%, var(--highlight) 44%); padding: 0 2px; border-radius: 0; }}
.page-break {{ display: flex; align-items: center; gap: 10px; margin: 22px 0 14px; color: #b8b2a4; font-size: 11px; }}
.page-break::before, .page-break::after {{ content: ""; flex: 1; border-top: 1px dashed #ddd6c8; }}

/* --- 阅读排版（优于原版 PDF：正文两端对齐、列表悬挂缩进、真表格） --- */
.doc-block .text {{ overflow-wrap: anywhere; }}
.doc-block:not(.heading):not(.short) .text {{ text-align: justify; hyphens: none; }}
.doc-block.short .text {{ text-align: left; }}
.doc-block.list-item .text {{ padding-left: 1.6em; text-indent: -1.6em; text-align: left; }}
.doc-table {{ margin: 14px 0 18px; }}
.doc-table figcaption {{ font-size: 12px; font-weight: 600; color: #6e7787; margin-bottom: 6px; letter-spacing: .02em; }}
.doc-table .table-badge {{ font-size: 10px; font-weight: 500; color: #8a6417; background: rgba(248,239,217,.8);
  border: 1px solid #e7d29a; border-radius: 999px; padding: 1px 7px; margin-left: 8px; vertical-align: 1px; }}
.doc-table .table-scroll {{ overflow-x: auto; border: 1px solid var(--line-strong); border-radius: 8px; }}
.doc-table {{ font-family: var(--sans); }}
.doc-table table {{ border-collapse: collapse; width: 100%; font-size: 13px; line-height: 1.55; }}
.doc-table th, .doc-table td {{ border: 0; border-bottom: 1px solid var(--line); border-right: 1px solid rgba(231,223,210,.5);
  padding: 6px 10px; text-align: left; vertical-align: top; min-width: 52px; }}
.doc-table th:last-child, .doc-table td:last-child {{ border-right: 0; }}
.doc-table thead th {{ background: #f3efe6; font-weight: 650; color: #43494f; position: relative; }}
.doc-table tbody tr:nth-child(even) td {{ background: rgba(245,242,236,.55); }}
.doc-table tbody tr:last-child td {{ border-bottom: 0; }}

.doc-block.in-span {{ box-shadow: inset 3px 0 0 #9fd3cc; }}
.doc-block.in-span.evidence {{ background: #ecf7f4; border-radius: 6px; box-shadow: none; }}
.dd-legend {{ font-size: 11px; color: #8a8f98; margin: 4px 0 8px; }}
.chip.sub .annotation-number {{ font-size: 10px; opacity: .75; }}
.dd-subitems li {{ margin-bottom: 4px; }}
.dd-table {{ border-collapse: collapse; font-size: 12px; width: 100%; margin-bottom: 8px; }}
.dd-table th, .dd-table td {{ border: 1px solid #e3e0d8; padding: 3px 8px; text-align: left; }}
.dd-table th {{ background: #f6f3ec; font-weight: 600; }}

/* chips（贴在引用原文后的行内角标） */
.chips {{ display: inline-flex; gap: 4px; align-items: baseline; margin-left: 5px; vertical-align: baseline; }}
.chip {{ display: inline-flex; align-items: center; justify-content: center; gap: 4px; font-size: 10px;
  border: 0; border-bottom: 1px solid var(--line-strong); border-radius: 0; padding: 0 2px 1px;
  background: transparent; cursor: pointer; color: var(--accent-quiet); height: auto; line-height: 1;
  transition: color .12s, border-color .12s, background .12s; white-space: nowrap; vertical-align: super; }}
.chip[data-inline-marker="1"] {{ margin-left: 5px; border-bottom: 2px solid var(--accent-quiet);
  color: var(--accent); transform: translateY(-0.08em); }}
.chip[data-inline-marker="1"] .annotation-dot {{ display: none; }}
.chip[data-inline-marker="1"] .annotation-number,
.chip[data-inline-marker="1"] .annotation-owner {{ font-size: 12px; font-weight: 750; letter-spacing: .03em; }}
.chip[data-inline-marker="1"] .annotation-owner {{ margin-left: 2px; }}
.chip[data-inline-marker="1"].quote-selected {{ background: var(--highlight); color: var(--accent); border-color: var(--accent); }}
.source-classification {{ display: inline-flex; margin-left: 5px; transform: translateY(-0.08em);
  color: var(--faint); border: 0; border-bottom: 1px dotted var(--line-strong); padding: 0 2px 1px;
  background: transparent; cursor: pointer; vertical-align: super; line-height: 1; font-family: inherit; }}
.source-classification .annotation-number,
.source-classification .annotation-owner {{ font-size: 12px; font-weight: 750; letter-spacing: .03em; }}
.source-classification .annotation-owner {{ margin-left: 2px; }}
.source-classification-hardware {{ color: #8a6417; }}
.source-classification-co_design {{ color: var(--accent-quiet); }}
.source-classification-software_term {{ color: #5b6f8f; }}
.source-classification:hover, .source-classification.sel {{ color: var(--accent); border-color: var(--accent); }}
.annotation-dot {{ width: 4px; height: 4px; border-radius: 50%; background: currentColor; opacity: .68; }}
.annotation-number {{ font-variant-numeric: tabular-nums; letter-spacing: .04em; }}
.chips, .chip, .source-classification, .page-break, .dd-legend, .omission-tag,
.doc-table figcaption, .region-collapse summary {{ font-family: var(--sans); }}
.chip:hover {{ color: var(--accent); border-color: var(--accent); }}
.chip.sel {{ color: var(--accent); border-color: var(--accent); font-weight: 700; }}
.chip.st-accepted {{ color: var(--st-accepted-tx); }}
.chip.st-rejected {{ color: var(--st-rejected-tx); }}
.chip.st-needs_discussion {{ color: var(--st-discussion-tx); }}
.omission-flag {{ margin: 1px 0 2px; }}
.omission-tag {{ font-size: 11px; color: var(--st-discussion-tx); background: rgba(248,239,217,.74);
  border: 1px solid #e7d29a; border-radius: 999px; padding: 1px 8px; }}

/* 折叠区 */
.region-collapse {{ margin: 16px 0; border: 1px solid var(--line); border-radius: 8px; background: rgba(250,248,242,.62); }}
.region-collapse summary {{ padding: 9px 14px; cursor: pointer; font-size: 13px; color: var(--muted); font-weight: 500; }}
.region-collapse summary:hover {{ background: rgba(49,95,114,.05); }}
.collapse-body {{ padding: 4px 14px 10px; }}
.collapse-body .doc-block.noise .text {{ opacity: 0.25; }}

/* --- 右：批注详情 --- */
.detail {{ border-left: 1px solid var(--line); overflow-y: auto; padding: 28px 22px; background: rgba(250,248,242,.72); }}
.detail .empty {{ color: var(--muted); text-align: center; padding-top: 64px; font-size: 13px; }}
.detail-card {{ background: rgba(255,253,248,.82); border: 1px solid var(--line); border-radius: 10px; padding: 20px 20px; margin-bottom: 14px;
  box-shadow: 0 14px 42px rgba(44,39,31,.06); }}
.dd-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
.dd-module {{ font-size: 12px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.04em; }}
.badge {{ font-size: 11px; padding: 2px 9px; border-radius: 999px; background: var(--line); }}
.badge.st-accepted {{ background: var(--st-accepted); color: var(--st-accepted-tx); }}
.badge.st-rejected {{ background: var(--st-rejected); color: var(--st-rejected-tx); }}
.badge.st-needs_discussion {{ background: var(--st-discussion); color: var(--st-discussion-tx); }}
.dd-title {{ margin: 10px 0 4px; font-size: 16px; font-weight: 650; color: var(--ink); line-height: 1.45; }}
.dd-meta {{ font-size: 12px; color: var(--muted); margin-bottom: 13px; }}
.dd-suspicion {{ font-size: 12px; color: #92400e; background: #fef3c7; border-radius: 6px; padding: 4px 8px; margin-bottom: 10px; }}
.dd-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin: 15px 0 5px; }}
.dd-body {{ font-size: 14px; line-height: 1.7; }}
.dd-list {{ margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.8; }}
.dd-list li {{ margin-bottom: 2px; }}
.dd-quote {{ font-size: 13px; color: #515761; border-left: 2px solid var(--line-strong); padding: 5px 10px;
  background: rgba(245,242,236,.7); border-radius: 0 4px 4px 0; }}
select, textarea {{ width: 100%; border: 1px solid var(--line); border-radius: 7px; padding: 8px 9px;
  font-size: 13px; font-family: inherit; background: var(--paper); color: var(--ink); }}
textarea {{ min-height: 52px; margin-top: 6px; resize: vertical; }}
.actions {{ display: flex; gap: 8px; margin-top: 12px; }}
.actions button {{ flex: 1; border: 1px solid var(--line); border-radius: 7px; padding: 8px 0; background: transparent;
  cursor: pointer; font-size: 13px; font-weight: 600; color: var(--ink); }}
.actions button:hover {{ background: var(--accent-soft); }}
.actions .accept {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.actions .accept:hover {{ opacity: 0.9; }}
.saved-hint {{ font-size: 12px; color: var(--st-accepted-tx); margin-top: 8px; min-height: 16px; }}

/* 窄屏：隐藏大纲 */
@media (max-width: 1100px) {{ .layout {{ grid-template-columns: 1fr 340px; }} .outline {{ display: none; }} }}
@media (max-width: 768px) {{ .layout {{ grid-template-columns: 1fr; }} .detail {{ display: none; }} }}
</style>
</head>
<body>
<div class="reader-shell">
<div class="reader-topbar topbar">
  <div class="brand">{source}</div>
  <div class="stats">
    <span>需求 <strong>{req_count}</strong></span>
    <span class="warn">疑似遗漏 <strong>{omission_count}</strong></span>
    <span>已裁决 <strong id="decided-count">0</strong></span>
  </div>
  <button id="export-btn">导出裁决 JSON</button>
</div>
<div class="read-progress"><i id="read-progress-fill"></i></div>
<div class="reader-layout layout">
  <nav class="outline" id="outline"><div class="outline-title">目录</div></nav>
  <article class="paper" id="paper">
    <div class="doc-content">
{blocks_html}
    </div>
  </article>
  <aside class="annotation-rail detail" id="detail"><div class="empty">点击批注标记查看详情</div></aside>
</div>
</div>
<script>
const DOC_ID = "{doc_id}";
const STORAGE_KEY = "ratomizer-decisions:" + DOC_ID;
const REQUIREMENTS = {requirements_json};
const MODULE_VOCAB = {module_vocab_json};
const GENERATED_AT = "{generated_at}";
const byId = {{}}; REQUIREMENTS.forEach(r => byId[r.ai_req_id] = r);
const STATUS_LABELS = {{ draft:"待审", accepted:"已接受", rejected:"已拒绝", needs_discussion:"待讨论", expert_pending:"专家待定" }};

function loadStore() {{ try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); }} catch(e) {{ return {{}}; }} }}
function saveStore(s) {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); refreshDecidedCount(); }}
function decisionOf(id) {{ return loadStore()[id] || null; }}
function statusOf(id) {{ const d = decisionOf(id); return (d && d.status) || (byId[id] && byId[id].status) || "draft"; }}
function moduleOf(r) {{ const d = decisionOf(r.ai_req_id); return (d && d.module_override) || r.module_effective || r.module || (r.labels||[])[0] || "未分模块"; }}
function currentOwnershipOverride(r) {{
  const d = decisionOf(r.ai_req_id);
  if (d && Object.prototype.hasOwnProperty.call(d, "ownership_override")) return d.ownership_override || "";
  return (r.review_state && r.review_state.ownership_override) || "";
}}
function baseOwnership(r) {{
  const serverOverride = (r.review_state && r.review_state.ownership_override) || "";
  if (serverOverride && r.ownership_effective === serverOverride) return r.ownership || "";
  return r.ownership_effective || r.ownership || "";
}}
function ownershipOf(r) {{
  return currentOwnershipOverride(r) || baseOwnership(r);
}}
function ownershipOverrideForSave(id) {{
  const r = byId[id] || {{}};
  const selected = document.getElementById("own-sel").value;
  if (!selected) return "";
  const current = currentOwnershipOverride(r);
  if (current && selected === current) return current;
  const base = baseOwnership(r);
  return selected !== base ? selected : "";
}}

function refreshDecidedCount() {{ document.getElementById("decided-count").textContent = String(Object.keys(loadStore()).length); }}
function esc(s) {{ const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }}

function paintChips() {{
  document.querySelectorAll(".chip").forEach(c => {{
    const id = c.getAttribute("data-req");
    c.classList.remove("st-accepted","st-rejected","st-needs_discussion");
    const st = statusOf(id);
    if (st !== "draft") c.classList.add("st-" + st);
  }});
}}

/* --- 左侧大纲：树形可折叠（h1 可展开/收起，h2/h3 嵌套） --- */
function buildOutline() {{
  const nav = document.getElementById("outline");
  // 文件目录（Python 侧权威判定 data-outline：章=1/节=2；印刷目录条目与深层条款不入）
  const headings = Array.from(document.querySelectorAll(".doc-block[data-outline]"));
  if (headings.length === 0) {{ nav.style.display = "none"; return; }}

  const frag = document.createDocumentFragment();
  let currentH1 = null;     // 当前 h1 组的 children 容器
  let currentH1Item = null; // 当前 h1 的 nav-item（用于 h2 归属）

  headings.forEach(h => {{
    const level = parseInt(h.getAttribute("data-outline") || "2", 10);
    const p = h.querySelector(".text"); if (!p) return;
    const text = p.textContent.trim().slice(0, 40); if (!text) return;

    const item = document.createElement("div");
    item.className = "nav-item " + "h" + level + "-item";
    item.innerHTML = '<span class="toggle">▼</span><span class="label">' + esc(text) + '</span>';
    item.title = text;

    // 点击 label 区域：跳转 + 高亮
    item.querySelector(".label").onclick = (e) => {{
      e.stopPropagation();
      nav.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      item.classList.add("active");
      h.scrollIntoView({{behavior:"smooth", block:"start"}});
    }};
    // 点击 toggle 箭头：折叠/展开（仅 h1 可折叠）
    item.querySelector(".toggle").onclick = (e) => {{
      e.stopPropagation();
      if (level === 1 && currentH1) {{
        item.classList.toggle("collapsed");
        currentH1.classList.toggle("collapsed");
      }}
    }};

    if (level === 1) {{
      // h1：新建组（nav-item + children 容器）。默认收起子项（避免大纲过长）
      currentH1Item = item;
      item.classList.add("collapsed");  // 默认收起
      currentH1 = document.createElement("div");
      currentH1.className = "nav-children collapsed";  // 默认隐藏子项
      frag.appendChild(item);
      frag.appendChild(currentH1);
    }} else {{
      // h2/h3：归入当前 h1 组（没有 h1 时直接放顶层）
      (currentH1 || frag).appendChild(item);
    }}
  }});
  nav.appendChild(frag);
}}

let selected = null;
function markSpan() {{
  document.querySelectorAll(".doc-block.in-span").forEach(el => el.classList.remove("in-span", "evidence"));
  const r = selected && byId[selected]; if (!r) return;
  const ids = (r.source_block_ids || []).concat([r.anchor_block_id]).filter(Boolean);
  ids.forEach(bid => {{
    const el = document.querySelector('.doc-block[data-block-id="' + bid + '"]');
    if (el) el.classList.add("in-span");
  }});
  // 证据块（蓝填充）：引用所在锚点段 + 子项批注所在段；其余仅左侧细条=分析上下文
  const anchor = r.anchor_block_id || (r.source_block_ids||[])[0];
  const anchorEl = anchor ? document.querySelector('.doc-block[data-block-id="' + anchor + '"]') : null;
  if (anchorEl) anchorEl.classList.add("evidence");
  document.querySelectorAll('.chip.sub[data-req="' + selected + '"]').forEach(chip => {{
    const blk = chip.closest(".doc-block");
    if (blk) blk.classList.add("evidence");
  }});
}}

function subItemsHtml(r) {{
  const items = r.sub_items || [];
  if (!items.length) return "";
  const rows = items.map(it => '<li><strong>' + esc(it.label || "·") + ')</strong> ' + esc(it.text || "") + '</li>').join("");
  return '<div class="dd-label">子项要求（二级）</div><ul class="dd-list dd-subitems">' + rows + '</ul>';
}}

function thresholdHtml(r) {{
  const t = r.threshold_table;
  if (!t || !(t.rows||[]).length) return "";
  const head = (t.columns||[]).length ? "<tr>" + t.columns.map(c => "<th>"+esc(c)+"</th>").join("") + "</tr>" : "";
  const body = t.rows.map(row => "<tr>" + (Array.isArray(row)?row:[row]).map(c => "<td>"+esc(String(c))+"</td>").join("") + "</tr>").join("");
  return '<div class="dd-label">参数表（数值原样照抄原文）</div><table class="dd-table">'+head+body+'</table>';
}}

function isHardwareRequirement(r) {{
  return ownershipOf(r) === "hardware";
}}

function hardwareTranslationHtml(r) {{
  if (!isHardwareRequirement(r)) return "";
  const text = r.hardware_summary || r.hardware_translation || r.source_quote || r.description || "";
  return text ? '<div class="dd-label">中文翻译 / 说明</div><div class="dd-body">'+esc(text)+'</div>' : "";
}}

function ownershipReasonHtml(r) {{
  if (!isHardwareRequirement(r)) return "";
  const text = r.ownership_reason || "";
  return text ? '<div class="dd-label">为什么判断为硬件</div><div class="dd-body">'+esc(text)+'</div>' : "";
}}

function highlightQuote() {{
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  document.querySelectorAll('.chip[data-inline-marker="1"].quote-selected').forEach(m => m.classList.remove("quote-selected"));
  const r = selected && byId[selected]; if (!r || !r.source_quote) return;
  const marker = document.querySelector('.chip[data-inline-marker="1"][data-req="' + selected + '"]');
  if (marker) {{ marker.classList.add("quote-selected"); return; }}
  const anchor = r.anchor_block_id || (r.source_block_ids||[])[0];
  const p = document.querySelector('.text[data-block-id="' + anchor + '"]'); if (!p) return;
  const t = p.textContent, q = r.source_quote, i = t.indexOf(q);
  if (i >= 0) p.innerHTML = esc(t.slice(0,i)) + "<mark>" + esc(q) + "</mark>" + esc(t.slice(i+q.length));
}}

function deselect() {{
  selected = null;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".source-classification").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll('.chip[data-inline-marker="1"].quote-selected').forEach(m => m.classList.remove("quote-selected"));
  document.querySelectorAll(".doc-block").forEach(el => el.classList.remove("in-span"));
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  document.getElementById("detail").innerHTML = '<div class="empty">点击批注标记查看详情</div>';
}}

function sourceClassificationReason(owner, text) {{
  if (owner === "hardware") return "该段原文描述制造主体、设备、部件、阀门、电池、物理结构或其它硬件对象，当前规则只做硬件归类与原文说明，不生成软件研发指引或测试指引。";
  if (owner === "co_design") return "该段原文同时涉及硬件与软件/通信接口，当前先标为软硬件协同提示，需要在功能分析阶段结合上下文再拆分软件侧职责。";
  if (owner === "software_term") return "该段原文是软件概念或事件/状态术语定义，当前没有独立的 shall/must 行为约束，因此未生成完整研发需求；它会作为后续事件记录、状态管理或数据处理需求的术语依据。";
  return "该段原文未进入软件需求分析。";
}}

function selectSourceClassification(el) {{
  selected = null;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".source-classification").forEach(c => c.classList.toggle("sel", c === el));
  document.querySelectorAll(".doc-block").forEach(block => block.classList.remove("in-span", "evidence"));
  const block = el.closest(".doc-block");
  if (block) block.classList.add("in-span", "evidence");
  const owner = el.getAttribute("data-source-classification") || "";
  const label = owner === "hardware" ? "硬件" : owner === "co_design" ? "软硬件协同" : owner === "software_term" ? "软件术语" : owner;
  const text = el.getAttribute("data-source-text") || "";
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">'+esc(label)+'</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">为什么没有生成研发需求</div>'+
    '<div class="dd-body">'+esc(sourceClassificationReason(owner, text))+'</div>'+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
    '</div>';
}}

function functionalMembershipHtml(r) {{
  if (!r.functional_requirement_id) return "";
  const behaviors = (r.functional_behaviors||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  const preconditions = (r.functional_preconditions||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  const constraints = (r.functional_data_constraints||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  const variants = (r.functional_variants||[]).map(value => '<li><strong>'+esc(value.name||"变体")+'</strong>：'+esc(value.behavior||"")+'</li>').join("");
  const conflicts = (r.functional_conflict_flags||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  return '<div class="dd-section"><div class="dd-label">所属研发功能</div>'+
    '<div class="dd-body"><strong>'+esc(r.functional_title||r.functional_requirement_id)+'</strong></div>'+
    (r.functional_objective ? '<div class="dd-body">'+esc(r.functional_objective)+'</div>' : '')+
    (behaviors ? '<div class="dd-label">功能行为</div><ul class="dd-list">'+behaviors+'</ul>' : '')+
    (preconditions ? '<div class="dd-label">前置条件</div><ul class="dd-list">'+preconditions+'</ul>' : '')+
    (constraints ? '<div class="dd-label">数据约束</div><ul class="dd-list">'+constraints+'</ul>' : '')+
    (variants ? '<div class="dd-label">功能变体</div><ul class="dd-list">'+variants+'</ul>' : '')+
    (conflicts ? '<div class="dd-suspicion">待澄清冲突<ul class="dd-list">'+conflicts+'</ul></div>' : '')+
    '</div>';
}}
function select(id) {{
  if (selected === id) {{ deselect(); return; }}  // 再点一下 → 取消选中
  selected = id;
  document.querySelectorAll(".source-classification").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("sel", c.getAttribute("data-req") === id));
  const r = byId[id]; if (!r) return;
  const d = decisionOf(id) || {{}};
  const st = statusOf(id);
  const isHardware = isHardwareRequirement(r);
  const dev = isHardware ? "" : (r.dev_guidance||[]).map(c => "<li>" + esc(c) + "</li>").join("");
  const acc = isHardware ? "" : (r.acceptance_criteria||[]).map(c => "<li>" + esc(c) + "</li>").join("");
  const analysisHtml = isHardware
    ? hardwareTranslationHtml(r) + ownershipReasonHtml(r)
    : '<div class="dd-label">需求分析</div><div class="dd-body">'+esc(r.description)+'</div>'+subItemsHtml(r)+thresholdHtml(r);
  const opts = MODULE_VOCAB.map(m => '<option value="'+esc(m)+'"'+(m===moduleOf(r)?' selected':'')+'>'+esc(m)+'</option>').join("");
  const ownershipOptions = [
    ["", "自动/不覆盖"],
    ["software", "软件"],
    ["hardware", "硬件"],
    ["co_design", "软硬件协同"],
  ].map(([value, label]) => '<option value="'+esc(value)+'"'+(value===ownershipOf(r)?' selected':'')+'>'+esc(label)+'</option>').join("");
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card"><div class="dd-head"><span class="dd-module">'+esc(moduleOf(r))+'</span>'+
    '<span class="badge st-'+st+'">'+esc(STATUS_LABELS[st]||st)+'</span></div>'+
    '<div class="dd-title">'+esc(r.title)+'</div>'+
    '<div class="dd-meta">'+esc(r.type)+' · '+esc(r.priority)+' · '+esc(r.source_section)+'</div>'+
    '<div class="dd-legend">正文标记：<span style="background:#ffe89a;padding:0 4px">黄=引用依据</span> · <span style="background:#eef4ff;padding:0 4px">蓝=证据段</span> · 左侧细条=分析上下文（模型通读范围）</div>'+
    ((r.suspicion_reasons||[]).length ? '<div class="dd-suspicion">⚠ 建议优先复核：'+esc((r.suspicion_reasons||[]).join("、"))+'</div>' : '')+
    analysisHtml+
    functionalMembershipHtml(r)+
    (dev ? '<div class="dd-label">研发指引 / 落地实现</div><ul class="dd-list">'+dev+'</ul>' : '')+
    (acc ? '<div class="dd-label">测试指引 / 验收</div><ul class="dd-list">'+acc+'</ul>' : '')+
    (r.source_quote ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(r.source_quote)+'</div>' : '')+
    '<div class="dd-label">模块（可改）</div><select id="mod-sel">'+opts+'</select>'+
    '<div class="dd-section"><div class="dd-label">归属（可改）</div><select id="own-sel" class="dd-select">'+ownershipOptions+'</select></div>'+
    '<textarea id="cmt" placeholder="审查意见（可选）">'+esc(d.reason||"")+'</textarea>'+
    '<div class="actions"><button class="accept" data-st="accepted">接受</button>'+
    '<button data-st="rejected">拒绝</button><button data-st="needs_discussion">讨论</button></div>'+
    '<div class="saved-hint" id="hint"></div></div>';
  document.querySelectorAll(".actions button").forEach(b => b.onclick = () => decide(id, b.getAttribute("data-st")));
  // 整个被分析跨度亮淡底 + 引句黄标（markSpan 内部先清后加，含锚点块）
  markSpan();
  highlightQuote();
}}

function decide(id, status) {{
  const store = loadStore();
  const ownershipOverride = ownershipOverrideForSave(id);
  store[id] = {{ ai_req_id: id, status: status,
    module_override: document.getElementById("mod-sel").value !== (byId[id].module_effective||byId[id].module||"") ? document.getElementById("mod-sel").value : "",
    ownership_override: ownershipOverride,
    reason: document.getElementById("cmt").value, ts: GENERATED_AT }};
  saveStore(store); paintChips();
  const h = document.getElementById("hint"); if (h) h.textContent = "已" + (STATUS_LABELS[status]||status) + "（本地已存）";
  const badge = document.querySelector(".badge"); if (badge) {{ badge.className = "badge st-"+status; badge.textContent = STATUS_LABELS[status]||status; }}
}}

document.getElementById("paper").addEventListener("click", e => {{
  const chip = e.target.closest(".chip"); if (chip) {{ select(chip.getAttribute("data-req")); return; }}
  const sourceMarker = e.target.closest(".source-classification"); if (sourceMarker) {{ selectSourceClassification(sourceMarker); return; }}
  const blk = e.target.closest(".doc-block.anchored");
  if (blk) {{ const c = blk.querySelector(".chip"); if (c) select(c.getAttribute("data-req")); }}
}});

document.getElementById("export-btn").onclick = () => {{
  const decisions = Object.values(loadStore());
  const payload = {{ doc_id: DOC_ID, source: "{source}", exported_at: new Date().toISOString(), decisions: decisions }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "ai_decisions_" + DOC_ID + ".json"; a.click();
}};

// 阅读进度条:中栏滚动比例(Instapaper 式)
(function () {{
  var paper = document.getElementById("paper");
  var fill = document.getElementById("read-progress-fill");
  if (!paper || !fill) return;
  paper.addEventListener("scroll", function () {{
    var max = paper.scrollHeight - paper.clientHeight;
    fill.style.width = (max > 0 ? Math.min(100, paper.scrollTop / max * 100) : 0) + "%";
  }}, {{ passive: true }});
}})();

paintChips(); buildOutline(); refreshDecidedCount();
</script>
</body>
</html>
"""
