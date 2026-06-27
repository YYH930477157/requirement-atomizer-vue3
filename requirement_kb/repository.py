from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .matching import clean_text, compile_term_pattern, find_matched_terms, normalize_match_term


KNOWN_ENTRY_KEYS = {
    "id",
    "type",
    "layer",
    "name",
    "aliases",
    "keywords",
    "domain_tags",
    "definition",
    "relations",
}


@dataclass(frozen=True)
class KBEntry:
    kb_id: str
    entry_id: str
    entry_type: str
    layer: str
    name: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    domain_tags: tuple[str, ...]
    definition: str
    relations: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    match_pattern: re.Pattern[str] | None = field(default=None, compare=False, repr=False)

    def to_dict(self, include_metadata: bool = True) -> dict[str, Any]:
        row = {
            "kb_id": self.kb_id,
            "entry_id": self.entry_id,
            "type": self.entry_type,
            "layer": self.layer,
            "name": self.name,
            "aliases": list(self.aliases),
            "keywords": list(self.keywords),
            "domain_tags": list(self.domain_tags),
            "definition": self.definition,
            "relations": list(self.relations),
        }
        if include_metadata:
            row["metadata"] = self.metadata
        return row


@dataclass(frozen=True)
class KBInfo:
    kb_id: str
    name: str
    version: str
    path: str
    entries: int


