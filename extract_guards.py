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


def values_left_behind(req: dict[str, Any], source: str) -> int:
    """确定性漏值检测：引句附近的数值清单没进需求（真实案例：粉尘粒径/成分百分比全被
    "规定的范围"指代吞掉，threshold_table=None——研发拿不到数值等于没写）。只标记不拦截。

    分母格式归一（0715 v2 审计:误报多为窗口里的条款号/枚举标号/页码）:与 0714
    analyze 侧遗漏分母同一套剥法——条款/引用号是"地址"不是"数值"。"""
    from text_normalize import join_digit_groups, strip_enum_markers, strip_reference_numbers
    quote = str(req.get("source_quote") or "")
    if not quote:
        return 0
    pos = source.find(quote)
    if pos < 0:
        return 0
    window = source[pos:pos + max(len(quote), _LEFT_BEHIND_WINDOW)]
    window = join_digit_groups(strip_reference_numbers(strip_enum_markers(window)))
    captured = extract_ints(join_digit_groups(" ".join([
        _produced_text(req), json.dumps(req.get("threshold_table") or {}),
    ])))
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


def vague_acceptance(req: dict[str, Any]) -> list[str]:
    """返回不可测的验收条目（命中空话且无任何可判定判据）。只标不拦。"""
    vague: list[str] = []
    for item in (req.get("acceptance_criteria") or []):
        text = str(item)
        low = text.lower()
        if any(p in low for p in _VAGUE_PHRASES) and not _TESTABLE_HINT_RE.search(text) \
                and not extract_codes(text):
            vague.append(text[:80])
    return vague


# 英文数词/序数并入整数基线(0715 v2 审计实证:原文 "three times",正文 "3 倍"——
# 基线只认阿拉伯数字,把有据验收当漂移剥掉,核心计量判据丢失。通用映射非文档词汇)
_SPELLED_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
}
_SPELLED_NUM_RE = re.compile(
    r"\b(" + "|".join(sorted(_SPELLED_NUMBERS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def source_int_baseline(text: str) -> set[str]:
    """整数基线 = 阿拉伯数字 ∪ 千分位并组("3,200"/"1 008"→3200/1008) ∪ 英文数词折算。

    千分位(0715 v2 审计):原文 "3,200 cycles" 被拆成 3/200,正文 "3200" 判无据,
    关键验收被剥空——与 0714 遗漏分母同一病灶,基线侧并组补齐。"""
    from text_normalize import join_digit_groups
    raw = str(text or "")
    ints = set(extract_ints(raw)) | set(extract_ints(join_digit_groups(raw)))
    for m in _SPELLED_NUM_RE.finditer(raw):
        ints.add(_SPELLED_NUMBERS[m.group(1).casefold()])
    return ints


def produced_ints(text: str) -> set[str]:
    """产出侧整数提取(千分位并组,与基线同口径——产出写 "3,200" 同样并成 3200)。"""
    from text_normalize import join_digit_groups
    return set(extract_ints(join_digit_groups(str(text or ""))))


# 数值配对待核(0715 五刀):调包类误读(甲条件配乙限值,如 1↔5 l/h 对调)两个数字都在
# 原文里,漂移检测原理上拦不住。确定性能做的是**路由注意力**:无参数表兜底、且产出与
# 原文同单位都出现多档数值 → 软标提醒核对"数值-条件配对"。深度复核走自检定向指令。
_VALUE_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:[.,]\d+)?)\s*"
    r"(l/h|m3/h|m³/h|mbar|bar|kPa|Pa|MHz|kHz|Hz|mm|cm|kg|g|ms|min|%|°C|℃|V|mA|A|mT|h|s)"
    r"(?![A-Za-z])")


def _unit_values(text: str) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for value, unit in _VALUE_UNIT_RE.findall(str(text or "")):
        values.setdefault(unit.casefold(), set()).add(value.replace(",", "."))
    return values


