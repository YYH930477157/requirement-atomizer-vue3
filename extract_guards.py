"""抽取护栏层（F3 拆分自 ai_extract）：确定性质量信号，只标不拦。

漏值检测（数值清单没进交付物）、模糊验收检测（"符合要求"式空话）、去重键、文本归一。
"""
from __future__ import annotations

import json
import re
from typing import Any

from cosem_behavior_spec import extract_codes, extract_ints

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


_VAGUE_PHRASES = ("符合要求", "满足要求", "正常工作", "工作正常", "运行正常", "表现良好",
                  "适当", "合理", "正确处理", "妥善处理", "gracefully", "properly",
                  "reasonable", "as expected", "correctly", "appropriately",
                  # 0715 内容审计扩面:全量审出 10 处空话验收漏网,词面补齐(通用短语)
                  "满足标准", "符合规定", "符合标准", "无异常", "正确运行", "保持正常",
                  "功能完好", "无误", "按规定", "满足本标准", "as specified", "as required",
                  "functions normally", "works as intended", "without issue")


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


# --- 忠实性守恒(0715 抽取质量重构,通用规则)---------------------------------
# 双线内容审计:186 条全量审出 29 处误读——现有护栏只看编码/数字,语义方向全盲。
# 可确定性化的两类在此拦截(软标不硬拒,自动判语义有误伤风险):
# ①情态升格:引句 should/recommended(建议) → 正文"必须/严禁/不得"(强制);
# ②标准号张冠李戴:正文引用的标准号不在本节基线里(利用了背景整数豁免的漏洞)。

_SOURCE_WEAK_MODAL_RE = re.compile(r"\bshould\b|\brecommended\b|\bmay\b", re.IGNORECASE)
_SOURCE_STRONG_MODAL_RE = re.compile(r"\bshall\b|\bmust\b|\brequired\b", re.IGNORECASE)
_PRODUCED_STRONG_RE = re.compile(r"必须|严禁|不得|禁止")
_STANDARD_REF_RE = re.compile(
    r"\b(?:EN|IEC|ISO|CEN|CENELEC|IEEE|ITU|NBR|ABNT|WELMEC|OIML)(?:\s?ISO)?\s?\d{2,6}(?:-\d{1,3})*\b",
    re.IGNORECASE)


def _modal_inflation(req: dict[str, Any]) -> bool:
    """引句只有建议性情态(should/may,无 shall/must),正文却用了强制表述 → 升格待核。"""
    quote = str(req.get("source_quote") or "")
    if not quote or not _SOURCE_WEAK_MODAL_RE.search(quote) or _SOURCE_STRONG_MODAL_RE.search(quote):
        return False
    produced = " ".join([str(req.get("title") or ""), str(req.get("description") or "")]
                        + [str(s.get("text") or "") for s in req.get("sub_items") or []])
    return bool(_PRODUCED_STRONG_RE.search(produced))


def _norm_standard_ref(token: str) -> str:
    return re.sub(r"\s+", "", token).upper()


def _foreign_standard_refs(req: dict[str, Any], baseline: str) -> list[str]:
    """正文里出现、但本节基线(原文+被引条款+术语定义)没有的标准号——张冠李戴待核。

    背景整数豁免(context_ints)会放行标准号数字部分,误归属由此漏网(实证:本标准
    被写成 EN 14236)——标准号按\"前缀+号\"整体核,不吃整数豁免。"""
    produced = _produced_text(req)
    base_refs = {_norm_standard_ref(m.group(0)) for m in _STANDARD_REF_RE.finditer(baseline or "")}
    foreign = []
    for m in _STANDARD_REF_RE.finditer(produced):
        token = _norm_standard_ref(m.group(0))
        if token not in base_refs and token not in foreign:
            foreign.append(m.group(0))
    return foreign


# 纯术语定义后筛(0715):术语章条目无任何约束力标记 → 不是需求(内容审计:14 条
# "定义X术语"是单一最大噪声源)。带固定规则/取值/限值的定义仍保留(prompt 本有此意,
# 模型守不住 → 确定性兜底)。
_TERMS_SECTION_RE = re.compile(r"terms?\b|definitions?\b|abbreviat|术语|定义", re.IGNORECASE)
_CONSTRAINT_MARK_RE = re.compile(
    r"[0-9０-９]|\bshall\b|\bmust\b|\bshould\b|\bonly\b|\bat least\b|\bnot exceed\b|"
    r"\bvalid for\b|\balways\b|必须|不得|只能|仅限|至少|不超过|应当|须", re.IGNORECASE)


def _is_definition_stub(req: dict[str, Any], section: dict[str, Any]) -> bool:
    context = " ".join([str(section.get("heading") or ""), str(section.get("section_id") or "")])
    if not _TERMS_SECTION_RE.search(context):
        return False
    if req.get("threshold_table"):
        return False
    produced = " ".join([str(req.get("title") or ""), str(req.get("description") or ""),
                         str(req.get("source_quote") or "")]
                        + [str(s.get("text") or "") for s in req.get("sub_items") or []])
    return not _CONSTRAINT_MARK_RE.search(produced)


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


def _norm_ws(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _produced_text(requirement: dict[str, Any]) -> str:
    # sub_items 与 threshold_table 此前不在漂移扫描内（2026-07-08 审计 B3/B4）：
    # 参数表被注释为"数值是研发的命根子"却是校验最弱的字段——编造/换算的数值零检测。
    # 纳入后：编造编码走硬拦（draft+拦截注），无据数字走软标（批注视图 suspicion 徽章）。
    sub_texts = " ".join(
        str(s.get("text") or "") for s in requirement.get("sub_items") or [] if isinstance(s, dict))
    table = requirement.get("threshold_table") or {}
    table_cells: list[str] = []
    if isinstance(table, dict):
        table_cells.extend(str(c) for c in table.get("columns") or [])
        for row in table.get("rows") or []:
            table_cells.extend(str(c) for c in (row if isinstance(row, list) else [row]))
    return " ".join([
        str(requirement.get("title") or ""),
        str(requirement.get("description") or ""),
        str(requirement.get("source_quote") or ""),
        " ".join(str(a) for a in requirement.get("acceptance_criteria") or []),
        # design_options 是"非规范候选"但直达交付描述（C1，0710 评审）：编造编码/数字同样
        # 要进漂移扫描——"不得带无依据容量"此前只是提示词约定
        " ".join(str(a) for a in requirement.get("design_options") or []),
        sub_texts,
        " ".join(table_cells),
    ])


