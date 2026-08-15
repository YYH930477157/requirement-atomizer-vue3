"""Agent Phase 2 WP1-B：review_tools 五工具的冻结契约测试。

正/反例、返回裁剪、未命中如实 null/error、确定性复现、TOOLS schema 与
REVIEW_TOOLS_VERSION 的联动契约（工具定义变更而版本未 bump → 本文件契约测试失败）。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import review_tools
from review_tools import (
    BLUE_BOOK_CONDENSED_MAX_CHARS,
    KB_DEFINITION_MAX_CHARS,
    KB_SEARCH_MAX_RESULTS,
    REVIEW_TOOLS_VERSION,
    SOURCE_BLOCK_MAX_CHARS,
    TOOLS,
    make_tool_executor,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


LONG_DEFINITION = "寄存器接口类定义" * 100   # 700 字 > 300 裁剪帽
LONG_BLOCK_TEXT = "原文块内容" * 600          # 3000 字 > source_read 裁剪帽
LONG_BB_TEXT = "Blue Book class definition. " * 200   # > 1500 裁剪帽


def _kb_file(root: Path) -> Path:
    kb = root / "kb.json"
    kb.write_text(json.dumps({
        "kb_id": "test_kb",
        "entries": [
            {"id": "cls_register", "name": "Register", "type": "cosem_interface_class",
             "layer": "cosem_class", "definition": LONG_DEFINITION,
             "class_id": 3, "attributes": [{"id": 1}], "obis": ["1-0:1.8.0.255"]},
            {"id": "term_tariff", "name": "Tariff", "type": "term", "layer": "term",
             "definition": "费率"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return kb


def _bb_index_file(root: Path) -> Path:
    index = root / "blue_book_index.json"
    index.write_text(json.dumps({
        "interface_classes": {
            "3": {"name": "Register", "section": "4.3.2", "text": LONG_BB_TEXT},
            "4": {"name": "Extended register", "section": "4.3.3", "text": "short text"},
        }
    }, ensure_ascii=False), encoding="utf-8")
    return index


def _seed_out(root: Path) -> Path:
    out = root / "out"
    out.mkdir()
    _write_jsonl(out / "blocks.jsonl", [
        {"block_id": "B1", "order": 1, "type": "paragraph", "noise": False,
         "text": "The meter shall store 12 months of data in 1-0:1.8.0.255.",
         "section_path": ["4", "4.1"]},
        {"block_id": "B2", "order": 2, "type": "paragraph", "noise": False,
         "text": LONG_BLOCK_TEXT, "section_path": ["9"]},
    ])
    # 真实 A 轨形状（审计 H1）：requirement/object/parameters/section_path/source_refs/
    # source_context；真实 OBIS 在 parameters.cosem_object.obis——不再有 source_quote/
    # source_section 旧字段（同写新旧字段曾掩盖 consistency 函数全字段落空的缺陷）
    paragraph = "The meter shall store 12 months of data in 1-0:1.8.0.255."
    _write_jsonl(out / "atomic_requirements.jsonl", [
        {"stable_req_id": "SREQ-1", "req_id": "AREQ-1", "source_id": "SRC-1",
         "requirement_type": "data_definition", "confidence": 0.6,
         "object": "Energy register",
         "requirement": "Store 12 months of data in 1-0:1.8.0.255.",
         "section_path": ["4", "4.1"], "source_refs": ["SRC-1"],
         "source_context": {"paragraph_text": paragraph, "prev_sentence": None},
         "parameters": {"cosem_object": {"object_name": "Energy register", "class_id": 3,
                                          "obis": "1-0:1.8.0.255"}}},
        {"stable_req_id": "SREQ-2", "req_id": "AREQ-2", "source_id": "SRC-2",
         "requirement_type": "data_definition", "confidence": 0.6,
         "object": "Energy register",
         "requirement": "Archive 12 months of data in 1-0:1.8.0.255.",
         "section_path": ["4", "4.1"], "source_refs": ["SRC-2"],
         "source_context": {"paragraph_text": paragraph, "prev_sentence": None},
         "parameters": {"cosem_object": {"object_name": "Energy register", "class_id": 3,
                                          "obis": "1-0:1.8.0.255"}}},
        {"stable_req_id": "SREQ-3", "req_id": "AREQ-3", "source_id": "SRC-3",
         "requirement_type": "event_definition", "confidence": 0.6,
         "object": "Tamper log",
         "requirement": "Log tamper events.",
         "section_path": ["7"], "source_refs": ["SRC-3"],
         "source_context": {"paragraph_text": "Tamper events shall be logged.", "prev_sentence": None},
         "parameters": {}},
        # OBIS 只在结构化 parameters 里（叙述/段落均不复述）——适配层注入 description 的锚
        {"stable_req_id": "SREQ-4", "req_id": "AREQ-4", "source_id": "SRC-4",
         "requirement_type": "cosem_object_instance", "confidence": 0.88,
         "object": "Billing register",
         "requirement": "COSEM object Billing register / CL 3 shall be defined by the profile.",
         "section_path": ["5"], "source_refs": ["SRC-4"],
         "source_context": {"paragraph_text": "Billing data profiles follow contractual terms.",
                            "prev_sentence": None},
         "parameters": {"cosem_object": {"object_name": "Billing register", "class_id": 3,
                                          "obis": "1-0:1.8.0.255"}}},
    ])
    return out


class ToolExecutorFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.out = _seed_out(root)
        self.executor = make_tool_executor(
            self.out, kb_paths=[_kb_file(root)], blue_book_index_path=_bb_index_file(root))

    def tearDown(self) -> None:
        self._tmp.cleanup()


class KbSearchToolTests(ToolExecutorFixture):
    def test_hit_returns_trimmed_fields(self) -> None:
        result = self.executor("kb_search", {"query": "Register"})
        hits = result["results"]
        self.assertTrue(hits)
        first = hits[0]
        self.assertEqual(set(first), {"entry_id", "name", "definition", "score"})
        self.assertEqual(first["entry_id"], "cls_register")
        self.assertLessEqual(len(first["definition"]), KB_DEFINITION_MAX_CHARS + 40)  # 截断标记余量
        self.assertIn("<truncated", first["definition"])

    def test_miss_returns_empty_results(self) -> None:
        self.assertEqual(self.executor("kb_search", {"query": "zzz-no-such-term"}), {"results": []})

    def test_missing_query_is_error(self) -> None:
        self.assertIn("error", self.executor("kb_search", {}))

    def test_limit_capped_at_five(self) -> None:
        result = self.executor("kb_search", {"query": "a", "limit": 99})
        self.assertLessEqual(len(result["results"]), KB_SEARCH_MAX_RESULTS)

    def test_deterministic_repeat(self) -> None:
        self.assertEqual(self.executor("kb_search", {"query": "Register"}),
                         self.executor("kb_search", {"query": "Register"}))


class KbGetToolTests(ToolExecutorFixture):
    def test_hit_returns_compact_metadata_whitelist(self) -> None:
        result = self.executor("kb_get", {"entry_id": "cls_register"})
        entry = result["result"]
        self.assertEqual(entry["entry_id"], "cls_register")
        self.assertEqual(entry["type"], "cosem_interface_class")
        self.assertEqual(entry["metadata"]["class_id"], 3)          # compact 白名单字段
        self.assertNotIn("aliases", entry["metadata"])              # 非白名单不进
        self.assertLessEqual(len(entry["definition"]), KB_DEFINITION_MAX_CHARS + 40)

    def test_miss_returns_null(self) -> None:
        self.assertEqual(self.executor("kb_get", {"entry_id": "nope"}), {"result": None})

    def test_missing_entry_id_is_error(self) -> None:
        self.assertIn("error", self.executor("kb_get", {"entry_id": "  "}))


class BlueBookClassToolTests(ToolExecutorFixture):
    def test_lookup_by_class_id(self) -> None:
        result = self.executor("blue_book_class", {"class_id": 3})
        entry = result["result"]
        self.assertEqual(entry["name"], "Register")
        self.assertEqual(entry["section"], "4.3.2")
        self.assertLessEqual(len(entry["condensed"]), BLUE_BOOK_CONDENSED_MAX_CHARS + 80)
        self.assertIn("节选", entry["condensed"])   # condensed_text 截断后缀

    def test_lookup_by_exact_name(self) -> None:
        result = self.executor("blue_book_class", {"name": "Extended register"})
        self.assertEqual(result["result"]["section"], "4.3.3")
        self.assertEqual(result["result"]["condensed"], "short text")

    def test_miss_returns_null(self) -> None:
        self.assertEqual(self.executor("blue_book_class", {"class_id": 999}), {"result": None})
        self.assertEqual(self.executor("blue_book_class", {"name": "no such class"}), {"result": None})

    def test_neither_arg_is_error(self) -> None:
        self.assertIn("error", self.executor("blue_book_class", {}))

    def test_index_unavailable_returns_null_with_note(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = _seed_out(Path(td))
            executor = make_tool_executor(out, kb_paths=[], blue_book_index_path=Path(td) / "missing.json")
            result = executor("blue_book_class", {"class_id": 3})
        self.assertIsNone(result["result"])
        self.assertIn("不可用", result["note"])

    def test_no_index_candidate_path_never_raises(self) -> None:
        """回归（test3 验收实证）：无显式路径且探测不到任何候选索引时,_resolve 返回 None,
        v1 直接 load_index(None) 抛 AttributeError → 同一需求 tool-loop 两连错中止进 stub。
        v2 起按空索引优雅降级（未命中 null + note）。隔离本机 out/bluebook 自动探测,
        主检出与 worktree 行为一致。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = _seed_out(root)
            fake_pkg = root / "pkg"
            fake_pkg.mkdir()   # 隔离仓库 out/bluebook 的自动探测
            env = dict(os.environ)
            env.pop(review_tools.BLUE_BOOK_INDEX_ENV, None)
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("resources.package_root", return_value=fake_pkg):
                    executor = make_tool_executor(out, kb_paths=[], blue_book_index_path=None)
                    result = executor("blue_book_class", {"class_id": 3})
                    again = executor("blue_book_class", {"name": "Extended register"})
        self.assertNotIn("error", result)
        self.assertIsNone(result["result"])
        self.assertIn("不可用", result["note"])
        self.assertNotIn("error", again)


