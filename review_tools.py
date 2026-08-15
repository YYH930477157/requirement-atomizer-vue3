"""Agent Phase 2 WP1-B：tool-using reviewer 的确定性只读工具面（冻结契约）。

五个工具（kb_search / kb_get / blue_book_class / source_read / coverage_check）只做现有
确定性函数的薄封装与返回裁剪——**不写、不猜、不联网**；同输入同输出（工具调用零 token）。
模型只能经这些工具读证据；结构化字段（OBIS/文号/访问）仍由确定性层裁决。

`REVIEW_TOOLS_VERSION`：工具定义（名称/参数/返回裁剪）任何变更必须 bump，并进入审查缓存
指纹（同 EXTRACT_GUARDS_VERSION 纪律，见 llm_pipeline.llm_cache_key）。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from blue_book_lookup import condensed_text, load_index, lookup_class, lookup_class_by_name
from io_utils import read_jsonl

# 工具定义/裁剪契约版本——TOOLS schema、返回字段、裁剪上限任何变更必须 bump
# v5：执行器内建一次性索引（block_id→块、需求候选 id 索引、一致性分组、预归一化引句
#     匹配语料）——同输入同输出不变（tests 双路比对恒等锁定），只消除每次工具调用的
#     全文档重扫；缓存指纹随 bump 轮换一次（旧审查缓存失效重审一次,可接受）
# v4：source_read 返回裁剪上限 2000→800，降低逐需求工具回灌成本
# v3：coverage_check 共引/重复/引句命中改走 A 轨适配层（v2 在 atomic 真实形状上三处恒空）
# v2：蓝皮书索引缺失优雅降级（v1 崩溃致 tool-loop 两连错中止）
REVIEW_TOOLS_VERSION = "review-tools-v5"

# 返回裁剪上限（冻结契约的一部分，见规格 §2 表格）
KB_SEARCH_MAX_RESULTS = 5
KB_DEFINITION_MAX_CHARS = 300
BLUE_BOOK_CONDENSED_MAX_CHARS = 1500
SOURCE_BLOCK_MAX_CHARS = 800
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
                "Read one source document block by block_id. Returns block text (<=800 chars) "
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

    全部数据惰性加载一次（审查批内共享，线程安全）；派生索引（块索引/需求索引/一致性
    分组/引句匹配语料）同样惰性构建一次——数据在执行器生命周期内冻结,逐调用全文档重算
    是纯浪费（v5 性能收口,输出恒等由 tests/test_review_tools 双路比对锁定）。加载失败/
    参数非法/未知工具名一律返回 {"error": ...}（由 llm_client 回灌模型一次让其纠正），
    绝不抛穿调用方。"""
    out_dir = Path(out_dir)
    state: dict[str, Any] = {
        "kb": None, "blocks": None, "requirements": None, "bb_index": None,
        "block_index": None, "consistency_index": None,
    }
    lock = threading.RLock()   # 可重入：派生索引惰性构建时嵌套取底层数据源

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
                    # 索引路径可能不存在（无蓝皮书环境）——如实按空索引降级（工具返回未命中
                    # null），不得让 load_index(None) 的 AttributeError 连环触发两次失败
                    # 中止整条 tool-loop（test3 验收实证：2 条需求因此进 stub）
                    index_path = _resolve_blue_book_index(blue_book_index_path, out_dir)
                    state["bb_index"] = load_index(index_path) if index_path is not None else {}
        return state["bb_index"]

    def _block_index() -> dict[str, dict[str, Any]]:
        if state["block_index"] is None:
            with lock:
                if state["block_index"] is None:
                    # 首个命中为准（与旧线性扫描一致,重复 block_id 时文件序在前者胜）
                    index: dict[str, dict[str, Any]] = {}
                    for block in _blocks():
                        index.setdefault(str(block.get("block_id") or ""), block)
                    state["block_index"] = index
        return state["block_index"]

    def _consistency_index() -> "_ConsistencyIndex":
        if state["consistency_index"] is None:
            with lock:
                if state["consistency_index"] is None:
                    state["consistency_index"] = _ConsistencyIndex(
                        _requirements(), _blocks())
        return state["consistency_index"]

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
                return _source_read(_block_index(), args)
            if tool_name == "coverage_check":
                return _coverage_check(_consistency_index(), args)
            return {"error": f"unknown tool: {tool_name} (available: {', '.join(sorted(_TOOL_NAMES))})"}
        except Exception as exc:  # 工具执行异常 → error 回灌（llm_client 对连续同工具错误禁用该工具）
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


