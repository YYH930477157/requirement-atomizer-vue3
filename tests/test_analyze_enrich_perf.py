"""性能修复回归（2026-08-14）：

- FIX 1：analyze_enrich_cache 改增量 JSONL（meta 行 + key/item 行）——每完成一个任务
  追加一行 fsync，不再整写全量 JSON（O(任务×缓存) 二次开销）；读侧 last-write-wins，
  且兼容只读旧版单 JSON 文件（read-both，JSONL 后读覆盖）。
- FIX 2：合批缺槽回退不再在批任务内串行单条重试——批任务把缺槽 job 原样交还编排器，
  编排器以独立单条任务重发到同一线程池（work_single），护栏/缓存语义不变。
- FIX 6：_software_prompt_parts 的模块词表序列化按 (run, module) 记忆化——同模块
  多条不再逐条重复 slim_vocabulary + json.dumps（结果逐字节等价，key 不变）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requirements_analysis as ra
from requirements_analysis import (
    ANALYZE_ENRICH_CACHE,
    ANALYZE_ENRICH_CACHE_LEGACY,
    ANALYZE_PROMPT_VERSION,
    ENRICH_CACHE_FORMAT_VERSION,
    _load_enrich_cache,
    _llm_enrich_batch,
    _llm_enrich_hardware_batch,
    _save_enrich_cache,
    _software_prompt_parts,
    run_requirements_analysis,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def _seed(out: Path, count: int, *, module: str = "事件记录") -> None:
    _write_jsonl(out / "ai_requirements.jsonl", [
        {"ai_req_id": f"AI-{i}", "title": f"任务{i}",
         "description": f"The meter shall do task {i}.",
         "source_quote": f"shall do task {i}",
         "source_block_ids": [f"B-{i}"], "module": module}
        for i in range(count)
    ])


CTX = {"template_refs": "", "exemplars": "", "answers": "",
       "doc_context": "", "section_context": "", "siblings": ""}


class BatchSlotRetryTests(unittest.TestCase):
    """FIX 2：缺槽由编排器以独立单条任务重发——批任务自身不再串行重试。"""

    def test_software_batch_missing_slots_returned_for_orchestrator(self) -> None:
        req_a = {"ai_req_id": "AI-A", "module": "事件记录",
                 "description": "Requirement alpha.", "source_quote": "Requirement alpha."}
        req_b = {"ai_req_id": "AI-B", "module": "事件记录",
                 "description": "Requirement beta.", "source_quote": "Requirement beta."}
        item_a = {"analysis_id": "SRA-001", "ownership": "software",
                  "ownership_reason": "rule", "ownership_source": "rule"}
        item_b = {"analysis_id": "SRA-002", "ownership": "software",
                  "ownership_reason": "rule", "ownership_source": "rule"}
        jobs = [(item_a, req_a, dict(CTX), "software"),
                (item_b, req_b, dict(CTX), "software")]
        calls: list[str] = []

        def chat(system: str, user: str) -> dict:
            calls.append(user)
            # 只回槽位 0——槽位 1 缺失
            return {"items": [{"enrich_slot": 0,
                               "software_requirement_text": "甲条成文。"}]}

        results, retries = _llm_enrich_batch(
            jobs, {"modules": ["事件记录"]}, chat, {}, "m")

        self.assertEqual(len(calls), 1)                     # 批任务内绝不再补单条调用
        self.assertEqual([r[0]["analysis_id"] for r in results], ["SRA-001"])
        self.assertTrue(results[0][1])
        self.assertEqual(retries, [jobs[1]])                # 缺槽 job 原样交还编排器

    def test_software_batch_total_failure_returns_all_pending(self) -> None:
        reqs = [({"analysis_id": f"SRA-{i}", "ownership": "software",
                  "ownership_reason": "rule", "ownership_source": "rule"},
                 {"ai_req_id": f"AI-{i}", "module": "事件记录",
                  "description": f"Requirement {i}.", "source_quote": f"Requirement {i}."},
                 dict(CTX), "software") for i in range(3)]

        def chat(system: str, user: str) -> dict:
            raise RuntimeError("batch boom")

        results, retries = _llm_enrich_batch(reqs, {"modules": []}, chat, {}, "m")
        self.assertEqual(results, [])
        self.assertEqual(retries, reqs)                     # 整批失败 → 全部交还重试

    def test_hardware_batch_missing_slots_returned_for_orchestrator(self) -> None:
        jobs = [
            ({"analysis_id": "SRA-H1", "ownership": "hardware"},
             {"ai_req_id": "AI-H1", "module": "机械结构",
              "description": "Sealed metal enclosure alpha.", "source_quote": "Sealed metal enclosure."},
             {}, "hardware"),
            ({"analysis_id": "SRA-H2", "ownership": "hardware"},
             {"ai_req_id": "AI-H2", "module": "机械结构",
              "description": "Sealed metal enclosure beta.", "source_quote": "Sealed metal enclosure."},
             {}, "hardware"),
        ]
        calls: list[str] = []

        def chat(system: str, user: str) -> dict:
            calls.append(user)
            return {"items": [{"enrich_slot": 0, "hardware_translation": "密封金属外壳甲。"}]}

        results, retries = _llm_enrich_hardware_batch(jobs, chat, {}, "m")

        self.assertEqual(len(calls), 1)
        self.assertEqual([r[0]["analysis_id"] for r in results], ["SRA-H1"])
        self.assertEqual(retries, [jobs[1]])

    def test_run_level_missing_slots_enriched_via_independent_singles(self) -> None:
        """端到端：合批缺 2 槽 → 编排器补 2 个独立单条任务，全部条目最终富化且不串条。"""
        batch_calls: list[str] = []
        single_calls: list[str] = []

        def chat(system: str, user: str) -> dict:
            if "（合批）" in user:                           # 合批 prompt 特征串
                batch_calls.append(user)
                return {"items": [
                    {"enrich_slot": 0, "software_requirement_text": "任务甲成文。"},
                    {"enrich_slot": 1, "software_requirement_text": "任务乙成文。"},
                ]}                                          # 槽位 2/3 缺失
            single_calls.append(user)
            entries = json.loads(user.split("需求 JSON:")[-1].strip())
            req_id = entries[0].get("ai_req_id") or ""
            return {"items": [{"software_requirement_text": f"{req_id} 单条补齐成文。"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 4)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            payload = json.loads((out / "engineering_analysis.json").read_text(encoding="utf-8"))
            texts = {item["source_requirement_ids"][0]: item["software_requirement_text"]
                     for item in payload["items"]}

        self.assertEqual(result["enriched"], 4)
        self.assertEqual(result["enrich_degraded"], 0)
        self.assertEqual(len(batch_calls), 1)
        self.assertEqual(len(single_calls), 2)              # 只有缺的 2 条走单条重试
        self.assertEqual(texts["AI-0"], "任务甲成文。")
        self.assertEqual(texts["AI-1"], "任务乙成文。")
        self.assertEqual(texts["AI-2"], "AI-2 单条补齐成文。")
        self.assertEqual(texts["AI-3"], "AI-3 单条补齐成文。")


class EnrichCacheJsonlTests(unittest.TestCase):
    """FIX 1：JSONL 增量缓存——meta 行 + key/item 行；旧单 JSON 只读兼容。"""

    def _run(self, out: Path, chat) -> dict:
        return run_requirements_analysis(out, route="openai_compatible", chat=chat)

    def test_run_writes_jsonl_meta_plus_item_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 3)
            self._run(out, lambda s, u: {"items": [{"software_requirement_text": "成文。"}]})

            legacy = out / ANALYZE_ENRICH_CACHE_LEGACY
            jsonl = out / ANALYZE_ENRICH_CACHE
            self.assertFalse(legacy.exists())               # 新运行不再写旧形状
            self.assertTrue(jsonl.exists())
            lines = jsonl.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1 + 3)             # 1 meta + 每键一行，无重复
            meta = json.loads(lines[0])
            self.assertEqual(meta, {"_meta": True, "format": ENRICH_CACHE_FORMAT_VERSION,
                                    "prompt": ANALYZE_PROMPT_VERSION, "model": "injected"})
            for line in lines[1:]:
                row = json.loads(line)
                self.assertIn("key", row)
                self.assertIsInstance(row["item"], dict)

    def test_incremental_append_never_rewrites_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "analyze_enrich_cache.jsonl"
            _save_enrich_cache(Path(td), "injected", [("k1", {"software_requirement_text": "一"})])
            first_snapshot = path.read_text(encoding="utf-8")
            _save_enrich_cache(Path(td), "injected", [("k2", {"software_requirement_text": "二"})])
            second_snapshot = path.read_text(encoding="utf-8")
            self.assertTrue(second_snapshot.startswith(first_snapshot))   # 只追加不重写
            self.assertEqual(len(second_snapshot.splitlines()), 3)
            self.assertEqual(json.loads(second_snapshot.splitlines()[0])["format"],
                             ENRICH_CACHE_FORMAT_VERSION)   # meta 行只在建文件时写一次

    def test_second_run_hits_cache_without_new_rows_or_calls(self) -> None:
        calls = {"n": 0}

        def chat(s, u):
            calls["n"] += 1
            entries = json.loads(u.split("需求 JSON:")[-1].strip())
            return {"items": [{"enrich_slot": slot, "software_requirement_text": "成文。"}
                              for slot in range(len(entries))]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 3)
            self._run(out, chat)
            after_first = (out / ANALYZE_ENRICH_CACHE).read_text(encoding="utf-8")
            self._run(out, chat)
            after_second = (out / ANALYZE_ENRICH_CACHE).read_text(encoding="utf-8")

        self.assertEqual(calls["n"], 1)                     # 一批一次调用；二跑零新调用
        self.assertEqual(after_first, after_second)         # 命中不追加（无重复行）

    def test_loader_reads_legacy_single_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            legacy = Path(td) / ANALYZE_ENRICH_CACHE_LEGACY
            legacy.write_text(json.dumps({
                "_meta": {"prompt": ANALYZE_PROMPT_VERSION, "model": "injected"},
                "items": {"k1": {"software_requirement_text": "旧缓存正文。"}}},
                ensure_ascii=False), encoding="utf-8")
            self.assertEqual(_load_enrich_cache(Path(td), "injected"),
                             {"k1": {"software_requirement_text": "旧缓存正文。"}})
            # prompt/模型漂移 → 旧缓存整份弃用（防复用异模型产物）
            self.assertEqual(_load_enrich_cache(Path(td), "other-model"), {})

    def test_loader_jsonl_wins_over_legacy_per_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td).joinpath(ANALYZE_ENRICH_CACHE_LEGACY).write_text(json.dumps({
                "_meta": {"prompt": ANALYZE_PROMPT_VERSION, "model": "injected"},
                "items": {"k1": {"v": "legacy"}, "k2": {"v": "legacy-only"}}},
                ensure_ascii=False), encoding="utf-8")
            Path(td).joinpath(ANALYZE_ENRICH_CACHE).write_text(
                json.dumps({"_meta": True, "format": ENRICH_CACHE_FORMAT_VERSION,
                            "prompt": ANALYZE_PROMPT_VERSION, "model": "injected"}) + "\n"
                + json.dumps({"key": "k1", "item": {"v": "jsonl"}}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            loaded = _load_enrich_cache(Path(td), "injected")
        self.assertEqual(loaded, {"k1": {"v": "jsonl"}, "k2": {"v": "legacy-only"}})

    def test_loader_jsonl_last_write_wins(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ANALYZE_ENRICH_CACHE
            path.write_text(
                json.dumps({"_meta": True, "format": ENRICH_CACHE_FORMAT_VERSION,
                            "prompt": ANALYZE_PROMPT_VERSION, "model": "injected"}) + "\n"
                + json.dumps({"key": "k1", "item": {"v": "first"}}) + "\n"
                + json.dumps({"key": "k1", "item": {"v": "second"}}) + "\n",
                encoding="utf-8")
            self.assertEqual(_load_enrich_cache(Path(td), "injected"), {"k1": {"v": "second"}})

    def test_loader_rejects_wrong_format_meta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td).joinpath(ANALYZE_ENRICH_CACHE).write_text(
                json.dumps({"_meta": True, "format": "analyze-enrich-cache-v1",
                            "prompt": ANALYZE_PROMPT_VERSION, "model": "injected"}) + "\n"
                + json.dumps({"key": "k1", "item": {"v": "stale-shape"}}) + "\n",
                encoding="utf-8")
            self.assertEqual(_load_enrich_cache(Path(td), "injected"), {})

    def test_loader_repairs_torn_tail_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ANALYZE_ENRICH_CACHE
            valid = (json.dumps({"_meta": True, "format": ENRICH_CACHE_FORMAT_VERSION,
                                 "prompt": ANALYZE_PROMPT_VERSION, "model": "injected"}) + "\n"
                     + json.dumps({"key": "k1", "item": {"v": "ok"}}) + "\n")
            path.write_text(valid + '{"key":', encoding="utf-8")   # 中断的尾行写入
            with self.assertLogs("requirement_atomizer", level="WARNING"):
                loaded = _load_enrich_cache(Path(td), "injected")
            self.assertEqual(loaded, {"k1": {"v": "ok"}})

    def test_legacy_cache_file_hits_end_to_end(self) -> None:
        """旧版单 JSON 在新版读侧照样命中（read-both 迁移语义），零新 LLM 调用。"""
        calls = {"n": 0}

        def chat(s, u):
            calls["n"] += 1
            return {"items": [{"software_requirement_text": "不该被调用。"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 1)
            from requirements_analysis_template import extract_template_vocabulary
            req = {"ai_req_id": "AI-0", "title": "任务0",
                   "description": "The meter shall do task 0.",
                   "source_quote": "shall do task 0",
                   "source_block_ids": ["B-0"], "module": "事件记录"}
            ctx = {"template_refs": "", "answers": "", "section_context": ""}
            _, _, key = _software_prompt_parts(
                {"ownership": "software"}, req, extract_template_vocabulary(None), "injected", ctx)
            (out / ANALYZE_ENRICH_CACHE_LEGACY).write_text(json.dumps({
                "_meta": {"prompt": ANALYZE_PROMPT_VERSION, "model": "injected"},
                "items": {key: {"software_requirement_text": "旧缓存命中的正文。"}}},
                ensure_ascii=False), encoding="utf-8")

            result = self._run(out, chat)

        self.assertEqual(calls["n"], 0)                     # 命中旧缓存，零调用
        self.assertEqual(result["enriched"], 1)
        self.assertEqual(result["enrich_degraded"], 0)

    def test_enrich_key_covers_cache_format_version(self) -> None:
        """文件格式版本必须折进内容指纹——旧形状键永不与新形状键碰撞。"""
        req = {"source_quote": "q", "description": "d", "requirement": "r", "module": "m"}
        key_now = ra._enrich_key(req, "model-x")
        with patch.object(ra, "ENRICH_CACHE_FORMAT_VERSION", "analyze-enrich-cache-vNEXT"):
            key_changed = ra._enrich_key(req, "model-x")
        self.assertNotEqual(key_now, key_changed)


class VocabSerializationMemoTests(unittest.TestCase):
    """FIX 6：模块词表瘦身+序列化按 (run, module) 记忆化——同模块只算一次，key 不变。"""

    SOURCE = {"ai_req_id": "AI-1", "module": "计量",
              "description": "The meter shall store data.",
              "source_quote": "The meter shall store data."}
    VOCAB = {"modules": ["计量", "时钟"], "submodules_by_module": {"计量": ["存储"], "时钟": []}}
    ITEM = {"analysis_id": "SRA-001", "ownership": "software",
            "ownership_reason": "rule", "ownership_source": "rule"}

    def test_memo_reuses_slim_vocab_and_serialization_per_module(self) -> None:
        import requirements_analysis_agent as agent
        calls = {"n": 0}
        real = agent.slim_vocabulary

        def counting(vocabulary, module):
            calls["n"] += 1
            return real(vocabulary, module)

        memo: dict = {}
        with patch.object(agent, "slim_vocabulary", side_effect=counting):
            parts_a = _software_prompt_parts(dict(self.ITEM), self.SOURCE, self.VOCAB, "m", CTX, memo)
            parts_b = _software_prompt_parts(dict(self.ITEM), self.SOURCE, self.VOCAB, "m", CTX, memo)
            other_module = dict(self.SOURCE, module="时钟")
            parts_c = _software_prompt_parts(dict(self.ITEM), other_module, self.VOCAB, "m", CTX, memo)

        self.assertEqual(calls["n"], 2)                     # 同模块第二次命中 memo
        self.assertEqual(parts_a[2], parts_b[2])            # key 逐字节不变
        self.assertNotEqual(parts_a[2], parts_c[2])

    def test_memo_is_per_run_instance(self) -> None:
        """memo 生命周期=一次 run（词表对象随 run 重建）——跨 run 不串词表。"""
        memo_a: dict = {}
        memo_b: dict = {}
        vocab_a = {"modules": ["计量"], "submodules_by_module": {"计量": ["存储"]}}
        vocab_b = {"modules": ["计量"], "submodules_by_module": {"计量": ["新版子模块"]}}
        key_a = _software_prompt_parts(dict(self.ITEM), self.SOURCE, vocab_a, "m", CTX, memo_a)[2]
        key_b = _software_prompt_parts(dict(self.ITEM), self.SOURCE, vocab_b, "m", CTX, memo_b)[2]
        self.assertNotEqual(key_a, key_b)                   # 词表变 → key 变（不因 memo 失真）

    def test_without_memo_still_correct(self) -> None:
        parts_plain = _software_prompt_parts(dict(self.ITEM), self.SOURCE, self.VOCAB, "m", CTX)
        memo: dict = {}
        parts_memo = _software_prompt_parts(dict(self.ITEM), self.SOURCE, self.VOCAB, "m", CTX, memo)
        self.assertEqual(parts_plain[2], parts_memo[2])     # memo 不改变任何输出


if __name__ == "__main__":
    unittest.main()
