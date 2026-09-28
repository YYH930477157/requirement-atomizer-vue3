"""Semantic pre-review hypotheses for paragraph assembly.

This layer reads parser-owned elements and records semantic relations as
hypotheses.  It never rewrites source text or becomes an authority for the
final partition; ``semantic_segmentation`` remains responsible for the
validated, source-conserving units.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Sequence


SEMANTIC_PRE_REVIEW_VERSION = "semantic-pre-review-v2"
SEMANTIC_PRE_REVIEW_PROMPT_VERSION = "semantic-pre-review-prompt-v2-windowed"
SEMANTIC_PRE_REVIEW_SCHEMA = "semantic-pre-review/v1"
SEMANTIC_PRE_REVIEW_FILENAME = "semantic_pre_review.json"
_OBLIGATION_RE = re.compile(r"\b(?:shall|must|should|required|may not|不得|必须|应当)\b", re.I)
_LIST_RE = re.compile(r"^\s*(?:[-*•▪◦]|\(?[a-z]\)|\(?\d+[.)])\s+", re.I)
_HEADING_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+[.)])\s+[^.。]{1,100}$", re.I)

ExtractChat = Callable[[str, str], dict[str, Any]]

_SYSTEM_PROMPT = (
    "You are a semantic pre-reviewer for a technical document. Read the ordered "
    "source elements and return only JSON. For each element, classify its role "
    "and whether it continues the previous element, introduces the next list, "
    "inherits a subject, or starts a new topic. Mark uncertainty explicitly. "
    "This is a hypothesis for a later deterministic assembler: never rewrite text, "
    "never invent facts, never omit an element, and preserve every element_id. "
    "A colon lead-in normally owns its immediately following list; a condition or "
    "exception normally continues the requirement it qualifies. A complete numbered "
    "sentence containing an obligation is body text, not a heading. Return JSON as "
    "{\"elements\":[{\"element_id\":\"...\",\"role\":\"...\","
    "\"relation_to_previous\":\"...\",\"boundary_after\":true,"
    "\"context_owner\":\"...\",\"uncertainty\":\"low|medium|high\","
    "\"reason\":\"...\"}]}"
)


def _role(block: dict[str, Any]) -> str:
    text = str(block.get("text") or "").strip()
    if block.get("noise"):
        return "noise"
    kind = str(block.get("type") or "paragraph")
    if kind == "table":
        return "table"
    if kind == "heading":
        return "body" if _OBLIGATION_RE.search(text) else "heading"
    if _LIST_RE.match(text) or block.get("is_list_item"):
        return "list_item"
    if _HEADING_RE.match(text) and not _OBLIGATION_RE.search(text):
        return "heading"
    return "body"


def _deterministic_elements(blocks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Produce conservative hypotheses when LLM is disabled or unavailable."""
    result: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for block in blocks:
        element_id = str(block.get("block_id") or "")
        if not element_id:
            continue
        text = str(block.get("text") or "").strip()
        role = _role(block)
        relation = "independent"
        boundary_after = True
        owner = ""
        uncertainty = "low"
        reason = "结构元素默认独立，等待语义复核"
        if previous is not None:
            prev_text = str(previous.get("text") or "").rstrip()
            prev_role = str(previous.get("role") or "")
            if prev_role == "noise" or role == "noise":
                relation = "noise_boundary"
                reason = "噪声与正文不得共用语义单元"
            elif prev_text.endswith((":", "：")) and role == "list_item":
                relation = "continues"
                boundary_after = False
                owner = prev_text[:120]
                reason = "冒号引导语承接紧邻清单"
            elif role == "list_item" and prev_role == "list_item":
                relation = "sibling"
                owner = str(previous.get("context_owner") or "")
                reason = "连续清单项共享前置语境，但边界仍需判断"
                uncertainty = "medium"
            elif prev_role == "body" and role == "body" and not _OBLIGATION_RE.search(prev_text):
                relation = "continues"
                boundary_after = False
                reason = "前一块无终止义务，可能是续句或补充说明"
                uncertainty = "medium"
            elif role == "body" and text[:1].islower():
                relation = "continues"
                boundary_after = False
                reason = "小写开头疑似上一句续文"
                uncertainty = "medium"
        result.append({
            "element_id": element_id,
            "role": role,
            "relation_to_previous": relation,
            "boundary_after": boundary_after,
            "context_owner": owner,
            "uncertainty": uncertainty,
            "reason": reason,
        })
        previous = {"text": text, "role": role, "context_owner": owner}
    return result


