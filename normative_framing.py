"""Deterministic grammar shared by target normalization and claim validation."""
from __future__ import annotations

import re


TARGET_NORMATIVE_GRAMMAR_VERSION = "target-normative-grammar-v1"

_SENTENCE_BOUNDARY_RE = re.compile(r"[。！？!?；;\n]")
_ZH_PRODUCT_OBLIGATION_RE = re.compile(
    r"(?:该|本)?(?:产品|系统|设备|装置|电能表|电表|仪表|表计|终端|模块|软件|固件|"
    r"控制器|计量器|输出(?:端口)?|通道|接口)\s*"
    r"(?:应当|应|必须|须|不得|禁止|需要)"
)
_EN_PRODUCT_OBLIGATION_RE = re.compile(
    r"\b(?:the\s+|this\s+)?(?:product|system|device|equipment|meter|unit|module|"
    r"software|firmware|controller|terminal|output|channel|interface)\b"
    r"[^.!?;\n]{0,48}?\b(?:shall|must|is\s+required\s+to|is\s+to)\b",
    re.IGNORECASE,
)
_ZH_WEAK_CAPABILITY_RE = re.compile(
    r"(?:可以|能够|(?<![不未无许])可(?!靠(?:性)?|用性|行性|能性|见性|知|读性|"
    r"维护性|扩展性|获得性|接受性))"
)


def has_weak_capability(text: str) -> bool:
    """Return whether Chinese target text contains capability-style grammar."""
    return bool(_ZH_WEAK_CAPABILITY_RE.search(str(text or "")))


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    sentence_start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text, 0, start):
        sentence_start = match.end()
    next_boundary = _SENTENCE_BOUNDARY_RE.search(text, end)
    sentence_end = next_boundary.start() if next_boundary else len(text)
    return sentence_start, sentence_end


def product_obligation_governs_span(text: str, start: int, end: int) -> bool:
    """Conservatively prove a product obligation governs one target-field span.

    An obligation inside the span is self-contained. An obligation outside the
    span is accepted deterministically only for a colon-headed complement; other
    same-sentence relationships remain for the independent semantic verifier.
    """
    value = str(text or "")
    if not value or start < 0 or end <= start or end > len(value):
        return False
    sentence_start, sentence_end = _sentence_bounds(value, start, end)
    sentence = value[sentence_start:sentence_end]
    local_start = start - sentence_start
    local_end = end - sentence_start
    matches = [
        *list(_ZH_PRODUCT_OBLIGATION_RE.finditer(sentence)),
        *list(_EN_PRODUCT_OBLIGATION_RE.finditer(sentence)),
    ]
    for match in matches:
        if local_start <= match.start() and match.end() <= local_end:
            return True
        if match.end() <= local_start:
            bridge = sentence[match.end():local_start]
            if re.search(r"[:：]\s*$", bridge):
                return True
    return False


def target_is_self_contained_product_obligation(text: str) -> bool:
    value = str(text or "")
    return product_obligation_governs_span(value, 0, len(value)) if value else False