class KnowledgeRepository:
    """File-backed knowledge repository with a stable query interface."""

    def __init__(self, entries: list[KBEntry], infos: list[KBInfo]):
        self.entries = entries
        self.infos = infos
        self._by_entry_id = {(entry.kb_id, entry.entry_id): entry for entry in entries}
        # 同一 entry_id 可能跨多个 KB 文件出现（实测默认 4 个 KB 有 86 处冲突）。
        # 旧实现用 dict 推导，悄悄保留「最后加载」的那份、遮蔽权威条目，且结果随加载顺序漂移。
        # 改为「首个加载优先」（default_kb_paths 把权威 KB 排在前），并记录冲突以便暴露而非静默。
        self._by_id: dict[str, KBEntry] = {}
        self._id_collisions: dict[str, list[str]] = {}
        for entry in entries:
            existing = self._by_id.get(entry.entry_id)
            if existing is None:
                self._by_id[entry.entry_id] = entry
            elif entry.kb_id != existing.kb_id:
                self._id_collisions.setdefault(entry.entry_id, [existing.kb_id]).append(entry.kb_id)

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> "KnowledgeRepository":
        entries: list[KBEntry] = []
        infos: list[KBInfo] = []
        for path in paths:
            resolved = path.expanduser().resolve()
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            kb_id = str(payload.get("kb_id") or resolved.stem)
            raw_entries = payload.get("entries", [])
            for raw in raw_entries:
                name = clean_text(raw.get("name"))
                keywords = sorted(
                    {
                        normalize_match_term(term)
                        for term in [name, *raw.get("aliases", []), *raw.get("keywords", [])]
                        if len(normalize_match_term(term)) > 1
                    },
                    key=len,
                    reverse=True,
                )
                match_pattern = compile_term_pattern(keywords)
                metadata = {key: value for key, value in raw.items() if key not in KNOWN_ENTRY_KEYS}
                entries.append(
                    KBEntry(
                        kb_id=kb_id,
                        entry_id=str(raw.get("id") or name),
                        entry_type=str(raw.get("type") or "term"),
                        layer=str(raw.get("layer") or payload.get("layer") or "term"),
                        name=name,
                        aliases=tuple(clean_text(v) for v in raw.get("aliases", [])),
                        keywords=tuple(keywords),
                        domain_tags=tuple(str(v) for v in raw.get("domain_tags", [])),
                        definition=clean_text(raw.get("definition")),
                        relations=tuple(raw.get("relations", [])),
                        metadata=metadata,
                        match_pattern=match_pattern,
                    )
                )
            infos.append(
                KBInfo(
                    kb_id=kb_id,
                    name=clean_text(payload.get("name")) or kb_id,
                    version=str(payload.get("version") or ""),
                    path=str(resolved),
                    entries=len(raw_entries),
                )
            )
        return cls(entries, infos)

    def info(self) -> list[dict[str, Any]]:
        return [info.__dict__ for info in self.infos]

    def id_collisions(self) -> dict[str, list[str]]:
        """entry_id -> 含该 id 的全部 kb_id 列表（仅跨 KB 冲突的 id）。"""
        return {entry_id: list(kb_ids) for entry_id, kb_ids in self._id_collisions.items()}

    def get(self, entry_id: str, kb_id: str | None = None) -> dict[str, Any] | None:
        entry = self._by_entry_id.get((kb_id, entry_id)) if kb_id else self._by_id.get(entry_id)
        if entry is None:
            return None
        row = entry.to_dict()
        if not kb_id and entry_id in self._id_collisions:
            # 未指定 kb_id 且该 id 跨多个 KB：返回首个（权威优先），但暴露歧义，
            # 提醒调用方用 kb_id 精确取，避免静默拿到非权威条目。
            row["kb_id_collisions"] = self._id_collisions[entry_id]
        return row

    def search(
        self,
        query: str,
        *,
        layer: str | None = None,
        entry_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        normalized = normalize_match_term(query)
        query_pattern = compile_term_pattern([normalized])
        scored: list[tuple[int, KBEntry, list[str]]] = []
        for entry in self.entries:
            if layer and entry.layer != layer:
                continue
            if entry_type and entry.entry_type != entry_type:
                continue
            score, matched_terms = score_entry(entry, normalized, query_pattern)
            if score > 0:
                scored.append((score, entry, matched_terms))
        scored.sort(key=lambda row: (-row[0], row[1].name))
        return [format_match(entry, matched_terms, score) for score, entry, matched_terms in scored[:limit]]

    def match_text(
        self,
        text: str,
        *,
        layer: str | None = None,
        entry_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        haystack = normalize_match_term(text)
        matches: list[tuple[int, KBEntry, list[str]]] = []
        for entry in self.entries:
            if layer and entry.layer != layer:
                continue
            if entry_type and entry.entry_type != entry_type:
                continue
            matched_terms = find_matched_terms(entry.match_pattern, haystack, normalized=True)
            if matched_terms:
                score = sum(max(1, len(term)) for term in matched_terms)
                matches.append((score, entry, matched_terms[:8]))
        matches.sort(key=lambda row: (-row[0], row[1].name))
        return [format_match(entry, matched_terms, score) for score, entry, matched_terms in matches[:limit]]

    def export_context(self, text: str, *, limit: int = 20) -> dict[str, Any]:
        matches = self.match_text(text, limit=limit)
        return {
            "kb_context_version": "1.0",
            "matches": matches,
            "compact_context": [
                {
                    "name": match["name"],
                    "type": match["type"],
                    "layer": match["layer"],
                    "definition": match["definition"],
                    "metadata": compact_metadata(match.get("metadata", {})),
                }
                for match in matches
            ],
        }


def score_entry(entry: KBEntry, query: str, query_pattern: re.Pattern[str] | None = None) -> tuple[int, list[str]]:
    if not query:
        return 0, []
    matched_terms: list[str] = []
    score = 0
    searchable = normalize_match_term(
        " ".join([entry.name, entry.definition, entry.entry_type, entry.layer, *entry.aliases, *entry.keywords, *entry.domain_tags])
    )
    if query == normalize_match_term(entry.name):
        score += 100
        matched_terms.append(entry.name)
    elif find_matched_terms(query_pattern, searchable, normalized=True):
        score += 40
        matched_terms.append(query)
    query_matched_terms = find_matched_terms(entry.match_pattern, query, normalized=True)
    if query_matched_terms:
        score += sum(min(30, len(term)) for term in query_matched_terms)
        matched_terms.extend(query_matched_terms)
    for term in entry.keywords:
        if query and (query in term or term in query):
            score += min(30, len(term))
            matched_terms.append(term)
    return score, list(dict.fromkeys(matched_terms))[:8]


def format_match(entry: KBEntry, matched_terms: list[str], score: int) -> dict[str, Any]:
    row = entry.to_dict()
    row["matched_terms"] = matched_terms
    row["score"] = score
    return row


def compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ["class_id", "attributes", "methods", "common_instances", "obis", "rules", "services", "suites", "states", "bits"]:
        if key in metadata:
            value = metadata[key]
            compact[key] = value[:12] if isinstance(value, list) else value
    return compact
