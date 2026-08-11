"""共用文本归一化：把抽取阶段产生的「英文数词」噪声确定性还原为数字。

来源:ABNT 文档抽取把部分序号抽成了英文词("two" 而非 "2","Etwo" 而非 "E2"),
P1/P2/P3 都遇到。这是**确定性映射**(非 LLM 猜测),安全;原值始终可经 source_refs 溯源。

- normalize_numeric：整字段就是英文数词 → 数字（用于 # / ID / State / bit 等纯数字字段）。
- normalize_event_id：只在事件号(G..-SG..-E..)内部,把粘在 G/SG/E 后的英文数词 → 数字,
  其它一概不动（'SGAll' 保留;普通正文里的 'someone' 不受影响）。
"""
from __future__ import annotations

import re


_WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}

_WORD_ALT = "|".join(sorted(_WORD_TO_DIGIT, key=len, reverse=True))
# 事件号子串：G…-SG…-E…（允许逗号/空格的组号，如 "G1, 2, 3-SGAll-E255"）
_EVENT_ID = re.compile(r"G[\w,\s]*?-SG[\w]+-E[\w]+")
# 事件号内部：G/SG/E 前缀 + 紧跟的英文数词
_GLUED_WORD = re.compile(rf"(?<![A-Za-z])(E|SG|G)({_WORD_ALT})(?![A-Za-z])", re.IGNORECASE)


def normalize_numeric(value: object) -> str:
    """整字段是英文数词 → 数字；否则原样（去首尾空白）。"""
    text = str(value or "").strip()
    return _WORD_TO_DIGIT.get(text.casefold(), text)


def _fix_event_id(eid: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return match.group(1) + _WORD_TO_DIGIT[match.group(2).casefold()]
    return _GLUED_WORD.sub(repl, eid)


def normalize_event_id(text: str) -> str:
    """把文本里事件号(G..-SG..-E..)内部的英文数词还原为数字，其余文本不动。"""
    return _EVENT_ID.sub(lambda m: _fix_event_id(m.group(0)), str(text or ""))


# 公式注入守卫：Excel/LibreOffice/Sheets 把以这些字符开头的单元格文本当作公式执行。
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_NUMERIC_CELL = re.compile(r"[+-]?\d+(?:[.,]\d+)*%?")
_ACCESS_CODE_CELL = re.compile(r"[RWAXrwax/\- ]+")


def formula_safe(value: object) -> object:
    """防电子表格公式注入。

    技术标准文档（含导入的客户 .xlsx/PDF）里的自由文本可能以 = + - @（或制表/回车）开头，
    导出到 Excel/CSV 后会被当作活公式——既是注入向量也是数值损坏。这里对以危险前缀开头的
    字符串前置单引号转为纯文本；非字符串（数字/None）原样返回；纯数字串与 DLMS 访问码串
    （R-/--/-A-- 等）豁免，避免误伤合法值。
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] not in _FORMULA_TRIGGERS:
        return value
    if _NUMERIC_CELL.fullmatch(value) or _ACCESS_CODE_CELL.fullmatch(value):
        return value
    return "'" + value

# 枚举标号：行首/明确句界后的 "1." "2)" "3、"（1-2 位,后不接数字）。翻译把 a) b) c)
# 列表转写成数字编号是格式归一不是编造数字(test18 实测 3 条硬件翻译被误拒)——
# 漂移护栏的 int 提取侧先剥标号再算。普通词后的空格和右括号都不是边界，避免
# "CLASS 1)" 一类标准标题丢失语义数字；"4.9.3.2" 后接数字也不匹配。
_ENUM_MARKER = re.compile(
    r"(^[ \t]*|[\n\r.;；:：,，、。！？!?][ \t]*)(\d{1,2})\s*[.、)）](?!\d)",
    re.MULTILINE,
)


def strip_enum_markers(text: object) -> str:
    """剥除列表枚举标号本体,供漂移护栏数字提取用;编码扫描不得经此剥除(仍严格)。"""
    return _ENUM_MARKER.sub(lambda match: f"{match.group(1)} ", str(text or ""))

# 引用性编号——条款号/附录号/图表类型引用,是"地址"不是"数值"。遗漏检测(source number
# missing)的分母侧剥除:extract_ints 会把 "7.4.1" 拆成 7/4/1、"Clause 7" 贡献 7,
# 这些小整数淹没真参数值遗漏(test18 实测 25 条警告几乎全是此类)。编向/正文侧不剥。
# ≥2 个点才算条款号("10.5 m3/h" 这类小数是真值,不碰);字母头(C.9.2.1/B.2)整体剥。
_CLAUSE_REF = re.compile(r"\d+(?:\.\d+){2,}")
_LETTER_CLAUSE_REF = re.compile(r"[A-Z](?:\.\d+)+")
_REF_WORD_NUM = re.compile(
    r"(?<![A-Za-z])(?:subclause|clause|table|figure|annex|type|part|class|note|section|chapter)\s+\d{1,2}(?![0-9])",
    re.IGNORECASE)


def strip_reference_numbers(text: object) -> str:
    """剥除引用性编号本体(条款/附录/图表引用),供遗漏检测分母用。"""
    s = str(text or "")
    s = _CLAUSE_REF.sub(" ", s)
    s = _LETTER_CLAUSE_REF.sub(" ", s)
    s = _REF_WORD_NUM.sub(" ", s)
    return s


# 千位分隔并组("4 000"/"4,000" → "4000")——遗漏比对两侧同步归一,
# 否则源文 "4 000" 拆出的 4/000 对不上正文的 "4000"(假遗漏)
_DIGIT_GROUP = re.compile(r"(?<=\d)[\s,](?=\d{3}(?:\D|$))")


def join_digit_groups(text: object) -> str:
    return _DIGIT_GROUP.sub("", str(text or ""))

