"""Agent Phase 2 WP1-B：review_tools 五工具的冻结契约测试。

正/反例、返回裁剪、未命中如实 null/error、确定性复现、TOOLS schema 与
REVIEW_TOOLS_VERSION 的联动契约（工具定义变更而版本未 bump → 本文件契约测试失败）。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

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
LONG_BLOCK_TEXT = "原文块内容" * 600          # 3000 字 > 2000 裁剪帽
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
    quote = "store 12 months of data in 1-0:1.8.0.255"
    _write_jsonl(out / "atomic_requirements.jsonl", [
        {"stable_req_id": "SREQ-1", "req_id": "AREQ-1", "source_id": "SRC-1",
         "requirement_type": "data_definition", "confidence": 0.6,
         "requirement": "Store 12 months of data in 1-0:1.8.0.255.",
         "source_quote": quote, "source_section": "4.1", "source_refs": ["SRC-1"]},
        {"stable_req_id": "SREQ-2", "req_id": "AREQ-2", "source_id": "SRC-2",
         "requirement_type": "data_definition", "confidence": 0.6,
         "requirement": "Archive 12 months of data in 1-0:1.8.0.255.",
         "source_quote": quote, "source_section": "4.1", "source_refs": ["SRC-2"]},
        {"stable_req_id": "SREQ-3", "req_id": "AREQ-3", "source_id": "SRC-3",
         "requirement_type": "event_definition", "confidence": 0.6,
         "requirement": "Log tamper events.", "source_quote": "log tamper events now",
         "source_section": "7", "source_refs": ["SRC-3"]},
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


class SourceReadToolTests(ToolExecutorFixture):
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
        self.assertEqual(result["quote_hit_block_ids"], ["B1"])      # 引句确定性命中块
        coref = result["obis_coreference"]
        self.assertEqual(len(coref), 1)
        self.assertEqual(coref[0]["obis"], "1-0:1.8.0.255")          # 共引 OBIS 清单
        self.assertEqual(set(coref[0]["members"]), {"SREQ-1", "SREQ-2"})
        dups = result["duplicate_candidates"]
        self.assertEqual(len(dups), 1)                               # 跨章重复候选（同引句）
        self.assertEqual(set(dups[0]["members"]), {"SREQ-1", "SREQ-2"})

    def test_requirement_without_group_gets_empty_lists(self) -> None:
        result = self.executor("coverage_check", {"requirement_id": "SREQ-3"})
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
    _PINNED_TOOLS_FINGERPRINT = "529a90d7ac78c05543dd009811b73e710ad674e5e45305e1b2c50faba2084b02"
    _PINNED_VERSION = "review-tools-v1"

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


if __name__ == "__main__":
    unittest.main()
