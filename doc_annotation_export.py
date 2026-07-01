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
                   covered: set[str]) -> str:
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

    for b in blocks:
        bid = str(b.get("block_id") or "")
        text = str(b.get("text") or "")
        # 清洁 + 跳过纯符号乱码
        text = _clean_block_text(text)
        if _is_symbol_only(text):
            continue
        path = b.get("section_path") or []
        region = str(b.get("doc_region") or "body")
        is_heading = b.get("type") == "heading" or (bool(path) and text == str(path[-1]))
        is_noise = bool(b.get("noise"))
        is_omission = bool(b.get("requirement_like")) and not is_noise and bid not in covered
        anchored = anchor_map.get(bid) or []

        # 渲染单个 block 的 HTML
        block_html = _render_one_block(bid, text, path, region, is_heading, is_noise, is_omission, anchored)

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


def _render_one_block(bid: str, text: str, path: list, region: str,
                      is_heading: bool, is_noise: bool, is_omission: bool,
                      anchored: list) -> str:
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
    depth = min(len(path), 4) if path else 0

    chips = "".join(
        f'<button class="chip annotation-index" data-req="{html.escape(str(r["ai_req_id"]))}" '
        f'title="{html.escape(str(r.get("module_effective") or ""))} · {html.escape(str(r.get("title") or ""))}" '
        f'aria-label="{html.escape(str(r.get("title") or "需求批注"))}">'
        f'<span class="annotation-dot"></span><span class="annotation-number">{i:02d}</span></button>'
        for i, r in enumerate(anchored, start=1)
    )
    omission_tag = '<span class="omission-tag">未覆盖</span>' if is_omission else ""
    return (
        f'<div class="{" ".join(cls)}" data-block-id="{html.escape(bid)}" style="--depth:{depth}">'
        f'<div class="block-inner">'
        f'<div class="chips">{chips}{omission_tag}</div>'
        f'<p class="text" data-block-id="{html.escape(bid)}">{html.escape(text)}</p>'
        f'</div></div>'
    )


def render_annotation_html(out_dir: Path) -> str:
    out_dir = Path(out_dir).expanduser().resolve()
    doc = build_document_blocks(out_dir)
    blocks = doc.get("blocks") or []
    requirements = build_ai_requirements(out_dir)
    covered = _covered_blocks(requirements)

    anchor_map: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        anchor = str(req.get("anchor_block_id") or (req.get("source_block_ids") or [""])[0] or "")
        if anchor:
            anchor_map.setdefault(anchor, []).append(req)

    omissions = sum(
        1 for b in blocks
        if b.get("requirement_like") and not b.get("noise") and str(b.get("block_id")) not in covered
    )
    blocks_html = _render_blocks(blocks, anchor_map, covered)
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
  --page: #f5f2ec;
  --paper: #fffdf8;
  --panel: #fbfaf6;
  --line: #e7dfd2;
  --line-strong: #d8cebd;
  --ink: #24282f;
  --muted: #858a92;
  --faint: #b4aaa0;
  --accent: #315f72;
  --accent-soft: #e8f0f1;
  --accent-quiet: #6e8791;
  --st-accepted: #e6f0e8; --st-accepted-tx: #2f6842;
  --st-rejected: #f4e7e3; --st-rejected-tx: #9b3b32;
  --st-discussion: #f6efd8; --st-discussion-tx: #8a6417;
  --omission-bg: #f8efd9;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
  color: var(--ink); background: var(--page); font-size: 15px; line-height: 1.76; }}
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
.topbar button {{ background: transparent; color: var(--accent); border: 1px solid var(--line-strong); border-radius: 999px;
  padding: 7px 14px; cursor: pointer; font-size: 12px; font-weight: 600; }}
.topbar button:hover {{ background: var(--accent-soft); border-color: var(--accent-quiet); }}

/* --- 三栏布局 --- */
.layout {{ display: grid; grid-template-columns: 240px minmax(0, 1fr) 390px; height: calc(100vh - 56px); }}

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
.doc-content {{ max-width: 760px; margin: 0 auto; padding: 48px 58px 70px; background: var(--paper);
  border: 1px solid rgba(231,223,210,.72); box-shadow: 0 24px 80px rgba(44,39,31,.08); }}

