"""把"文档批注审核"导出成可离线分享的 HTML bundle。

优化模式把文档原文 + AI 抽取需求数据直接嵌进 HTML；原版模式把源 PDF 原字节复制为
同目录 sidecar 并由浏览器直接显示。两种模式都不需 app/服务器。需求像批注挂在原文对应
小段或 PDF 页索引上（anchor_block_id 精确锚点），点开看
模块/所属研发功能/测试指引/原文引用；裁决（接受/拒绝/讨论/改模块/写意见）静默存浏览器
localStorage（按 doc 命名空间隔离），一键「导出裁决 JSON」可回灌 app 合进交付物。
未覆盖的 requirement_like 段标「未覆盖」，顶部给疑似遗漏计数。

排版（Notion 风）：三栏（左大纲 / 中文档窄列居中 / 右批注卡片）；前言/目录/引言默认
折叠；noise 块灰显；leader-dots 与纯框线乱码在渲染层清洁（不触及抽取层）。

数据组装复用 api_server.build_document_blocks / build_ai_requirements（含锚点）。
"""
from __future__ import annotations

import datetime
import difflib
import hashlib
import html
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from api_server import (ANNOTATION_TRANSLATIONS, build_ai_requirements, build_document_blocks,
                        load_annotation_translations, translation_key)
from io_utils import read_jsonl
from requirement_kb.matching import clean_text as normalize_text

ANNOTATION_HTML = "document_annotation.html"
ANNOTATION_SOURCE_PDF = "document_source.pdf"
ANNOTATION_PAGES_DIR = "document_pages"
ANNOTATION_PAGES_MANIFEST = "manifest.json"
ANNOTATION_PDF_GEOMETRY = "document_pdf_geometry.json"
PDF_PAGE_RENDER_DPI = 144
LAYOUT_OPTIMIZED = "optimized"
LAYOUT_PDF_ORIGINAL = "pdf_original"
ANNOTATION_LAYOUT_MODES = {LAYOUT_OPTIMIZED, LAYOUT_PDF_ORIGINAL}
# 翻译缓存键/加载器的唯一实现在 api_server（两个渲染面共用防分叉）；生成侧在本模块。
_TRANSLATION_BATCH = 8
# 数字并组：千位空格/逗号分隔（"4 000"→"4000"），护栏基线用
_DIGIT_GROUP_RE = re.compile(r"(?<=\d)[\s,  ](?=\d)")

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
# 渲染期状态：本次渲染出现的说明标记文本（hash → (owner, text)，翻译阶段消费）与可嵌入译文
_collected_marker_texts: dict[str, tuple[str, str]] = {}
_active_translations: dict[str, str] = {}
_active_translation_notes: dict[str, str] = {}


_translation_key = translation_key
_load_annotation_translations = load_annotation_translations