def _hash_file_content(path: Path | None) -> str | None:
    """文件内容 sha256；缺失/非文件如实返回 None（指纹里记 null，不猜不跳过）。"""
    if path is None:
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_payload(out_dir: Path, kb_paths: Iterable[str | Path] | None) -> dict[str, Any]:
    """工具实际加载的证据文件集合 + 内容 hash（KB/原文块/原子需求/蓝皮书索引）。

    KB 与蓝皮书索引按 make_tool_executor 同一回退路径解析——指纹覆盖的文件集合
    必须等于工具真实读取的集合，否则改证据后旧审查被静默复用（审计 P1-d）。"""
    root = Path(out_dir).expanduser().resolve()
    if kb_paths is None:
        from requirement_kb.cli import default_kb_paths
        resolved_kb = list(default_kb_paths())
    else:
        resolved_kb = [Path(path) for path in kb_paths]
    index_path = _resolve_blue_book_index(None, root)
    return {
        "kb": [
            {
                "path": str(Path(path).expanduser().resolve()),
                "sha256": _hash_file_content(Path(path)),
            }
            for path in resolved_kb
        ],
        "blocks_jsonl": _hash_file_content(root / "blocks.jsonl"),
        "atomic_requirements_jsonl": _hash_file_content(root / "atomic_requirements.jsonl"),
        "blue_book_index": {
            "path": str(index_path) if index_path is not None else None,
            "sha256": _hash_file_content(index_path),
        },
    }


