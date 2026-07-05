"""AI 主导需求抽取（杠杆②）。

LLM 逐章节读已解析文本 → 直接产出功能级结构化需求（标题/自包含描述/类型/优先级/标签/
原文引用/验收）。面向"通用文档解读"：DLMS 结构化与通用标准文档统一一套流程。

防幻觉（数字双引擎，分严/松级）：
- 受保护编码（OBIS / 事件号 / 十六进制，extract_codes）只能来自源文/确定性层。LLM 输出里
  冒出原文没有的这类编码 → **严格拦**：该条降级 draft + 记 note，不当已确认。
- 普通整数（extract_ints）漂移 → **软标**：可能是 LLM 合理展开（如"RS-485"），记 note 待核，保留。

可复现（稳定）：温度 0 + 章节内容指纹缓存（同文本 + 同模型 → 命中、零再调，重跑逐字一致）。
成本：相邻小章节合并到目标字数再调（少调用）+ 并发；失败按章节降级、不崩。

route（复用 review_pipeline.yaml）：默认 stub（零 LLM）；openai_compatible 才真调
（DeepSeek / Ollama 等，OpenAI 兼容）。

用法：python -m ai_extract --out <atomizer 输出目录> [--route openai_compatible] [--doc]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from cosem_behavior_spec import extract_codes, extract_ints
from llm_client import LLMClientConfig, LLMError, chat_json
from llm_pipeline import (
    DEFAULT_PIPELINE_PATH,
    apply_llm_environment_overrides,
    llm_config_from_route,
    load_review_pipeline,
    read_jsonl,
    resolve_route_name,
)
from spec_excel import METERING_DOMAINS  # 受控模块词表（DLMS 域 + 通用补充）

OTHER_MODULE = "其它"  # LLM 判定"无贴切模块"的逃生项（与 spec_export.OTHER_DOMAIN 对齐）
MODULE_VOCAB = list(METERING_DOMAINS) + [OTHER_MODULE]

LOGGER = logging.getLogger("requirement_atomizer")

AI_EXTRACT_PROMPT_VERSION = "ai-extract-v10"  # v10：自检对齐条款族（结构摘要+子项覆盖记账+包含去重），防拆碎（缓存失效重抽）
SELF_CHECK_ENV = "RATOMIZER_AI_SELFCHECK"  # 完整性自检开关（默认开；=0/false/off 关）
SELF_CHECK_ROUNDS_ENV = "RATOMIZER_AI_SELFCHECK_ROUNDS"  # 自检收敛轮数上限（默认 3，防发散）
DEFAULT_SELF_CHECK_MAX_ROUNDS = 3
MAX_SELF_CHECK_ROUNDS = 6  # 硬上限：再多也几乎无新增，纯烧 token
DOC_CONTEXT_GLOSSARY_MAX = 1800   # 术语表注入上限（控 token 成本）
DOC_CONTEXT_OUTLINE_MAX = 60      # 章节大纲最多条目
_TERMS_HEADING_RE = re.compile(r"term|definition|abbreviat|glossary|术语|定义|符号", re.IGNORECASE)
AI_EXTRACT_CACHE = "ai_extract_cache.jsonl"
AI_REQUIREMENTS = "ai_requirements.jsonl"
DEFAULT_MERGE_CHARS = 2800
DEFAULT_CONCURRENCY = 4
MAX_CONCURRENCY = 16
CONCURRENCY_ENV = "RATOMIZER_LLM_CONCURRENCY"
# 推理模型（如 deepseek-v4-flash / GLM-5.2）会先花大量 token 在隐藏 reasoning 上，
# max_tokens 太小会把正文 JSON 截断 → finish_reason=length → 解析失败 → 整章节判失败。
# 实测 deepseek-v4-flash：1024 必截断；2800 字章节正文最高用到 ~3500 token，6144 留足余量。
# 注意：仅抬 max_tokens 不够——超大源章节（5k-9k 字）即便 8192 也会截断，必须配合 merge_sections
# 的拆分（每次 LLM 输入 ≤target_chars），二者缺一不可。
AI_EXTRACT_MIN_MAX_TOKENS = 6144

ChatFn = Callable[[str, str], dict[str, Any]]


def resolve_concurrency(explicit: int | None = None) -> int:
    """并发度：显式参数优先，其次环境变量 RATOMIZER_LLM_CONCURRENCY（GUI 设置面板写入），否则默认。夹在 1..MAX。"""
    raw: Any = explicit if explicit is not None else os.environ.get(CONCURRENCY_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_CONCURRENCY
    return max(1, min(MAX_CONCURRENCY, value))


def resolve_self_check(explicit: bool | None = None) -> bool:
    """完整性自检开关：显式参数优先，否则环境变量 RATOMIZER_AI_SELFCHECK。

    默认开；仅显式的 0/false/no/off 关。未设或空字符串一律回落默认（空串≠关闭）。
    """
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get(SELF_CHECK_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off")


def resolve_self_check_rounds(explicit: int | None = None) -> int:
    """自检收敛轮数上限：显式参数优先，其次环境变量 RATOMIZER_AI_SELFCHECK_ROUNDS，否则默认 3。

    夹在 1..MAX_SELF_CHECK_ROUNDS。收敛循环通常 1-2 轮就 dry（零新增）提前停，上限只是防发散兜底。
    """
    raw: Any = explicit if explicit is not None else os.environ.get(SELF_CHECK_ROUNDS_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SELF_CHECK_MAX_ROUNDS
    return max(1, min(MAX_SELF_CHECK_ROUNDS, value))

VALID_TYPES = {"functional", "non_functional", "constraint", "business_rule"}
VALID_PRIORITIES = {"P0", "P1", "P2"}

SYSTEM_PROMPT = (
    "你是表计行业（电表/水表/气表）需求分析师。读给定的标准/规范文本，抽取其中的需求条目。"
    "把同一功能的零散语句**合并成一条功能需求**，不要逐句拆；表格类规范化为一条带说明的需求。"
    "每条需求输出：title（不超过 80 字）、description（自包含中文叙述：背景+具体要求+适用条件+参数）、"
    "type（functional/non_functional/constraint/business_rule）、priority（P0/P1/P2，按重要性区分）、"
    "module（该需求归属的模块，**必须原样照抄下面清单里的一个词**，按需求实质语义选最贴切的；"
    "确实都不贴切时才填\"" + OTHER_MODULE + "\"）：" + "、".join(MODULE_VOCAB) + "。"
    "labels（额外的细分标签，至少一个，可自由）、source_quote（原文逐字引用，不可改写）、"
    "source_section（该需求所属的章节号/标题，从文本里的小节标题判断）、"
    "acceptance_criteria（可测试的验收点数组）、"
    "sub_items（**可选**：条款枚举子项数组，每项 {\"label\": \"a\", \"text\": \"该子项的自包含中文要求\"}——"
    "原文以 a) b) c) 枚举多个要求时逐项填写，作为需求的二级结构）、"
    "dev_guidance（**研发落地指引**数组：为满足本需求，研发要实现的具体功能/逻辑/数据结构/接口，"
    "写\"做什么\"的可执行条目，不复述原文、不写空话）、"
    "threshold_table（**仅当原文含参数/门限/档位表**时输出 {\"columns\": [...], \"rows\": [[...]]}，"
    "数字逐格照抄原文，不重排不换算；原文无表格则省略此字段）。"
    "质量准则：description 必须自包含（研发不回原文即可实现：条件+动作+参数齐全）；"
    "acceptance_criteria 必须可测（有明确的通过/失败判据，避免\"符合要求\"这类空话）；"
    "一个需求点不拆散成多条，不同需求点不合并成一条。"
    "示例：原文 \"The meter shall store at least 12 monthly billing records.\" → "
    "{\"title\": \"存储至少12个月的月结算记录\", "
    "\"description\": \"电表须在本地存储不少于12个月的月结算记录，供结算追溯读取。\", "
    "\"type\": \"non_functional\", \"priority\": \"P1\", \"module\": \"结算\", \"labels\": [\"数据存储\"], "
    "\"source_quote\": \"The meter shall store at least 12 monthly billing records.\", "
    "\"dev_guidance\": [\"实现月结算记录存储区，容量不少于12条，写满后新记录覆盖最旧记录\", "
    "\"提供按月份读取历史结算记录的访问接口\"], "
    "\"acceptance_criteria\": [\"连续产生12个月结算记录后，最早一个月的记录仍可完整读出\"]}。"
    "若提供了【文档背景/章节大纲/术语定义】，据此保持术语一致、模块判断准确、解析跨章节引用；"
    "但这些背景仅供参考——需求内容与 source_quote 必须来自【当前章节】原文，不得从背景里搬运。"
    "严禁编造原文没有的 OBIS 码、事件号、十六进制、数字——这些只能原样引用或不出现。"
    "**不要输出**：目录/标题行、参考文献条目、范围声明（This standard specifies/applies to…）、"
    "仅引用其他标准编号而无本设备行为要求的语句——这些不是需求。"
    "**条款族=一条需求**：输入单元若是条款族（如 4.6 AFD2 含 4.6.1 Requirements 与 4.6.2 Test）："
    "以条款为单位产出**一条**需求——Requirements 的枚举项 a)b)c)d) 逐项写进 sub_items，"
    "对应的 Test 项按 a↔a、b↔b 对应写进 acceptance_criteria；**Test/测试方法不单独抽成需求**。"
    "**数值必须落地**：原文列出的数值清单（粒径/成分百分比/档位/限值/容差）必须**逐项完整**"
    "进入 threshold_table 或 description，绝不许用\"规定的范围\"\"指定成分\"这类指代替代——"
    "研发拿不到数值等于没写。若给出【被引用条款】，把其中的具体数值整合进描述（引用视为有据），"
    "不要只写\"见 X.X 节\"。"
    "只输出 JSON：{\"requirements\": [ {…}, … ]}。"
)


# --- 章节聚合与合并 -------------------------------------------------------

# 目录点线行（"4.15 Resistance to storage temperature ..... 23"）不是内容：LLM 会把目录
# 标题当需求抽出、与正文抽取成对重复且成批堆在目录段锚点上（test7 实测：16 条堆一段），
# 还污染覆盖率分母与自检焦点。PDF 解析的 doc_region 检测不总生效，此处兜底行级清洗。
# 两种形态（test7 实测）：① 行尾点线 + 页码（页码可能空格断裂"3 3"或掉行）；
# ② PDF 把整页目录挤成一行——几十个"标题.....页码"内联，用点线段密度识别（≥3 段）
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

    sections: list[dict[str, Any]] = []
    for unit in groups.values():
        body = "\n".join(unit["texts"]).strip()
        if not body:
            continue
        sections.append({"section_id": unit["section_id"], "section_path": unit["section_path"],
                         "heading": unit["heading"], "text": body, "block_ids": unit["block_ids"]})
    return sections


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


# 条款族允许比普通目标更大（保住"要求+测试"同单元）；超过后仍在成员/行边界拆（防 JSON 截断）
CLAUSE_FAMILY_MAX_FACTOR = 2
# 整章阅读模式（架构 A/B：少过程工程、多模型自由+结果验证）：按顶层章号分组（"4.14.1"→"4"），
# 模型一次通读整章——跨条款引用天然可见、无需自检环轮轮追打。上限防超上下文/输出截断。
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
        if len(piece) > target_chars:
            # 超大源章节：拆成 ≤split 的多块，各自独立成段（同段 block_ids 全量保留以便溯源）。
            # drift_source 保留完整原文：漂移护栏须以整章为 baseline，否则 LLM 合理引用同章
            # 其它片段里的 OBIS/事件码会被误判为"原文未见的结构漂移"（假阳性误伤）。
            flush()
            for chunk in _split_text(piece, split_chars):
                merged.append(_finalize_merged({
                    "section_id": sec["section_id"], "heading": sec.get("heading", ""),
                    "texts": [chunk], "block_ids": block_ids, "drift_source": piece}))
            continue
        if cur is None:
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": block_ids, "len": len(piece)}
        elif cur["len"] + len(piece) > target_chars and cur["texts"]:
            flush()
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": block_ids, "len": len(piece)}
        else:
            cur["texts"].append(piece)
            cur["block_ids"].extend(block_ids)
            cur["len"] += len(piece)
    flush()
    return merged


def _finalize_merged(cur: dict[str, Any]) -> dict[str, Any]:
    text = "\n\n".join(cur["texts"]).strip()
    # 漂移护栏 baseline：拆分片段用整章原文，其余默认用自身文本（无跨片段码）
    drift_source = cur.get("drift_source") or text
    return {"section_id": cur["section_id"], "heading": cur["heading"],
            "section_path": [cur["heading"]] if cur["heading"] else [],
            "text": text, "block_ids": cur["block_ids"], "drift_source": drift_source}


# --- 抽取与防幻觉护栏 -----------------------------------------------------

def section_fingerprint(section: dict[str, Any], model: str, context_key: str = "") -> str:
    refs = section.get("ref_texts") or []
    refs_key = hashlib.sha256(json.dumps(refs, ensure_ascii=False).encode("utf-8")).hexdigest()[:12] if refs else ""
    digest = hashlib.sha256(
        f"{section.get('text', '')}\n{model}\n{AI_EXTRACT_PROMPT_VERSION}\n{context_key}\n{refs_key}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


def build_section_prompt(section: dict[str, Any]) -> str:
    payload = {"heading": section.get("heading"), "text": section.get("text", "")[:12000]}
    base = json.dumps(payload, ensure_ascii=False, indent=2)
    refs = section.get("ref_texts") or []
    if not refs:
        return base
    ref_block = "\n\n".join(
        f"【被引用条款 {r['clause']}——本章节文字引用了它。请把其中的具体数值/限值整合进需求描述，"
        f"引用这些数值视为有据】\n{r['text']}" for r in refs)
    return f"{base}\n\n{ref_block}"


# --- 跨章节引用解析 -------------------------------------------------------
# "the leak rate does not exceed the values given in 7.13.4.5.1"——限值正文在别的单元，
# 抽取时看不见 → 描述只能写"不得超过 7.13.4.5.1 规定的限值"（不自包含，研发还得回原文）。
# 检测内部条款引用，把被引条款的正文摘录注入 prompt（并入漂移基线：引用其数值=有据）。
_CLAUSE_REF_RE = re.compile(
    r"\b(?:given in|specified in|according to|defined in|listed in|in accordance with|see)\s+"
    r"(\d+(?:\.\d+){1,5})\b", re.IGNORECASE)
_CLAUSE_HEADING_RE = re.compile(r"(?m)^(\d+(?:\.\d+){1,5})\b")
MAX_REFS_PER_SECTION = 2      # 控 token 成本
REF_EXCERPT_CHARS = 1200


def resolve_section_refs(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """就地给含内部引用的 section 挂 ref_texts + drift_source。必须对**全文**单元表跑
    （试抽采样前），被引条款可能在未被抽样的单元里。确定性、零 LLM。"""
    clause_pos: dict[str, tuple[int, int]] = {}
    for idx, s in enumerate(sections):
        for m in _CLAUSE_HEADING_RE.finditer(s["text"]):
            clause_pos.setdefault(m.group(1), (idx, m.start()))
    for idx, s in enumerate(sections):
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        for m in _CLAUSE_REF_RE.finditer(s["text"]):
            clause = m.group(1)
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


# --- 上下文工程：文档全局背景注入 ---------------------------------------

_CTX_GARBAGE_RE = re.compile(r"(?:\d+\s+)?[,`'=\-*_~|+…]{4,}")  # PDF 框线乱码片段


def _clean_ctx_text(text: str) -> str:
    """上下文文本清洁：剥离框线乱码、折叠空白。"""
    return re.sub(r"\s+", " ", _CTX_GARBAGE_RE.sub(" ", text or "")).strip()


def _outline_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """章节大纲：去重的章节标题序列（给 LLM 文档结构感，解析跨章节引用）。每条限长、去乱码。"""
    seen: list[str] = []
    seen_set: set[str] = set()
    for b in blocks:
        path = b.get("section_path") or []
        head = _clean_ctx_text(str(path[-1]))[:70].strip() if path else ""
        if len(head) > 1 and head not in seen_set:
            seen_set.add(head)
            seen.append(head)
        if len(seen) >= DOC_CONTEXT_OUTLINE_MAX:
            break
    return " / ".join(seen)


def _glossary_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """术语表：Terms/Definitions 节的文本（确定性截取 + 去乱码，不做脆弱的 term→def 解析）。"""
    parts: list[str] = []
    total = 0
    for b in blocks:
        if b.get("noise"):
            continue
        path = b.get("section_path") or []
        if not any(_TERMS_HEADING_RE.search(str(p)) for p in path):
            continue
        text = _clean_ctx_text(str(b.get("text") or ""))
        if not text:
            continue
        parts.append(text)
        total += len(text) + 1
        if total >= DOC_CONTEXT_GLOSSARY_MAX:
            break
    return "\n".join(parts)[:DOC_CONTEXT_GLOSSARY_MAX]


def build_doc_context(out_dir: Path, blocks: list[dict[str, Any]]) -> str:
    """文档全局上下文（表计类型/目标标准/章节大纲/术语表），注入每次章节抽取。确定性、可复现。

    只作术语与模块一致性、跨章节引用解析的**参考**；需求内容与 source_quote 仍须来自当前章节
    原文，且结构字段仍过双引擎漂移护栏（context 里的编码不会因此被当作源）。
    """
    try:
        from meter_profile import infer_meter_profile
        profile = infer_meter_profile(out_dir)
    except Exception as exc:  # pragma: no cover - 兜底，缺 manifest 等
        LOGGER.warning("文档画像失败，上下文降级：%s", exc)
        profile = {"meter_type": "", "target_standards": []}
    meter_type = str(profile.get("meter_type") or "未定")
    stds = "、".join(profile.get("target_standards") or []) or "未提取到"
    outline = _outline_from_blocks(blocks)
    glossary = _glossary_from_blocks(blocks)

    lines = [f"【文档背景】表计类型：{meter_type}；目标标准：{stds}。"]
    if outline:
        lines.append(f"【章节大纲】{outline}")
    if glossary:
        lines.append("【术语/定义（节选，仅供术语与模块一致性参考，勿据此编造原文没有的编码/数字）】")
        lines.append(glossary)
    return "\n".join(lines)


def _produced_text(requirement: dict[str, Any]) -> str:
    return " ".join([
        str(requirement.get("title") or ""),
        str(requirement.get("description") or ""),
        str(requirement.get("source_quote") or ""),
        " ".join(str(a) for a in requirement.get("acceptance_criteria") or []),
    ])


def code_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """受保护编码漂移：需求里出现、源文没有的 OBIS/事件号/十六进制（严格）。"""
    return sorted(extract_codes(_produced_text(requirement)) - extract_codes(source_text))


def int_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """普通整数漂移：需求里出现、源文没有的数字（软标）。"""
    return sorted(extract_ints(_produced_text(requirement)) - extract_ints(source_text))


def extract_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """编码 + 整数漂移合并（保留以兼容外部调用）。"""
    return sorted(set(code_drift(requirement, source_text)) | set(int_drift(requirement, source_text)))


def normalize_requirement(raw: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    rtype = str(raw.get("type") or "functional")
    if rtype not in VALID_TYPES:
        rtype = "functional"
    priority = str(raw.get("priority") or "P2")
    if priority not in VALID_PRIORITIES:
        priority = "P2"
    labels = [str(x) for x in (raw.get("labels") or []) if str(x).strip()]
    acceptance = [str(x) for x in (raw.get("acceptance_criteria") or []) if str(x).strip()]
    sub_items = [{"label": str(item.get("label") or "").strip()[:8],
                  "text": str(item.get("text") or "").strip()}
                 for item in (raw.get("sub_items") or [])
                 if isinstance(item, dict) and str(item.get("text") or "").strip()]
    dev_guidance = [str(x) for x in (raw.get("dev_guidance") or []) if str(x).strip()]
    module = str(raw.get("module") or "").strip()  # LLM 受控分类，ensure_domain_labels 据此定首要领域
    return {
        "title": str(raw.get("title") or "").strip()[:80],
        "description": str(raw.get("description") or "").strip(),
        "type": rtype,
        "priority": priority,
        "module": module,
        "status": "draft",
        "source_section": str(raw.get("source_section") or section.get("heading") or section.get("section_id") or "").strip(),
        "source_quote": str(raw.get("source_quote") or "").strip(),
        "threshold_table": raw.get("threshold_table") if isinstance(raw.get("threshold_table"), dict) else None,
        "sub_items": sub_items,
        "acceptance_criteria": acceptance,
        "dev_guidance": dev_guidance,
        "dependencies": [],
        "parent": None,
        "children": [],
        "labels": labels,
        "notes": "",
        "extracted_by": "ai_extract",
        "source_block_ids": list(section.get("block_ids") or []),
    }


# 纯引用/范围声明剔除（确定性、保守）：只杀两类明确无行为要求的条目——
# ① source_quote 本身就是标准号（"EN 16314:2013 (E)"）；② 范围声明（"This (European)
# Standard specifies/applies to ..."）。提及标准号但带设备行为的（"按 EN 1359 的方法测试
# 后应…"）不受影响。test7 实测 9 条此类条目混进交付物。
_CITATION_ONLY_RE = re.compile(r"^[\s]*(?:pr)?(?:EN|ISO|IEC|OIML|NBR|ABNT)[\s\d:.,/()\-+A-Z]*$")
_SCOPE_STMT_RE = re.compile(
    r"^\s*this\s+(?:european\s+|international\s+)?standard\s+(?:specifies|applies|is\s+applicable|covers|defines)",
    re.IGNORECASE)


def _is_reference_stub(req: dict[str, Any]) -> bool:
    quote = str(req.get("source_quote") or "").strip()
    if quote and _CITATION_ONLY_RE.match(quote):
        return True
    basis = quote or str(req.get("description") or "")
    return bool(_SCOPE_STMT_RE.match(basis))


def _process_raw_requirements(raw_reqs: list[Any], section: dict[str, Any],
                              context_ints: frozenset[str] | set[str] = frozenset()) -> list[dict[str, Any]]:
    """raw LLM 需求 → 归一 + 分级漂移护栏。抽取与完整性自检共用（补的也过同一套护栏）。

    context_ints：文档背景（画像/术语表）里出现过的普通整数。LLM 引用背景里的标准号
    （如"依据 EN 16314"）属合理行为，不软标为数字漂移——否则每条都是假阳性，稀释真漂移信号。
    受保护编码（OBIS/事件号/十六进制）**不豁免**：仍只认当前章节原文。
    """
    source = section.get("drift_source") or section.get("text", "")
    results: list[dict[str, Any]] = []
    for raw in raw_reqs:
        if not isinstance(raw, dict):
            continue
        req = normalize_requirement(raw, section)
        if not req["description"] and not req["source_quote"]:
            continue
        if _is_reference_stub(req):
            # 纯标准引用/范围声明不是设备需求（用户裁定当前阶段忽略）：剔除并留痕
            LOGGER.info("剔除引用/范围声明条目：%s | quote=%s",
                        req.get("title", "")[:40], req.get("source_quote", "")[:60])
            continue
        codes = code_drift(req, source)
        ints = [i for i in int_drift(req, source) if i not in context_ints]
        notes = []
        if codes:  # 受保护编码漂移 → 严格：降级 draft 待核
            req["status"] = "draft"
            notes.append(f"结构漂移已拦截（编码，原文未见）：{', '.join(codes[:8])}")
        if ints:  # 普通整数漂移 → 软标：保留，待核
            notes.append(f"数字漂移（待核）：{', '.join(ints[:8])}")
        if not codes:
            # 无编码漂移：若模型给了状态信号则尊重，否则默认 draft（AI 抽取一律待审）
            req["status"] = "draft"
        req["notes"] = "；".join(notes)
        # 可疑度信号（零 LLM）：给审核视图排优先级——先审最可疑的
        suspicion: list[str] = []
        if codes:
            suspicion.append("编码漂移")
        if ints:
            suspicion.append("数字漂移")
        quote_norm = re.sub(r"\s+", " ", req["source_quote"]).strip().lower()
        if quote_norm and quote_norm not in re.sub(r"\s+", " ", source).lower():
            suspicion.append("引用非逐字")
        left_behind = _values_left_behind(req, source)
        if left_behind:
            suspicion.append("原文数值未带全")
            note = f"原文数值未带全（引句附近 {left_behind} 个数值未进需求，请核对参数清单）"
            req["notes"] = f"{req['notes']}；{note}" if req["notes"] else note
        vague = _vague_acceptance(req)
        if vague:
            suspicion.append("验收不可测")
            note = f"验收不可测（空话验收 {len(vague)} 条，如「{vague[0][:40]}」，请给出可判定条件）"
            req["notes"] = f"{req['notes']}；{note}" if req["notes"] else note
        if suspicion:
            req["suspicion_reasons"] = suspicion
        results.append(req)
    return results


# 模糊验收检测（BMAD "Done-ness clarity" 模式）：封杀"符合要求/正常工作"式空话验收——
# 研发看不出"完成"长什么样。命中空话短语且不含任何数字/编码/比较判据的验收条 → 标记待澄清。
_VAGUE_PHRASES = ("符合要求", "满足要求", "正常工作", "工作正常", "运行正常", "表现良好",
                  "适当", "合理", "正确处理", "妥善处理", "gracefully", "properly",
                  "reasonable", "as expected", "correctly", "appropriately")
_TESTABLE_HINT_RE = re.compile(r"[0-9０-９]|≥|≤|>|<|＝|=|不超过|不少于|不小于|不大于|之内|以内|以上|以下")


def _vague_acceptance(req: dict[str, Any]) -> list[str]:
    """返回不可测的验收条目（命中空话且无任何可判定判据）。只标不拦。"""
    vague: list[str] = []
    for item in (req.get("acceptance_criteria") or []):
        text = str(item)
        low = text.lower()
        if any(p in low for p in _VAGUE_PHRASES) and not _TESTABLE_HINT_RE.search(text) \
                and not extract_codes(text):
            vague.append(text[:80])
    return vague


_LEFT_BEHIND_MIN = 4      # 引句附近 ≥N 个数值没被带走才标（避免零星页码/序号误报）
_LEFT_BEHIND_WINDOW = 800  # 引句起往后看的窗口（枚举清单/成分表通常紧跟引句）


def _values_left_behind(req: dict[str, Any], source: str) -> int:
    """确定性漏值检测：引句附近的数值清单没进需求（真实案例：粉尘粒径/成分百分比全被
    "规定的范围"指代吞掉，threshold_table=None——研发拿不到数值等于没写）。只标记不拦截。"""
    quote = str(req.get("source_quote") or "")
    if not quote:
        return 0
    pos = source.find(quote)
    if pos < 0:
        return 0
    window = source[pos:pos + max(len(quote), _LEFT_BEHIND_WINDOW)]
    captured = extract_ints(" ".join([
        _produced_text(req), json.dumps(req.get("threshold_table") or {}),
    ]))
    left = extract_ints(window) - captured
    return len(left) if len(left) >= _LEFT_BEHIND_MIN else 0


def _req_key(req: dict[str, Any]) -> str:
    """去重键：source_quote（归一）→ title → description 前 80 字。

    三级回退保证过了护栏的条目（必有 description 或 quote）键恒非空——否则"有描述但
    无引用无标题"的自检补充项会因空键被静默丢弃（与初抽路径不对称）。
    """
    q = re.sub(r"\s+", " ", str(req.get("source_quote") or "")).strip().lower()
    if q:
        return q
    title = str(req.get("title") or "").strip().lower()
    if title:
        return title
    return str(req.get("description") or "").strip().lower()[:80]


def critique_section(section: dict[str, Any], existing: list[dict[str, Any]],
                     chat: ChatFn, doc_context: str = "",
                     context_ints: frozenset[str] | set[str] = frozenset(),
                     focus_lines: list[str] | None = None) -> list[dict[str, Any]]:
    """完整性自检：对着原文找已抽取需求**未覆盖**的遗漏项，补上（去重 + 同一套漂移护栏）。

    focus_lines：解析层标记 requirement_like 但未被任何已抽需求覆盖的原文语句——
    定向查漏的重点核查清单（比盲查更准）。
    """
    # 给模型看**结构摘要**而非裸标题：真实案例（4.14）——初抽按条款族正确合成一条（子项
    # a-e + 验收），自检只见标题、看不见 a-e 已在 sub_items 里 → 判"遗漏"又拆回 4 条碎片，
    # 一个条款 18 个批注点。摘要必须暴露子项与验收，让"已覆盖"判断有据。
    summaries = "\n".join(
        f"- {r.get('title', '')}"
        + (f"｜子项:{','.join(str(s.get('label') or '·') for s in r.get('sub_items') or [])}"
           if r.get("sub_items") else "")
        + (f"｜验收 {len(r.get('acceptance_criteria') or [])} 条"
           if r.get("acceptance_criteria") else "")
        for r in existing) or "（无）"
    parts: list[str] = []
    if doc_context:
        parts.append(doc_context)
        parts.append("---")
    parts.append(
        "【查漏补缺任务】下面是一个章节的原文 + 已抽取的需求结构摘要。找出章节里**尚未被覆盖**的"
        "需求/约束/可测语句，只输出这些**遗漏项**（同样的 JSON schema、同样的 module 受控清单）；"
        "已覆盖的不要重复；原文没有的绝不编造；若无遗漏，输出 {\"requirements\": []}。"
        "**覆盖判定**：已抽需求的 sub_items（枚举子项 a/b/c…）与 acceptance_criteria 覆盖的语句"
        "算已覆盖——条款的枚举项、测试前/后判据、测试方法是该条款需求的组成部分，"
        "**不要**把它们拆成新需求，也不要输出与已抽需求同源的重复表述"
        "（条款族=一条需求的原则对遗漏项同样适用）。")
    parts.append(f"当前章节：\n{build_section_prompt(section)}")
    parts.append(f"已抽取（勿重复）：\n{summaries}")
    if focus_lines:
        hints = "\n".join(f"- {line}" for line in focus_lines[:12])
        parts.append(f"重点核查以下原文语句是否含被遗漏的需求（解析层判定疑似需求但尚无需求覆盖）：\n{hints}")
    payload = chat(SYSTEM_PROMPT, "\n\n".join(parts))
    raw = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    seen = {_req_key(r) for r in existing}
    # 包含式去重基底：真实案例里自检补的"新"条目引句是已抽引句的**前缀子串**（精确匹配拦不住）
    existing_quotes = [q for q in (_norm_ws(r.get("source_quote")) for r in existing) if len(q) >= 20]
    extra: list[dict[str, Any]] = []
    for req in _process_raw_requirements(raw, section, context_ints):
        key = _req_key(req)
        if not key or key in seen:
            continue
        quote = _norm_ws(req.get("source_quote"))
        if len(quote) >= 20 and any(quote in q or q in quote for q in existing_quotes):
            continue   # 与已抽需求同源（引句互为包含）→ 重复，弃
        seen.add(key)
        if len(quote) >= 20:
            existing_quotes.append(quote)
        req["self_check_added"] = True  # 初抽遗漏、自检补回——审核时优先看
        req["suspicion_reasons"] = list(req.get("suspicion_reasons") or []) + ["自检补充（初抽遗漏）"]
        extra.append(req)
    return extra


def _norm_ws(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _uncovered_requirement_lines(section: dict[str, Any], existing: list[dict[str, Any]],
                                 block_info: dict[str, dict[str, Any]] | None) -> list[str] | None:
    """本章节内 requirement_like 且未被任何已抽 source_quote 覆盖的原文语句。

    返回 None 表示无块信息（调用方回退全量盲查）。拆分片段只核查落在本片段文本里的语句，
    防同一遗漏被多个片段重复补。
    """
    if not block_info:
        return None
    quotes = [q for q in (_norm_ws(r.get("source_quote")) for r in existing) if q]
    # 子项覆盖记账：条款族合并后 a)b)c) 各行活在 sub_items 里而非 source_quote 里——
    # 不认子项标签会把它们永远判"未覆盖"，定向自检轮轮追打、拆碎条款（真实案例 4.14）
    sub_labels = {str(s.get("label") or "").strip().lower()
                  for r in existing for s in (r.get("sub_items") or [])}
    sub_labels.discard("")
    section_text = _norm_ws(section.get("text"))
    uncovered: list[str] = []
    seen: set[str] = set()
    for bid in section.get("block_ids") or []:
        block = block_info.get(str(bid))
        if not block or not block.get("requirement_like") or block.get("noise"):
            continue
        if block.get("type") == "heading":
            continue   # 标题被关键词误标 requirement_like（如 "4.14.1 Requirement"）——不是内容
        cleaned = clean_block_text(block)   # 目录点线行不进自检焦点（追着目录行查漏纯烧调用）
        bt = _norm_ws(cleaned)
        if not bt or bt in seen or bt not in section_text:
            continue
        seen.add(bt)
        if any(q in bt or bt in q for q in quotes):
            continue
        m = re.match(r"^\(?([a-z])\)", bt)
        if m and m.group(1) in sub_labels:
            continue   # 该枚举项已被某条需求的 sub_items 覆盖
        uncovered.append(cleaned[:200])
    return uncovered


def extract_section(section: dict[str, Any], chat: ChatFn, doc_context: str = "",
                    self_check: bool = False,
                    block_info: dict[str, dict[str, Any]] | None = None,
                    self_check_rounds: int | None = None) -> list[dict[str, Any]]:
    """对一个章节调 chat 抽取需求，归一 + 分级漂移护栏。doc_context 注入文档全局背景。

    self_check：抽完**收敛式**查漏补缺——每轮对着当前已抽集重算未覆盖清单再补，直到某轮零新增
    /全覆盖/触顶为止。单趟只能补"第一层可见"的遗漏；有些遗漏要等前几条补进去、覆盖清单缩小后才
    暴露，收敛循环才抓得到。有 block_info 时**定向**（未覆盖 requirement_like 语句作重点核查
    清单）；全覆盖则提前停。无 block_info 回退全量盲查，靠"零新增"收敛。自检失败不致命——保留已抽。
    """
    user = build_section_prompt(section)
    if doc_context:
        user = f"{doc_context}\n\n---\n以下是待抽取的**当前章节**（需求内容与 source_quote 只能来自这段原文）：\n{user}"
    context_ints = frozenset(extract_ints(doc_context)) if doc_context else frozenset()
    payload = chat(SYSTEM_PROMPT, user)
    raw_reqs = payload.get("requirements") if isinstance(payload, dict) else None
    results = _process_raw_requirements(raw_reqs, section, context_ints) if isinstance(raw_reqs, list) else []
    if not self_check:
        return results

    # 收敛循环只在**定向模式**（有 block_info，确定性覆盖信号）多轮：每轮针对仍未覆盖的
    # requirement_like 语句补，覆盖清单随之缩小，直到全覆盖/零新增/触顶。有些遗漏要等前几条
    # 补进去、清单缩小后才暴露，单趟抓不到。盲查（无 block_info）保持单趟——无覆盖锚点时反复
    # 追问会诱发过度生成（幻觉压力），得不偿失。
    max_rounds = resolve_self_check_rounds(self_check_rounds) if block_info else 1
    added_total = 0
    for round_no in range(1, max_rounds + 1):
        uncovered = _uncovered_requirement_lines(section, results, block_info)
        # 定向模式下 requirement_like 全覆盖即收敛（无可查项，省一次调用）
        if uncovered is not None and not uncovered and results:
            LOGGER.info("自检收敛（requirement_like 全覆盖，章节 %s，第 %d 轮）",
                        section.get("section_id"), round_no)
            break
        try:
            extra = critique_section(section, results, chat, doc_context, context_ints,
                                     focus_lines=uncovered or None)
        except LLMError as exc:  # 自检失败不致命，保留已抽（含前几轮成果）
            LOGGER.warning("完整性自检第 %d 轮失败（保留已抽）：%s", round_no, exc)
            break
        if not extra:  # 零新增 → 已收敛，无需再问
            LOGGER.info("自检收敛（零新增，章节 %s，第 %d 轮）", section.get("section_id"), round_no)
            break
        results = results + extra
        added_total += len(extra)
        LOGGER.info("完整性自检第 %d 轮补充 %d 条（章节 %s）", round_no, len(extra), section.get("section_id"))
        if round_no == max_rounds:  # 触顶仍有新增：记一笔，未必已穷尽（防发散优先）
            LOGGER.info("自检触顶 %d 轮仍有新增（章节 %s，累计补 %d 条）",
                        max_rounds, section.get("section_id"), added_total)
    return results


# --- 缓存 + 批处理 --------------------------------------------------------

def read_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row.get("fingerprint") or "")
            if key:
                cache[key] = row.get("requirements") or []
    return cache


def append_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_all(
    sections: list[dict[str, Any]],
    chat: ChatFn,
    *,
    model: str,
    cache_path: Path,
    concurrency: int = 1,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    stats: dict[str, Any] | None = None,
    doc_context: str = "",
    self_check: bool = False,
    self_check_rounds: int | None = None,
    block_info: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """逐章节抽取（缓存优先 + 并发 + 失败降级）。返回扁平需求列表，可复现。

    progress_callback：每完成一章节回调一次（GUI 进度条用，否则界面看着像卡死）。
    逐章节增量写缓存：长跑中途被中断也不丢已完成章节。
    stats：可选 out-dict，回填 total_sections / cached_sections / failed_sections。
    doc_context：文档全局上下文，注入每次抽取并计入指纹（背景变→缓存失效重抽）。
    self_check_rounds：自检收敛轮数上限（None 走默认/env）；计入指纹，改轮数→缓存失效重抽。
    """
    rounds = resolve_self_check_rounds(self_check_rounds) if self_check else 0
    context_key = (hashlib.sha256(doc_context.encode("utf-8")).hexdigest()[:12] if doc_context else "")
    if self_check:  # 自检开/关 + 轮数不同 → 产出不同，计入指纹，缓存不串
        context_key += f"|selfcheck{rounds}"
    cache = read_cache(cache_path)
    results: list[list[dict[str, Any]] | None] = [None] * len(sections)
    pending: list[tuple[int, dict[str, Any], str]] = []
    for i, section in enumerate(sections):
        fp = section_fingerprint(section, model, context_key)
        hit = cache.get(fp)
        if hit is not None:
            results[i] = hit
        else:
            pending.append((i, section, fp))

    total = len(sections)
    cached = total - len(pending)
    completed = cached
    failed = 0

    def emit() -> None:
        if progress_callback is not None and total:
            progress_callback({
                "stage": "ai_extract",
                "completed": completed,
                "total": total,
                "percent": int(round(completed * 100 / total)),
                "model": model,
            })

    emit()  # 初始进度（含缓存命中数），让界面立刻有反馈

    def work(item: tuple[int, dict[str, Any], str]) -> tuple[int, str, list[dict[str, Any]], bool]:
        idx, section, fp = item
        try:
            return idx, fp, extract_section(section, chat, doc_context, self_check, block_info,
                                            self_check_rounds=rounds or None), True
        except LLMError as exc:  # 最佳努力：该章节降级、不崩、不缓存（留待重跑）
            LOGGER.warning("AI 抽取章节失败：%s", exc)
            return idx, fp, [], False

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = [executor.submit(work, item) for item in pending]
            for future in as_completed(futures):
                idx, fp, reqs, ok = future.result()
                results[idx] = reqs
                if ok:
                    # 逐章节增量缓存：中途中断不丢已完成章节
                    append_cache(cache_path, [{"fingerprint": fp, "model": model,
                                               "prompt_version": AI_EXTRACT_PROMPT_VERSION,
                                               "requirements": reqs}])
                else:
                    failed += 1
                completed += 1
                emit()

    if stats is not None:
        stats["total_sections"] = total
        stats["cached_sections"] = cached
        stats["failed_sections"] = failed

    flat: list[dict[str, Any]] = []
    for reqs in results:
        flat.extend(reqs or [])
    return flat


# --- skill 格式 doc / Excel ----------------------------------------------

def ensure_domain_labels(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """定首要领域（labels[0]，按域分组/出 Excel 都用它），优先级：

    1. LLM 选的 module 在受控词表内 → 直接作首要领域（LLM 读了整段、最懂上下文）。
    2. LLM 明确判 "其它" → 尊重其判断，归 OTHER（不再被 map_labels 误塞进通信协议）。
    3. module 缺失/越界 → 确定性 map_labels 关键词兜底。

    LLM 的自由 labels 始终保留为补充。对缓存结果也生效、不需重调 LLM。
    """
    import requirement_schema as rs
    domain_set = set(METERING_DOMAINS)
    for req in requirements:
        existing = [str(x) for x in (req.get("labels") or [])]
        module = str(req.get("module") or "").strip()
        if module in domain_set or module == OTHER_MODULE:  # LLM 受控分类优先
            req["labels"] = [module] + [label for label in existing if label != module]
            continue
        if any(label in domain_set for label in existing):
            continue
        text = f"{req.get('title', '')} {req.get('description', '')} {req.get('source_quote', '')}"
        domains = [d for d in rs.map_labels(text) if d in domain_set]
        req["labels"] = domains + [label for label in existing if label not in domains]
    return requirements


def build_skill_doc(requirements: list[dict[str, Any]], *, source: str, extracted_at: str,
                    meter_type: str = "multi", target_standards: list[str] | None = None) -> dict[str, Any]:
    """把 AI 抽取的需求装配成公司 skill 格式 doc（REQ-NNN 重编号 + analysis）。"""
    import requirement_schema as rs
    return rs.make_doc(requirements, source=source, extracted_at=extracted_at,
                       meter_type=meter_type, target_standards=target_standards)


# --- 双引擎合并 -----------------------------------------------------------

def merge_requirements(deterministic: list[dict[str, Any]],
                       ai_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """双引擎合并：确定性的**结构**需求（有属性/访问表，OBIS 权威）+ AI 的**行为**需求。

    丢掉确定性里纯散文模板需求（无 threshold_table）——这部分由 AI 行为需求替代，避免模板与
    AI 叙述重复。确定性结构需求逐字保留（OBIS/数字一位不动）。
    """
    structural: list[dict[str, Any]] = []
    for req in deterministic:
        tt = req.get("threshold_table")
        if isinstance(tt, dict) and tt.get("rows"):
            req.setdefault("extracted_by", "deterministic")
            structural.append(req)
    return structural + list(ai_requirements)


def load_or_build_deterministic(out_dir: Path, *, source: str, extracted_at: str) -> list[dict[str, Any]]:
    """取确定性装配需求：优先读已有 dlms_cosem_spec_requirements.json，否则现装配。"""
    doc_path = out_dir / "dlms_cosem_spec_requirements.json"
    if doc_path.exists():
        return json.loads(doc_path.read_text(encoding="utf-8")).get("requirements", [])
    from assemble_spec import assemble
    reviews = out_dir / "llm_review_results.jsonl"
    doc, _ = assemble(out_dir, reviews if reviews.exists() else None,
                      source=source, extracted_at=extracted_at)
    return doc.get("requirements", [])


def apply_ai_decisions(out_dir: Path, ai_requirements: list[dict[str, Any]],
                       stats: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """把专家裁决（批注视图/HTML 导入 → ai_review_states.jsonl）应用到 AI 需求，回流交付物。

    rejected → 剔除（不进研发规格）；module_override → 生效并重定首要领域；
    accepted → status=confirmed；reason → 追加"专家意见"到 notes。无裁决原样保留。
    """
    from ai_review_actions import read_ai_review_states, source_ai_requirement_id
    states = read_ai_review_states(out_dir)
    applied = 0
    dropped = 0
    kept: list[dict[str, Any]] = []
    for req in ai_requirements:
        state = states.get(source_ai_requirement_id(req)) if states else None
        if not state:
            kept.append(req)
            continue
        applied += 1
        if state.get("status") == "rejected":
            dropped += 1
            continue
        req = dict(req)
        if state.get("module_override"):
            req["module"] = state["module_override"]  # ensure_domain_labels 会按 module 重排首要领域
        if state.get("status") == "accepted":
            req["status"] = "confirmed"
        if state.get("reason"):
            note = f"专家意见：{state['reason']}"
            req["notes"] = f"{req.get('notes') or ''}；{note}".strip("；")
        kept.append(req)
    if applied:
        ensure_domain_labels(kept)  # module（含 override）重新驱动首要领域
    if stats is not None:
        stats["decisions_applied"] = applied
        stats["rejected_dropped"] = dropped
    return kept


def build_merged_doc(out_dir: Path, ai_requirements: list[dict[str, Any]],
                     *, source: str, extracted_at: str,
                     stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """合并 AI 行为需求（先应用专家裁决）+ 确定性结构需求 → skill 格式 doc。"""
    ai_requirements = apply_ai_decisions(out_dir, ai_requirements, stats)
    deterministic = load_or_build_deterministic(out_dir, source=source, extracted_at=extracted_at)
    merged = merge_requirements(deterministic, ai_requirements)
    from meter_profile import infer_meter_profile
    profile = infer_meter_profile(out_dir)
    return build_skill_doc(merged, source=source, extracted_at=extracted_at,
                           meter_type=profile["meter_type"], target_standards=profile["target_standards"])


def _write_merged_outputs(out_dir: Path, merged: dict[str, Any]) -> list[str]:
    """写 merged_spec_requirements.json + merged_spec.xlsx，返回写出的文件名。"""
    written: list[str] = []
    merged_json = out_dir / "merged_spec_requirements.json"
    merged_json.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(merged_json.name)
    try:
        from spec_excel import write_xlsx
        merged_xlsx = out_dir / "merged_spec.xlsx"
        write_xlsx(merged, merged_xlsx)
        written.append(merged_xlsx.name)
    except Exception as exc:  # Excel 失败不阻断 JSON 产出
        LOGGER.warning("合并 Excel 生成失败：%s", exc)
    try:
        written.append(_write_consistency_report(out_dir, merged).name)
    except Exception as exc:  # 一致性报表失败不阻断交付物产出
        LOGGER.warning("全局一致性报表生成失败：%s", exc)
    return written


def _write_consistency_report(out_dir: Path, merged: dict[str, Any]) -> Path:
    """P1 全局一致性 critic：跨章去重 + OBIS 共引 + 覆盖缺口（确定性，非破坏，只标记）。"""
    import merged_consistency
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    req_like = ([b for b in blocks if b.get("requirement_like") and not b.get("noise") and clean_block_text(b)]
                if blocks else None)  # 纯目录块不进覆盖分母
    report = merged_consistency.analyze_consistency(merged.get("requirements") or [], req_like)
    path = out_dir / "consistency_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    dg = report["summary"]["duplicate_groups"]
    vd = report["summary"]["obis_values_differ"]
    if dg or vd:
        LOGGER.info("全局一致性：疑似跨章重复 %d 组、OBIS 数值待核 %d 组（详见 consistency_report.json）", dg, vd)
    return path


def rebuild_merged_spec(out_dir: Path) -> dict[str, Any]:
    """免 LLM 重建交付物：读已抽 ai_requirements.jsonl + 最新裁决，重合并重写 json/xlsx。

    批注视图裁决、导入裁决 JSON 后调用——专家的接受/拒绝/改模块即时反映到 merged_spec。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    ai_requirements = read_jsonl(out_dir / AI_REQUIREMENTS)
    stats: dict[str, Any] = {}
    merged = build_merged_doc(out_dir, ai_requirements, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              stats=stats)
    written = _write_merged_outputs(out_dir, merged)
    try:
        # 裁决学习回路：每次裁决回流后刷新 override 复盘报告（确定性，失败不阻断交付物）
        import review_insights
        review_insights.write_insights(out_dir)
        written.append(review_insights.INSIGHTS_JSON)
    except Exception as exc:  # pragma: no cover - 复盘失败不影响交付物
        LOGGER.warning("裁决复盘报告生成失败（忽略）：%s", exc)
    return {"written": written, "total": merged["analysis"]["total_count"], **stats}