def _validate_llm_elements(payload: Any, expected_ids: list[str]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("semantic pre-review response must contain elements")
    by_id: dict[str, dict[str, Any]] = {}
    allowed_roles = {"noise", "heading", "body", "list_item", "table", "table_header", "table_row", "continuation"}
    allowed_relations = {"independent", "continues", "sibling", "inherits", "noise_boundary", "new_topic"}
    for row in payload["elements"]:
        if not isinstance(row, dict):
            raise ValueError("semantic pre-review element is not an object")
        element_id = str(row.get("element_id") or "")
        if element_id in by_id or element_id not in set(expected_ids):
            raise ValueError("semantic pre-review element ID is unknown or duplicated")
        role = str(row.get("role") or "")
        relation = str(row.get("relation_to_previous") or "")
        uncertainty = str(row.get("uncertainty") or "")
        if role not in allowed_roles or relation not in allowed_relations or uncertainty not in {"low", "medium", "high"}:
            raise ValueError("semantic pre-review element has an invalid enum")
        by_id[element_id] = {
            "element_id": element_id,
            "role": role,
            "relation_to_previous": relation,
            "boundary_after": bool(row.get("boundary_after", True)),
            "context_owner": str(row.get("context_owner") or "").strip(),
            "uncertainty": uncertainty,
            "reason": str(row.get("reason") or "").strip(),
        }
    if list(by_id) != expected_ids:
        raise ValueError("semantic pre-review must cover every source element in order")
    return [by_id[element_id] for element_id in expected_ids]


def _semantic_map(blocks: Sequence[dict[str, Any]], elements: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(b.get("block_id")): b for b in blocks}
    topics: dict[str, list[str]] = defaultdict(list)
    for annotation in elements:
        block = by_id.get(str(annotation["element_id"]), {})
        path = [str(x) for x in (block.get("section_path") or []) if str(x).strip()]
        topic = " / ".join(path) if path else "(root)"
        topics[topic].append(str(annotation["element_id"]))
    return {
        "topics": [
            {"topic": topic, "element_ids": ids, "element_count": len(ids)}
            for topic, ids in topics.items()
        ],
        "relation_edges": [
            {
                "from_element_id": elements[index - 1]["element_id"],
                "to_element_id": row["element_id"],
                "relation": row["relation_to_previous"],
            }
            for index, row in enumerate(elements)
            if index and row["relation_to_previous"] not in {"independent", "noise_boundary", "new_topic"}
        ],
    }


def _payload_row(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "element_id": str(block["block_id"]),
        "text": str(block.get("text") or ""),
        "type": str(block.get("type") or "paragraph"),
        "section_path": list(block.get("section_path") or []),
        "page": block.get("page_number"),
        "is_list_item": bool(block.get("is_list_item")),
        "table_id": block.get("table_id"),
    }


def _payload_chunks(
    blocks: Sequence[dict[str, Any]],
    *,
    max_chars: int,
) -> list[list[dict[str, Any]]]:
    """Split the pre-review request without dropping or truncating blocks."""
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for block in blocks:
        row = _payload_row(block)
        if not current:
            if len(json.dumps([row], ensure_ascii=False)) > max_chars:
                raise RuntimeError(
                    f"semantic pre-review element {row['element_id']} exceeds window budget"
                )
            current = [row]
            continue
        candidate = [*current, row]
        if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
            chunks.append(current)
            current = [row]
            if len(json.dumps(current, ensure_ascii=False)) > max_chars:
                raise RuntimeError(
                    f"semantic pre-review element {row['element_id']} exceeds window budget"
                )
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_semantic_pre_review(
    blocks: Sequence[dict[str, Any]],
    source: Path,
    *,
    mode: str = "deterministic",
    route: str = "stub",
    chat: ExtractChat | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Build a source-conserving pre-review report.

    ``mode=llm`` is explicit.  The injected chat path is intended for tests;
    production callers must provide an OpenAI-compatible route.  An unavailable
    or invalid LLM result falls back to deterministic hypotheses and records it.
    """
    if mode not in {"deterministic", "llm"}:
        raise ValueError("semantic pre-review mode must be deterministic or llm")
    source_blocks = [dict(block) for block in blocks if str(block.get("block_id") or "")]
    expected_ids = [str(block["block_id"]) for block in source_blocks]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    annotations = _deterministic_elements(source_blocks)
    deterministic_annotations = annotations
    errors: list[str] = []
    effective_mode = "deterministic"
    route_used = "stub"
    llm_window_count: int | None = None
    if mode == "llm":
        try:
            active_chat = chat
            if active_chat is None:
                from functional_extract import _resolve_extract_chat
                active_chat, route_used = _resolve_extract_chat(route, None)
            else:
                route_used = "injected"
            if active_chat is None:
                raise RuntimeError("semantic pre-review LLM route unavailable")
            chunks = _payload_chunks(source_blocks, max_chars=max_chars)
            llm_window_count = len(chunks)
            annotations = []
            for chunk_index, chunk in enumerate(chunks):
                chunk_ids = [str(row["element_id"]) for row in chunk]
                payload = json.dumps(chunk, ensure_ascii=False)
                raw = active_chat(_SYSTEM_PROMPT, payload)
                chunk_annotations = _validate_llm_elements(raw, chunk_ids)
                if chunk_index:
                    # The model cannot see the previous window. A hard
                    # boundary is safer than allowing a cross-window merge.
                    chunk_annotations[0]["relation_to_previous"] = "independent"
                    chunk_annotations[0]["boundary_after"] = True
                    chunk_annotations[0]["reason"] = (
                        "窗口边界无跨窗上下文，保守切开"
                    )
                annotations.extend(chunk_annotations)
            effective_mode = "llm"
        except Exception as exc:  # pre-review must never block source parsing
            errors.append(type(exc).__name__ + ": " + str(exc))
            annotations = deterministic_annotations
    return {
        "schema": SEMANTIC_PRE_REVIEW_SCHEMA,
        "version": SEMANTIC_PRE_REVIEW_VERSION,
        "prompt_version": SEMANTIC_PRE_REVIEW_PROMPT_VERSION,
        "source_sha256": source_hash,
        "mode_requested": mode,
        "effective_mode": effective_mode,
        "route": route_used,
        "quality_status": "not_evaluated",
        "errors": errors,
        "llm_window_count": llm_window_count,
        "counts": {
            "source_elements": len(source_blocks),
            "annotations": len(annotations),
            "uncertain": sum(row["uncertainty"] != "low" for row in annotations),
        },
        "elements": annotations,
        "semantic_map": _semantic_map(source_blocks, annotations),
    }