class SourceReadToolTests(ToolExecutorFixture):
    def test_source_read_cap_is_eight_hundred_chars(self) -> None:
        self.assertEqual(SOURCE_BLOCK_MAX_CHARS, 800)

    def test_hit_returns_text_and_section_path(self) -> None:
        result = self.executor("source_read", {"block_id": "B1"})
        self.assertEqual(result["block_id"], "B1")
        self.assertIn("12 months", result["text"])
        self.assertEqual(result["section_path"], ["4", "4.1"])

    def test_long_text_trimmed_at_cap(self) -> None:
        result = self.executor("source_read", {"block_id": "B2"})
        self.assertLessEqual(len(result["text"]), SOURCE_BLOCK_MAX_CHARS + 40)
        self.assertIn("<truncated", result["text"])

    def test_unknown_id_is_error(self) -> None:
        self.assertIn("unknown block_id", self.executor("source_read", {"block_id": "BZZ"})["error"])

    def test_missing_block_id_is_error(self) -> None:
        self.assertIn("error", self.executor("source_read", {}))


class CoverageCheckToolTests(ToolExecutorFixture):
    def test_hit_quote_coreference_duplicates(self) -> None:
        result = self.executor("coverage_check", {"requirement_id": "SREQ-1"})
        self.assertEqual(result["requirement_id"], "SREQ-1")
        self.assertEqual(result["quote_hit_block_ids"], ["B1"])      # paragraph_text 确定性命中块
        self.assertEqual(result["match_methods"], ["exact"])         # 段落全文 == 块文本
        coref = result["obis_coreference"]
        self.assertEqual(len(coref), 1)
        self.assertEqual(coref[0]["obis"], "1-0:1.8.0.255")          # 共引 OBIS 清单
        # 成员为适配行的 req_id；AREQ-4 的 OBIS 仅来自结构化 parameters（叙述未复述）
        self.assertEqual(set(coref[0]["members"]), {"AREQ-1", "AREQ-2", "AREQ-4"})
        dups = result["duplicate_candidates"]
        self.assertEqual(len(dups), 1)                               # 重复候选（同段落引句）
        self.assertEqual(set(dups[0]["members"]), {"AREQ-1", "AREQ-2"})

    def test_structured_obis_only_requirement_joins_coreference(self) -> None:
        """OBIS 只在 parameters.cosem_object.obis（叙述与段落均不复述）的需求也进共引组——
        适配层把结构化编码注入 description,extract_codes 才能命中（审计 H1 锚）。"""
        result = self.executor("coverage_check", {"requirement_id": "SREQ-4"})
        coref = result["obis_coreference"]
        self.assertEqual(len(coref), 1)
        self.assertEqual(coref[0]["obis"], "1-0:1.8.0.255")
        self.assertIn("AREQ-4", coref[0]["members"])

    def test_requirement_without_group_gets_empty_lists(self) -> None:
        result = self.executor("coverage_check", {"requirement_id": "SREQ-3"})
        self.assertEqual(result["quote_hit_block_ids"], [])
        self.assertEqual(result["obis_coreference"], [])
        self.assertEqual(result["duplicate_candidates"], [])

    def test_lookup_by_secondary_id(self) -> None:
        # 模型可能拿 req_id 而非 stable_req_id——候选 id 全集匹配
        result = self.executor("coverage_check", {"requirement_id": "AREQ-1"})
        self.assertEqual(result["requirement_id"], "AREQ-1")
        self.assertEqual(result["quote_hit_block_ids"], ["B1"])

    def test_unknown_id_is_error(self) -> None:
        self.assertIn("unknown requirement_id", self.executor("coverage_check", {"requirement_id": "X"})["error"])

    def test_deterministic_repeat(self) -> None:
        self.assertEqual(self.executor("coverage_check", {"requirement_id": "SREQ-1"}),
                         self.executor("coverage_check", {"requirement_id": "SREQ-1"}))


