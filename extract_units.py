"""抽取单元层（F3 拆分自 ai_extract）：块→章节→LLM 输入单元的全部确定性机器。

职责：TOC 行清洗、章节聚合、条款族/整章切分、试抽采样、跨条款/附录引用解析、
术语条目收集与定向挂载。零 LLM、零外部状态——独立可测。
"""
from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

DEFAULT_MERGE_CHARS = 2800

_TOC_LINE_END_RE = re.compile(r"\.{5,}[\s\d]*$")


_TOC_LEADER_RUN_RE = re.compile(r"\.{5,}")


def _is_toc_line(line: str) -> bool:
    if _TOC_LINE_END_RE.search(line):
        return True
    return len(_TOC_LEADER_RUN_RE.findall(line)) >= 3


def clean_block_text(block: dict[str, Any]) -> str:
    """block 文本去目录点线行；清完为空 = 纯目录块，各消费处按无内容处理。"""
    text = str(block.get("text") or "")
    lines = [line for line in text.splitlines() if not _is_toc_line(line)]
    return "\n".join(lines).strip()


def assemble_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把已解析 blocks 按 section_path 聚合成章节单元（章节文本 + 溯源 block）。"""
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for block in blocks:
        section_path = [str(s) for s in (block.get("section_path") or [])]
        key = " / ".join(section_path) or "(root)"
        unit = groups.get(key)
        if unit is None:
            unit = {"section_id": key, "section_path": section_path,
                    "heading": section_path[-1] if section_path else "",
                    "texts": [], "block_ids": []}
            groups[key] = unit
        text = clean_block_text(block)
        if text:
            unit["texts"].append(text)
        if block.get("block_id"):
            unit["block_ids"].append(block["block_id"])
            unit.setdefault("source_blocks", []).append({"block_id": block["block_id"], "text": text})

    sections: list[dict[str, Any]] = []
    for unit in groups.values():
        body = "\n".join(unit["texts"]).strip()
        if not body:
            continue
        sections.append({"section_id": unit["section_id"], "section_path": unit["section_path"],
                         "heading": unit["heading"], "text": body, "block_ids": unit["block_ids"],
                         "source_blocks": unit.get("source_blocks", [])})
    return sections


def clause_key(section: dict[str, Any]) -> str | None:
    """两级条款族键：4.6.1 Requirements / 4.6.2 Test → "4.6"；4.15 → "4.15"；无编号 → None。

    标准文档的天然语义单元是条款族——X.Y 是一个需求整体，X.Y.1 是要求、X.Y.2 是对应测试
    （a↔a、b↔b 对应）。按字数贪心切分会把要求和测试拆进不同 LLM 单元（真实反馈："分段乱乱的"）。
    """
    m = re.match(r"^(\d+(?:\.\d+)*)", str(section.get("heading") or section.get("section_id") or "").strip())
    if not m:
        return None
    parts = m.group(1).split(".")
    return ".".join(parts[:2])


CLAUSE_FAMILY_MAX_FACTOR = 2


UNIT_MODE_ENV = "RATOMIZER_AI_UNIT_MODE"   # clause(默认) | chapter


CHAPTER_MAX_CHARS = 24000


CHAPTER_MIN_MAX_TOKENS = 16384  # 整章几十条需求的 JSON 输出预算（推理模型思维链之外）


def merge_sections(sections: list[dict[str, Any]], *, target_chars: int = DEFAULT_MERGE_CHARS,
                   unit_mode: str = "clause") -> list[dict[str, Any]]:
    """章节 → LLM 输入单元：**先按条款族分组（语义边界），族内再按字数规整（经济边界）**。

    同族（如 4.6.1/4.6.2）保持同单元、上限放宽到 2×target；**不同条款族绝不合并**——此前的
    纯字数贪心会把 4.5 尾巴和 4.6 开头拼在一起（真实反馈"分段乱乱的"的根源）。无编号章节沿用
    旧贪心合并（向后兼容散文/标题乱码文档）。
    """
    chapter_mode = unit_mode == "chapter"
    groups: list[tuple[str | None, list[dict[str, Any]]]] = []
    for sec in sections:
        key = clause_key(sec)
        if chapter_mode and key is not None:
            key = key.split(".")[0]   # 整章：4.14.1 → "4"（同章条款全部同单元）
        if groups and groups[-1][0] == key and key is not None:
            groups[-1][1].append(sec)      # 同条款族 → 同组
        elif groups and groups[-1][0] is None and key is None:
            groups[-1][1].append(sec)      # 连续无编号 → 同组（旧贪心处理）
        else:
            groups.append((key, [sec]))

    units: list[dict[str, Any]] = []
    for key, group in groups:
        if chapter_mode:
            limit = CHAPTER_MAX_CHARS if key is not None else target_chars
            split = CHAPTER_MAX_CHARS if key is not None else target_chars
        else:
            limit = target_chars * CLAUSE_FAMILY_MAX_FACTOR if key is not None else target_chars
            split = target_chars
        units.extend(_pack_sections(group, target_chars=limit, split_chars=split))
    return units


def _pack_sections(sections: list[dict[str, Any]], *, target_chars: int,
                   split_chars: int) -> list[dict[str, Any]]:
    """组内按字数规整（原贪心逻辑）：小节拼接 ≤target；超大单节按 split_chars 拆。"""
    merged: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and cur["texts"]:
            merged.append(_finalize_merged(cur))
        cur = None

    for sec in sections:
        piece = f"## {sec['heading']}\n{sec['text']}" if sec.get("heading") else sec["text"]
        block_ids = list(sec.get("block_ids") or [])
        source_blocks = list(sec.get("source_blocks") or [])
        if len(piece) > target_chars:
            # 超大源章节：拆成 ≤split 的多块，各自独立成段（同段 block_ids 全量保留以便溯源）。
            # drift_source 保留完整原文：漂移护栏须以整章为 baseline，否则 LLM 合理引用同章
            # 其它片段里的 OBIS/事件码会被误判为"原文未见的结构漂移"（假阳性误伤）。
            flush()
            for chunk in _split_text(piece, split_chars):
                merged.append(_finalize_merged({
                    "section_id": sec["section_id"], "heading": sec.get("heading", ""),
                    "texts": [chunk], "block_ids": block_ids, "source_blocks": source_blocks,
                    "drift_source": piece}))
            continue
        if cur is None:
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": block_ids, "source_blocks": source_blocks, "len": len(piece)}
        elif cur["len"] + len(piece) > target_chars and cur["texts"]:
            flush()
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": block_ids, "source_blocks": source_blocks, "len": len(piece)}
        else:
            cur["texts"].append(piece)
            cur["block_ids"].extend(block_ids)
            cur.setdefault("source_blocks", []).extend(source_blocks)
            cur["len"] += len(piece)
    flush()
    return merged


def _finalize_merged(cur: dict[str, Any]) -> dict[str, Any]:
    text = "\n\n".join(cur["texts"]).strip()
    # 漂移护栏 baseline：拆分片段用整章原文，其余默认用自身文本（无跨片段码）
    drift_source = cur.get("drift_source") or text
    return {"section_id": cur["section_id"], "heading": cur["heading"],
            "section_path": [cur["heading"]] if cur["heading"] else [],
            "text": text, "block_ids": cur["block_ids"], "source_blocks": cur.get("source_blocks", []),
            "drift_source": drift_source}


def _split_text(text: str, target_chars: int) -> list[str]:
    """把超长文本按行贪心切成 ≤target 的块；单行超长则硬切。保证每次 LLM 输入有界。"""
    if len(text) <= target_chars:
        return [text]
    units: list[str] = []
    for line in text.split("\n"):
        if len(line) <= target_chars:
            units.append(line)
        else:  # 单行超长（如无换行的长表格）：硬切
            units.extend(line[i:i + target_chars] for i in range(0, len(line), target_chars))
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for unit in units:
        add = len(unit) + 1
        if cur and cur_len + add > target_chars:
            chunks.append("\n".join(cur))
            cur, cur_len = [unit], add
        else:
            cur.append(unit)
            cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c.strip()]


def sample_sections(sections: list[dict[str, Any]], limit: int | None) -> tuple[list[dict[str, Any]], bool]:
    """试抽样本：均匀取 N 章（确定性步长，非"前 N 章"——文档开头是范围/术语，需求密度最低，
    前 N 章会给出误导性的质量样本）。缓存指纹按章节内容算，样本章节的缓存全量跑时原样复用。"""
    if not limit or limit <= 0 or limit >= len(sections):
        return sections, False
    stride = len(sections) / limit
    picked = [sections[min(int(i * stride), len(sections) - 1)] for i in range(limit)]
    return picked, True


_CLAUSE_REF_RE = re.compile(
    r"\b(?:given in|specified in|according to|defined in|listed in|in accordance with|see)\s+"
    r"(Annex\s+[A-Z]\b|[A-Z]\.\d+(?:\.\d+)*\b|\d+(?:\.\d+){1,5})", re.IGNORECASE)


_CLAUSE_HEADING_RE = re.compile(r"(?m)^(?:Annex\s+([A-Z])\b|([A-Z]\.\d+(?:\.\d+)*)\b|(\d+(?:\.\d+){1,5})\b)")


MAX_REFS_PER_SECTION = 2      # 控 token 成本


REF_EXCERPT_CHARS = 1200


def _normalize_clause_ref(raw: str) -> str:
    """引用 token 归一：\"Annex A\"→\"A\"（与标题索引键一致）；其余原样。"""
    token = raw.strip()
    if token.lower().startswith("annex"):
        return token.split()[-1].upper()
    return token