_NUM_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _num_multiset(text: str) -> tuple[str, ...]:
    """文本里全部数值 token 的多重集(小数点归一)——近重复判定的数字守卫。"""
    return tuple(sorted(t.replace(",", ".") for t in _NUM_TOKEN_RE.findall(str(text or ""))))


def _gram_jaccard(a: str, b: str, n: int = 3) -> float:
    """去空白+标点字符 n-gram Jaccard。短文本(<2n)退回精确比较,不给假高分。

    v6 校准:标点/下划线剥离后真复读(P_max↔Pmax、≤↔不超过格式变体)J=0.53-0.67,
    语义不同对 0.41(异档数值对靠数字守卫另拦)——0.5 阈值可分离。"""
    na = re.sub(r"[\W_]+", "", str(a or ""))
    nb = re.sub(r"[\W_]+", "", str(b or ""))
    if len(na) < 2 * n or len(nb) < 2 * n:
        return 1.0 if na and na == nb else 0.0
    ga = {na[i:i + n] for i in range(len(na) - n + 1)}
    gb = {nb[i:i + n] for i in range(len(nb) - n + 1)}
    return len(ga & gb) / max(1, len(ga | gb))


# 中文引用词+编号(表8/条款4.9.2/附录D…)——产出侧是中文,text_normalize 只剥英文引用词
_CN_REF_RE = re.compile(r"(?:表|图|条款|章节|附录|第)\s*[0-9A-Z]+(?:\.\d+)*\s*(?:节|章|条)?")
# 型号/接口指代符(RS232/RS-232/IP54/JTAG2…):字母≥2 后紧跟数字≥2 是命名不是数值。
# 数值+单位是数字在前(20mA),不会误伤。v6 实测:验收因枚举 RS232 被整行误杀清空
_DESIGNATOR_RE = re.compile(r"\b[A-Za-z]{2,}-?\d{2,}\b")


def strip_produced_refs(text: str) -> str:
    """剥除产出文本里的引用性编号(条款/标准号/表图号/型号指代符),供**交付字段整移判定**分母用。

    v5 审计:验收行因带 EN 标准号示例被"无依据数字"整行误移进 notes,把核心阈值
    (≤1/3 MPE)一起带走——引用编号是"地址"不是"数值",不该触发整移。
    数字漂移**软标**仍按原文本计算不剥(引用号抄错也值得一个待核标)。"""
    from text_normalize import strip_reference_numbers
    s = strip_reference_numbers(text)
    s = _STANDARD_REF_RE.sub(" ", s)
    s = _CN_REF_RE.sub(" ", s)
    s = _DESIGNATOR_RE.sub(" ", s)
    return s


def _threshold_desc_mismatch(req: dict[str, Any]) -> list[str]:
    """正文/验收与自身 threshold_table 的单元格级一致性核对(确定性,只标不拦)。

    v5 实测:表通道可靠(6 处展开 5 对 1 错),错的都在自然语言通道——Type 1 阀门
    1 l/h 被正文写成 5 l/h,而同条目的表写的是对的。句子提及行键(Type 1/1型)与
    某列条件数值时,该行该列的单元格数值必须出现在句中,否则记一处不一致。"""
    tt = req.get("threshold_table") or {}
    rows = tt.get("rows") or []
    cols = [str(c) for c in (tt.get("columns") or [])]
    if not rows or len(cols) < 2:
        return []
    text = " ".join([str(req.get("description") or "")]
                    + [str(x) for x in (req.get("acceptance_criteria") or [])])
    findings: list[str] = []
    for sent in re.split(r"[。;；\n]", text):
        if not _NUM_TOKEN_RE.search(sent):
            continue
        for row in rows:
            cells = [str(c) for c in (row if isinstance(row, list) else [row])]
            if not cells:
                continue
            key = cells[0].strip()
            key_digits = re.findall(r"\d+", key)
            key_res = [rf"(?:type\s*{kd}|{kd}\s*型|类型\s*{kd}|class\s*{kd}|{kd}\s*级)"
                       for kd in key_digits[:1]]
            mentioned = bool(key) and (key.casefold() in sent.casefold() or any(
                re.search(kr, sent, re.IGNORECASE) for kr in key_res))
            if not mentioned:
                continue
            # 只掩掉"键的提及文本"再取数——单元格值可能与键数字相同(Type 1 的限值恰为 1),
            # 整集扣除键数字会把合法的一致数值一起扣掉,制造假阳性
            masked = sent.replace(key, " ") if key else sent
            for kr in key_res:
                masked = re.sub(kr, " ", masked, flags=re.IGNORECASE)
            sent_nums = {t.replace(",", ".") for t in _NUM_TOKEN_RE.findall(masked)}
            for ci in range(1, min(len(cells), len(cols))):
                cond = [t.replace(",", ".") for t in _NUM_TOKEN_RE.findall(cols[ci])]
                cell = [t.replace(",", ".") for t in _NUM_TOKEN_RE.findall(cells[ci])]
                if not cond or not cell:
                    continue
                if cond[0] in sent_nums and not set(cell) & sent_nums:
                    findings.append(f"{key}@{cols[ci][:20]}={cells[ci]}")
    return list(dict.fromkeys(findings))