class ToolContractTests(unittest.TestCase):
    """TOOLS 定义（名称/参数/返回裁剪）变更必须 bump REVIEW_TOOLS_VERSION——
    本测试是联动绊线：改 TOOLS 不改版本 → 指纹断言失败；改版本 → 版本断言提醒同步指纹。"""

    # review-tools-v1 的 TOOLS 规范指纹（canonical JSON sha256）；变更工具面时连同
    # REVIEW_TOOLS_VERSION 一起更新本指纹（缓存失效靠它,见 llm_pipeline.llm_cache_key）
    _PINNED_TOOLS_FINGERPRINT = "cac9c497ab24b8e81b593aa8f9488937bac38ff13305f32d83b52f3471f70357"
    _PINNED_VERSION = "review-tools-v5"

    def test_version_constant(self) -> None:
        self.assertEqual(REVIEW_TOOLS_VERSION, self._PINNED_VERSION)

    def test_tools_fingerprint_matches_version(self) -> None:
        canonical = json.dumps(TOOLS, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if not self._PINNED_TOOLS_FINGERPRINT:
            self.fail(f"pin the fingerprint for {REVIEW_TOOLS_VERSION}: {fingerprint}")
        self.assertEqual(fingerprint, self._PINNED_TOOLS_FINGERPRINT)

    def test_five_tools_openai_shape(self) -> None:
        self.assertEqual(
            [tool["function"]["name"] for tool in TOOLS],
            ["kb_search", "kb_get", "blue_book_class", "source_read", "coverage_check"],
        )
        for tool in TOOLS:
            self.assertEqual(tool["type"], "function")
            params = tool["function"]["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertFalse(params["additionalProperties"])   # 严格参数面（未知参数端点侧可拒）

    def test_unknown_tool_name_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            executor = make_tool_executor(Path(td))
            result = executor("kb_delete", {})
        self.assertIn("unknown tool", result["error"])
        self.assertIn("kb_search", result["error"])   # 如实列出可用工具面

    def test_executor_never_raises_on_data_failure(self) -> None:
        """数据源缺失（KB 路径不存在）→ {"error": ...} 回灌,不抛穿回调契约。"""
        with tempfile.TemporaryDirectory() as td:
            executor = make_tool_executor(Path(td), kb_paths=[Path(td) / "missing_kb.json"])
            result = executor("kb_search", {"query": "x"})
        self.assertIn("error", result)


def _reference_coverage_check(
    requirements: list[dict],
    blocks: list[dict],
    requirement_id: str,
) -> dict:
    """旧路径参考实现（每次调用全量重算,逐字对应 v4 逐调用算法）。

    执行器记忆化路径（v5：一次性块索引/需求索引/一致性分组/引句匹配语料）必须与
    本参考在任意输入上逐字节恒等——双路比对锁定"只提速、不改结果"。"""
    from merged_consistency import (
        find_cross_section_duplicates,
        find_obis_coreference,
        match_source_quote_blocks,
    )
    requirement = review_tools._find_requirement(requirements, requirement_id)
    if requirement is None:
        return {"error": f"unknown requirement_id: {requirement_id}"}
    candidate_ids = review_tools._requirement_candidate_ids(requirement)
    consistency_rows = [review_tools._atomic_to_consistency_row(row) for row in requirements]
    target_row = review_tools._atomic_to_consistency_row(requirement)
    quote = str(target_row.get("source_quote") or "")
    hit_block_ids: list[str] = []
    methods: list[str] = []
    if quote.strip():
        matched, method = match_source_quote_blocks(quote, blocks)
        for block_id in matched:
            if block_id not in hit_block_ids:
                hit_block_ids.append(block_id)
        if method:
            methods.append(method)
    coreference = [
        {"obis": str(group.get("obis") or ""), "members": [str(m) for m in (group.get("members") or [])],
         "values_differ": bool(group.get("values_differ")), "count": group.get("count")}
        for group in find_obis_coreference(consistency_rows)
        if candidate_ids.intersection(str(m) for m in (group.get("members") or []))
    ][:review_tools._COVERAGE_GROUP_MAX]
    duplicates = [
        {"members": [str(m) for m in (group.get("members") or [])],
         "sections": [str(s) for s in (group.get("sections") or [])], "count": group.get("count")}
        for group in find_cross_section_duplicates(consistency_rows)
        if candidate_ids.intersection(str(m) for m in (group.get("members") or []))
    ][:review_tools._COVERAGE_GROUP_MAX]
    return {
        "requirement_id": requirement_id,
        "quote_hit_block_ids": hit_block_ids,
        "match_methods": methods,
        "obis_coreference": coreference,
        "duplicate_candidates": duplicates,
    }


def _reference_source_read(blocks: list[dict], block_id: str) -> dict:
    """旧路径参考实现（空 id 守卫 + 线性扫描首个命中）——与执行器块索引路径恒等比对。"""
    if not str(block_id or "").strip():
        return {"error": "source_read requires a non-empty block_id"}
    for block in blocks:
        if str(block.get("block_id") or "") == block_id:
            return {
                "block_id": block_id,
                "text": review_tools._trim(block.get("text"), review_tools.SOURCE_BLOCK_MAX_CHARS),
                "section_path": [str(value) for value in (block.get("section_path") or [])],
            }
    return {"error": f"unknown block_id: {block_id}"}


def _synthetic_corpus(root: Path) -> Path:
    """多样性合成语料：乱序 order/重复 block_id/噪声块/空文本/多段引句/结构化 OBIS/
    候选 id 交集/超短引句——把两路实现可能分叉的缝全部钉住。"""
    out = root / "out-corpus"
    out.mkdir()
    shared_paragraph = "The meter shall store 12 months of load profile data in 1-0:1.8.0.255."
    _write_jsonl(out / "blocks.jsonl", [
        # order 乱序 + 同 block_id 重复（首个命中为准确认 first-wins）
        {"block_id": "B5", "order": 5, "type": "paragraph", "noise": False,
         "text": "Tamper events shall be logged with timestamps.", "section_path": ["7"]},
        {"block_id": "B1", "order": 1, "type": "paragraph", "noise": False,
         "text": shared_paragraph, "section_path": ["4", "4.1"]},
        {"block_id": "B2", "order": 2, "type": "paragraph", "noise": True,
         "text": "Machine Translated by Google", "section_path": []},
        {"block_id": "B3", "order": 3, "type": "paragraph", "noise": False,
         "text": "Page 12", "section_path": []},
        {"block_id": "B4", "order": 4, "type": "table_row", "noise": False,
         "text": "最大需量 1-0:1.6.0.255 存储 12 个月", "section_path": ["5", "5.2"]},
        # 无 order / 空 text / 非 dict 兼容字段缺失
        {"block_id": "B6", "type": "paragraph", "noise": False, "text": "", "section_path": ["8"]},
        {"block_id": "B7", "order": 7, "type": "paragraph", "noise": False,
         "text": "Part one of a split quote about demand.", "section_path": ["6"]},
        {"block_id": "B8", "order": 8, "type": "paragraph", "noise": False,
         "text": "Part two of the split quote continues here.", "section_path": ["6"]},
        # 重复 block_id：文件序在前者胜（与旧线性扫描一致）
        {"block_id": "B5", "order": 9, "type": "paragraph", "noise": False,
         "text": "LATER DUPLICATE never wins", "section_path": ["9"]},
    ])
    _write_jsonl(out / "atomic_requirements.jsonl", [
        {"stable_req_id": "SYN-1", "req_id": "SYNR-1", "source_id": "SYNS-1",
         "object": "Load profile register", "requirement_type": "data_definition",
         "requirement": "Store 12 months of load profile data in 1-0:1.8.0.255.",
         "section_path": ["4", "4.1"], "source_context": {"paragraph_text": shared_paragraph},
         "parameters": {"cosem_object": {"obis": "1-0:1.8.0.255", "class_id": 3}}},
        {"stable_req_id": "SYN-2", "req_id": "SYNR-2", "source_id": "SYNS-2",
         "object": "Load profile register", "requirement_type": "data_definition",
         "requirement": "Archive 12 months of load profile data in 1-0:1.8.0.255 with 32 entries.",
         "section_path": ["4", "4.2"], "source_context": {"paragraph_text": shared_paragraph},
         "parameters": {"cosem_object": {"obis": "1-0:1.8.0.255", "class_id": 3}}},
        # 多段摘录引句（省略号分隔）——match_source_quote_blocks 分片路径
        {"stable_req_id": "SYN-3", "req_id": "SYNR-3", "source_id": "SYNS-3",
         "object": "Split quote", "requirement_type": "event_definition",
         "requirement": "Demand records span two blocks.",
         "section_path": ["6"],
         "source_context": {"paragraph_text":
                            "Part one of a split quote about demand. … Part two of the split quote continues here."},
         "parameters": {}},
        # 结构化 OBIS（叙述不复述）+ 无段落 → 引句退 requirement 文本
        {"stable_req_id": "SYN-4", "req_id": "SYNR-4", "source_id": "SYNS-4",
         "object": "Demand register", "requirement_type": "cosem_object_instance",
         "requirement": "最大需量 1-0:1.6.0.255 存储 12 个月",
         "section_path": ["5", "5.2"], "parameters": {"cosem_object": {"obis": "1-0:1.6.0.255"}}},
        # 超短引句（<12 归一字符）——不参与来源匹配
        {"stable_req_id": "SYN-5", "req_id": "SYNR-5", "source_id": "SYNS-5",
         "object": "Short", "requirement_type": "event_definition",
         "requirement": "Log events.", "section_path": ["7"],
         "source_context": {"paragraph_text": "see 4.2"}},
        # 候选 id 与他行碰撞（req_id 与 SYN-1 的 source_id 不同名,但 SOURCE 行缺失验证 unknown）
        {"stable_req_id": "SYN-6", "req_id": "SYNR-6", "source_id": "SYNS-6",
         "object": "No quote", "requirement_type": "event_definition",
         "requirement": "Nothing quotable.", "section_path": ["8"],
         "source_context": {"paragraph_text": ""}, "parameters": {}},
    ])
    return out


class ExecutorMemoizationIdentityTests(unittest.TestCase):
    """v5 记忆化执行器 vs v4 逐调用全量重算参考实现：任意输入上逐字节恒等。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.corpus = _synthetic_corpus(root)
        self.requirements = [
            json.loads(line) for line in
            (self.corpus / "atomic_requirements.jsonl").read_text(encoding="utf-8").splitlines() if line
        ]
        self.blocks = [
            json.loads(line) for line in
            (self.corpus / "blocks.jsonl").read_text(encoding="utf-8").splitlines() if line
        ]
        self.executor = make_tool_executor(
            self.corpus, kb_paths=[], blue_book_index_path=root / "missing.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _all_lookup_ids(self) -> list[str]:
        ids: list[str] = []
        for row in self.requirements:
            ids.extend(sorted(review_tools._requirement_candidate_ids(row)))
        return ids

    def test_coverage_check_identical_to_per_call_recompute(self) -> None:
        for requirement_id in (*self._all_lookup_ids(), "SYN-1", "SYNR-3", "NO-SUCH-ID"):
            with self.subTest(requirement_id=requirement_id):
                memoized = self.executor("coverage_check", {"requirement_id": requirement_id})
                reference = _reference_coverage_check(
                    self.requirements, self.blocks, requirement_id)
                self.assertEqual(memoized, reference)

    def test_coverage_check_identity_holds_across_repeat_calls(self) -> None:
        # 同一执行器反复调用（记忆化命中路径）也不得漂移
        for _ in range(3):
            for requirement_id in ("SYN-1", "SYN-3", "SYN-4", "SYN-5"):
                memoized = self.executor("coverage_check", {"requirement_id": requirement_id})
                reference = _reference_coverage_check(
                    self.requirements, self.blocks, requirement_id)
                self.assertEqual(memoized, reference)

    def test_source_read_identical_to_linear_scan(self) -> None:
        block_ids = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "", "BZZ"]
        for _ in range(2):
            for block_id in block_ids:
                with self.subTest(block_id=block_id):
                    self.assertEqual(
                        self.executor("source_read", {"block_id": block_id}),
                        _reference_source_read(self.blocks, block_id),
                    )

    def test_consistency_analysis_runs_once_per_executor(self) -> None:
        """全文档一致性分组（共引/重复）在执行器生命周期内只计算一次——
        每次工具调用重算是 v4 的性能缺陷,不是契约。"""
        import merged_consistency
        calls = {"coref": 0, "dups": 0}
        original_coref = merged_consistency.find_obis_coreference
        original_dups = merged_consistency.find_cross_section_duplicates

        def counting_coref(rows):
            calls["coref"] += 1
            return original_coref(rows)

        def counting_dups(rows):
            calls["dups"] += 1
            return original_dups(rows)

        with mock.patch.object(merged_consistency, "find_obis_coreference", counting_coref), \
                mock.patch.object(merged_consistency, "find_cross_section_duplicates", counting_dups):
            for requirement_id in ("SYN-1", "SYN-2", "SYN-3", "SYN-4", "SYN-1", "SYN-6"):
                self.assertNotIn("error", self.executor(
                    "coverage_check", {"requirement_id": requirement_id}))
        self.assertEqual(calls["coref"], 1)
        self.assertEqual(calls["dups"], 1)

    def test_quote_corpus_built_once_per_executor(self) -> None:
        """块语料（排序 + 逐块归一化）只在首次使用时构建——每次引句匹配重新
        排序/归一化全部块是 v4 的性能缺陷,不是契约。"""
        import merged_consistency
        ordered_calls = {"count": 0}
        compact_calls = {"count": 0}
        original_ordered = merged_consistency._ordered_source_blocks
        original_compact = merged_consistency.compact_source_text

        def counting_ordered(blocks):
            ordered_calls["count"] += 1
            return original_ordered(blocks)

        def counting_compact(text):
            compact_calls["count"] += 1
            return original_compact(text)

        with mock.patch.object(merged_consistency, "_ordered_source_blocks", counting_ordered), \
                mock.patch.object(merged_consistency, "compact_source_text", counting_compact):
            for requirement_id in ("SYN-1", "SYN-2", "SYN-3", "SYN-4", "SYN-6"):
                self.assertNotIn("error", self.executor(
                    "coverage_check", {"requirement_id": requirement_id}))
            self.assertEqual(ordered_calls["count"], 1)   # 块语料只构建一次
            before = compact_calls["count"]
            # 同一需求重复调用：语料与引句命中全记忆化,零新增归一化
            self.executor("coverage_check", {"requirement_id": "SYN-1"})
            self.executor("coverage_check", {"requirement_id": "SYN-3"})
            self.assertEqual(compact_calls["count"], before)


if __name__ == "__main__":
    unittest.main()