def resolve_section_refs(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """就地给含内部引用的 section 挂 ref_texts + drift_source。必须对**全文**单元表跑
    （试抽采样前），被引条款可能在未被抽样的单元里。确定性、零 LLM。

    覆盖数字条款与**附录**（EN 系标准的测试程序全在 Annex——\"see A.1.4.6\"/\"in accordance
    with Annex A\" 此前是瞎的，真实反馈）。"""
    clause_pos: dict[str, tuple[int, int]] = {}
    for idx, s in enumerate(sections):
        for m in _CLAUSE_HEADING_RE.finditer(s["text"]):
            key = m.group(1) or m.group(2) or m.group(3)
            clause_pos.setdefault(key, (idx, m.start()))
    for idx, s in enumerate(sections):
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        for m in _CLAUSE_REF_RE.finditer(s["text"]):
            clause = _normalize_clause_ref(m.group(1))
            if clause in seen:
                continue
            seen.add(clause)
            target = clause_pos.get(clause)
            if not target or target[0] == idx:   # 找不到 or 就在本单元 → 无需注入
                continue
            t_idx, start = target
            refs.append({"clause": clause,
                         "text": sections[t_idx]["text"][start:start + REF_EXCERPT_CHARS]})
            if len(refs) >= MAX_REFS_PER_SECTION:
                break
        if refs:
            s["ref_texts"] = refs
            s["drift_source"] = s["text"] + "\n" + "\n".join(r["text"] for r in refs)
    return sections


TERM_DEFS_MAX = 4


TERM_DEF_CHARS = 240


_TERM_NAME_RE = re.compile(r"^\d+(?:\.\d+)*\s+(.{4,60}?)\s*$")


def collect_term_entries(sections: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """从术语小节收集 (术语名, 定义文本)。术语名取子节标题去编号；名太短/太泛的丢弃。"""
    entries: list[tuple[str, str]] = []
    for s in sections:
        path = " / ".join([str(x) for x in (s.get("section_path") or [])] + [str(s.get("heading") or "")])
        if not _TERMS_HEADING_RE.search(path):
            continue
        heading = str(s.get("heading") or "").strip()
        m = _TERM_NAME_RE.match(heading)
        if not m:
            continue
        term = m.group(1).strip()
        if len(term) < 8 and " " not in term:
            continue   # 单个短词（如 "AFD"）在正文中到处出现，注入价值低且刷屏
        if _TERMS_HEADING_RE.search(term):
            continue   # 术语章自身的结构标题（"Terms and definitions"/"Abbreviated terms"）
                       # 不是术语——真实产物里混进对照表浪费槽位（v11 实检）
        entries.append((term, s.get("text", "")[:TERM_DEF_CHARS]))
    return entries


def attach_term_definitions(sections: list[dict[str, Any]],
                            entries: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """就地给正文单元挂 term_defs（本单元用到的术语定义）。定义并入漂移基线（定义里的
    数字=有据）。与 ref_texts 同折进缓存指纹。"""
    if not entries:
        return sections
    lowered = [(term, term.casefold(), text) for term, text in entries]
    for s in sections:
        path = " / ".join(str(x) for x in (s.get("section_path") or []))
        if _TERMS_HEADING_RE.search(path):
            continue   # 术语小节自身不注入
        body = s.get("text", "").casefold()
        hits = [{"term": term, "text": text}
                for term, low, text in lowered if low in body][:TERM_DEFS_MAX]
        if hits:
            s["term_defs"] = hits
            s["drift_source"] = (s.get("drift_source") or s["text"]) + "\n" + \
                "\n".join(h["text"] for h in hits)
    return sections


_TERMS_HEADING_RE = re.compile(r"term|definition|abbreviat|glossary|术语|定义|符号", re.IGNORECASE)


