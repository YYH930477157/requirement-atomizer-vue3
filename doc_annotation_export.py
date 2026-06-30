"""把"文档批注审核"导出成一个自包含 HTML 文件。

完全独立：文档原文 + AI 抽取需求数据直接嵌进 HTML，内联 CSS/JS，任意浏览器双击即开、
不需 app/服务器。需求像批注挂在原文对应小段上（anchor_block_id 精确锚点），点开看
模块/需求分析/测试指引/原文引用；裁决（接受/拒绝/讨论/改模块/写意见）静默存浏览器
localStorage（按 doc 命名空间隔离），一键「导出裁决 JSON」可回灌 app 合进交付物。
未覆盖的 requirement_like 段标「未覆盖」，顶部给疑似遗漏计数。

数据组装复用 api_server.build_document_blocks / build_ai_requirements（含锚点）。
"""
from __future__ import annotations

import datetime
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from api_server import build_ai_requirements, build_document_blocks

ANNOTATION_HTML = "document_annotation.html"

# 镜像 ai_extract.MODULE_VOCAB（改模块下拉用）；惰性取，避免强依赖。
def _module_vocab() -> list[str]:
    try:
        from ai_extract import MODULE_VOCAB
        return list(MODULE_VOCAB)
    except Exception:  # pragma: no cover - 兜底
        return ["其它"]


def _doc_id(out_dir: Path) -> str:
    """localStorage 命名空间：用输出目录路径指纹，确保不同文档裁决互不串。"""
    return hashlib.sha1(str(out_dir).encode("utf-8")).hexdigest()[:10]