def _multi_value_pairing_risk(req: dict[str, Any], source: str) -> list[str]:
    """返回产出与原文都出现 ≥2 档数值的单位清单(配对调包风险区);有参数表的不标
    (表格逐格照抄,配对由表结构承载)。"""
    if req.get("threshold_table"):
        return []
    produced = _unit_values(_produced_text(req))
    src_units = _unit_values(source)
    risky = [unit for unit, vals in produced.items()
             if len(vals) >= 2 and len(src_units.get(unit) or ()) >= 2]
    return sorted(risky)


# --- 忠实性守恒(0715 抽取质量重构,通用规则)---------------------------------
# 双线内容审计:186 条全量审出 29 处误读——现有护栏只看编码/数字,语义方向全盲。
# 可确定性化的两类在此拦截(软标不硬拒,自动判语义有误伤风险):
# ①情态升格:引句 should/recommended(建议) → 正文"必须/严禁/不得"(强制);
# ②标准号张冠李戴:正文引用的标准号不在本节基线里(利用了背景整数豁免的漏洞)。

_SOURCE_WEAK_MODAL_RE = re.compile(
    r"\bshould\b|\brecommended\b|\bmay\b(?!\s+not\b)", re.IGNORECASE)
_SOURCE_STRONG_MODAL_RE = re.compile(r"\bshall\b|\bmust\b|\brequired\b", re.IGNORECASE)
_PRODUCED_STRONG_RE = re.compile(r"必须|严禁|不得|禁止")
_STANDARD_REF_RE = re.compile(
    r"\b(?:EN|IEC|ISO|CEN|CENELEC|IEEE|ITU|NBR|ABNT|WELMEC|OIML)(?:\s?ISO)?\s?\d{2,6}(?:-\d{1,3})*\b",
    re.IGNORECASE)


def _modal_inflation(req: dict[str, Any], source_baseline: str | None = None) -> bool:
    """引句只有建议性情态且完整来源无强情态,正文却用了强制表述 → 升格待核。

    ``may not`` 本身表达禁止/不允许,不能按弱情态 ``may`` 处理。自动软化还要求完整
    来源基线没有 shall/must/required,避免短引句漏掉同一条款里的强制依据后误改正文。
    """
    quote = str(req.get("source_quote") or "")
    baseline = str(source_baseline if source_baseline is not None else quote)
    if (not quote or not _SOURCE_WEAK_MODAL_RE.search(quote)
            or _SOURCE_STRONG_MODAL_RE.search(quote)
            or _SOURCE_STRONG_MODAL_RE.search(baseline)):
        return False
    produced = " ".join([str(req.get("title") or ""), str(req.get("description") or "")]
                        + [str(s.get("text") or "") for s in req.get("sub_items") or []])
    return bool(_PRODUCED_STRONG_RE.search(produced))


_MODAL_SOFTEN_MAP = [("必须", "宜"), ("严禁", "不宜"), ("不得", "不宜"), ("禁止", "不宜")]


