from __future__ import annotations

import re
from collections.abc import Iterable


TEXT_REPLACEMENTS = {
    "\u00a0": " ",
    "\u3000": " ",
    "\uf020": " ",
    "\uf03d": "=",
    "\uf03e": ">",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2026": "...",
}


def clean_text(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value)
    for source, replacement in TEXT_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_match_term(value: object | None) -> str:
    text = clean_text(value).lower()
    if not text:
        return ""
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compile_term_pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    normalized_terms = sorted(
        {
            term
            for term in (normalize_match_term(value) for value in terms)
            if term
        },
        key=len,
        reverse=True,
    )
    if not normalized_terms:
        return None
    branches = [term_branch(term) for term in normalized_terms]
    return re.compile("|".join(branches), re.IGNORECASE)


def term_branch(term: str) -> str:
    prefix = r"(?<![a-z0-9])" if term[0].isalnum() else ""
    postfix = r"(?![a-z0-9])" if term[-1].isalnum() else ""
    return f"{prefix}({re.escape(term)})(?:e?s)?{postfix}"


def find_matched_terms(pattern: re.Pattern[str] | None, haystack: str, *, normalized: bool = False) -> list[str]:
    if pattern is None or not haystack:
        return []
    normalized_haystack = haystack if normalized else normalize_match_term(haystack)
    matched: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(normalized_haystack):
        term = next(group for group in match.groups() if group is not None)
        if not normalized:
            term = normalize_match_term(term)
        if term and term not in seen:
            matched.append(term)
            seen.add(term)
    return matched