# --- 主入口 ---------------------------------------------------------------

def config_for_route(route: str | None, pipeline_path: Path = DEFAULT_PIPELINE_PATH) -> LLMClientConfig | None:
    pipeline = load_review_pipeline(pipeline_path)
    route_name = resolve_route_name(pipeline, route)
    if route_name != "openai_compatible":
        return None
    # 复用 review 同一套 env 覆盖：GUI 在设置面板配的端点经 RATOMIZER_LLM_* 覆盖 yaml
    payload = apply_llm_environment_overrides(dict(pipeline.model_routes.get("openai_compatible") or {}))
    return llm_config_from_route(payload)


def sample_sections(sections: list[dict[str, Any]], limit: int | None) -> tuple[list[dict[str, Any]], bool]:
    """试抽样本：均匀取 N 章（确定性步长，非"前 N 章"——文档开头是范围/术语，需求密度最低，
    前 N 章会给出误导性的质量样本）。缓存指纹按章节内容算，样本章节的缓存全量跑时原样复用。"""
    if not limit or limit <= 0 or limit >= len(sections):
        return sections, False
    stride = len(sections) / limit
    picked = [sections[min(int(i * stride), len(sections) - 1)] for i in range(limit)]
    return picked, True


def run_ai_extract(out_dir: Path, *, route: str | None, merge_chars: int = DEFAULT_MERGE_CHARS,
                   write_doc: bool = False, merge_deterministic: bool = False,
                   pipeline_path: Path = DEFAULT_PIPELINE_PATH,
                   progress_callback: Callable[[dict[str, Any]], None] | None = None,
                   concurrency: int | None = None,
                   self_check: bool | None = None,
                   limit_sections: int | None = None,
                   sample_ratio: float | None = None,
                   unit_mode: str | None = None) -> dict[str, Any]:
    """读 blocks → 章节合并 → AI 抽取 → 写 ai_requirements.jsonl（可选 skill doc + Excel + 双引擎合并）。

    试抽模式（分钟级出质量样本，不等全量）：limit_sections=固定 N 章；sample_ratio=按比例
    （如 0.2 = 全文 1/5，随文档规模自适应——「测试运行」用这个，不写死条数）。两者都给时固定数优先。
    """
    out_dir = out_dir.expanduser().resolve()
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    resolved_mode = (unit_mode or os.environ.get(UNIT_MODE_ENV) or "clause").strip().lower()
    if resolved_mode not in ("clause", "chapter"):
        resolved_mode = "clause"
    all_sections = merge_sections(assemble_sections(blocks), target_chars=merge_chars,
                                  unit_mode=resolved_mode)
    resolve_section_refs(all_sections)  # 跨章节引用注入（须在采样前，被引条款可能不在样本里）
    if not limit_sections and sample_ratio and 0 < sample_ratio < 1:
        limit_sections = max(1, round(len(all_sections) * sample_ratio))
    sections, sampled = sample_sections(all_sections, limit_sections)
    if sampled:
        LOGGER.info("试抽模式：全文 %d 章均匀抽样 %d 章（质量指标只对样本计算）",
                    len(all_sections), len(sections))

    config = config_for_route(route, pipeline_path)
    written: list[str] = []
    code_flagged = 0
    int_flagged = 0
    failed_sections = 0
    model: str | None = None
    result_quality: dict[str, Any] | None = None

    if config is None:
        # stub 路由：不调 LLM，AI 行为需求为空——但确定性引擎（双引擎之一）仍照常
        # 产出结构规格，所以不在此 early-return，继续走 write_doc / merge_deterministic。
        requirements: list[dict[str, Any]] = []
        route_label = "stub"
    else:
        min_tokens = CHAPTER_MIN_MAX_TOKENS if resolved_mode == "chapter" else AI_EXTRACT_MIN_MAX_TOKENS
        if config.max_tokens < min_tokens:  # 给推理模型留出正文预算，防 JSON 截断（整章输出更长）
            config = replace(config, max_tokens=min_tokens)

        def chat(system: str, user: str) -> dict[str, Any]:
            return chat_json(config, system, user)

        doc_context = build_doc_context(out_dir, blocks)  # 上下文工程：文档全局背景注入每次抽取
        block_info = {str(b.get("block_id")): b for b in blocks if b.get("block_id")}  # 定向自检/覆盖率用
        extract_stats: dict[str, Any] = {}
        requirements = extract_all(sections, chat, model=config.model,
                                   cache_path=out_dir / AI_EXTRACT_CACHE,
                                   concurrency=resolve_concurrency(concurrency),
                                   progress_callback=progress_callback,
                                   stats=extract_stats,
                                   doc_context=doc_context,
                                   self_check=resolve_self_check(self_check),
                                   block_info=block_info)
        ensure_domain_labels(requirements)  # 确定性补领域标签，保证按域 Excel 不塌进未分类
        code_flagged = sum(1 for r in requirements if "结构漂移已拦截" in (r.get("notes") or ""))
        int_flagged = sum(1 for r in requirements if "数字漂移" in (r.get("notes") or ""))
        failed_sections = int(extract_stats.get("failed_sections", 0))
        model = config.model
        route_label = "openai_compatible"

        target = out_dir / AI_REQUIREMENTS
        with target.open("w", encoding="utf-8", newline="\n") as f:
            for req in requirements:
                f.write(json.dumps(req, ensure_ascii=False) + "\n")
        written.append(target.name)

        # 质量报表：这轮抽取的可核指标（覆盖率/漂移/自检补充/模块分布），落盘供追溯
        req_like = [b for b in block_info.values()
                    if b.get("requirement_like") and not b.get("noise") and clean_block_text(b)]
        if sampled:  # 试抽模式：覆盖率分母只算样本章节的块，否则数字必然假低
            sampled_ids = {str(bid) for s in sections for bid in (s.get("block_ids") or [])}
            req_like = [b for b in req_like if str(b.get("block_id")) in sampled_ids]
        quotes = [q for q in (_norm_ws(r.get("source_quote")) for r in requirements) if q]
        covered = sum(
            1 for b in req_like
            if (lambda bt: bt and any(q in bt or bt in q for q in quotes))(_norm_ws(b.get("text")))
        )
        by_module: dict[str, int] = {}
        for r in requirements:
            m = str((r.get("labels") or ["未分模块"])[0])
            by_module[m] = by_module.get(m, 0) + 1
        quality = {
            "sections": len(sections),
            "requirements": len(requirements),
            "failed_sections": int(extract_stats.get("failed_sections", 0)),
            "cached_sections": int(extract_stats.get("cached_sections", 0)),
            "self_check_added": sum(1 for r in requirements if r.get("self_check_added")),
            "code_drift_flagged": code_flagged,
            "int_drift_flagged": int_flagged,
            "requirement_like_blocks": len(req_like),
            "covered_blocks": covered,
            "coverage_pct": round(covered * 100 / len(req_like), 1) if req_like else None,
            "by_module": dict(sorted(by_module.items(), key=lambda x: -x[1])),
        }
        quality_path = out_dir / "ai_extract_quality.json"
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(quality_path.name)
        result_quality = quality

    result: dict[str, Any] = {"route": route_label, "sections": len(sections),
              "requirements": len(requirements), "code_drift_flagged": code_flagged,
              "int_drift_flagged": int_flagged, "failed_sections": failed_sections,
              "written": written}
    if sampled:
        result["sampled"] = {"sections": len(sections), "total_sections": len(all_sections)}
    if model:
        result["model"] = model
    if config is None:
        result["note"] = "stub 路由：未调 LLM（AI 行为需求为空，仅产确定性结构规格）"
    elif failed_sections:
        result["note"] = (f"{failed_sections} 个章节 LLM 调用失败（端点/Key/超时）——"
                          "已按可用结果产出，请用「测试连接」确认配置后重跑")
    if result_quality is not None:
        result["quality"] = result_quality

    if write_doc:
        from meter_profile import infer_meter_profile
        profile = infer_meter_profile(out_dir)
        doc = build_skill_doc(requirements, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              meter_type=profile["meter_type"], target_standards=profile["target_standards"])
        doc_path = out_dir / "ai_requirements_doc.json"
        doc_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(doc_path.name)
        try:
            from spec_excel import write_xlsx
            xlsx_path = out_dir / "ai_requirements.xlsx"
            write_xlsx(doc, xlsx_path)
            written.append(xlsx_path.name)
        except Exception as exc:  # Excel 失败不阻断 JSON 产出
            LOGGER.warning("AI 需求 Excel 生成失败：%s", exc)
        result["analysis"] = doc.get("analysis", {}).get("by_priority", {})

    if merge_deterministic:
        merge_stats: dict[str, Any] = {}
        merged = build_merged_doc(out_dir, requirements, source=out_dir.name,
                                  extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                                  stats=merge_stats)
        written.extend(_write_merged_outputs(out_dir, merged))
        ai_in_merged = len(requirements) - int(merge_stats.get("rejected_dropped", 0))
        result["merged"] = {"total": merged["analysis"]["total_count"],
                            "ai_behavioral": ai_in_merged,
                            "deterministic_structural": merged["analysis"]["total_count"] - ai_in_merged,
                            **merge_stats}
        # 一致性闭环：报表摘要随任务载荷透出（GUI 跑完消息 + 批注视图标记都吃它，不再只写不读）
        try:
            report = json.loads((out_dir / "consistency_report.json").read_text(encoding="utf-8"))
            result["consistency"] = report.get("summary", {})
        except (OSError, json.JSONDecodeError):
            pass

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-first requirement extraction.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory (含 blocks.jsonl)")
    parser.add_argument("--route", default=None, help="stub | openai_compatible")
    parser.add_argument("--limit-sections", type=int, default=0,
                        help="试抽模式：均匀抽样 N 章快速看质量（0=全量）")
    parser.add_argument("--merge-chars", type=int, default=DEFAULT_MERGE_CHARS, help="章节合并目标字数")
    parser.add_argument("--doc", action="store_true", help="同时产 skill 格式 doc + Excel（仅 AI 需求）")
    parser.add_argument("--merge", action="store_true", help="双引擎合并：AI 行为 + 确定性结构 → merged_spec")
    parser.add_argument("--concurrency", type=int, default=None,
                        help=f"LLM 并发章节数（默认 {DEFAULT_CONCURRENCY}，或环境变量 {CONCURRENCY_ENV}；夹在 1..{MAX_CONCURRENCY}）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_ai_extract(args.out, route=args.route, merge_chars=args.merge_chars,
                            write_doc=args.doc, merge_deterministic=args.merge,
                            concurrency=args.concurrency,
                            limit_sections=args.limit_sections or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
