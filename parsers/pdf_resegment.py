"""PDF 词典重分词器（A8②）。

机翻 PDF 常见碎词问题：词内被真实空格字形切断（"Water M eters"）。
本模块提供可配置词典的重分词器，默认关闭；开启后作为 pdf_parser 去碎流程的
可选增强路径。
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


PDF_RESEG_SWITCH = "RATOMIZER_PDF_RESEG"
PDF_RESEG_WORDLIST = "RATOMIZER_PDF_RESEG_WORDLIST"
PDF_RESEG_VERSION = "pdf-resegment-v1"

# 默认补充词表（计量/电力领域常见词，与 pdf_parser 内置补充词表同源但不重复）
DEFAULT_RESEG_WORDS: tuple[str, ...] = (
    "meter", "meters", "metrology", "metrological", "measurement", "measurements",
    "electricity", "electrical", "electromagnetic", "firmware", "modem", "modem",
    "profile", "profiles", "register", "registers", "tariff", "tariffs",
    "interface", "interfaces", "object", "objects", "attribute", "attributes",
    "association", "associations", "authentication", "encryption", "signature",
    "bidirectional", "unidirectional", "multitariff", "nonvolatile", "alphanumeric",
    "configuration", "configurable", "communication", "communicate", "protocol",
    "verification", "verifiable", "conformity", "compliance", "certificate",
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-]+")


def _load_yaml_wordlist(path: Path) -> list[str]:
    """从 YAML 加载词表；缺失/损坏返回空列表（调用方回退默认）。"""
    try:
        import yaml  # type: ignore[import-untyped]
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        words = data.get("words") or data.get("wordlist") or data.get("resegment") or []
    else:
        words = data or []
    if isinstance(words, (list, tuple)):
        return [str(w).strip().lower() for w in words if str(w).strip()]
    return []


@lru_cache(maxsize=1)
def load_resegment_wordlist() -> frozenset[str]:
    """加载重分词词典：env YAML > 内置。"""
    raw: list[str] = list(DEFAULT_RESEG_WORDS)
    env_path = os.environ.get(PDF_RESEG_WORDLIST, "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if path.suffix.lower() in (".yaml", ".yml"):
            raw.extend(_load_yaml_wordlist(path))
        else:
            try:
                raw.extend(
                    line.strip().lower()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")
                )
            except OSError:
                pass
    return frozenset(dict.fromkeys(raw))


def _try_merge(token: str, wordlist: frozenset[str]) -> str | None:
    """尝试把带空格的 token 合并成词典词；成功返回词典形态，失败返回 None。"""
    alphanumeric = "".join(_TOKEN_RE.findall(token))
    if not alphanumeric:
        return None
    lower = alphanumeric.lower()
    if lower in wordlist:
        return lower
    return None


def resegment_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """对文本做词典重分词，返回 (新文本, 变更事件列表)。

    策略保守：只处理由空格切断的字母数字片段；仅当合并结果命中词典时才替换。
    采用贪心：从每个 alnum token 开始，尝试与后续 1-3 个 token 合并；命中最长词典
    词时替换。
    """
    wordlist = load_resegment_wordlist()
    if not wordlist:
        return text, []
    events: list[dict[str, Any]] = []
    # 把文本拆成 (token, separator) 对
    tokens = _TOKEN_RE.findall(text)
    if len(tokens) < 2:
        return text, []
    # 记录每个 token 在原文中的起止位置
    token_spans: list[tuple[int, int]] = []
    pos = 0
    for token in tokens:
        idx = text.find(token, pos)
        if idx < 0:
            break
        token_spans.append((idx, idx + len(token)))
        pos = idx + len(token)
    if len(token_spans) < 2:
        return text, []
    pieces: list[str] = []
    cursor = 0
    index = 0
    while index < len(tokens):
        merged_word: str | None = None
        merge_end_index = index
        # 尝试合并后续最多 3 个 token（即最多 4 个 token）
        for end in range(min(index + 3, len(tokens) - 1), index, -1):
            candidate = "".join(tokens[index:end + 1])
            lower = candidate.lower()
            if lower in wordlist:
                # 在相同长度内 prefer 最长；end 从大到小，第一个命中即最长
                if merged_word is None or len(candidate) > len(merged_word):
                    merged_word = lower
                    merge_end_index = end
        if merged_word is not None:
            start = token_spans[index][0]
            end = token_spans[merge_end_index][1]
            pieces.append(text[cursor:start])
            pieces.append(merged_word)
            events.append({
                "rule": "dictionary_resegment",
                "start": start,
                "end": end,
                "before": text[start:end],
                "after": merged_word,
                "version": PDF_RESEG_VERSION,
            })
            cursor = end
            index = merge_end_index + 1
        else:
            index += 1
    pieces.append(text[cursor:])
    return "".join(pieces), events


def resegment_enabled() -> bool:
    return os.environ.get(PDF_RESEG_SWITCH, "").strip().lower() in {"1", "true", "yes", "on"}


def maybe_resegment(text: str) -> tuple[str, list[dict[str, Any]]]:
    """开关受控入口：默认关，开启时执行。"""
    if not resegment_enabled():
        return text, []
    return resegment_text(text)
