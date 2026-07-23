"""Agent Phase 2 WP1-B：tool-using reviewer 的确定性只读工具面（冻结契约）。

五个工具（kb_search / kb_get / blue_book_class / source_read / coverage_check）只做现有
确定性函数的薄封装与返回裁剪——**不写、不猜、不联网**；同输入同输出（工具调用零 token）。
模型只能经这些工具读证据；结构化字段（OBIS/文号/访问）仍由确定性层裁决。

`REVIEW_TOOLS_VERSION`：工具定义（名称/参数/返回裁剪）任何变更必须 bump，并进入审查缓存
指纹（同 EXTRACT_GUARDS_VERSION 纪律，见 llm_pipeline.llm_cache_key）。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable

from blue_book_lookup import condensed_text, load_index, lookup_class, lookup_class_by_name
from io_utils import read_jsonl

# 工具定义/裁剪契约版本——TOOLS schema、返回字段、裁剪上限任何变更必须 bump
REVIEW_TOOLS_VERSION = "review-tools-v1"

# 返回裁剪上限（冻结契约的一部分，见规格 §2 表格）
KB_SEARCH_MAX_RESULTS = 5
KB_DEFINITION_MAX_CHARS = 300
BLUE_BOOK_CONDENSED_MAX_CHARS = 1500
SOURCE_BLOCK_MAX_CHARS = 2000
_COVERAGE_GROUP_MAX = 5

# 蓝皮书索引自动探测顺序与 desktop_tasks.resolve_blue_book_index 一致（显式注入 > env >
# 输出目录约定位置 > dev 仓库 out/bluebook）——桌面「运行」链没有索引输入口，自动探测零配置。
BLUE_BOOK_INDEX_ENV = "RATOMIZER_BLUE_BOOK_INDEX"


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": (
                "Search the local DLMS/COSEM knowledge base (deterministic, read-only). "
                "Returns up to 5 matches with entry_id, name, definition (<=300 chars), score."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "term or phrase to look up"},
                    "limit": {
                        "type": "integer", "minimum": 1, "maximum": KB_SEARCH_MAX_RESULTS,
                        "description": "max results (default 5, capped at 5)",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_get",
            "description": (
                "Fetch one knowledge-base entry by entry_id. Returns whitelist fields plus "
                "compact metadata; result is null when the entry does not exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "entry_id returned by kb_search"},
                },
                "required": ["entry_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "blue_book_class",
            "description": (
                "Look up a DLMS Blue Book interface class by numeric class_id or exact class "
                "name. Returns section, name and condensed definition (<=1500 chars); "
                "result is null when not found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "class_id": {"type": ["integer", "string"], "description": "COSEM interface class id"},
                    "name": {"type": "string", "description": "exact interface class name"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "source_read",
            "description": (
                "Read one source document block by block_id. Returns block text (<=2000 chars) "
                "and its section path; returns an error when the block_id is unknown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "string", "description": "block id from blocks.jsonl"},
                },
                "required": ["block_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coverage_check",
            "description": (
                "Deterministic coverage facts for one requirement id: source-quote block hits, "
                "OBIS co-reference groups and cross-section duplicate candidates that include "
                "this requirement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string", "description": "requirement id from the review prompt"},
                },
                "required": ["requirement_id"],
                "additionalProperties": False,
            },
        },
    },
]

_TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS}


def make_tool_executor(
    out_dir: Path,
    *,
    kb_paths: list[Path] | None = None,
    blue_book_index_path: Path | None = None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """on_tool_call 回调工厂：按 out_dir 绑定只读数据源（blocks/atomic_requirements/KB/蓝皮书）。

    全部数据惰性加载一次（审查批内共享，线程安全）；加载失败/参数非法/未知工具名一律
    返回 {"error": ...}（由 llm_client 回灌模型一次让其纠正），绝不抛穿调用方。"""
    out_dir = Path(out_dir)
    state: dict[str, Any] = {"kb": None, "blocks": None, "requirements": None, "bb_index": None}
    lock = threading.Lock()

    def _kb() -> Any:
        if state["kb"] is None:
            with lock:
                if state["kb"] is None:
                    from requirement_kb.cli import default_kb_paths
                    from requirement_kb.repository import KnowledgeRepository
                    paths = kb_paths if kb_paths is not None else default_kb_paths()
                    state["kb"] = KnowledgeRepository.from_paths(paths)
        return state["kb"]

    def _blocks() -> list[dict[str, Any]]:
        if state["blocks"] is None:
            with lock:
                if state["blocks"] is None:
                    state["blocks"] = read_jsonl(out_dir / "blocks.jsonl")
        return state["blocks"]

    def _requirements() -> list[dict[str, Any]]:
        if state["requirements"] is None:
            with lock:
                if state["requirements"] is None:
                    state["requirements"] = read_jsonl(out_dir / "atomic_requirements.jsonl")
        return state["requirements"]

    def _bb_index() -> dict[str, Any] | None:
        if state["bb_index"] is None:
            with lock:
                if state["bb_index"] is None:
                    state["bb_index"] = load_index(_resolve_blue_book_index(blue_book_index_path, out_dir)) or {}
        return state["bb_index"]

    def execute(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        args = arguments if isinstance(arguments, dict) else {}
        try:
            if tool_name == "kb_search":
                return _kb_search(_kb(), args)
            if tool_name == "kb_get":
                return _kb_get(_kb(), args)
            if tool_name == "blue_book_class":
                return _blue_book_class(_bb_index(), args)
            if tool_name == "source_read":
                return _source_read(_blocks(), args)
            if tool_name == "coverage_check":
                return _coverage_check(_requirements(), _blocks(), args)
            return {"error": f"unknown tool: {tool_name} (available: {', '.join(sorted(_TOOL_NAMES))})"}
        except Exception as exc:  # 工具执行异常 → error 回灌（llm_client 同轮再犯即抛）
            return {"error": f"{tool_name} failed: {exc}"}

    return execute


def _resolve_blue_book_index(explicit: Path | None, out_dir: Path) -> Path | None:
    if explicit is not None:
        return explicit
    env_value = os.environ.get(BLUE_BOOK_INDEX_ENV, "").strip()
    if env_value:
        return Path(env_value)
    from resources import package_root
    for candidate in (
        out_dir / "blue_book_index.json",
        out_dir / "bluebook" / "blue_book_index.json",
        package_root() / "out" / "bluebook" / "blue_book_index.json",
    ):
        if candidate.exists():
            return candidate
    return None


def _trim(text: Any, max_chars: int) -> str:
    value = str(text or "")
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + f"…<truncated {len(value) - max_chars} chars>"


def _kb_search(repo: Any, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "kb_search requires a non-empty query"}
    try:
        limit = int(args.get("limit") or KB_SEARCH_MAX_RESULTS)
    except (TypeError, ValueError):
        limit = KB_SEARCH_MAX_RESULTS
    limit = max(1, min(KB_SEARCH_MAX_RESULTS, limit))
    rows = repo.search(query, limit=limit)
    return {
        "results": [
            {
                "entry_id": str(row.get("entry_id") or ""),
                "name": str(row.get("name") or ""),
                "definition": _trim(row.get("definition"), KB_DEFINITION_MAX_CHARS),
                "score": row.get("score"),
            }
            for row in rows[:KB_SEARCH_MAX_RESULTS]
        ]
    }


def _kb_get(repo: Any, args: dict[str, Any]) -> dict[str, Any]:
    entry_id = str(args.get("entry_id") or "").strip()
    if not entry_id:
        return {"error": "kb_get requires a non-empty entry_id"}
    from requirement_kb.repository import compact_metadata
    row = repo.get(entry_id)
    if row is None:
        return {"result": None}
    return {
        "result": {
            "entry_id": str(row.get("entry_id") or ""),
            "name": str(row.get("name") or ""),
            "type": str(row.get("type") or ""),
            "layer": str(row.get("layer") or ""),
            "definition": _trim(row.get("definition"), KB_DEFINITION_MAX_CHARS),
            "metadata": compact_metadata(row.get("metadata") or {}),
        }
    }


def _blue_book_class(index: dict[str, Any] | None, args: dict[str, Any]) -> dict[str, Any]:
    class_id = args.get("class_id")
    name = str(args.get("name") or "").strip()
    if class_id in (None, "") and not name:
        return {"error": "blue_book_class requires class_id or name"}
    if not index:
        return {"result": None, "note": "blue_book_index 不可用（未探测到编译索引）"}
    entry = lookup_class(index, class_id) if class_id not in (None, "") else lookup_class_by_name(index, name)
    if entry is None:
        return {"result": None}
    return {
        "result": {
            "section": str(entry.get("section") or ""),
            "name": str(entry.get("name") or ""),
            "condensed": condensed_text(entry, BLUE_BOOK_CONDENSED_MAX_CHARS),
        }
    }


def _source_read(blocks: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    block_id = str(args.get("block_id") or "").strip()
    if not block_id:
        return {"error": "source_read requires a non-empty block_id"}
    for block in blocks:
        if str(block.get("block_id") or "") == block_id:
            return {
                "block_id": block_id,
                "text": _trim(block.get("text"), SOURCE_BLOCK_MAX_CHARS),
                "section_path": [str(value) for value in (block.get("section_path") or [])],
            }
    return {"error": f"unknown block_id: {block_id}"}


def _requirement_candidate_ids(requirement: dict[str, Any]) -> set[str]:
    ids = {
        str(requirement.get(key) or "").strip()
        for key in ("stable_req_id", "req_id", "source_id", "id", "requirement_id", "ai_req_id")
    }
    ids.discard("")
    return ids


def _find_requirement(requirements: list[dict[str, Any]], requirement_id: str) -> dict[str, Any] | None:
    for requirement in requirements:
        if requirement_id in _requirement_candidate_ids(requirement):
            return requirement
    return None


def _coverage_check(
    requirements: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    args: dict[str, Any],
) -> dict[str, Any]:
    from merged_consistency import (
        find_cross_section_duplicates,
        find_obis_coreference,
        match_source_quote_blocks,
    )
    requirement_id = str(args.get("requirement_id") or "").strip()
    if not requirement_id:
        return {"error": "coverage_check requires a non-empty requirement_id"}
    requirement = _find_requirement(requirements, requirement_id)
    if requirement is None:
        return {"error": f"unknown requirement_id: {requirement_id}"}
    candidate_ids = _requirement_candidate_ids(requirement)
    # 引句命中块：source_quote/source_quotes 逐条确定性匹配，块序并集
    quotes = [str(requirement.get("source_quote") or "")]
    quotes.extend(str(value or "") for value in (requirement.get("source_quotes") or []))
    hit_block_ids: list[str] = []
    methods: list[str] = []
    for quote in quotes:
        if not quote.strip():
            continue
        matched, method = match_source_quote_blocks(quote, blocks)
        for block_id in matched:
            if block_id not in hit_block_ids:
                hit_block_ids.append(block_id)
        if method and method not in methods:
            methods.append(method)
    coreference = [
        {"obis": str(group.get("obis") or ""), "members": [str(m) for m in (group.get("members") or [])],
         "values_differ": bool(group.get("values_differ")), "count": group.get("count")}
        for group in find_obis_coreference(requirements)
        if candidate_ids.intersection(str(m) for m in (group.get("members") or []))
    ][:_COVERAGE_GROUP_MAX]
    duplicates = [
        {"members": [str(m) for m in (group.get("members") or [])],
         "sections": [str(s) for s in (group.get("sections") or [])], "count": group.get("count")}
        for group in find_cross_section_duplicates(requirements)
        if candidate_ids.intersection(str(m) for m in (group.get("members") or []))
    ][:_COVERAGE_GROUP_MAX]
    return {
        "requirement_id": requirement_id,
        "quote_hit_block_ids": hit_block_ids,
        "match_methods": methods,
        "obis_coreference": coreference,
        "duplicate_candidates": duplicates,
    }
