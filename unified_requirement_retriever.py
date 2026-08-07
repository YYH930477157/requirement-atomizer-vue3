"""Unified requirement retriever (WS-C3).

把三库——``requirement_library``（既有功能需求汇总库）、``base_library``（历史 xlsx
基本需求库）、``solution_library``（历史项目 design_options 方案库）——统一接入
T3 已交付的 ``RequirementRetriever`` 插件点。

默认行为：
- 词面 Jaccard（``LiteralRequirementRetriever``）跨库检索；
- vector 开关仅预研，无向量依赖，请求时如实回退词面；
- 返回结果带 ``library_source`` 字段区分来源，下游确定性校验不放松。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from requirement_schema import (
    RequirementRetriever,
    build_requirement_retriever,
    search_requirement_library,
    tokenize_requirement,
)


UNIFIED_RETRIEVER_KIND = "unified-literal"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _prepare_library(rows: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    """给每条库记录添加/刷新 tokens 与来源标记。"""
    prepared: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = dict(row)
        # 统一搜索文本：objective/behaviors/option/title/description
        text_parts = [
            str(entry.get("objective") or ""),
            str(entry.get("title") or ""),
            str(entry.get("description") or ""),
            str(entry.get("option") or ""),
            " ".join(str(b) for b in (entry.get("behaviors") or [])),
        ]
        text = " ".join(p for p in text_parts if p).strip()
        entry["tokens"] = sorted(tokenize_requirement(text))
        entry["library_source"] = source
        prepared.append(entry)
    return prepared


class UnifiedRequirementRetriever:
    """跨三库词面检索器，满足 ``RequirementRetriever`` Protocol。"""

    retriever_kind = UNIFIED_RETRIEVER_KIND

    def __init__(
        self,
        libraries: dict[str, list[dict[str, Any]]],
        *,
        min_overlap: int = 1,
    ) -> None:
        self.sources: dict[str, list[dict[str, Any]]] = {}
        for source, rows in libraries.items():
            self.sources[source] = _prepare_library(rows, source=source)
        self.min_overlap = max(1, int(min_overlap))

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        query_tokens = tokenize_requirement(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, bool, str, str, dict[str, Any]]] = []
        for source, rows in self.sources.items():
            for entry in rows:
                entry_tokens = set(entry.get("tokens") or [])
                if not entry_tokens:
                    continue
                intersection = query_tokens & entry_tokens
                if len(intersection) < self.min_overlap:
                    continue
                union = query_tokens | entry_tokens
                score = len(intersection) / len(union) if union else 0.0
                if score <= 0.0:
                    continue
                corrected = bool(entry.get("ownership_corrected"))
                title = str(entry.get("title") or entry.get("objective") or entry.get("option") or "")
                scored.append((score, corrected, source, title, entry))
        # 主键 score 降序；修正优先；来源稳定；标题稳定
        scored.sort(key=lambda row: (-row[0], 0 if row[1] else 1, row[2], row[3]))
        results = []
        for score, _corrected, _source, _title, entry in scored[:limit]:
            rendered = {key: value for key, value in entry.items() if key != "tokens"}
            rendered["overlap_score"] = round(score, 4)
            results.append(rendered)
        return results


def default_library_paths() -> dict[str, Path | None]:
    """返回三库路径配置；未配置返回 None。"""
    return {
        "requirement": _env_path("RATOMIZER_REQUIREMENT_LIBRARY"),
        "base": _env_path("RATOMIZER_BASE_LIBRARY"),
        "solution": _env_path("RATOMIZER_SOLUTION_LIBRARY"),
    }


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def build_unified_retriever(
    *,
    library_paths: dict[str, Path | None] | None = None,
    retriever: RequirementRetriever | None = None,
) -> RequirementRetriever:
    """构造三库统一检索器。

    ``retriever`` 注入优先（测试/外部向量插件）；否则按默认词面跨库检索。
    """
    if retriever is not None:
        return retriever
    paths = library_paths or default_library_paths()
    libraries: dict[str, list[dict[str, Any]]] = {}
    for source, path in paths.items():
        if path is None:
            continue
        libraries[source] = _load_jsonl(path)
    return UnifiedRequirementRetriever(libraries)


def unified_requirement_search(
    query: str,
    *,
    library_paths: dict[str, Path | None] | None = None,
    limit: int = 20,
    retriever: RequirementRetriever | None = None,
) -> dict[str, Any]:
    """跨三库检索入口：返回统一形态结果 + 来源统计。"""
    retriever_obj = build_unified_retriever(library_paths=library_paths, retriever=retriever)
    results = retriever_obj.search(query, limit=limit)
    sources: dict[str, int] = {}
    for row in results:
        source = str(row.get("library_source") or "unknown")
        sources[source] = sources.get(source, 0) + 1
    return {
        "schema": "unified-requirement-search/v1",
        "kind": "unified_requirement_search",
        "query": query,
        "retriever_kind": getattr(retriever_obj, "retriever_kind", "unknown"),
        "matches": len(results),
        "results": results,
        "source_counts": sources,
    }


# Back-compat: when only the legacy requirement library is configured, behave like
# the original single-library search.
__all__ = [
    "UnifiedRequirementRetriever",
    "build_unified_retriever",
    "unified_requirement_search",
    "UNIFIED_RETRIEVER_KIND",
]