def evidence_fingerprint(out_dir: Path, kb_paths: Iterable[str | Path] | None = None) -> str:
    """工具证据的内容指纹（确定性聚合 sha1）。

    改 KB 任一文件、blocks.jsonl、atomic_requirements.jsonl 或蓝皮书索引的内容 →
    指纹变 → 审查缓存 key（llm_pipeline.llm_cache_key）与 llm-review 阶段 producer
    （desktop_tasks.stage_producer）随之失效；缺失文件如实记 null。"""
    canonical = json.dumps(
        _evidence_payload(out_dir, kb_paths),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def evidence_fingerprint_parts(
    out_dir: Path,
    kb_paths: Iterable[str | Path] | None = None,
) -> dict[str, str]:
    """证据指纹按审查缓存口径切分（FIX 4, 2026-08-14）。

    - stable_fingerprint：KB + blocks.jsonl + 蓝皮书索引——这些证据只在管线轮次间
      变化，专家审查编辑（改 atomic_requirements 某一行）期间不动 → 进每条审查缓存
      key，编辑一条需求不再全文档失效。
    - atomic_requirements_sha256：atomic_requirements.jsonl 整文件内容 hash——只有
      coverage_check（全文档聚合）的审查行依赖它，写入缓存行 evidence_deps、命中时
      校验（llm_pipeline.cached_review_or_none），失配即失效。

    旧整指纹 evidence_fingerprint（含 atomic 维度）保持原样——desktop 阶段戳等
    全文档口径消费方继续使用。"""
    payload = _evidence_payload(out_dir, kb_paths)
    atomic_sha = payload.pop("atomic_requirements_jsonl")
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    stable = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    return {"stable_fingerprint": stable, "atomic_requirements_sha256": atomic_sha or ""}


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


def _source_read(block_index: dict[str, dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    """块索引直查（v5）：语义与逐块线性扫描首个命中完全一致（索引构建 first-wins，
    tests 双路比对锁定）。"""
    block_id = str(args.get("block_id") or "").strip()
    if not block_id:
        return {"error": "source_read requires a non-empty block_id"}
    block = block_index.get(block_id)
    if block is None:
        return {"error": f"unknown block_id: {block_id}"}
    return {
        "block_id": block_id,
        "text": _trim(block.get("text"), SOURCE_BLOCK_MAX_CHARS),
        "section_path": [str(value) for value in (block.get("section_path") or [])],
    }


def _requirement_candidate_ids(requirement: dict[str, Any]) -> set[str]:
    ids = {
        str(requirement.get(key) or "").strip()
        for key in ("stable_req_id", "req_id", "source_id", "id", "requirement_id", "ai_req_id")
    }
    ids.discard("")
    return ids


def _build_requirement_index(
    requirements: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """候选 id → 需求行（首个命中为准,与 _find_requirement 线性扫描语义一致）。"""
    index: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        for candidate_id in _requirement_candidate_ids(requirement):
            if candidate_id not in index:
                index[candidate_id] = requirement
    return index


def _find_requirement(requirements: list[dict[str, Any]], requirement_id: str) -> dict[str, Any] | None:
    for requirement in requirements:
        if requirement_id in _requirement_candidate_ids(requirement):
            return requirement
    return None


def _atomic_to_consistency_row(requirement: dict[str, Any]) -> dict[str, Any]:
    """A 轨 atomic 行 → merged_consistency 函数期望的 B 轨形状（只读映射，不改 B 轨行为）。

    审计 H1：find_obis_coreference/find_cross_section_duplicates 读 title/description/
    source_quote/source_section/id，而 atomic_requirements.jsonl 的真实字段是
    requirement/object/parameters/section_path/source_context——直接喂入三个检测全落空
    （2337 条真实产物实测共引/重复 0/0、引句命中恒空）。结构化 OBIS 只从确定性位置
    （parameters.cosem_object.obis）取并追加进 description，叙述未复述编码的需求也参与
    共引分组——宁漏勿错，不解析不猜。"""
    text = str(requirement.get("requirement") or "")
    parameters = requirement.get("parameters")
    cosem_object = parameters.get("cosem_object") if isinstance(parameters, dict) else None
    structured = []
    if isinstance(cosem_object, dict):
        obis = str(cosem_object.get("obis") or "").strip()
        if obis:
            structured.append(f"OBIS {obis}")
    context = requirement.get("source_context")
    paragraph = str(context.get("paragraph_text") or "") if isinstance(context, dict) else ""
    section_path = [str(value) for value in (requirement.get("section_path") or [])]
    return {
        "id": str(requirement.get("req_id") or ""),
        "title": str(requirement.get("object") or "") or text[:40],
        "description": f"{text} [{'; '.join(structured)}]" if structured else text,
        "source_quote": paragraph or text,
        "source_section": " / ".join(section_path),
    }


class _BlockQuoteIndex:
    """预归一化引句匹配语料（v5）：块排序 + 逐块 compact_source_text 只做一次。

    匹配编排（多段分片/噪声豁免/去重定序/最短窗口）逐字复用
    merged_consistency 的 `_match_compact_quote`/`_matches_only_noise`——与
    match_source_quote_blocks(quote, blocks) 同输入同输出（tests 双路比对恒等锁定），
    仅消除每次调用的逐块重新归一化。输入块列表在执行器生命周期内冻结,按引句原文
    记忆化命中结果。"""

    __slots__ = ("_normalized", "_memo")

    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        from merged_consistency import _ordered_source_blocks, compact_source_text
        ordered = _ordered_source_blocks(blocks)
        self._normalized: list[tuple[dict[str, Any], str]] = [
            (block, compact_source_text(block.get("text"))) for block in ordered
        ]
        self._memo: dict[str, tuple[list[str], str]] = {}

    def match(self, source_quote: Any) -> tuple[list[str], str]:
        raw_quote = str(source_quote or "")
        cached = self._memo.get(raw_quote)
        if cached is None:
            cached = self._match(raw_quote)
            self._memo[raw_quote] = cached
        return cached

    def _match(self, raw_quote: str) -> tuple[list[str], str]:
        from merged_consistency import (
            _MIN_SOURCE_MATCH_CHARS,
            _SOURCE_EXCERPT_SEPARATOR_RE,
            _match_compact_quote,
            _matches_only_noise,
            compact_source_text,
        )
        excerpts = [
            compact_source_text(value)
            for value in _SOURCE_EXCERPT_SEPARATOR_RE.split(raw_quote)
            if len(compact_source_text(value)) >= _MIN_SOURCE_MATCH_CHARS
        ]
        if len(excerpts) > 1:
            excerpt_matches: list[str] = []
            for excerpt in excerpts:
                matched, _method = _match_compact_quote(excerpt, self._normalized)
                if not matched:
                    # 只命中噪声块的片段按噪声内容跳过（同 match_source_quote_blocks）
                    if _matches_only_noise(excerpt, self._normalized):
                        continue
                    return [], ""
                excerpt_matches.extend(matched)
            excerpt_matches = list(dict.fromkeys(excerpt_matches))
            return (
                excerpt_matches,
                "multi_block" if len(excerpt_matches) > 1 else "contains",
            )
        quote = compact_source_text(raw_quote)
        if len(quote) < _MIN_SOURCE_MATCH_CHARS:
            return [], ""
        return _match_compact_quote(quote, self._normalized)


class _ConsistencyIndex:
    """coverage_check 的全文档一次性语料（v5 记忆化）：适配行、需求候选 id 索引、
    OBIS 共引组、跨章重复组、引句匹配语料。全部是冻结输入的纯函数——构建一次后
    每次调用只做按目标需求的过滤,不再全文档重算。"""

    __slots__ = ("requirement_index", "coref_groups", "duplicate_groups", "quote_index")

    def __init__(self, requirements: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> None:
        from merged_consistency import find_cross_section_duplicates, find_obis_coreference
        consistency_rows = [_atomic_to_consistency_row(row) for row in requirements]
        self.requirement_index = _build_requirement_index(requirements)
        self.coref_groups = find_obis_coreference(consistency_rows)
        self.duplicate_groups = find_cross_section_duplicates(consistency_rows)
        self.quote_index = _BlockQuoteIndex(blocks)


def _coverage_check(index: _ConsistencyIndex, args: dict[str, Any]) -> dict[str, Any]:
    """按目标需求过滤一次性语料——结果与 v4 逐调用全量重算路径逐字节恒等。"""
    requirement_id = str(args.get("requirement_id") or "").strip()
    if not requirement_id:
        return {"error": "coverage_check requires a non-empty requirement_id"}
    requirement = index.requirement_index.get(requirement_id)
    if requirement is None:
        return {"error": f"unknown requirement_id: {requirement_id}"}
    candidate_ids = _requirement_candidate_ids(requirement)
    # 共引/重复/引句命中三处全部走适配后的行（merged_consistency 为 B 轨 merged 形状设计,
    # A 轨 atomic 行须经 _atomic_to_consistency_row 映射,否则在真实产物上三处检测恒空）
    target_row = _atomic_to_consistency_row(requirement)
    # 引句命中块：适配后的 source_quote（source_context.paragraph_text,缺省退 requirement
    # 文本）确定性匹配,块序并集
    quote = str(target_row.get("source_quote") or "")
    hit_block_ids: list[str] = []
    methods: list[str] = []
    if quote.strip():
        matched, method = index.quote_index.match(quote)
        for block_id in matched:
            if block_id not in hit_block_ids:
                hit_block_ids.append(block_id)
        if method:
            methods.append(method)
    coreference = [
        {"obis": str(group.get("obis") or ""), "members": [str(m) for m in (group.get("members") or [])],
         "values_differ": bool(group.get("values_differ")), "count": group.get("count")}
        for group in index.coref_groups
        if candidate_ids.intersection(str(m) for m in (group.get("members") or []))
    ][:_COVERAGE_GROUP_MAX]
    duplicates = [
        {"members": [str(m) for m in (group.get("members") or [])],
         "sections": [str(s) for s in (group.get("sections") or [])], "count": group.get("count")}
        for group in index.duplicate_groups
        if candidate_ids.intersection(str(m) for m in (group.get("members") or []))
    ][:_COVERAGE_GROUP_MAX]
    return {
        "requirement_id": requirement_id,
        "quote_hit_block_ids": hit_block_ids,
        "match_methods": methods,
        "obis_coreference": coreference,
        "duplicate_candidates": duplicates,
    }