.doc-block {{ margin-bottom: 5px; }}
.block-inner {{ position: relative; padding-left: calc(var(--depth, 0) * 16px); }}
.doc-block .text {{ margin: 0; padding: 2px 0; }}
.doc-block.heading .text {{ font-weight: 600; margin-top: 20px; }}
.doc-block.h1 .text {{ font-size: 22px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }}
.doc-block.h2 .text {{ font-size: 18px; }}
.doc-block.h2 .block-inner {{ border-left: 2px solid var(--accent-quiet); padding-left: 12px; margin-left: -14px; }}
.doc-block.h3 .text {{ font-size: 16px; color: #515761; }}
.doc-block.noise .text {{ opacity: 0.3; font-size: 13px; }}
.doc-block.omission {{ background: linear-gradient(90deg, var(--omission-bg), rgba(248,239,217,.35)); border-radius: 4px; padding: 4px 8px; margin: 5px 0; }}
.doc-block.omission .text {{ border-left: 2px solid #cda85c; padding-left: 9px; }}
.doc-block.anchored {{ cursor: pointer; border-radius: 4px; }}
.doc-block.anchored:hover {{ background: var(--accent-soft); }}
.doc-block.in-span {{ background: var(--accent-soft); border-radius: 4px; }}
.text mark {{ background: #ffe89a; padding: 0 2px; border-radius: 2px; }}

/* chips（inline 段末，Notion 式小标签） */
.chips {{ display: inline-flex; gap: 5px; flex-wrap: wrap; margin: 0 0 0 -34px; vertical-align: middle;
  min-width: 28px; float: left; }}
.chip {{ display: inline-flex; align-items: center; justify-content: center; gap: 5px; font-size: 10px;
  border: 0; border-left: 1px solid var(--line-strong); border-radius: 0; padding: 0 0 0 7px;
  background: transparent; cursor: pointer; color: var(--accent-quiet); height: 20px; transition: color .12s, border-color .12s; }}
.annotation-dot {{ width: 4px; height: 4px; border-radius: 50%; background: currentColor; opacity: .68; }}
.annotation-number {{ font-variant-numeric: tabular-nums; letter-spacing: .04em; }}
.chip:hover {{ color: var(--accent); border-color: var(--accent); }}
.chip.sel {{ color: var(--accent); border-color: var(--accent); font-weight: 700; }}
.chip.st-accepted {{ color: var(--st-accepted-tx); }}
.chip.st-rejected {{ color: var(--st-rejected-tx); }}
.chip.st-needs_discussion {{ color: var(--st-discussion-tx); }}
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
<div class="reader-layout layout">
  <nav class="outline" id="outline"><div class="outline-title">大纲</div></nav>
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
  const headings = Array.from(document.querySelectorAll(".doc-block.heading"));
  if (headings.length === 0) {{ nav.style.display = "none"; return; }}

  const frag = document.createDocumentFragment();
  let currentH1 = null;     // 当前 h1 组的 children 容器
  let currentH1Item = null; // 当前 h1 的 nav-item（用于 h2 归属）

  headings.forEach(h => {{
    const level = h.classList.contains("h1") ? 1 : h.classList.contains("h3") ? 3 : 2;
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
function highlightQuote() {{
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  const r = selected && byId[selected]; if (!r || !r.source_quote) return;
  const anchor = r.anchor_block_id || (r.source_block_ids||[])[0];
  const p = document.querySelector('.text[data-block-id="' + anchor + '"]'); if (!p) return;
  const t = p.textContent, q = r.source_quote, i = t.indexOf(q);
  if (i >= 0) p.innerHTML = esc(t.slice(0,i)) + "<mark>" + esc(q) + "</mark>" + esc(t.slice(i+q.length));
}}

function select(id) {{
  selected = id;
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("sel", c.getAttribute("data-req") === id));
  const r = byId[id]; if (!r) return;
  const d = decisionOf(id) || {{}};
  const st = statusOf(id);
  const acc = (r.acceptance_criteria||[]).map(c => "<li>" + esc(c) + "</li>").join("");
  const opts = MODULE_VOCAB.map(m => '<option value="'+esc(m)+'"'+(m===moduleOf(r)?' selected':'')+'>'+esc(m)+'</option>').join("");
  document.getElementById("detail").innerHTML =
    '<div class="annotation-card detail-card"><div class="dd-head"><span class="dd-module">'+esc(moduleOf(r))+'</span>'+
    '<span class="badge st-'+st+'">'+esc(STATUS_LABELS[st]||st)+'</span></div>'+
    '<div class="dd-title">'+esc(r.title)+'</div>'+
    '<div class="dd-meta">'+esc(r.type)+' · '+esc(r.priority)+' · '+esc(r.source_section)+'</div>'+
    '<div class="dd-label">需求分析</div><div class="dd-body">'+esc(r.description)+'</div>'+
    (acc ? '<div class="dd-label">测试指引 / 验收</div><ul class="dd-list">'+acc+'</ul>' : '')+
    (r.source_quote ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(r.source_quote)+'</div>' : '')+
    '<div class="dd-label">模块（可改）</div><select id="mod-sel">'+opts+'</select>'+
    '<textarea id="cmt" placeholder="审查意见（可选）">'+esc(d.reason||"")+'</textarea>'+
    '<div class="actions"><button class="accept" data-st="accepted">接受</button>'+
    '<button data-st="rejected">拒绝</button><button data-st="needs_discussion">讨论</button></div>'+
    '<div class="saved-hint" id="hint"></div></div>';
  document.querySelectorAll(".actions button").forEach(b => b.onclick = () => decide(id, b.getAttribute("data-st")));
  document.querySelectorAll(".doc-block").forEach(el => el.classList.remove("in-span"));
  (r.source_block_ids||[]).forEach(bid => {{ const el = document.querySelector('.doc-block[data-block-id="'+bid+'"]'); if (el) el.classList.add("in-span"); }});
  highlightQuote();
}}

function decide(id, status) {{
  const store = loadStore();
  store[id] = {{ ai_req_id: id, status: status,
    module_override: document.getElementById("mod-sel").value !== (byId[id].module_effective||byId[id].module||"") ? document.getElementById("mod-sel").value : "",
    reason: document.getElementById("cmt").value, ts: GENERATED_AT }};
  saveStore(store); paintChips();
  const h = document.getElementById("hint"); if (h) h.textContent = "已" + (STATUS_LABELS[status]||status) + "（本地已存）";
  const badge = document.querySelector(".badge"); if (badge) {{ badge.className = "badge st-"+status; badge.textContent = STATUS_LABELS[status]||status; }}
}}

document.getElementById("paper").addEventListener("click", e => {{
  const chip = e.target.closest(".chip"); if (chip) {{ select(chip.getAttribute("data-req")); return; }}
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

paintChips(); buildOutline(); refreshDecidedCount();
</script>
</body>
</html>
"""