def _read_translation_sidecar(out_dir: Path) -> dict[str, dict[str, Any]]:
    """生成侧读完整条目（含被拒留账的）——pending 计算要把被拒的也当已判定,不重试。"""
    try:
        data = json.loads((Path(out_dir) / ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return {str(k): dict(v) for k, v in items.items() if isinstance(v, dict)} if isinstance(items, dict) else {}


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


def _source_input_path(out_dir: Path) -> Path | None:
    """读取原子化 manifest 中的源文档路径；相对路径按输出目录解析。"""
    try:
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = str(manifest.get("input") or "").strip() if isinstance(manifest, dict) else ""
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = out_dir / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _source_pdf_path(out_dir: Path) -> Path | None:
    source = _source_input_path(out_dir)
    return source if source and source.suffix.casefold() == ".pdf" and source.is_file() else None


def _normalize_layout_mode(layout_mode: str | None) -> str:
    mode = str(layout_mode or LAYOUT_OPTIMIZED).strip().casefold()
    if mode not in ANNOTATION_LAYOUT_MODES:
        raise ValueError(
            f"未知批注排版模式：{layout_mode}（可用：{', '.join(sorted(ANNOTATION_LAYOUT_MODES))}）")
    return mode


def _page_number(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_pdf_regions(value: Any) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        bbox = raw.get("bbox")
        page = _page_number(raw.get("page_number"))
        try:
            coords = [float(item) for item in bbox] if isinstance(bbox, list) and len(bbox) == 4 else []
            width = float(raw.get("page_width") or 0)
            height = float(raw.get("page_height") or 0)
        except (TypeError, ValueError):
            continue
        if page and len(coords) == 4 and width > 0 and height > 0:
            regions.append({
                "page_number": page,
                "bbox": coords,
                "page_width": width,
                "page_height": height,
            })
    return regions


def _geometry_match_text(value: Any) -> str:
    text = normalize_text(str(value or ""))
    text = re.sub(r"\bcolumn_\d+\b", " ", text, flags=re.IGNORECASE).replace("|", " ")
    return " ".join(text.split())


def _resolve_pdf_geometry(source_pdf: Path, blocks: list[dict[str, Any]],
                          cache_path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """读取块坐标；旧输出无坐标时确定性重跑 PDF 文本解析，只回填几何数据。"""
    block_signature = hashlib.sha256(json.dumps([
        [block.get("block_id"), block.get("page_number"), block.get("text")]
        for block in blocks
    ], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    source_hash = _file_sha256(source_pdf)
    if cache_path:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
        if (cached.get("version") == 2 and cached.get("source_sha256") == source_hash
                and cached.get("block_signature") == block_signature
                and isinstance(cached.get("geometry"), dict)):
            return {
                str(block_id): regions
                for block_id, value in cached["geometry"].items()
                if (regions := _valid_pdf_regions(value))
            }
    geometry = {
        str(block.get("block_id") or ""): regions
        for block in blocks
        if (regions := _valid_pdf_regions(block.get("pdf_regions")))
    }
    missing = [block for block in blocks if str(block.get("block_id") or "") not in geometry]
    if not missing:
        return geometry

    try:
        from parsers.pdf_parser import extract_pdf
        parsed_blocks, _ = extract_pdf(source_pdf, knowledge_bases=[], document_profile=None)
    except Exception:
        return geometry

    parsed_by_id = {str(block.get("block_id") or ""): block for block in parsed_blocks}
    parsed_by_text: dict[tuple[int | None, str], list[dict[str, Any]]] = {}
    for block in parsed_blocks:
        key = (_page_number(block.get("page_number")), _geometry_match_text(block.get("text")))
        parsed_by_text.setdefault(key, []).append(block)

    for block in missing:
        block_id = str(block.get("block_id") or "")
        candidate = parsed_by_id.get(block_id)
        normalized = _geometry_match_text(block.get("text"))
        if candidate and _geometry_match_text(candidate.get("text")) != normalized:
            candidate = None
        if candidate is None:
            candidates = parsed_by_text.get((_page_number(block.get("page_number")), normalized)) or []
            candidate = candidates[0] if len(candidates) == 1 else None
        regions = _valid_pdf_regions(candidate.get("pdf_regions")) if candidate else []
        if not regions and normalized:
            same_page = [
                item for item in parsed_blocks
                if _page_number(item.get("page_number")) == _page_number(block.get("page_number"))
            ]
            contained = [
                item for item in same_page
                if len(_geometry_match_text(item.get("text"))) >= 16
                and _geometry_match_text(item.get("text")) in normalized
            ]
            if contained:
                for item in contained:
                    regions.extend(_valid_pdf_regions(item.get("pdf_regions")))
            elif same_page:
                best = max(
                    same_page,
                    key=lambda item: difflib.SequenceMatcher(
                        None, normalized, _geometry_match_text(item.get("text"))).ratio(),
                )
                ratio = difflib.SequenceMatcher(
                    None, normalized, _geometry_match_text(best.get("text"))).ratio()
                if ratio >= 0.72:
                    regions = _valid_pdf_regions(best.get("pdf_regions"))
        if regions:
            geometry[block_id] = regions
    if cache_path:
        payload = {
            "version": 2,
            "source_sha256": source_hash,
            "block_signature": block_signature,
            "geometry": geometry,
        }
        tmp = cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cache_path)
    return geometry


def _ensure_pdf_page_images(source_pdf: Path, out_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """把原 PDF 页缓存为原坐标比例 PNG，供 HTML 叠加独立批注层。"""
    pages_dir = out_dir / ANNOTATION_PAGES_DIR
    manifest_path = pages_dir / ANNOTATION_PAGES_MANIFEST
    source_hash = _file_sha256(source_pdf)
    expected = {"version": 1, "source_sha256": source_hash, "dpi": PDF_PAGE_RENDER_DPI}
    try:
        cached = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached = {}
    cached_pages = cached.get("pages") if isinstance(cached, dict) else None
    if all(cached.get(key) == value for key, value in expected.items()) and isinstance(cached_pages, list):
        files = [pages_dir / str(page.get("file") or "") for page in cached_pages if isinstance(page, dict)]
        if files and all(path.is_file() and path.stat().st_size > 0 for path in files):
            pages = [
                {**page, "href": f"{ANNOTATION_PAGES_DIR}/{page['file']}"}
                for page in cached_pages if isinstance(page, dict)
            ]
            return pages, [str(path) for path in files] + [str(manifest_path)]

    import pdfplumber
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    files: list[str] = []
    with pdfplumber.open(source_pdf) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            filename = f"page-{index:04d}.png"
            target = pages_dir / filename
            page.to_image(resolution=PDF_PAGE_RENDER_DPI, antialias=True).save(target, format="PNG")
            pages.append({
                "page_number": index,
                "file": filename,
                "href": f"{ANNOTATION_PAGES_DIR}/{filename}",
                "width": float(page.width),
                "height": float(page.height),
            })
            files.append(str(target))
    manifest = {**expected, "pages": [{k: v for k, v in page.items() if k != "href"} for page in pages]}
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    files.append(str(manifest_path))
    return pages, files


def _covered_blocks(requirements: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for req in requirements:
        for bid in req.get("source_block_ids") or []:
            covered.add(str(bid))
        for bid in req.get("echo_block_ids") or []:   # 回声段有条目覆盖,不算遗漏/背景
            covered.add(str(bid))
    return covered


def _clean_block_text(text: str) -> str:
    """渲染层文本清洁：剥离段内框线乱码片段、去 leader-dots/页码、折叠空白。纯符号行返回空。"""
    # 剥离段内嵌的框线乱码（正文 + 句末框线噪声，如 'When --``,``-- tested' → 'When tested'）
    text = normalize_text(text)
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
                   sub_anchor_map: dict[str, list] | None = None,
                   echo_map: dict[str, list[dict[str, Any]]] | None = None) -> str:
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
        # 覆盖/遗漏统一口径（E3b）：payload 带 coverage_candidate 用之;旧数据回退宽口径
        candidate = (bool(b.get("coverage_candidate")) if "coverage_candidate" in b
                     else bool(b.get("requirement_like")) and not is_noise)
        is_omission = candidate and bid not in covered
        anchored = anchor_map.get(bid) or []

        # 渲染单个 block 的 HTML（表格块带 data_rows 时渲染真表格，旧 out_dir 无该字段回退扁平文字）
        block_html = _render_one_block(bid, text, path, region, is_heading, is_noise, is_omission, anchored,
                                       req_numbers or {}, (sub_anchor_map or {}).get(bid) or [],
                                       block=b, marker_state=marker_state,
                                       outline_level=outline_map.get(bid),
                                       echo_reqs=(echo_map or {}).get(bid) or [])

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
_NOTE_TEXT_RE = re.compile(r"^NOTE(?:\s|$)", re.IGNORECASE)


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
    key = _translation_key(text)
    if text.strip():
        _collected_marker_texts.setdefault(key, (owner, text))
    translation = _active_translations.get(key, "")
    note = _active_translation_notes.get(key, "")
    return (
        f'<button class="source-classification source-classification-{html.escape(owner)}" '
        f'data-source-classification="{html.escape(owner)}" '
        f'data-source-text="{html.escape(text)}" '
        f'data-source-translation="{html.escape(translation)}" '
        f'data-source-translation-note="{html.escape(note)}" '
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
                      outline_level: int | None = None,
                      echo_reqs: list[dict[str, Any]] | None = None) -> str:
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
    if _NOTE_TEXT_RE.match(text):
        cls.append("note")
    if len(text) < 160:
        cls.append("short")   # 短行不 justify（目录条目/落款,拉词距很丑——真实截图反馈）
    depth = min(len(path), 4) if path else 0

    numbers = req_numbers or {}
    state = marker_state if marker_state is not None else {"next": 1, "req_numbers": {}}
    omission_html = ""
    if is_omission:
        # 未覆盖段与说明标记同待遇（真实反馈 2026-07-12）：可点击 → 三段式卡片
        # （为什么未覆盖/原文翻译/原文引用）;文本进翻译收集,LLM 导出时自动补齐译文
        key = _translation_key(text)
        if text.strip():
            _collected_marker_texts.setdefault(key, ("omission", text))
        translation = _active_translations.get(key, "")
        note = _active_translation_notes.get(key, "")
        omission_html = ('<button class="omission-tag" type="button" '
                         f'data-omission-text="{html.escape(text)}" '
                         f'data-omission-translation="{html.escape(translation)}" '
                         f'data-omission-translation-note="{html.escape(note)}" '
                         'title="疑似需求但未被任何抽取需求覆盖，点击查看说明">未覆盖</button>')
    echo_html = ""
    if echo_reqs and not anchored:
        # 回声段轻量标记(0716 用户裁定:批注不过度显示——重复段不挂完整批注,
        # 只给指向汇总条目的"重复"角标;同段关联多条需求时全部列出,不静默吞掉后项)
        linked: list[tuple[str, int | None]] = []
        seen: set[str] = set()
        for req in echo_reqs:
            rid = str(req.get("ai_req_id") or "")
            if rid and rid not in seen:
                linked.append((rid, (req_numbers or {}).get(rid)))
                seen.add(rid)
        linked.sort(key=lambda item: item[1] if item[1] is not None else 10**9)
        req_ids = [rid for rid, _ in linked]
        nums = [num for _, num in linked if num is not None]
        label = "重复·见" + "/".join(f"{num:02d}" for num in nums) if nums else "重复段"
        first = req_ids[0] if req_ids else ""
        echo_html = (f'<button class="echo-tag" type="button" data-echo-req="{html.escape(first)}" '
                     f'data-echo-reqs="{html.escape(" ".join(req_ids))}" '
                     'title="本段与已抽取需求的来源段落内容重复，点击查看汇总条目">'
                     f'{html.escape(label)}</button>')
    if is_table and block is not None:
        table_html, placed_ids = _render_table_inner(block, anchored, numbers, state)
        fallback = _render_fallback_chips(anchored, numbers, placed_ids, state)
        sub_chips = _render_sub_anchor_chips(sub_anchors, numbers, state)
        trailing_items = f'{fallback}{sub_chips}{omission_html}{echo_html}'
        trailing = f'<span class="chips inline-chips">{trailing_items}</span>' if trailing_items else ""
        content = f'{table_html}{trailing}'
    else:
        text_html, placed_ids = _render_text_with_quote_markers(text, anchored, numbers, marker_state=state)
        fallback = _render_fallback_chips(anchored, numbers, placed_ids, state)
        collectable = (not is_heading and not is_noise and text.strip()
                       and region not in ("front_matter", "table_of_contents"))
        if not placed_ids and not fallback:
            owner = _unanalyzed_owner_for_text(text)
            if owner:
                text_html += _source_classification_marker(owner, state, text)
            elif collectable and not is_omission:
                # 背景段也进翻译收集（全文每段都有分析结果——真实反馈 2026-07-12）
                _collected_marker_texts.setdefault(_translation_key(text), ("context", text))
        elif collectable:
            # 有批注的正文块同样收集（test18：硬件卡的块级翻译回退此前无料可用）
            _collected_marker_texts.setdefault(_translation_key(text), ("covered", text))
        sub_chips = _render_sub_anchor_chips(sub_anchors, numbers, state)
        key = _translation_key(text)
        translation_attrs = ""
        if not is_heading and not is_noise and text.strip():
            translation_attrs = (
                f' data-translation="{html.escape(_active_translations.get(key, ""))}"'
                f' data-translation-note="{html.escape(_active_translation_notes.get(key, ""))}"')
        content = (f'<p class="text" data-block-id="{html.escape(bid)}"{translation_attrs}>'
                   f'{text_html}{fallback}{sub_chips}{omission_html}{echo_html}</p>')
    return (
        f'<div class="{" ".join(cls)}" data-block-id="{html.escape(bid)}"'
        f'{f" data-outline={outline_level}" if outline_level else ""} style="--depth:{depth}">'
        f'<div class="block-inner">'
        f'{content}'
        f'</div></div>'
    )


def render_annotation_html(out_dir: Path, *, layout_mode: str = LAYOUT_OPTIMIZED,
                           pdf_href: str | None = None,
                           pdf_pages: list[dict[str, Any]] | None = None,
                           pdf_geometry: dict[str, list[dict[str, Any]]] | None = None) -> str:
    global _active_unanalyzed_terms, _active_translations, _active_translation_notes
    out_dir = Path(out_dir).expanduser().resolve()
    layout_mode = _normalize_layout_mode(layout_mode)
    if layout_mode == LAYOUT_PDF_ORIGINAL and not pdf_href:
        pdf_href = ANNOTATION_SOURCE_PDF
    _active_unanalyzed_terms = _load_annotation_terms(out_dir)   # 语料词表可覆盖（默认=内置）
    _active_translations, _active_translation_notes = _load_annotation_translations(out_dir)
    _collected_marker_texts.clear()
    doc = build_document_blocks(out_dir)
    blocks = doc.get("blocks") or []
    requirements = build_ai_requirements(out_dir)
    covered = _covered_blocks(requirements)

    anchor_map: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        anchor = str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")
        if anchor:
            anchor_map.setdefault(anchor, []).append(req)
    # 回声段不重复挂完整批注(用户裁定 0716:批注不过度显示,汇总层才归并)——
    # 只给轻量"重复段"标记:指向该条目,点击跳转;段落卡片给本段翻译+汇总指引
    echo_map: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        for echo in req.get("echo_block_ids") or []:
            echo_map.setdefault(str(echo), []).append(req)

    # 全文连续编号（按锚点块在文档中的出现顺序）——此前每块内部从 01 重数，满屏"01"无层级感。
    # 子项锚：需求带 sub_items 时，把各子项挂到其 source_block_ids 里以 "a)" 开头的段落
    # （二级批注 01.a/01.b…，与一级条款需求同色同点击目标）。
    block_order = {str(b.get("block_id") or ""): i for i, b in enumerate(blocks)}
    ordered = sorted(
        requirements,
        key=lambda r: block_order.get(
            str(r.get("anchor_block_id") or (r.get("source_block_ids") or [""])[0] or ""), 1 << 30))
    req_numbers = {str(r.get("ai_req_id")): i for i, r in enumerate(ordered, start=1)}
    blocks_by_id = {str(block.get("block_id") or ""): block for block in blocks}
    for req in requirements:
        req_id = str(req.get("ai_req_id") or "")
        req["annotation_number"] = req_numbers.get(req_id)
        anchor = str(req.get("anchor_block_id") or "")
        source_ids = [str(value) for value in (req.get("source_block_ids") or []) if str(value)]
        page = None
        for block_id in ([anchor] if anchor else []) + source_ids:
            page = _page_number((blocks_by_id.get(block_id) or {}).get("page_number"))
            if page is not None:
                break
        req["source_page"] = page
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

    omission_items = _omission_records(blocks, covered)
    omissions = len(omission_items)
    overlay_enabled = bool(layout_mode == LAYOUT_PDF_ORIGINAL and pdf_pages)
    pdf_context_map: dict[str, dict[str, Any]] = {}
    pdf_semantics: list[dict[str, Any]] = []
    if layout_mode == LAYOUT_PDF_ORIGINAL:
        # 翻译属于解析语义，不依赖页图或坐标是否成功生成；geometry 只决定左页热区。
        pdf_semantics = _pdf_block_semantics(blocks, requirements, covered)
        _collect_pdf_translation_texts(pdf_semantics)
    if overlay_enabled:
        block_zones = _pdf_block_zones(
            blocks, requirements, pdf_geometry or {}, covered, semantics=pdf_semantics)
        pdf_context_map = _pdf_context_records(
            blocks, block_zones, include_requirements=True, semantics=pdf_semantics)
        blocks_html = _render_pdf_page_stack(
            pdf_pages or [], requirements, omission_items, req_numbers, pdf_geometry or {},
            block_zones=block_zones)
    elif layout_mode == LAYOUT_PDF_ORIGINAL:
        source = html.escape(str(pdf_href or ANNOTATION_SOURCE_PDF), quote=True)
        blocks_html = (
            f'<iframe id="pdf-frame" class="pdf-frame" src="{source}#view=FitH" '
            'title="原始 PDF"></iframe>')
    else:
        blocks_html = _render_blocks(blocks, anchor_map, covered, req_numbers, sub_anchor_map,
                                     echo_map=echo_map)
    reqs_json = json.dumps(requirements, ensure_ascii=False).replace("</", "<\\/")
    omissions_json = json.dumps(omission_items, ensure_ascii=False).replace("</", "<\\/")
    pdf_context_json = json.dumps(pdf_context_map, ensure_ascii=False).replace("</", "<\\/")
    vocab_json = json.dumps(_module_vocab(), ensure_ascii=False).replace("</", "<\\/")
    pdf_href_json = json.dumps(str(pdf_href or ""), ensure_ascii=False).replace("</", "<\\/")
    generated_at = datetime.datetime.now().isoformat(timespec="seconds")

    return _TEMPLATE.format(
        doc_id=_doc_id(out_dir),
        source=html.escape(out_dir.name),
        generated_at=html.escape(generated_at),
        req_count=len(requirements),
        omission_count=omissions,
        blocks_html=blocks_html,
        layout_class=(" pdf-original pdf-annotated" if overlay_enabled else
                      " pdf-original" if layout_mode == LAYOUT_PDF_ORIGINAL else ""),
        pdf_mode="true" if layout_mode == LAYOUT_PDF_ORIGINAL else "false",
        pdf_overlay_enabled="true" if overlay_enabled else "false",
        pdf_page_count=len(pdf_pages or []),
        pdf_href_json=pdf_href_json,
        requirements_json=reqs_json,
        omissions_json=omissions_json,
        pdf_context_json=pdf_context_json,
        module_vocab_json=vocab_json,
    )


def _translate_marker_batch(chat: Any, batch: list[tuple[str, str, str]]) -> dict[int, str]:
    # 发送前做渲染同款清洁（目录点引导线/页码/框线乱码），模型不必翻译排版噪声
    numbered = [{"id": i, "text": " ".join(_clean_block_text(text).split()) or " ".join(text.split())}
                for i, (_key, _owner, text) in enumerate(batch, start=1)]
    system = "你是电表/燃气表等技术标准文档的翻译助手。"
    user = "\n".join([
        "把下列标准原文逐条忠实翻译成中文。规则：",
        "- 逐条对应，不合并、不拆分、不遗漏；",
        "- 忠实原文：不得新增原文没有的数字、编号、协议代码、单位或任何建议/解释；",
        "- 专有名词与缩写（如 M-Bus、DLMS、OBIS 及设备/机构缩写）保留原文；",
        "- 只输出 JSON 对象 {\"items\":[{\"id\":1,\"translation\":\"...\"}]}。",
        "原文条目 JSON:",
        json.dumps(numbered, ensure_ascii=False),
    ])
    payload = chat(system, user)
    items = payload.get("items") if isinstance(payload, dict) else None
    result: dict[int, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        result[item_id] = str(item.get("translation") or "").strip()
    return result


def generate_annotation_translations(out_dir: Path, *, route: str | None,
                                     texts: dict[str, tuple[str, str]] | None = None,
                                     chat: Any = None) -> dict[str, Any]:
    """块级"说明"标记的原文中文翻译（评审卡三段式：归类原因/原文翻译/原文引用）。

    翻译只在此处生成、按内容哈希写 annotation_translations.json；渲染层只读缓存，
    保持确定性（裁决回流免 LLM 重建不受影响）。护栏同硬件翻译通路（检查单 #2）：
    忠实翻译不会引入源文没有的编码/数字——出现即拒绝该条并留账（不嵌入、不重试）。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    if texts is None:
        render_annotation_html(out_dir)   # 收集本文档全部说明标记文本
        texts = dict(_collected_marker_texts)
    sidecar = _read_translation_sidecar(out_dir)
    pending = {key: value for key, value in texts.items() if key not in sidecar}
    summary: dict[str, Any] = {
        "route": "stub", "model": "", "total_markers": len(texts),
        "cached": len(texts) - len(pending), "translated": 0, "rejected": 0,
        "unresolved": 0, "failed_calls": 0,
    }
    if not pending:
        # 无新文本：不必解析 LLM 配置；缓存条目本就全部来自真 LLM
        summary["route"] = "openai_compatible" if summary["cached"] else "stub"
        return summary
    from functional_synthesis import _resolve_catalog_chat
    invoke, executed = _resolve_catalog_chat(route, chat)
    if invoke is None:
        summary["unresolved"] = len(pending)   # 诚实降级：stub 绝不虚标（检查单 #4）
        return summary
    summary["route"] = "openai_compatible"
    summary["model"] = executed.split(":", 1)[1] if executed.startswith("llm:") else executed
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock

    from cosem_behavior_spec import extract_codes, extract_ints

    def _flush() -> None:
        target = out_dir / ANNOTATION_TRANSLATIONS
        payload = {"version": 1, "model": summary["model"],
                   "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                   "items": sidecar}
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)

    pending_list = [(key, owner, text) for key, (owner, text) in pending.items()]
    batches = [pending_list[start:start + _TRANSLATION_BATCH]
               for start in range(0, len(pending_list), _TRANSLATION_BATCH)]
    lock = Lock()
    changed = False
    try:
        from ai_extract import resolve_concurrency
        workers = resolve_concurrency(None)
    except Exception:  # pragma: no cover - 兜底串行
        workers = 1
    # 并发批次 + 每批完成即落盘（分析富化 288 条串行数小时+零落盘的教训，同对策）
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(_translate_marker_batch, invoke, batch): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            try:
                translations = future.result()
            except Exception:
                with lock:
                    summary["failed_calls"] += 1
                continue
            with lock:
                for index, (key, owner, text) in enumerate(batch, start=1):
                    translation = translations.get(index, "")
                    if not translation:
                        summary["unresolved"] += 1   # 漏译不落账 → 下次导出自动补齐
                        continue
                    # 基线含数字并组形态：欧标千位分隔 "4 000"，忠实翻译写 "4000" 是格式
                    # 归一不是编造（test16 实测 3 条误伤）;枚举标号同理（test18：a)→1. 转写），
                    # int 提取先剥标号。编码仍按原文严格。
                    from text_normalize import strip_enum_markers
                    basis = f"{text} {_DIGIT_GROUP_RE.sub('', text)}"
                    fabricated = sorted((extract_codes(translation) - extract_codes(text))
                                        | (extract_ints(strip_enum_markers(translation)) - extract_ints(basis)))
                    entry: dict[str, Any] = {"owner": owner, "model": summary["model"],
                                             "source_head": " ".join(text.split())[:120]}
                    if fabricated:
                        entry.update({"translation": "", "rejected": True,
                                      "reason": "翻译含无据编码/数字: " + ", ".join(str(x) for x in fabricated[:6])})
                        summary["rejected"] += 1
                    else:
                        entry["translation"] = translation
                        summary["translated"] += 1
                    sidecar[key] = entry
                    changed = True
                if changed:
                    _flush()   # 中途被杀不丢已完成的真实调用
    return summary


def _omission_records(blocks: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    from merged_consistency import is_coverage_candidate
    records: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        text = str(block.get("text") or "").strip()
        if not is_coverage_candidate(block) or block_id in covered or not text:
            continue
        key = _translation_key(text)
        records.append({
            "block_id": block_id,
            "text": text,
            "source_page": _page_number(block.get("page_number")),
            "translation": _active_translations.get(key, ""),
            "translation_note": _active_translation_notes.get(key, ""),
        })
    return records


def _pdf_zone_rect(region: dict[str, Any]) -> dict[str, float]:
    """块坐标 → 页面百分比矩形（导出 HTML 与应用内视图共用的唯一换算实现）。"""
    x0, top, x1, bottom = region["bbox"]
    width = float(region["page_width"])
    height = float(region["page_height"])
    left = max(0.0, min(100.0, x0 / width * 100))
    top_pct = max(0.0, min(98.0, top / height * 100))
    zone_width = max(0.8, min(100.0 - left, (x1 - x0) / width * 100))
    zone_height = max(0.8, min(100.0 - top_pct, (bottom - top) / height * 100))
    return {"left": round(left, 3), "top": round(top_pct, 3),
            "width": round(zone_width, 3), "height": round(zone_height, 3)}


def _pdf_zone_style(region: dict[str, Any]) -> tuple[str, float]:
    rect = _pdf_zone_rect(region)
    return (
        f"left:{rect['left']:.3f}%;top:{rect['top']:.3f}%;width:{rect['width']:.3f}%;height:{rect['height']:.3f}%",
        rect["top"],
    )


def _pdf_block_semantics(blocks: list[dict[str, Any]], requirements: list[dict[str, Any]],
                         covered: set[str]) -> list[dict[str, Any]]:
    """与 PDF 几何无关的段落语义；翻译收集和热区生成共用，避免静默漏译。"""
    from merged_consistency import is_coverage_candidate

    anchor_to_reqs: dict[str, list[str]] = {}
    echo_to_reqs: dict[str, list[str]] = {}
    covered_to_reqs: dict[str, list[str]] = {}
    for req in requirements:
        req_id = str(req.get("ai_req_id") or "")
        anchor = str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")
        if req_id and anchor:
            req_ids = anchor_to_reqs.setdefault(anchor, [])
            if req_id not in req_ids:
                req_ids.append(req_id)
        if req_id:
            for echo in req.get("echo_block_ids") or []:
                block_ids = echo_to_reqs.setdefault(str(echo), [])
                if req_id not in block_ids:
                    block_ids.append(req_id)
            echo_ids = {str(value) for value in (req.get("echo_block_ids") or []) if str(value)}
            for source_id in req.get("source_block_ids") or []:
                block_id = str(source_id)
                if not block_id or block_id == anchor or block_id in echo_ids:
                    continue
                req_ids = covered_to_reqs.setdefault(block_id, [])
                if req_id not in req_ids:
                    req_ids.append(req_id)

    semantics: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        text = str(block.get("text") or "").strip()
        if not block_id or not text or block.get("noise"):
            continue
        anchor_req_ids = anchor_to_reqs.get(block_id) or []
        if anchor_req_ids:
            kind = "req"
        elif echo_to_reqs.get(block_id):
            kind = "echo"
        elif covered_to_reqs.get(block_id):
            kind = "covered"
        elif is_coverage_candidate(block) and block_id not in covered:
            kind = "omission"
        elif str(block.get("type") or "") in ("heading", "table"):
            continue
        else:
            kind = "context"
        item: dict[str, Any] = {"block_id": block_id, "text": text, "kind": kind}
        if anchor_req_ids:
            item["req_id"] = anchor_req_ids[0]
            item["req_ids"] = list(anchor_req_ids)
        if kind in {"echo", "covered"}:
            item["req_ids"] = list(
                echo_to_reqs[block_id] if kind == "echo" else covered_to_reqs[block_id])
        semantics.append(item)
    return semantics


def _collect_pdf_translation_texts(semantics: list[dict[str, Any]]) -> None:
    for item in semantics:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "context")
        owner = "covered" if kind == "req" else kind
        _collected_marker_texts.setdefault(_translation_key(text), (owner, text))


def _pdf_block_zones(blocks: list[dict[str, Any]], requirements: list[dict[str, Any]],
                     geometry: dict[str, list[dict[str, Any]]],
                     covered: set[str], *,
                     semantics: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """影印模式全段落热区（0714「点一段出翻译和解析」）——双渲染器共用的唯一语义源。

    kind 路由与重排模式的块点击语义一一对应：
    - req: 该块是某需求锚点 → 点击选中需求（多需求同锚取首个,与重排 anchored[0] 同）;
    - echo: 该块是一个或多个需求的重复出现处 → 重复段卡片列出全部汇总条目;
    - covered: 该块被一个或多个需求纳入来源范围，但不是锚点或重复段 → 关联需求卡;
    - omission: 覆盖口径疑似遗漏（is_coverage_candidate 且未覆盖）→ 遗漏卡;
    - context: 普通正文段 → 背景说明卡（原因/翻译/引用）;
    - 标题/表格/噪声不给热区（重排同样不可点;锚在表格/标题上的需求经 req 热区仍可达）。
    """
    zones: list[dict[str, Any]] = []
    semantic_items = (semantics if semantics is not None
                      else _pdf_block_semantics(blocks, requirements, covered))
    for item in semantic_items:
        block_id = str(item.get("block_id") or "")
        kind = str(item.get("kind") or "context")
        for region in geometry.get(block_id) or []:
            page = _page_number(region.get("page_number"))
            if not page:
                continue
            zone: dict[str, Any] = {"block_id": block_id, "page": page,
                                    "rect": _pdf_zone_rect(region), "kind": kind}
            if item.get("req_id"):
                zone["req_id"] = str(item["req_id"])
            if kind in {"req", "echo", "covered"}:
                zone["req_ids"] = list(item.get("req_ids") or [])
            zones.append(zone)
    return zones


def _pdf_context_records(blocks: list[dict[str, Any]],
                         zones: list[dict[str, Any]], *,
                         include_requirements: bool = False,
                         semantics: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """静态影印页的段落卡片及需求翻译回退数据（block_id → 原文/翻译/页码）。

    翻译键双查（键同源纪律）：先原始文本键（旧缓存兼容）,未命中再清洗键。"""
    detail_kinds = {"context", "echo", "covered"}
    if include_requirements:
        detail_kinds.add("req")
    detail_zones = {str(z["block_id"]): z for z in zones if z.get("kind") in detail_kinds}
    if include_requirements:
        for item in semantics or []:
            if item.get("kind") == "req" and item.get("block_id"):
                detail_zones.setdefault(str(item["block_id"]), item)
    page_by_block = {z["block_id"]: z["page"] for z in reversed(zones)}
    records: dict[str, dict[str, Any]] = {}
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        if block_id not in detail_zones:
            continue
        text = str(block.get("text") or "").strip()
        translation = ""
        note = ""
        for key in (_translation_key(text), _translation_key(_clean_block_text(text))):
            if key in _active_translations:
                translation = _active_translations[key]
                break
            if not note and key in _active_translation_notes:
                note = _active_translation_notes[key]
        zone = detail_zones[block_id]
        record = {"text": text, "translation": translation,
                  "translation_note": note,
                  "page": page_by_block.get(block_id, _page_number(block.get("page_number")) or 0),
                  "kind": str(zone.get("kind") or "context")}
        if zone.get("kind") == "echo":
            record["echo_req_ids"] = [str(rid) for rid in (zone.get("req_ids") or []) if rid]
        elif zone.get("kind") == "covered":
            record["covered_req_ids"] = [str(rid) for rid in (zone.get("req_ids") or []) if rid]
        elif zone.get("kind") == "req":
            record["req_ids"] = [str(rid) for rid in (zone.get("req_ids") or []) if rid]
        records[block_id] = record
    return records


def _render_pdf_page_stack(pages: list[dict[str, Any]], requirements: list[dict[str, Any]],
                           omissions: list[dict[str, Any]], req_numbers: dict[str, int],
                           geometry: dict[str, list[dict[str, Any]]],
                           block_zones: list[dict[str, Any]] | None = None) -> str:
    markers: dict[int, list[dict[str, Any]]] = {}

    for req in requirements:
        req_id = str(req.get("ai_req_id") or "")
        anchor = str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")
        regions = geometry.get(anchor) or []
        if not req_id or not regions:
            continue
        region = regions[0]
        page = _page_number(region.get("page_number"))
        if not page:
            continue
        owner = str(req.get("ownership_effective") or req.get("ownership") or "software")
        if owner not in _OWNER_LABELS:
            owner = "software"
        zone_style, top_pct = _pdf_zone_style(region)
        number = req_numbers.get(req_id, 0)
        markers.setdefault(page, []).append({
            "kind": "requirement",
            "top": top_pct,
            "zone": (
                f'<span class="pdf-source-zone" data-zone-req="{html.escape(req_id, quote=True)}" '
                f'style="{zone_style}"></span>'),
            "button": (
                f'<button class="pdf-marker marker-requirement owner-{html.escape(owner)}" type="button" '
                f'data-req="{html.escape(req_id, quote=True)}" data-page="{page}" '
                f'title="批注 {number:02d} · {html.escape(str(req.get("title") or "需求"), quote=True)}">'
                f'{number:02d}</button>'),
        })

    for omission in omissions:
        block_id = str(omission.get("block_id") or "")
        for region in geometry.get(block_id) or []:
            page = _page_number(region.get("page_number"))
            if not page:
                continue
            zone_style, top_pct = _pdf_zone_style(region)
            markers.setdefault(page, []).append({
                "kind": "omission",
                "top": top_pct,
                "zone": (
                    f'<span class="pdf-source-zone omission-zone" '
                    f'data-zone-omission="{html.escape(block_id, quote=True)}" style="{zone_style}"></span>'),
                "button": (
                    '<button class="pdf-marker omission-tag marker-omission" type="button" '
                    f'data-block-id="{html.escape(block_id, quote=True)}" data-page="{page}" '
                    f'data-omission-text="{html.escape(str(omission.get("text") or ""), quote=True)}" '
                    f'data-omission-translation="{html.escape(str(omission.get("translation") or ""), quote=True)}" '
                    f'data-omission-translation-note="{html.escape(str(omission.get("translation_note") or ""), quote=True)}" '
                    'title="疑似需求未覆盖">!</button>'),
            })

    # 全段落热区（0714）：透明可点矩形铺满每个块——点一段出翻译和解析。渲染在标记
    # 之前（DOM 序即层序,标记浮在热区上,两者都可点）
    zones_by_page: dict[int, list[str]] = {}
    for zone in block_zones or []:
        rect = zone.get("rect") or {}
        style = (f"left:{rect.get('left', 0):.3f}%;top:{rect.get('top', 0):.3f}%;"
                 f"width:{rect.get('width', 0):.3f}%;height:{rect.get('height', 0):.3f}%")
        kind = str(zone.get("kind") or "context")
        title = {"req": "查看需求批注", "echo": "重复段·点击查看汇总需求",
                 "covered": "该段已纳入需求解析·点击查看关联需求",
                 "omission": "疑似需求未覆盖·点击查看"}.get(kind, "查看该段翻译与解析")
        req_attr = (f' data-req="{html.escape(str(zone.get("req_id") or ""), quote=True)}"'
                    if zone.get("req_id") else "")
        reqs_attr = ""
        echo_attr = ""
        covered_attr = ""
        echo_content = ""
        if kind == "req":
            req_ids = [str(rid) for rid in (zone.get("req_ids") or []) if rid]
            reqs_attr = f' data-reqs="{html.escape(" ".join(req_ids), quote=True)}"'
        elif kind == "echo":
            req_ids = [str(rid) for rid in (zone.get("req_ids") or []) if rid]
            req_ids = list(dict.fromkeys(req_ids))
            req_ids.sort(key=lambda rid: req_numbers.get(rid, 10**9))
            nums = [req_numbers[rid] for rid in req_ids if rid in req_numbers]
            label = "重复·见" + "/".join(f"{num:02d}" for num in nums) if nums else "重复段"
            echo_attr = f' data-echo-reqs="{html.escape(" ".join(req_ids), quote=True)}"'
            echo_content = f'<span class="pdf-echo-tag">{html.escape(label)}</span>'
        elif kind == "covered":
            req_ids = [str(rid) for rid in (zone.get("req_ids") or []) if rid]
            covered_attr = f' data-covered-reqs="{html.escape(" ".join(req_ids), quote=True)}"'
        zones_by_page.setdefault(int(zone["page"]), []).append(
            f'<button class="pdf-block-zone zone-{kind}" type="button" '
            f'data-zone-kind="{kind}" data-block-id="{html.escape(str(zone["block_id"]), quote=True)}"'
            f'{req_attr}{reqs_attr}{echo_attr}{covered_attr} data-page="{int(zone["page"])}" style="{style}" '
            f'title="{html.escape(title, quote=True)}" aria-label="{html.escape(title, quote=True)}" '
            f'aria-pressed="false">{echo_content}</button>')

    page_html: list[str] = []
    for page in pages:
        page_number = int(page["page_number"])
        page_markers = sorted(markers.get(page_number) or [], key=lambda item: item["top"])
        previous_top = -100.0
        lane = 0
        rendered_markers: list[str] = []
        for marker in page_markers:
            lane = lane + 1 if marker["top"] - previous_top < 2.6 else 0
            previous_top = marker["top"]
            rendered_markers.append(marker["zone"])
            rendered_markers.append(
                marker["button"].replace(">", f' style="top:calc({marker["top"]:.3f}% + {lane * 25}px)">', 1))
        aspect = float(page["width"]) / max(1.0, float(page["height"]))
        page_html.append(
            f'<section class="pdf-page" id="pdf-page-{page_number}" data-page="{page_number}" '
            f'style="aspect-ratio:{aspect:.6f}">'
            f'<img src="{html.escape(str(page["href"]), quote=True)}" alt="PDF 第 {page_number} 页" '
            'loading="lazy" decoding="async" />'
            f'<div class="pdf-page-overlay">{"".join(zones_by_page.get(page_number, []))}{"".join(rendered_markers)}</div>'
            f'<span class="pdf-page-label">{page_number}</span></section>')

    return (
        '<div class="pdf-renderer" id="pdf-renderer">'
        '<div class="pdf-toolbar">'
        '<div class="pdf-marker-legend"><span><i class="legend-annotation">01</i>批注</span>'
        '<span><i class="legend-omission">!</i>未覆盖</span></div>'
        '<div class="pdf-toolbar-actions">'
        '<button id="pdf-zoom-out" type="button" title="缩小" aria-label="缩小">&#8722;</button>'
        f'<span id="pdf-page-status">1 / {len(pages)}</span>'
        '<button id="pdf-zoom-in" type="button" title="放大" aria-label="放大">+</button>'
        f'<a href="{ANNOTATION_SOURCE_PDF}" target="_blank" title="打开原始 PDF">PDF</a>'
        '</div></div>'
        f'<div class="pdf-page-list" id="pdf-page-list">{"".join(page_html)}</div></div>')


def build_pdf_annotation_payload(out_dir: Path) -> dict[str, Any]:
    """应用内「原版影印」批注数据（与导出 HTML 同源：同几何缓存/页图/百分比换算——
    双渲染器等价靠共用本模块实现,不是各写一份）。

    只读现成 sidecar：页图缺失时不现场渲染（首次生成走「导出批注HTML·原版影印」,
    之后常驻复用）,返回 available=False + reason 供前端提示。标记只带数据
    （req_id/block_id + 页码 + 百分比矩形）,编号/文案由前端用它自己的编号器渲染。"""
    out_dir = Path(out_dir).expanduser().resolve()
    source_pdf = _source_pdf_path(out_dir)
    if source_pdf is None:
        return {"available": False, "reason": "非 PDF 输入或缺少源文档，无原版影印模式"}
    pages_dir = out_dir / ANNOTATION_PAGES_DIR
    try:
        manifest = json.loads((pages_dir / ANNOTATION_PAGES_MANIFEST).read_text(encoding="utf-8"))
        manifest_pages = manifest.get("pages") if isinstance(manifest, dict) else None
    except (OSError, json.JSONDecodeError):
        manifest = {}
        manifest_pages = None
    try:
        source_hash = _file_sha256(source_pdf)
    except OSError:
        return {"available": False, "reason": "无法读取当前源 PDF，原版影印模式不可用"}
    expected_identity = {
        "version": 1,
        "source_sha256": source_hash,
        "dpi": PDF_PAGE_RENDER_DPI,
    }
    if (not isinstance(manifest, dict)
            or any(manifest.get(key) != value for key, value in expected_identity.items())):
        return {
            "available": False,
            "reason": "影印页缓存与当前 PDF 或渲染版本不一致——请重新导出批注 HTML 以生成最新影印页",
        }
    pages: list[dict[str, Any]] = []
    for page in manifest_pages or []:
        if not isinstance(page, dict):
            continue
        filename = str(page.get("file") or "")
        target = pages_dir / filename
        if filename and target.is_file() and target.stat().st_size > 0:
            pages.append({"page_number": int(page.get("page_number") or 0),
                          "file": filename,
                          "width": float(page.get("width") or 0.0),
                          "height": float(page.get("height") or 0.0)})
    if not pages:
        return {"available": False,
                "reason": "影印页尚未生成——请重新导出批注 HTML（生成后将常驻复用）"}

    blocks = read_jsonl(out_dir / "blocks.jsonl")
    requirements = build_ai_requirements(out_dir)
    geometry = _resolve_pdf_geometry(source_pdf, blocks,
                                     cache_path=out_dir / ANNOTATION_PDF_GEOMETRY)
    requirement_markers: list[dict[str, Any]] = []
    for req in requirements:
        req_id = str(req.get("ai_req_id") or "")
        anchor = str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")
        regions = geometry.get(anchor) or []
        if not req_id or not regions:
            continue
        page = _page_number(regions[0].get("page_number"))
        if not page:
            continue
        requirement_markers.append({"req_id": req_id, "page": page,
                                    "rect": _pdf_zone_rect(regions[0])})
    covered = _covered_blocks(requirements)
    from merged_consistency import is_coverage_candidate
    omission_markers: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        if (not is_coverage_candidate(block)
                or block_id in covered or not str(block.get("text") or "").strip()):
            continue
        for region in geometry.get(block_id) or []:
            page = _page_number(region.get("page_number"))
            if page:
                omission_markers.append({"block_id": block_id, "page": page,
                                         "rect": _pdf_zone_rect(region)})
    return {"available": True, "pages": pages, "pages_dir": ANNOTATION_PAGES_DIR,
            "requirement_markers": requirement_markers, "omission_markers": omission_markers,
            # 全段落热区（0714）：点一段出翻译和解析——语义与静态影印同源（_pdf_block_zones）
            "block_zones": _pdf_block_zones(blocks, requirements, geometry, covered)}


def export_annotation_bundle(out_dir: Path, *, route: str | None = None,
                             layout_mode: str = LAYOUT_PDF_ORIGINAL) -> tuple[Path, dict[str, Any]]:
    out_dir = Path(out_dir).expanduser().resolve()
    requested_mode = _normalize_layout_mode(layout_mode)
    source_pdf = _source_pdf_path(out_dir) if requested_mode == LAYOUT_PDF_ORIGINAL else None
    actual_mode = (LAYOUT_PDF_ORIGINAL
                   if requested_mode == LAYOUT_PDF_ORIGINAL and source_pdf else LAYOUT_OPTIMIZED)
    copied_pdf: Path | None = None
    pdf_pages: list[dict[str, Any]] = []
    page_files: list[str] = []
    pdf_geometry: dict[str, list[dict[str, Any]]] = {}
    pdf_render_error = ""
    if actual_mode == LAYOUT_PDF_ORIGINAL and source_pdf is not None:
        copied_pdf = out_dir / ANNOTATION_SOURCE_PDF
        if source_pdf.resolve() != copied_pdf.resolve():
            shutil.copyfile(source_pdf, copied_pdf)
        try:
            blocks = build_document_blocks(out_dir).get("blocks") or []
            pdf_geometry = _resolve_pdf_geometry(
                source_pdf, blocks, cache_path=out_dir / ANNOTATION_PDF_GEOMETRY)
            pdf_pages, page_files = _ensure_pdf_page_images(source_pdf, out_dir)
        except Exception as exc:
            pdf_render_error = str(exc)

    target = out_dir / ANNOTATION_HTML
    rendered = render_annotation_html(
        out_dir,
        layout_mode=actual_mode,
        pdf_href=ANNOTATION_SOURCE_PDF if copied_pdf else None,
        pdf_pages=pdf_pages,
        pdf_geometry=pdf_geometry,
    )
    summary: dict[str, Any] = {"route": "stub", "total_markers": len(_collected_marker_texts)}
    if route and route != "stub":
        summary = generate_annotation_translations(out_dir, route=route,
                                                   texts=dict(_collected_marker_texts))
        if summary.get("translated") or summary.get("rejected"):
            rendered = render_annotation_html(
                out_dir, layout_mode=actual_mode,
                pdf_href=ANNOTATION_SOURCE_PDF if copied_pdf else None,
                pdf_pages=pdf_pages,
                pdf_geometry=pdf_geometry)   # 重渲染嵌入新译文或拒绝原因（毫秒级）
    summary.update({
        "layout_mode_requested": requested_mode,
        "layout_mode": actual_mode,
        "source_pdf": str(copied_pdf) if copied_pdf else None,
        "annotation_overlay": bool(pdf_pages and pdf_geometry),
        "page_files": page_files,
        "pdf_render_error": pdf_render_error or None,
    })
    target.write_text(rendered, encoding="utf-8")
    return target, summary


def export_annotation_html(out_dir: Path, route: str | None = None,
                           layout_mode: str = LAYOUT_PDF_ORIGINAL) -> Path:
    return export_annotation_bundle(out_dir, route=route, layout_mode=layout_mode)[0]


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
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: var(--sans);
  color: var(--ink); background: var(--page); font-size: 14px; line-height: 1.7; }}
.reader-shell {{ min-height: 100vh; background:
  linear-gradient(90deg, rgba(255,255,255,.62), rgba(255,255,255,0) 18%, rgba(255,255,255,0) 82%, rgba(255,255,255,.5)),
  var(--page); }}
.reader-shell.pdf-original .read-progress {{ display: none; }}
.reader-shell.pdf-original .paper {{ padding: 0; overflow: auto; background: #3f4144; }}
.reader-shell.pdf-original .doc-content {{ width: 100%; max-width: none; height: 100%; margin: 0; padding: 0;
  border: 0; border-radius: 0; box-shadow: none; background: #525659; }}
.pdf-frame {{ display: block; width: 100%; height: 100%; border: 0; background: #525659; }}
.reader-shell.pdf-annotated .doc-content {{ height: auto; min-height: 100%; overflow: visible; background: #3f4144; }}
.pdf-renderer {{ min-height: 100%; --pdf-page-width: min(850px, calc(100vw - 696px)); }}
.pdf-toolbar {{ position: sticky; top: 0; z-index: 7; height: 44px; display: flex; align-items: center;
  justify-content: space-between; padding: 0 14px; color: #f4f4f4; background: rgba(38,39,41,.96);
  border-bottom: 1px solid #5b5d60; font-family: var(--sans); }}
.pdf-marker-legend, .pdf-toolbar-actions {{ display: flex; align-items: center; gap: 10px; }}
.pdf-marker-legend span {{ display: inline-flex; align-items: center; gap: 5px; color: #d5d7da; font-size: 11px; }}
.pdf-marker-legend i {{ width: 21px; height: 21px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%; font-style: normal; font-size: 9px; font-weight: 700; }}
.legend-annotation {{ color: #ffffff; background: #0f766e; }}
.legend-omission {{ color: #474747; background: #ddd9d1; border: 1px solid #aaa59b; }}
.pdf-toolbar-actions button, .pdf-toolbar-actions a {{ width: 28px; height: 28px; display: inline-flex;
  align-items: center; justify-content: center; border: 0; border-radius: 4px; color: #f5f5f5;
  background: transparent; text-decoration: none; cursor: pointer; font: 600 14px/1 var(--sans); }}
.pdf-toolbar-actions button:hover, .pdf-toolbar-actions a:hover {{ background: #57595d; }}
#pdf-page-status {{ min-width: 62px; text-align: center; font-size: 11px; font-variant-numeric: tabular-nums; }}
.pdf-page-list {{ display: flex; flex-direction: column; align-items: center; gap: 18px; width: max-content;
  min-width: 100%; padding: 20px 48px 48px 32px; }}
.pdf-page {{ position: relative; width: var(--pdf-page-width); flex: 0 0 auto;
  background: #ffffff; box-shadow: 0 2px 12px rgba(0,0,0,.38); overflow: visible; }}
.pdf-page > img {{ display: block; width: 100%; height: 100%; object-fit: fill; }}
.pdf-page-overlay {{ position: absolute; inset: 0; overflow: visible; pointer-events: none; }}
.pdf-source-zone {{ position: absolute; z-index: 1; border: 1px solid transparent; background: transparent;
  pointer-events: none; transition: background .12s, border-color .12s; }}
.pdf-source-zone.selected {{ background: transparent; border-color: transparent; }}
.pdf-source-zone.omission-zone.selected {{ background: transparent; border-color: transparent; }}
/* 全段落热区（0714）：透明可点,悬停淡蓝提示——点一段出翻译和解析 */
.pdf-block-zone {{ position: absolute; z-index: 2; margin: 0; padding: 0; border: 1px solid transparent;
  background: transparent; cursor: pointer; pointer-events: auto; border-radius: 3px;
  transition: background .12s, border-color .12s; }}
.pdf-block-zone:hover {{ background: rgba(89, 120, 247, .04); border-color: rgba(89, 120, 247, .42); }}
.pdf-block-zone.selected {{ background: rgba(89, 120, 247, .06); border-color: rgba(89, 120, 247, .72); }}
.pdf-block-zone:focus-visible {{ outline: 2px solid rgba(89, 120, 247, .85); outline-offset: 1px; }}
.pdf-block-zone.zone-omission:hover {{ background: rgba(204, 137, 37, .05); border-color: rgba(204, 137, 37, .48); }}
.pdf-block-zone.zone-omission.selected {{ background: rgba(204, 137, 37, .07); border-color: rgba(180, 83, 9, .7); }}
.pdf-block-zone.zone-echo:hover, .pdf-block-zone.zone-echo.selected {{
  background: rgba(15,118,110,.05); border-color: rgba(15,118,110,.5); }}
.pdf-echo-tag {{ position: absolute; right: 2px; top: -13px; display: inline-block; padding: 0 2px 1px;
  border-bottom: 1px dashed #667085; color: #4b5563; background: rgba(255,255,255,.92);
  z-index: 2; font: 600 9px/1.15 var(--sans); white-space: nowrap; pointer-events: auto;
  cursor: pointer; opacity: 0;
  transition: opacity .12s; }}
.pdf-block-zone.zone-echo:hover .pdf-echo-tag,
.pdf-block-zone.zone-echo.selected .pdf-echo-tag {{ opacity: 1; }}
.pdf-page .pdf-marker {{ position: absolute; right: -34px; z-index: 3; width: 25px; height: 25px; margin: 0;
  display: inline-flex; align-items: center; justify-content: center; padding: 0; border-radius: 50%;
  border: 2px solid #ffffff; color: #ffffff; cursor: pointer; pointer-events: auto;
  font: 700 9px/1 var(--sans); box-shadow: 0 2px 7px rgba(0,0,0,.32); opacity: .92; }}
.pdf-page .pdf-marker:hover, .pdf-page .pdf-marker.sel {{ transform: scale(1.12); opacity: 1; }}
.pdf-page .pdf-marker.owner-software {{ background: #0f766e; }}
.pdf-page .pdf-marker.owner-hardware {{ background: #9a6700; }}
.pdf-page .pdf-marker.owner-co_design {{ background: #315f72; }}
.pdf-page .pdf-marker.owner-software_term {{ background: #6b7280; }}
.pdf-page .pdf-marker.marker-omission {{ color: #5d5549; background: #ddd9d1; border: 1px solid #9f998e;
  box-shadow: 0 1px 5px rgba(0,0,0,.2); opacity: .68; }}
.pdf-page .pdf-marker.marker-omission:hover, .pdf-page .pdf-marker.marker-omission.sel {{ color: #7a5610;
  background: #f3ead4; border-color: #a97a22; opacity: 1; }}
.pdf-page-label {{ position: absolute; left: 50%; bottom: -17px; transform: translateX(-50%);
  color: #d3d4d6; font: 10px/1 var(--sans); }}

/* --- 顶栏 --- */
.topbar {{ position: sticky; top: 0; z-index: 10; display: flex; justify-content: space-between; align-items: center;
  padding: 0 28px; height: 56px; background: rgba(253,251,246,.86); border-bottom: 1px solid var(--line);
  backdrop-filter: blur(18px); }}
.topbar .brand {{ font-weight: 600; font-size: 14px; color: var(--ink); letter-spacing: .01em; }}
.topbar .stats {{ display: flex; gap: 22px; font-size: 12px; color: var(--muted); }}
.topbar .stats strong {{ color: var(--ink); font-weight: 600; }}
.topbar .stats .warn strong {{ color: var(--muted); }}
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
.outline .req-index-item {{ width: 100%; align-items: flex-start; gap: 7px; border: 0; background: transparent;
  font: inherit; text-align: left; margin: 0 0 2px; }}
.outline .req-index-number {{ min-width: 22px; color: var(--accent); font-variant-numeric: tabular-nums; }}
.outline .req-index-copy {{ min-width: 0; display: flex; flex-direction: column; }}
.outline .req-index-copy small {{ color: var(--faint); font-size: 10px; line-height: 1.4; }}
.pdf-index-tabs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2px; margin: 0 6px 10px;
  padding: 2px; background: #ebe8e1; border-radius: 4px; }}
.pdf-index-tabs button {{ min-width: 0; border: 0; border-radius: 3px; padding: 5px 4px; color: var(--muted);
  background: transparent; cursor: pointer; font: 600 11px/1.2 var(--sans); }}
.pdf-index-tabs button.active {{ color: var(--ink); background: #ffffff; box-shadow: 0 1px 2px rgba(0,0,0,.08); }}
.outline .omission-index-item .req-index-number {{ color: #8a6417; }}
.outline .omission-index-item {{ opacity: .82; }}

/* --- 中：文档 --- */
.paper {{ overflow-y: auto; padding: 26px 0 48px; }}
.doc-content {{ max-width: 720px; margin: 0 auto; padding: 40px 52px 52px; background: var(--paper);
  border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 18px 50px rgba(23, 23, 23, 0.08);
  font-family: var(--sans); font-size: 16px; line-height: 1.65; }}

.doc-block {{ margin-bottom: 0; }}
.block-inner {{ position: relative; padding-left: calc(var(--depth, 0) * 16px); }}
.doc-block .text {{ margin: 0; padding: 1px 0; }}
.doc-block:not(.heading):not(.noise):not(.list-item):not(.is-table) {{ margin-bottom: 9px; }}
.doc-block.list-item {{ margin-bottom: 2px; }}
.doc-block.list-item + .doc-block:not(.list-item):not(.heading) {{ margin-top: 7px; }}
.doc-block.heading .text {{ font-weight: 600; margin-top: 14px; }}
.doc-block.heading .text {{ line-height: 1.3; }}
.doc-block.h1 .text {{ font-size: 32px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }}
.doc-block.h2 .text {{ font-size: 23px; }}
.doc-block.h2 .block-inner {{ border-left: 2px solid var(--accent-quiet); padding-left: 12px; margin-left: -14px; }}
.doc-block.h3 .text {{ font-size: 19px; color: #3d3d3d; }}
.doc-block.noise .text {{ opacity: 0.3; font-size: 13px; }}
.doc-block.omission:hover {{ background: rgba(248,239,217,.2); }}
.doc-block.anchored {{ cursor: pointer; border-radius: 4px; }}
.doc-block.anchored:hover {{ background: var(--accent-soft); }}
.doc-block.in-span {{ background: var(--accent-soft); border-radius: 4px; }}
.text mark {{ background: linear-gradient(transparent 44%, var(--highlight) 44%); padding: 0 2px; border-radius: 0; }}
mark.sc-quote {{ background: linear-gradient(transparent 44%, var(--highlight) 44%); padding: 0 2px; border-radius: 0; }}
.page-break {{ display: flex; align-items: center; gap: 10px; margin: 16px 0 10px; color: #b8b2a4; font-size: 11px; }}
.page-break::before, .page-break::after {{ content: ""; flex: 1; border-top: 1px dashed #ddd6c8; }}

/* --- 阅读排版（优于原版 PDF：正文两端对齐、列表悬挂缩进、真表格） --- */
.doc-block .text {{ overflow-wrap: anywhere; }}
.doc-block:not(.heading):not(.short) .text {{ text-align: justify; hyphens: none; }}
.doc-block.short .text {{ text-align: left; }}
.doc-block.list-item .text {{ padding-left: 1.6em; text-indent: -1.6em; text-align: left; }}
.doc-block.note .text {{ padding-left: 3.4em; text-indent: -3.4em; }}
.doc-table {{ margin: 10px 0 12px; }}
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
.omission-tag {{ display: inline-flex; margin-left: 6px; padding: 0 2px 1px; border: 0;
  border-bottom: 1px dotted var(--line-strong); border-radius: 0; background: transparent;
  color: var(--faint); font-size: 10px; line-height: 1; cursor: pointer; vertical-align: super;
  font-family: var(--sans); transition: color .12s, border-color .12s, background .12s; }}
.omission-tag:hover, .omission-tag.sel {{ color: var(--st-discussion-tx); border-color: var(--st-discussion-tx);
  background: rgba(248,239,217,.45); }}
.echo-tag {{ display: inline-flex; margin-left: 6px; padding: 0 2px 1px; border: 0;
  border-bottom: 1px dashed var(--line-strong); border-radius: 0; background: transparent;
  color: var(--faint); font-size: 10px; line-height: 1; cursor: pointer; vertical-align: super;
  font-family: var(--sans); transition: color .12s, border-color .12s; }}
.echo-tag:hover {{ color: var(--ink); border-color: var(--ink); }}
.echo-jump {{ padding: 0; border: 0; background: transparent; color: var(--st-accepted-tx, #1d8a5c);
  text-decoration: underline dotted; cursor: pointer; font: inherit; text-align: left; }}

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
.dd-consistency {{ font-size: 12px; color: #1e41c9; background: #eef2ff; border-radius: 6px; padding: 4px 8px; margin-bottom: 10px; }}
.dd-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin: 15px 0 5px; }}
.dd-body {{ font-size: 14px; line-height: 1.7; }}
.dd-result-primary {{ margin: 12px 0; padding: 11px 12px; border-left: 3px solid var(--accent);
  border-radius: 0 6px 6px 0; background: rgba(15,118,110,.055); }}
.dd-result-primary .dd-label {{ margin-top: 0; color: var(--accent); font-weight: 700; letter-spacing: 0; text-transform: none; }}
.dd-result-primary .dd-body {{ color: var(--ink); font-size: 15px; }}
.dd-empty {{ color: var(--faint); }}
.dd-prewrap {{ white-space: pre-wrap; }}
.src-badge {{ font-size: 10px; text-transform: none; letter-spacing: 0; color: var(--accent);
  border: 1px solid var(--accent-soft); background: var(--accent-soft); border-radius: 8px; padding: 0 6px; }}
.src-badge.quiet {{ color: var(--faint); border-color: var(--line); background: transparent; }}
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
@media (max-width: 1100px) {{
  .layout {{ grid-template-columns: minmax(0, 1fr) 340px; }}
  .outline {{ display: none; }}
  .pdf-renderer {{ --pdf-page-width: min(850px, calc(100vw - 436px)); }}
}}
@media (max-width: 768px) {{
  .topbar {{ padding: 0 10px; gap: 8px; }}
  .topbar .stats {{ display: none; }}
  .topbar button {{ padding: 6px 9px; font-size: 11px; }}
  .layout {{ display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 56fr) minmax(0, 44fr);
    height: calc(100vh - 56px); overflow: hidden; }}
  .detail {{ display: block; min-height: 0; overflow-y: auto; padding: 16px 14px;
    border-top: 1px solid var(--line); border-left: 0; background: var(--panel); }}
  .detail .empty {{ padding-top: 28px; }}
  .detail-card {{ max-width: 680px; margin: 0 auto 14px; padding: 16px; }}
  .paper {{ min-width: 0; min-height: 0; padding: 16px 0 32px; }}
  .doc-content {{ width: 100%; max-width: none; margin: 0; padding: 28px 18px 40px;
    border-left: 0; border-right: 0; border-radius: 0; }}
  .doc-block.h1 .text {{ font-size: 27px; }}
  .doc-block.h2 .text {{ font-size: 21px; }}
  .doc-block:not(.heading):not(.short) .text {{ text-align: left; }}
  .block-inner {{ padding-left: calc(var(--depth, 0) * 8px); }}
  .pdf-renderer {{ --pdf-page-width: calc(100vw - 64px); }}
  .pdf-page-list {{ padding-left: 8px; padding-right: 40px; }}
  .pdf-page .pdf-marker {{ right: -30px; }}
  .pdf-marker-legend span {{ font-size: 0; gap: 0; }}
}}
</style>
</head>
<body>
<div class="reader-shell{layout_class}">
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
  <aside class="annotation-rail detail" id="detail"><div class="empty">点击原文段落或页边编号查看解析结果</div></aside>
</div>
</div>
<script>
const DOC_ID = "{doc_id}";
const STORAGE_KEY = "ratomizer-decisions:" + DOC_ID;
const REQUIREMENTS = {requirements_json};
const PDF_OMISSIONS = {omissions_json};
const PDF_CONTEXT = {pdf_context_json};
const MODULE_VOCAB = {module_vocab_json};
const GENERATED_AT = "{generated_at}";
const PDF_MODE = {pdf_mode};
const PDF_OVERLAY_ENABLED = {pdf_overlay_enabled};
const PDF_PAGE_COUNT = {pdf_page_count};
const PDF_HREF = {pdf_href_json};
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

function showPdfPage(page) {{
  if (!PDF_MODE) return;
  const pageNumber = Number.parseInt(String(page || ""), 10);
  if (!Number.isFinite(pageNumber) || pageNumber < 1) return;
  if (PDF_OVERLAY_ENABLED) {{
    const pageElement = document.getElementById("pdf-page-" + pageNumber);
    if (pageElement) pageElement.scrollIntoView({{behavior:"smooth", block:"start"}});
    const status = document.getElementById("pdf-page-status");
    if (status) status.textContent = pageNumber + " / " + PDF_PAGE_COUNT;
    return;
  }}
  if (!PDF_HREF) return;
  const frame = document.getElementById("pdf-frame");
  if (frame) frame.setAttribute("src", PDF_HREF + "#page=" + pageNumber + "&view=FitH");
}}

/* --- 左侧大纲：树形可折叠（h1 可展开/收起，h2/h3 嵌套） --- */
function buildOutline() {{
  const nav = document.getElementById("outline");
  if (PDF_MODE) {{
    const title = nav.querySelector(".outline-title");
    if (title) title.textContent = "批注索引";
    const ownerLabels = {{software:"软件", hardware:"硬件", co_design:"软硬件协同"}};
    const rows = REQUIREMENTS.slice().sort((a, b) =>
      Number(a.annotation_number || 999999) - Number(b.annotation_number || 999999));
    if (!rows.length && !PDF_OMISSIONS.length) {{ nav.style.display = "none"; return; }}
    const tabs = document.createElement("div");
    tabs.className = "pdf-index-tabs";
    const list = document.createElement("div");
    list.className = "pdf-index-list";

    function renderIndex(kind) {{
      tabs.querySelectorAll("button").forEach(button =>
        button.classList.toggle("active", button.getAttribute("data-kind") === kind));
      list.innerHTML = "";
      if (kind === "annotations") {{
        rows.forEach((r, index) => {{
          const item = document.createElement("button");
          item.type = "button";
          item.className = "nav-item req-index-item";
          item.setAttribute("data-req", r.ai_req_id || "");
          const number = String(r.annotation_number || index + 1).padStart(2, "0");
          const owner = ownerLabels[ownershipOf(r)] || "待分类";
          const page = Number(r.source_page || 0);
          const meta = owner + (page > 0 ? " · 第 " + page + " 页" : "");
          item.innerHTML = '<span class="req-index-number">' + esc(number) + '</span>' +
            '<span class="req-index-copy"><span class="label">' + esc(r.title || r.description || r.ai_req_id) +
            '</span><small>' + esc(meta) + '</small></span>';
          item.onclick = () => select(r.ai_req_id);
          list.appendChild(item);
        }});
      }} else {{
        PDF_OMISSIONS.forEach(row => {{
          const item = document.createElement("button");
          item.type = "button";
          item.className = "nav-item req-index-item omission-index-item";
          item.setAttribute("data-omission-block", row.block_id || "");
          const page = Number(row.source_page || 0);
          item.innerHTML = '<span class="req-index-number">!</span>' +
            '<span class="req-index-copy"><span class="label">' + esc(row.text || "未覆盖原文") +
            '</span><small>未覆盖' + (page > 0 ? " · 第 " + page + " 页" : "") + '</small></span>';
          item.onclick = () => {{
            showPdfPage(page);
            const marker = document.querySelector('.marker-omission[data-block-id="' + row.block_id + '"]');
            if (marker) selectOmission(marker); else selectOmissionRecord(row);
          }};
          list.appendChild(item);
        }});
      }}
    }}

    [["annotations", "批注 " + rows.length], ["omissions", "未覆盖 " + PDF_OMISSIONS.length]].forEach(entry => {{
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("data-kind", entry[0]);
      button.textContent = entry[1];
      button.onclick = () => renderIndex(entry[0]);
      tabs.appendChild(button);
    }});
    nav.appendChild(tabs);
    nav.appendChild(list);
    renderIndex("annotations");
    return;
  }}
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
  document.querySelectorAll(".pdf-source-zone").forEach(el => el.classList.remove("selected"));
  const r = selected && byId[selected]; if (!r) return;
  document.querySelectorAll('.pdf-source-zone[data-zone-req="' + selected + '"]').forEach(el =>
    el.classList.add("selected"));
  const ids = (r.source_block_ids || []).concat(r.echo_block_ids || []).concat([r.anchor_block_id]).filter(Boolean);
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

function anchorBlockTranslation(r) {{
  const anchor = r.anchor_block_id || (r.source_block_ids||[])[0];
  if (!anchor) return "";
  const pdfRecord = PDF_CONTEXT[anchor];
  if (pdfRecord && pdfRecord.translation) return String(pdfRecord.translation);
  const p = document.querySelector('.text[data-block-id="' + anchor + '"]');
  return p ? (p.getAttribute("data-translation") || "") : "";
}}

function hardwareTranslationHtml(r) {{
  if (!isHardwareRequirement(r)) return "";
  // 诚实回退（真实反馈 2026-07-12,test18）：确定性兜底的 hardware_translation 是英文原文,
  // 不得顶着"中文翻译"标签展示。候选含中文才用;否则回退锚点块的全文翻译;再无 → 空态。
  // 原文本就在卡片底部「原文引用」区,不丢信息。
  const cjk = /[一-鿿]/;
  const label = '<div class="dd-label">中文翻译 / 说明</div>';
  for (const candidate of [r.hardware_summary, r.hardware_translation]) {{
    if (candidate && cjk.test(String(candidate))) return label + '<div class="dd-body">'+esc(candidate)+'</div>';
  }}
  const blockT = anchorBlockTranslation(r);
  if (blockT) return label + '<div class="dd-body">'+esc(blockT)+'</div>';
  return label + '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>';
}}

function ownershipReasonHtml(r) {{
  // 归属原因全类别显示（真实反馈 2026-07-12）：此前只硬件有"为什么",软件/协同全链路无原因
  const labels = {{ software: "软件", hardware: "硬件", co_design: "软硬件协同" }};
  const own = ownershipOf(r);
  const reason = r.ownership_reason || "";
  if (!reason) return "";
  let html = '<div class="dd-label">为什么判为' + esc(labels[own] || own) + '</div>'+
             '<div class="dd-body">'+esc(reason)+'</div>';
  const base = String(r.ownership || "");
  const effective = String(r.ownership_effective || base);
  if (base && effective && base !== effective) {{
    html += '<div class="dd-body dd-empty">已被人工覆盖为' + esc(labels[effective] || effective) +
            '（原判' + esc(labels[base] || base) + '）</div>';
  }}
  return html;
}}

function requirementSummaryHtml(r) {{
  const summary = String(r.description || "").trim();
  return '<div class="dd-section dd-result-primary"><div class="dd-label">抽取需求</div>'+
         '<div class="dd-body'+(summary ? '' : ' dd-empty')+'">'+
         (summary ? esc(summary) : '未生成需求摘要')+'</div></div>';
}}

function markQuoteTextNodes(container, quote) {{
  // 引用片段精确黄标（真实反馈 2026-07-11）：不重建 innerHTML——角标按钮/其它需求的
  // 标记都保留,只把 source_quote 命中的文本节点区间包进 mark。角标插在引用末尾,
  // 引用文本通常完整落在单个文本节点里;跨节点(被子项角标截断)时放弃黄标不误标。
  if (!container || !quote) return false;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {{
    const i = node.textContent.indexOf(quote);
    if (i < 0) continue;
    const range = document.createRange();
    range.setStart(node, i);
    range.setEnd(node, i + quote.length);
    const m = document.createElement("mark");
    m.className = "sc-quote";
    range.surroundContents(m);
    return true;
  }}
  return false;
}}

function highlightQuote() {{
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  document.querySelectorAll('.chip[data-inline-marker="1"].quote-selected').forEach(m => m.classList.remove("quote-selected"));
  const r = selected && byId[selected]; if (!r || !r.source_quote) return;
  const marker = document.querySelector('.chip[data-inline-marker="1"][data-req="' + selected + '"]');
  if (marker) {{
    marker.classList.add("quote-selected");
    // 引用片段黄标、上下文整块保持蓝底：黄标只盖 source_quote 本体,与右卡「原文引用」一致
    markQuoteTextNodes(marker.parentElement, r.source_quote);
    return;
  }}
  const anchor = r.anchor_block_id || (r.source_block_ids||[])[0];
  const p = document.querySelector('.text[data-block-id="' + anchor + '"]'); if (!p) return;
  const t = p.textContent, q = r.source_quote, i = t.indexOf(q);
  if (i >= 0) p.innerHTML = esc(t.slice(0,i)) + "<mark>" + esc(q) + "</mark>" + esc(t.slice(i+q.length));
}}

function clearSourceQuoteMarks() {{
  // 说明标记的引用黄标（p 与 td 两种容器）；replaceWith 文本节点,不经 innerHTML 免转义
  document.querySelectorAll("mark.sc-quote").forEach(m => m.replaceWith(document.createTextNode(m.textContent)));
}}

function deselect() {{
  selected = null;
  selectedContextBlock = null;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".source-classification").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".pdf-marker").forEach(marker => marker.classList.remove("sel"));
  document.querySelectorAll(".pdf-source-zone").forEach(zone => zone.classList.remove("selected"));
  paintZoneSelection("");
  document.querySelectorAll(".req-index-item").forEach(item => item.classList.remove("active"));
  document.querySelectorAll('.chip[data-inline-marker="1"].quote-selected').forEach(m => m.classList.remove("quote-selected"));
  document.querySelectorAll(".doc-block").forEach(el => el.classList.remove("in-span"));
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  clearSourceQuoteMarks();
  document.getElementById("detail").innerHTML = '<div class="empty">点击原文段落或页边编号查看解析结果</div>';
}}

// 与 DocumentReview.vue 同文案（双渲染器契约）：未覆盖=疑似需求但无任何抽取需求覆盖
const OMISSION_REASON = "该段含规范性措辞（shall/must/应…），被判为疑似需求，但没有任何已抽取需求的来源范围覆盖它。可能原因：抽取遗漏（自检未补回）或该句实为背景说明。确属需求请反馈补抽；背景说明可忽略。";
const CONTEXT_REASON = "该段未检出规范性措辞（shall/must/应…），被判定为背景/说明性内容，因此没有生成研发需求；其信息会作为上下文供相邻需求的分析使用。如认为该段实际包含需求，请反馈补抽。";
const ECHO_REASON = "该段与已抽取需求的来源段落内容重复（同文多次出现）。解析已汇总至对应需求条目，本段不重复挂批注；点击「重复·见」角标或下方链接可跳转查看该条目。";
const COVERED_REASON = "该段已纳入一个或多个抽取需求的来源范围，用于补充该需求的约束、条件或上下文；它不是主锚点，因此不重复挂页边编号。";
const REQUIREMENT_GROUP_REASON = "该段原文解析出了多条独立需求。为避免只展示第一条，下面列出该段的全部解析结果。";
let selectedContextBlock = null;

function echoTargets(reqIds) {{
  return Array.from(new Set(reqIds || []))
    .map(rid => byId[rid]).filter(Boolean)
    .sort((a, b) => Number(a.annotation_number || 999999) - Number(b.annotation_number || 999999));
}}

function echoLinksHtml(reqIds) {{
  return echoTargets(reqIds).map(target => {{
    const num = String(target.annotation_number || "").padStart(2, "0");
    return '<div class="dd-body"><button type="button" class="echo-jump" data-echo-req="'+esc(target.ai_req_id)+'">'+
      '查看批注 '+esc(num)+'《'+esc(target.title || "")+'》</button></div>';
  }}).join("");
}}

function bindEchoJumps() {{
  document.querySelectorAll("#detail .echo-jump").forEach(jump =>
    jump.addEventListener("click", () => select(jump.getAttribute("data-echo-req"))));
}}

function echoDetailsHtml(reqIds, text, translation, note, page) {{
  const location = page ? '<div class="dd-meta">原文位置 · PDF 第 '+esc(page)+' 页</div>' : '';
  const translationHtml = '<div class="dd-label">原文翻译</div>'+
    (translation ? '<div class="dd-body">'+esc(translation)+'</div>'
     : note ? '<div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(note)+'）</div>'
     : '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>');
  return '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">重复段</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">该段解析已汇总</div>'+location+
    '<div class="dd-body">'+esc(ECHO_REASON)+'</div>'+echoLinksHtml(reqIds)+translationHtml+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
     '</div>';
}}

function coveredDetailsHtml(reqIds, text, translation, note, page) {{
  const location = page ? '<div class="dd-meta">原文位置 · PDF 第 '+esc(page)+' 页</div>' : '';
  const translationHtml = '<div class="dd-label">原文翻译</div>'+
    (translation ? '<div class="dd-body">'+esc(translation)+'</div>'
     : note ? '<div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(note)+'）</div>'
     : '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>');
  return '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">已解析来源段</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">该段已纳入需求解析</div>'+location+
    '<div class="dd-body">'+esc(COVERED_REASON)+'</div>'+echoLinksHtml(reqIds)+translationHtml+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
    '</div>';
}}

function requirementGroupDetailsHtml(reqIds, text, translation, note, page) {{
  const location = page ? '<div class="dd-meta">原文位置 · PDF 第 '+esc(page)+' 页</div>' : '';
  const translationHtml = '<div class="dd-label">原文翻译</div>'+
    (translation ? '<div class="dd-body">'+esc(translation)+'</div>'
     : note ? '<div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(note)+'）</div>'
     : '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>');
  return '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">解析结果</span><span class="badge">'+esc(reqIds.length)+' 条</span></div>'+
    '<div class="dd-title">该段解析出 '+esc(reqIds.length)+' 条需求</div>'+location+
    '<div class="dd-body">'+esc(REQUIREMENT_GROUP_REASON)+'</div>'+echoLinksHtml(reqIds)+translationHtml+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
    '</div>';
}}

function selectContextBlock(blk) {{
  const bid = blk.getAttribute("data-block-id") || "";
  if (selectedContextBlock === bid) {{ selectedContextBlock = null; deselect(); return; }}
  selected = null;
  selectedContextBlock = bid;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".source-classification").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".doc-block").forEach(b => b.classList.remove("in-span", "evidence"));
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  clearSourceQuoteMarks();
  blk.classList.add("in-span", "evidence");
  const p = blk.querySelector(".text");
  markWholeTextNodes(p);
  const text = p ? p.textContent : "";
  const translation = p ? (p.getAttribute("data-translation") || "") : "";
  const note = p ? (p.getAttribute("data-translation-note") || "") : "";
  const echoTag = blk.querySelector(".echo-tag");
  const translationHtml = '<div class="dd-label">原文翻译</div>'+
    (translation ? '<div class="dd-body">'+esc(translation)+'</div>'
     : note ? '<div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(note)+'）</div>'
     : '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>');
  if (echoTag) {{
    // 重复段卡片：本段解析（翻译/引用）+ 全部汇总条目，不再只保留第一条。
    const reqIds = (echoTag.getAttribute("data-echo-reqs") || "").split(/\s+/).filter(Boolean);
    document.getElementById("detail").innerHTML = echoDetailsHtml(reqIds, text, translation, note, 0);
    bindEchoJumps();
    return;
  }}
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">背景/上下文</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">为什么没有生成研发需求</div>'+
    '<div class="dd-body">'+esc(CONTEXT_REASON)+'</div>'+
    translationHtml+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
    '</div>';
}}

function markWholeTextNodes(container) {{
  if (!container) return;
  Array.from(container.childNodes).forEach(node => {{
    if (node.nodeType === 3 && node.textContent.trim()) {{
      const m = document.createElement("mark");
      m.className = "sc-quote";
      node.parentNode.insertBefore(m, node);
      m.appendChild(node);
    }}
  }});
}}

function renderOmissionDetails(text, translation, note, page) {{
  const location = page ? '<div class="dd-meta">原文位置 · PDF 第 '+esc(page)+' 页</div>' : '';
  const translationHtml = translation
    ? '<div class="dd-label">原文翻译</div><div class="dd-body">'+esc(translation)+'</div>'
    : note
      ? '<div class="dd-label">原文翻译</div><div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(note)+'）</div>'
      : PDF_MODE ? ''
      : '<div class="dd-label">原文翻译</div><div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>';
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">未覆盖</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">为什么标为未覆盖</div>'+location+
    '<div class="dd-body">'+esc(OMISSION_REASON)+'</div>'+translationHtml+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
    '</div>';
}}

function selectOmissionRecord(row) {{
  selected = null;
  selectedContextBlock = null;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".source-classification").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".pdf-source-zone").forEach(zone => zone.classList.remove("selected"));
  document.querySelectorAll('.pdf-source-zone[data-zone-omission="' + row.block_id + '"]').forEach(zone =>
    zone.classList.add("selected"));
  document.querySelectorAll(".doc-block").forEach(block => block.classList.remove("in-span", "evidence"));
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  clearSourceQuoteMarks();
  paintZoneSelection(row.block_id || "");
  renderOmissionDetails(row.text || "", row.translation || "", row.translation_note || "", row.source_page || 0);
}}

// 全段落热区选中高亮（0714）：req 热区随 select() 走 data-req,块级热区按 block_id 走这里
function paintZoneSelection(blockId) {{
  document.querySelectorAll(".pdf-block-zone").forEach(z => {{
    const active = Boolean(blockId) && z.getAttribute("data-block-id") === blockId;
    z.classList.toggle("selected", active);
    z.setAttribute("aria-pressed", String(active));
  }});
}}

function selectPdfContextRecord(blockId, info, clickedPage) {{
  const sourcePage = Number(clickedPage || info.page || 0);
  const selectionKey = blockId + "@pdf:" + sourcePage;
  if (selectedContextBlock === selectionKey) {{ selectedContextBlock = null; deselect(); return; }}
  selected = null;
  selectedContextBlock = selectionKey;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".pdf-marker").forEach(marker => marker.classList.remove("sel"));
  document.querySelectorAll(".pdf-source-zone").forEach(zone => zone.classList.remove("selected"));
  paintZoneSelection(blockId);
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">背景/上下文</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">为什么没有生成研发需求</div>'+
    (sourcePage ? '<div class="dd-meta">原文位置 · PDF 第 '+esc(sourcePage)+' 页</div>' : '')+
    '<div class="dd-body">'+esc(CONTEXT_REASON)+'</div>'+
    '<div class="dd-label">原文翻译</div>'+
    (info.translation ? '<div class="dd-body">'+esc(info.translation)+'</div>'
     : info.translation_note ? '<div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(info.translation_note)+'）</div>'
     : '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>')+
    (info.text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(info.text)+'</div>' : '')+
    '</div>';
}}

function selectPdfEchoRecord(blockId, info, clickedPage) {{
  const sourcePage = Number(clickedPage || info.page || 0);
  const selectionKey = blockId + "@pdf:" + sourcePage;
  if (selectedContextBlock === selectionKey) {{ selectedContextBlock = null; deselect(); return; }}
  selected = null;
  selectedContextBlock = selectionKey;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".pdf-marker").forEach(marker => marker.classList.remove("sel"));
  document.querySelectorAll(".pdf-source-zone").forEach(zone => zone.classList.remove("selected"));
  paintZoneSelection(blockId);
  document.getElementById("detail").innerHTML = echoDetailsHtml(
    info.echo_req_ids || [], info.text || "", info.translation || "",
    info.translation_note || "", sourcePage);
  bindEchoJumps();
}}

function selectPdfCoveredRecord(blockId, info, clickedPage) {{
  const sourcePage = Number(clickedPage || info.page || 0);
  const selectionKey = blockId + "@pdf:" + sourcePage;
  if (selectedContextBlock === selectionKey) {{ selectedContextBlock = null; deselect(); return; }}
  selected = null;
  selectedContextBlock = selectionKey;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".pdf-marker").forEach(marker => marker.classList.remove("sel"));
  document.querySelectorAll(".pdf-source-zone").forEach(zone => zone.classList.remove("selected"));
  paintZoneSelection(blockId);
  document.getElementById("detail").innerHTML = coveredDetailsHtml(
    info.covered_req_ids || [], info.text || "", info.translation || "",
    info.translation_note || "", sourcePage);
  bindEchoJumps();
}}

function selectPdfRequirementGroup(blockId, info, reqIds, clickedPage) {{
  const sourcePage = Number(clickedPage || info.page || 0);
  const selectionKey = blockId + "@pdf:" + sourcePage;
  if (selectedContextBlock === selectionKey) {{ selectedContextBlock = null; deselect(); return; }}
  selected = null;
  selectedContextBlock = selectionKey;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".pdf-marker").forEach(marker => marker.classList.remove("sel"));
  document.querySelectorAll(".pdf-source-zone").forEach(zone => zone.classList.remove("selected"));
  paintZoneSelection(blockId);
  document.getElementById("detail").innerHTML = requirementGroupDetailsHtml(
    reqIds, info.text || "", info.translation || "", info.translation_note || "", sourcePage);
  bindEchoJumps();
}}

function selectOmission(el) {{
  const row = {{
    block_id: el.getAttribute("data-block-id") || "",
    text: el.getAttribute("data-omission-text") || "",
    translation: el.getAttribute("data-omission-translation") || "",
    translation_note: el.getAttribute("data-omission-translation-note") || "",
    source_page: Number(el.getAttribute("data-page") || 0),
  }};
  selectOmissionRecord(row);
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.toggle("sel", t === el));
  const block = el.closest(".doc-block");
  if (block) {{
    block.classList.add("in-span", "evidence");
    markWholeTextNodes(block.querySelector(".text"));   // 整段=引用本体 → 黄标,块底保持蓝
  }}
}}

function sourceClassificationReason(owner, text) {{
  if (owner === "hardware") return "该段原文描述制造主体、设备、部件、阀门、电池、物理结构或其它硬件对象，当前规则只做硬件归类与原文说明，不生成软件研发指引或测试指引。";
  if (owner === "co_design") return "该段原文同时涉及硬件与软件/通信接口，当前先标为软硬件协同提示，需要在功能分析阶段结合上下文再拆分软件侧职责。";
  if (owner === "software_term") return "该段原文是软件概念或事件/状态术语定义，当前没有独立的 shall/must 行为约束，因此未生成完整研发需求；它会作为后续事件记录、状态管理或数据处理需求的术语依据。";
  return "该段原文未进入软件需求分析。";
}}

function selectSourceClassification(el) {{
  selected = null;
  selectedContextBlock = null;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".source-classification").forEach(c => c.classList.toggle("sel", c === el));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  document.querySelectorAll(".doc-block").forEach(block => block.classList.remove("in-span", "evidence"));
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  clearSourceQuoteMarks();
  const block = el.closest(".doc-block");
  if (block) block.classList.add("in-span", "evidence");
  // 引用片段黄标、上下文整块保持蓝底（真实反馈 2026-07-11）：标记按钮所在容器
  // （段落 p 或表格 td）的文本＝原文引用本体,逐文本节点包 mark 保住按钮不重建
  markWholeTextNodes(el.parentElement);
  const owner = el.getAttribute("data-source-classification") || "";
  const label = owner === "hardware" ? "硬件" : owner === "co_design" ? "软硬件协同" : owner === "software_term" ? "软件术语" : owner;
  const text = el.getAttribute("data-source-text") || "";
  const translation = el.getAttribute("data-source-translation") || "";
  const translationNote = el.getAttribute("data-source-translation-note") || "";
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card">'+
    '<div class="dd-head"><span class="dd-module">'+esc(label)+'</span><span class="badge">说明</span></div>'+
    '<div class="dd-title">为什么没有生成研发需求</div>'+
    '<div class="dd-body">'+esc(sourceClassificationReason(owner, text))+'</div>'+
    '<div class="dd-label">原文翻译</div>'+
    (translation ? '<div class="dd-body">'+esc(translation)+'</div>'
     : translationNote ? '<div class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（'+esc(translationNote)+'）</div>'
     : '<div class="dd-body dd-empty">未生成翻译（开启 LLM 后重新导出批注 HTML 可自动补齐）</div>')+
    (text ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(text)+'</div>' : '')+
    '</div>';
}}

// 跨章合并徽章（双渲染器契约字段——与 DocumentReview.vue mergeBadgeOf 同语义,契约夹具锁文案）：
// 单源不显示（置信恒 1.0 是噪声）;置信 < 0.9 提示核对（0.75=仅同 key 弱合并,最易错并）
function functionalMergeBadge(r) {{
  const count = Number(r.functional_source_count || 0);
  const method = String(r.functional_merge_method || "");
  if (!method || count < 2) return "";
  const conf = Number(r.functional_merge_confidence == null ? 1 : r.functional_merge_confidence);
  return '跨章合并 '+count+' 条（'+method+'，置信 '+conf+'）'+(conf < 0.9 ? '——建议核对合并是否恰当' : '');
}}

function functionalMembershipHtml(r) {{
  if (!r.functional_requirement_id) return "";
  const mergeBadge = functionalMergeBadge(r);
  const mergeClass = Number(r.functional_merge_confidence == null ? 1 : r.functional_merge_confidence) < 0.9 ? "dd-suspicion" : "dd-consistency";
  const behaviors = (r.functional_behaviors||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  const preconditions = (r.functional_preconditions||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  const constraints = (r.functional_data_constraints||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  const variants = (r.functional_variants||[]).map(value => '<li><strong>'+esc(value.name||"变体")+'</strong>：'+esc(value.behavior||"")+'</li>').join("");
  const conflicts = (r.functional_conflict_flags||[]).map(value => '<li>'+esc(value)+'</li>').join("");
  return '<div class="dd-section"><div class="dd-label">所属研发功能</div>'+
    '<div class="dd-body"><strong>'+esc(r.functional_title||r.functional_requirement_id)+'</strong></div>'+
    (mergeBadge ? '<div class="'+mergeClass+'">⧉ '+esc(mergeBadge)+'</div>' : '')+
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
  selectedContextBlock = null;
  document.querySelectorAll(".source-classification").forEach(c => c.classList.remove("sel"));
  document.querySelectorAll(".omission-tag").forEach(t => t.classList.remove("sel"));
  clearSourceQuoteMarks();   // 说明标记的引用黄标不跨选中残留（td 容器不在 .text 清扫范围内）
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("sel", c.getAttribute("data-req") === id));
  document.querySelectorAll(".pdf-marker").forEach(marker =>
    marker.classList.toggle("sel", marker.getAttribute("data-req") === id));
  document.querySelectorAll(".pdf-block-zone").forEach(zone => {{
    const reqs = (zone.getAttribute("data-reqs") || "").split(/\s+/).filter(Boolean);
    const echoes = (zone.getAttribute("data-echo-reqs") || "").split(/\s+/).filter(Boolean);
    const covered = (zone.getAttribute("data-covered-reqs") || "").split(/\s+/).filter(Boolean);
    const active = zone.getAttribute("data-req") === id || reqs.includes(id) ||
      echoes.includes(id) || covered.includes(id);
    zone.classList.toggle("selected", active);
    zone.setAttribute("aria-pressed", String(active));
  }});
  const r = byId[id]; if (!r) return;
  document.querySelectorAll(".req-index-item").forEach(item =>
    item.classList.toggle("active", item.getAttribute("data-req") === id));
  if (PDF_MODE) showPdfPage(r.source_page);
  const d = decisionOf(id) || {{}};
  const st = statusOf(id);
  const isHardware = isHardwareRequirement(r);
  const devSrc = r.dev_guidance||[];
  const accSrc = r.acceptance_criteria||[];
  const dev = isHardware ? "" : devSrc.map(c => "<li>" + esc(c) + "</li>").join("");
  const acc = isHardware ? "" : accSrc.map(c => "<li>" + esc(c) + "</li>").join("");
  // 归属判定挪到「原文引用」之后（真实反馈 2026-07-12）；设计候选暂不渲染（数据仍在 xlsx）
  const summaryHtml = requirementSummaryHtml(r);
  const sourceQuoteHtml = r.source_quote
    ? '<div class="dd-section"><div class="dd-label">抽取原句（对照左页）</div><div class="dd-quote">'+esc(r.source_quote)+'</div></div>'
    : '';
  const functionalHtml = isHardware ? "" : functionalMembershipHtml(r);
  const primaryHtml = summaryHtml + sourceQuoteHtml + (isHardware ? hardwareTranslationHtml(r) : functionalHtml);
  const detailHtml = isHardware ? "" : subItemsHtml(r) + thresholdHtml(r);
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
    (PDF_MODE
      ? (r.source_page ? '<div class="dd-legend">原文位置 · PDF 第 '+esc(r.source_page)+' 页</div>' : '')
      : '<div class="dd-legend">正文标记：<span style="background:#ffe89a;padding:0 4px">黄=引用依据</span> · <span style="background:#eef4ff;padding:0 4px">蓝=证据段</span> · 左侧细条=分析上下文（模型通读范围）</div>')+
    ((r.suspicion_reasons||[]).length ? '<div class="dd-suspicion">⚠ 建议优先复核：'+esc((r.suspicion_reasons||[]).join("、"))+'</div>' : '')+
    ((r.consistency_flags||[]).length ? '<div class="dd-consistency">⇄ 全文档一致性：'+esc((r.consistency_flags||[]).join("；"))+'</div>' : '')+
    primaryHtml+
    detailHtml+
    (dev ? '<div class="dd-label">研发指引 / 落地实现</div><ul class="dd-list">'+dev+'</ul>' : '')+
    (acc ? '<div class="dd-label">测试指引 / 验收</div><ul class="dd-list">'+acc+'</ul>' : '')+
    ownershipReasonHtml(r)+
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
  const pdfMarker = e.target.closest('.pdf-marker[data-req]');
  if (pdfMarker) {{ select(pdfMarker.getAttribute("data-req")); return; }}
  // 全段落热区（0714）：影印页任意段落可点——req→需求卡 / omission→遗漏卡 / context→背景卡
  const zone = e.target.closest(".pdf-block-zone");
  if (zone) {{
    const kind = zone.getAttribute("data-zone-kind");
    const bid = zone.getAttribute("data-block-id") || "";
    const page = Number(zone.getAttribute("data-page") || 0);
    const info = PDF_CONTEXT[bid];
    if (kind === "req") {{
      const reqIds = (zone.getAttribute("data-reqs") || zone.getAttribute("data-req") || "")
        .split(/\s+/).filter(Boolean);
      if (reqIds.length > 1 && info) {{ selectPdfRequirementGroup(bid, info, reqIds, page); return; }}
      select(zone.getAttribute("data-req"));
      return;
    }}
    if (kind === "omission") {{
      const row = PDF_OMISSIONS.find(r => r.block_id === bid);
      if (row) {{ selectOmissionRecord({{...row, source_page: page || row.source_page || 0}}); return; }}
    }}
    if (kind === "echo" && info) {{ selectPdfEchoRecord(bid, info, page); return; }}
    if (kind === "covered" && info) {{ selectPdfCoveredRecord(bid, info, page); return; }}
    if (info) {{ selectPdfContextRecord(bid, info, page); return; }}
    return;
  }}
  const sourceMarker = e.target.closest(".source-classification"); if (sourceMarker) {{ selectSourceClassification(sourceMarker); return; }}
  const omission = e.target.closest(".omission-tag"); if (omission) {{ selectOmission(omission); return; }}
  const echoTag = e.target.closest(".echo-tag");
  if (echoTag) {{ const block = echoTag.closest(".doc-block"); if (block) selectContextBlock(block); return; }}
  const blk = e.target.closest(".doc-block.anchored");
  if (blk) {{ const c = blk.querySelector(".chip"); if (c) select(c.getAttribute("data-req")); return; }}
  // 全文每段都有分析结果：无批注/无标记的正文段落点击 → 背景说明卡（原因/翻译/引用）
  const plain = e.target.closest(".doc-block");
  if (plain && !plain.classList.contains("heading") && !plain.classList.contains("noise")
      && !plain.classList.contains("is-table")) {{
    const om = plain.querySelector(".omission-tag"); if (om) {{ selectOmission(om); return; }}
    const marker = plain.querySelector(".source-classification"); if (marker) {{ selectSourceClassification(marker); return; }}
    const p = plain.querySelector(".text");
    if (p && p.textContent.trim()) selectContextBlock(plain);
  }}
}});

document.getElementById("export-btn").onclick = () => {{
  const decisions = Object.values(loadStore());
  const payload = {{ doc_id: DOC_ID, source: "{source}", exported_at: new Date().toISOString(), decisions: decisions }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "ai_decisions_" + DOC_ID + ".json"; a.click();
}};

const PDF_ZOOM_STEP = 100;
let pdfPageWidth = 850;
function pdfZoomMinimum() {{
  const paper = document.getElementById("paper");
  const viewportWidth = Math.max(0, window.innerWidth || document.documentElement.clientWidth || 0);
  const containerWidth = paper ? paper.getBoundingClientRect().width : viewportWidth;
  const pageChrome = viewportWidth <= 768 ? 64 : 96;
  return Math.max(240, Math.min(520, Math.floor(containerWidth - pageChrome - PDF_ZOOM_STEP)));
}}
function setPdfZoom(width) {{
  if (!PDF_OVERLAY_ENABLED) return;
  const minimum = Math.min(pdfPageWidth, pdfZoomMinimum());
  pdfPageWidth = Math.max(minimum, Math.min(1500, Number(width) || 850));
  const renderer = document.getElementById("pdf-renderer");
  if (renderer) renderer.style.setProperty("--pdf-page-width", pdfPageWidth + "px");
}}

function initializePdfOverlay() {{
  if (!PDF_OVERLAY_ENABLED) return;
  const firstPage = document.querySelector(".pdf-page");
  if (firstPage) pdfPageWidth = Math.round(firstPage.getBoundingClientRect().width) || pdfPageWidth;
  const zoomOut = document.getElementById("pdf-zoom-out");
  const zoomIn = document.getElementById("pdf-zoom-in");
  if (zoomOut) zoomOut.onclick = () => setPdfZoom(pdfPageWidth - PDF_ZOOM_STEP);
  if (zoomIn) zoomIn.onclick = () => setPdfZoom(pdfPageWidth + PDF_ZOOM_STEP);
  const paper = document.getElementById("paper");
  const status = document.getElementById("pdf-page-status");
  if (!("IntersectionObserver" in window) || !paper || !status) return;
  const visibility = new Map();
  const observer = new IntersectionObserver(entries => {{
    entries.forEach(entry => visibility.set(entry.target, entry.intersectionRatio));
    let current = null;
    let ratio = 0;
    visibility.forEach((value, page) => {{ if (value > ratio) {{ current = page; ratio = value; }} }});
    if (current) status.textContent = current.getAttribute("data-page") + " / " + PDF_PAGE_COUNT;
  }}, {{root: paper, threshold: [0, .15, .35, .6, .9]}});
  document.querySelectorAll(".pdf-page").forEach(page => observer.observe(page));
  const linkedRequirement = new URLSearchParams(window.location.search).get("req");
  if (linkedRequirement && byId[linkedRequirement]) {{
    setTimeout(() => select(linkedRequirement), 80);
    return;
  }}
  const initial = /(?:^#|&)page=(\d+)/.exec(window.location.hash || "");
  if (initial) setTimeout(() => showPdfPage(Number(initial[1])), 80);
}}

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

paintChips(); buildOutline(); refreshDecidedCount(); initializePdfOverlay();
</script>
</body>
</html>
"""