def _soften_modals(text: str) -> str:
    """把强制情态词软化为建议级(should→宜)——仅在情态升格实锤时由调用方使用。

    v6 审计:should→必须 升格反复出现且 prompt 约束挡不住(u36 差评);引句是
    should-only 时强制措辞是确定性可证的误译,按引句校正比只挂软标更诚实。"""
    s = str(text or "")
    for hard, soft in _MODAL_SOFTEN_MAP:
        s = s.replace(hard, soft)
    return s


def _norm_standard_ref(token: str) -> str:
    return re.sub(r"\s+", "", token).upper()


def _standard_ref_root(token: str) -> str:
    m = re.search(r"\d{2,6}", token)
    return m.group(0) if m else ""


def foreign_standard_refs(req: dict[str, Any], baseline: str) -> list[str]:
    """正文里出现、但本节基线(原文+被引条款+术语定义)没有的标准号——张冠李戴待核。

    背景整数豁免(context_ints)会放行标准号数字部分,误归属由此漏网(实证:本标准
    被写成 EN 14236)——标准号按\"前缀+号\"整体核,不吃整数豁免。
    比对按**号根**(0715 v2 审计:\"ISO 6270\" vs 基线 \"EN ISO 6270-1\" 前缀变体全是
    误报)——同一主号即同一标准,机构前缀写法差异不定罪。"""
    produced = _produced_text(req)
    base_roots = {_standard_ref_root(m.group(0)) for m in _STANDARD_REF_RE.finditer(baseline or "")}
    base_roots.discard("")
    foreign = []
    seen: set[str] = set()
    for m in _STANDARD_REF_RE.finditer(produced):
        root = _standard_ref_root(m.group(0))
        if root and root not in base_roots and root not in seen:
            seen.add(root)
            foreign.append(m.group(0))
    return foreign


# 纯术语定义后筛(0715):术语章条目无任何约束力标记 → 不是需求(内容审计:14 条
# "定义X术语"是单一最大噪声源)。带固定规则/取值/限值的定义仍保留(prompt 本有此意,
# 模型守不住 → 确定性兜底)。
_TERMS_SECTION_RE = re.compile(r"terms?\b|definitions?\b|abbreviat|术语|定义", re.IGNORECASE)
_CONSTRAINT_MARK_RE = re.compile(
    r"\bshall\b|\bmust\b|\bshould\b|\bonly\b|\bat least\b|\bnot exceed\b|"
    r"\bvalid for\b|\balways\b|必须|不得|只能|仅限|至少|不超过|应当|须", re.IGNORECASE)
# 数字只在带比较语境时才算约束证据(带单位另由 _VALUE_UNIT_RE 判)——术语章里条款号/
# 型号枚举(Type 1、缩写+序号)是裸数字最大来源,v4 实测 4 条定义条目全靠裸数字混过桩判定
_CONSTRAINT_VALUE_RE = re.compile(
    r"(?:[≤≥<>±=]|max\w*|min\w*|最大|最小|上限|下限)\s*[0-9０-９]", re.IGNORECASE)


def _is_definition_stub(req: dict[str, Any], section: dict[str, Any]) -> bool:
    context = " ".join([str(section.get("heading") or ""), str(section.get("section_id") or "")])
    if not _TERMS_SECTION_RE.search(context):
        return False
    if req.get("threshold_table"):
        return False
    produced = " ".join([str(req.get("title") or ""), str(req.get("description") or ""),
                         str(req.get("source_quote") or "")]
                        + [str(s.get("text") or "") for s in req.get("sub_items") or []])
    if _CONSTRAINT_MARK_RE.search(produced):
        return False
    # 带单位的数值 / 比较语境里的数字 = 定义携带固定规则,保留
    if _unit_values(produced) or _CONSTRAINT_VALUE_RE.search(produced):
        return False
    return True


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
    compliance_texts = " ".join(
        str(s.get("text") or "")
        for s in requirement.get("compliance_obligations") or []
        if isinstance(s, dict)
    )
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
        compliance_texts,
        " ".join(table_cells),
    ])