def _covered_blocks(requirements: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for req in requirements:
        for bid in req.get("source_block_ids") or []:
            covered.add(str(bid))
    return covered


def _render_blocks(blocks: list[dict[str, Any]], anchor_map: dict[str, list[dict[str, Any]]],
                   covered: set[str]) -> str:
    parts: list[str] = []
    for b in blocks:
        bid = str(b.get("block_id") or "")
        text = str(b.get("text") or "")
        path = b.get("section_path") or []
        is_heading = b.get("type") == "heading" or (bool(path) and text == path[-1])
        is_omission = bool(b.get("requirement_like")) and not b.get("noise") and bid not in covered
        anchored = anchor_map.get(bid) or []
        cls = ["doc-block"]
        if is_heading:
            cls.append("heading")
        if is_omission:
            cls.append("omission")
        if anchored:
            cls.append("anchored")
        chips = "".join(
            f'<button class="chip" data-req="{html.escape(str(r["ai_req_id"]))}" '
            f'title="{html.escape(str(r.get("module_effective") or ""))} · {html.escape(str(r.get("title") or ""))}">'
            f'💬 {html.escape(str(r.get("module_effective") or "需求"))}</button>'
            for r in anchored
        )
        omission_tag = '<span class="omission-tag">⚠ 未覆盖</span>' if is_omission else ""
        parts.append(
            f'<div class="{" ".join(cls)}" data-block-id="{html.escape(bid)}">'
            f'<div class="gutter">{chips}{omission_tag}</div>'
            f'<p class="text" data-block-id="{html.escape(bid)}">{html.escape(text)}</p></div>'
        )
    return "\n".join(parts)


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
    # 嵌入 JS 的数据：防 </script> 截断
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
    out_dir = Path(out_dir).expanduser().resolve()
    target = out_dir / ANNOTATION_HTML
    target.write_text(render_annotation_html(out_dir), encoding="utf-8")
    return target


_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>文档批注审核 · {source}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; color: #334155; background: #f1f5f9; }}
.topbar {{ position: sticky; top: 0; z-index: 5; display: flex; justify-content: space-between; align-items: center;
  padding: 10px 18px; background: #0f172a; color: #e2e8f0; }}
.topbar .stats {{ display: flex; gap: 18px; font-size: 13px; }}
.topbar strong {{ color: #fff; }}
.topbar .warn strong {{ color: #fbbf24; }}
.topbar button {{ background: #2563eb; color: #fff; border: 0; border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 13px; }}
.topbar button:hover {{ background: #1d4ed8; }}
.layout {{ display: grid; grid-template-columns: 1fr 380px; gap: 0; height: calc(100vh - 52px); }}
.paper {{ overflow: auto; padding: 22px 26px; background: #fff; }}
.doc-block {{ display: grid; grid-template-columns: 150px 1fr; gap: 12px; padding: 3px 6px; border-left: 3px solid transparent; transition: background .15s; }}
.doc-block.anchored {{ cursor: pointer; border-left-color: #3b82f6; }}
.doc-block.anchored:hover {{ background: #f8fafc; }}
.doc-block.in-span {{ background: #eff6ff; }}
.doc-block.omission {{ border-left: 3px dashed #f59e0b; }}
.doc-block.heading .text {{ font-weight: 700; color: #0f172a; margin-top: 10px; }}
.gutter {{ display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }}
.text {{ margin: 0; font-size: 13.5px; line-height: 1.6; white-space: pre-wrap; }}
.text mark {{ background: #fde68a; padding: 0 1px; border-radius: 2px; }}
.chip {{ font-size: 11px; border: 1px solid #cbd5e1; border-radius: 11px; padding: 2px 9px; background: #fff; cursor: pointer;
  max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; transition: transform .12s, box-shadow .12s; }}
.chip:hover {{ transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,.12); }}
.chip.sel {{ outline: 2px solid #3b82f6; }}
.chip.st-accepted {{ border-color: #16a34a; color: #16a34a; }}
.chip.st-rejected {{ border-color: #dc2626; color: #dc2626; }}
.chip.st-needs_discussion {{ border-color: #d97706; color: #d97706; }}
.omission-tag {{ font-size: 10px; color: #b45309; }}
.detail {{ border-left: 1px solid #e2e8f0; overflow: auto; padding: 16px; background: #fafafa; }}
.detail .empty {{ color: #94a3b8; text-align: center; padding-top: 48px; font-size: 13px; }}
.dd-head {{ display: flex; justify-content: space-between; align-items: center; }}
.dd-module {{ font-weight: 700; color: #1d4ed8; }}
.badge {{ font-size: 12px; padding: 2px 9px; border-radius: 9px; background: #e2e8f0; }}
.badge.st-accepted {{ background: #dcfce7; color: #166534; }}
.badge.st-rejected {{ background: #fee2e2; color: #991b1b; }}
.badge.st-needs_discussion {{ background: #fef3c7; color: #92400e; }}
.dd-title {{ margin: 10px 0 2px; font-size: 15px; color: #0f172a; }}
.dd-meta {{ font-size: 12px; color: #64748b; margin-bottom: 8px; }}
.dd-label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; margin: 12px 0 3px; }}
.dd-body {{ font-size: 13px; line-height: 1.6; }}
.dd-list {{ margin: 0; padding-left: 18px; font-size: 13px; }}
.dd-quote {{ font-size: 12px; color: #475569; border-left: 3px solid #cbd5e1; padding-left: 8px; font-style: italic; }}
select, textarea {{ width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; font-size: 13px; font-family: inherit; }}
textarea {{ min-height: 56px; margin-top: 8px; resize: vertical; }}
.actions {{ display: flex; gap: 8px; margin-top: 10px; }}
.actions button {{ flex: 1; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 0; background: #fff; cursor: pointer; font-size: 13px; }}
.actions .accept {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
.saved-hint {{ font-size: 11px; color: #16a34a; margin-top: 6px; min-height: 14px; }}
</style>
</head>
<body>
<div class="topbar">
  <div class="stats">
    <span>文档 <strong>{source}</strong></span>
    <span>需求 <strong>{req_count}</strong></span>
    <span class="warn">疑似遗漏 <strong>{omission_count}</strong></span>
    <span>已裁决 <strong id="decided-count">0</strong></span>
  </div>
  <div>
    <button id="export-btn">导出裁决 JSON</button>
  </div>
</div>
<div class="layout">
  <article class="paper" id="paper">
{blocks_html}
  </article>
  <aside class="detail" id="detail"><div class="empty">点左侧 💬 批注查看需求详情</div></aside>
</div>
<script>
const DOC_ID = "{doc_id}";
const STORAGE_KEY = "ratomizer-decisions:" + DOC_ID;
const REQUIREMENTS = {requirements_json};
const MODULE_VOCAB = {module_vocab_json};
const GENERATED_AT = "{generated_at}";
const byId = {{}}; REQUIREMENTS.forEach(r => byId[r.ai_req_id] = r);
const STATUS_LABELS = {{ draft:"待审", accepted:"已接受", rejected:"已拒绝", needs_discussion:"待讨论", expert_pending:"专家待定" }};

function loadStore() {{ try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); }} catch (e) {{ return {{}}; }} }}
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

let selected = null;
function highlightQuote() {{
  document.querySelectorAll(".text mark").forEach(m => {{ m.outerHTML = esc(m.textContent); }});
  const r = selected && byId[selected];
  if (!r || !r.source_quote) return;
  const anchor = r.anchor_block_id || (r.source_block_ids||[])[0];
  const p = document.querySelector('.text[data-block-id="' + anchor + '"]');
  if (!p) return;
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
    '<div class="dd-head"><span class="dd-module">'+esc(moduleOf(r))+'</span>'+
    '<span class="badge st-'+st+'">'+esc(STATUS_LABELS[st]||st)+'</span></div>'+
    '<h3 class="dd-title">'+esc(r.title)+'</h3>'+
    '<div class="dd-meta">'+esc(r.type)+' · '+esc(r.priority)+' · '+esc(r.source_section)+'</div>'+
    '<div class="dd-label">需求分析</div><div class="dd-body">'+esc(r.description)+'</div>'+
    (acc ? '<div class="dd-label">测试指引 / 验收</div><ul class="dd-list">'+acc+'</ul>' : '')+
    (r.source_quote ? '<div class="dd-label">原文引用</div><div class="dd-quote">'+esc(r.source_quote)+'</div>' : '')+
    '<div class="dd-label">模块（可改）</div><select id="mod-sel">'+opts+'</select>'+
    '<textarea id="cmt" placeholder="审查意见（可选）">'+esc(d.reason||"")+'</textarea>'+
    '<div class="actions"><button class="accept" data-st="accepted">接受</button>'+
    '<button data-st="rejected">拒绝</button><button data-st="needs_discussion">讨论</button></div>'+
    '<div class="saved-hint" id="hint"></div>';
  document.querySelectorAll(".actions button").forEach(b => b.onclick = () => decide(id, b.getAttribute("data-st")));
  document.querySelectorAll('.doc-block').forEach(el => el.classList.remove("in-span"));
  (r.source_block_ids||[]).forEach(bid => {{ const el = document.querySelector('.doc-block[data-block-id="'+bid+'"]'); if (el) el.classList.add("in-span"); }});
  highlightQuote();
}}

function decide(id, status) {{
  const store = loadStore();
  store[id] = {{ ai_req_id: id, status: status,
    module_override: document.getElementById("mod-sel").value !== (byId[id].module_effective||byId[id].module||"") ? document.getElementById("mod-sel").value : "",
    reason: document.getElementById("cmt").value, ts: GENERATED_AT }};
  saveStore(store);
  paintChips();
  const h = document.getElementById("hint"); if (h) h.textContent = "已" + (STATUS_LABELS[status]||status) + "（本地已存）";
  const r = byId[id]; if (r) {{ const badge = document.querySelector(".badge"); if (badge) {{ badge.className = "badge st-"+status; badge.textContent = STATUS_LABELS[status]||status; }} }}
}}

document.getElementById("paper").addEventListener("click", e => {{
  const chip = e.target.closest(".chip"); if (chip) {{ select(chip.getAttribute("data-req")); return; }}
  const blk = e.target.closest(".doc-block.anchored");
  if (blk) {{ const c = blk.querySelector(".chip"); if (c) select(c.getAttribute("data-req")); }}
}});

document.getElementById("export-btn").onclick = () => {{
  const store = loadStore();
  const decisions = Object.values(store);
  const payload = {{ doc_id: DOC_ID, source: "{source}", exported_at: new Date().toISOString(), decisions: decisions }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "ai_decisions_" + DOC_ID + ".json";
  a.click();
}};

paintChips();
refreshDecidedCount();
</script>
</body>
</html>
"""
