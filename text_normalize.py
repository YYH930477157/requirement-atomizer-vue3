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
