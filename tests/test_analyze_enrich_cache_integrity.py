"""富化缓存完整性回归（2026-08-14 四缺陷修复）：

- DEFECT 1（世代翻转）：旧 _save_enrich_cache 只在文件缺失/空时写 meta 行——模型/prompt
  切换后新行追加在旧 meta 之后，而读侧见 meta 不匹配整份弃用 → 缓存永久变砖（写进去
  永远读不出）。现写入侧锁内三态：缺失/空→建文件；meta 一致→撕裂尾行修复后追加；
  不一致→原子整替新 meta+新行（旧世代弃用，与读侧 mismatch 弃用同语义）。
- DEFECT 2（跨进程锁）：旧实现裸 path.open("a")——并发进程可交叉追加或写双 meta 行，
  读侧命中中段损坏即整份弃用。现世代初始化/撕裂尾行截断/追加全在 process_file_lock
  锁内，追加/替换带 8 次线性退避 PermissionError 重试（repo 标准）。
- DEFECT 3（键碰撞）：_software_prompt_parts 五段上下文 "".join——("ab","c") 与
  ("a","bc") 同键，一条需求的富化结果可被错用到另一上下文。改 canonical JSON 数组编码；
  ENRICH_CACHE_FORMAT_VERSION v2→v3（键方案变更，旧中间文件不得在新格式号下被读）。
- DEFECT 4（先记后存）：flush_new_cache_rows 在调用 save 前就把键记进 flushed_keys，
  而 save 吞 OSError → 一次瞬态写失败后本 run 已付费结果被当作已落盘永不重试。
  现 save 返回成功 bool，flush 只把真正落盘的键记为已刷，失败键下次 flush 重试。
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requirements_analysis as ra
from io_utils import read_jsonl_recover_torn_tail


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


def _meta_row(model: str) -> dict:
    return {"_meta": True, "format": ra.ENRICH_CACHE_FORMAT_VERSION,
            "prompt": ra.ANALYZE_PROMPT_VERSION, "model": model}


class GenerationRolloverTests(unittest.TestCase):
    """DEFECT 1：meta 不一致 → 世代翻转（原子整替新 meta+新行），读侧随即可用。"""

    def test_model_switch_rolls_generation_and_loader_reads_new_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = out / ra.ANALYZE_ENRICH_CACHE
            _write_jsonl(path, [
                {"_meta": True, "format": ra.ENRICH_CACHE_FORMAT_VERSION,
                 "prompt": ra.ANALYZE_PROMPT_VERSION, "model": "old-model"},
                {"key": "k-old", "item": {"software_requirement_text": "旧模型产物"}},
            ])

            ok = ra._save_enrich_cache(out, "new-model",
                                       [("k-new", {"software_requirement_text": "新模型产物"})])

            self.assertTrue(ok)
            rows = read_jsonl_recover_torn_tail(path)
            metas = [r for r in rows if r.get("_meta")]
            self.assertEqual(len(metas), 1)                       # 单 meta 行
            self.assertEqual(metas[0], _meta_row("new-model"))    # 已翻转为新模型
            self.assertEqual([r.get("key") for r in rows if not r.get("_meta")],
                             ["k-new"])                           # 旧世代行弃用
            # 读侧立即看到新记录（旧实现：写了但永远读不出）
            self.assertEqual(ra._load_enrich_cache(out, "new-model"),
                             {"k-new": {"software_requirement_text": "新模型产物"}})
            self.assertEqual(ra._load_enrich_cache(out, "old-model"), {})

    def test_prompt_drift_rolls_generation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = out / ra.ANALYZE_ENRICH_CACHE
            _write_jsonl(path, [_meta_row("m"),
                                {"key": "k1", "item": {"v": 1}}])
            with patch.object(ra, "ANALYZE_PROMPT_VERSION", "analyze-llm-vNEXT"):
                ok = ra._save_enrich_cache(out, "m", [("k2", {"v": 2})])
                self.assertTrue(ok)
                loaded_next = ra._load_enrich_cache(out, "m")
            rows = read_jsonl_recover_torn_tail(path)
            self.assertEqual([r.get("key") for r in rows if not r.get("_meta")], ["k2"])
            self.assertEqual(loaded_next, {"k2": {"v": 2}})   # 新 prompt 世代可读

    def test_interim_v2_format_file_rolls_over_under_v3(self) -> None:
        """v3 键方案下，v2 中间文件（format=analyze-enrich-cache-v2）必须翻转、不得续读。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = out / ra.ANALYZE_ENRICH_CACHE
            _write_jsonl(path, [
                {"_meta": True, "format": "analyze-enrich-cache-v2",
                 "prompt": ra.ANALYZE_PROMPT_VERSION, "model": "injected"},
                {"key": "k-v2", "item": {"v": "v2-shape"}},
            ])
            self.assertEqual(ra._load_enrich_cache(out, "injected"), {})
            self.assertTrue(ra._save_enrich_cache(out, "injected", [("k-v3", {"v": 3})]))
            self.assertEqual(ra._load_enrich_cache(out, "injected"), {"k-v3": {"v": 3}})

    def test_model_switch_end_to_end_second_run_hits_new_cache(self) -> None:
        calls = {"n": 0}

        def chat(s, u):
            calls["n"] += 1
            entries = json.loads(u.split("需求 JSON:")[-1].strip())
            return {"items": [{"enrich_slot": slot, "software_requirement_text": "新模型成文。"}
                              for slot in range(len(entries))]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 3)
            path = out / ra.ANALYZE_ENRICH_CACHE
            _write_jsonl(path, [
                {"_meta": True, "format": ra.ENRICH_CACHE_FORMAT_VERSION,
                 "prompt": ra.ANALYZE_PROMPT_VERSION, "model": "old-model"},
                {"key": "k-old", "item": {"software_requirement_text": "旧模型产物"}},
            ])

            ra.run_requirements_analysis(out, route="openai_compatible", chat=chat)

            rows = read_jsonl_recover_torn_tail(path)
            metas = [r for r in rows if r.get("_meta")]
            self.assertEqual(len(metas), 1)
            self.assertEqual(metas[0]["model"], "injected")        # meta 行已被翻转
            self.assertNotIn("k-old", {r.get("key") for r in rows})
            self.assertEqual(calls["n"], 1)                       # 旧世代不可用 → 真实调用

            ra.run_requirements_analysis(out, route="openai_compatible", chat=chat)

        self.assertEqual(calls["n"], 1)                           # 新世代命中 → 零新调用

    def test_shape_untrusted_file_rolls_over(self) -> None:
        """首行不是 meta / 中段坏行：读侧本就整份弃用——写侧按翻转处理，文件恢复健康。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = out / ra.ANALYZE_ENRICH_CACHE
            path.write_text(
                json.dumps({"key": "k1", "item": {"v": 1}}) + "\n"
                + json.dumps({"key": "k2", "item": {"v": 2}}) + "\n",
                encoding="utf-8")
            self.assertEqual(ra._load_enrich_cache(out, "injected"), {})
            self.assertTrue(ra._save_enrich_cache(out, "injected", [("k3", {"v": 3})]))
            rows = read_jsonl_recover_torn_tail(path)
            self.assertEqual(rows[0], _meta_row("injected"))
            self.assertEqual(ra._load_enrich_cache(out, "injected"), {"k3": {"v": 3}})


class ConcurrentWriterTests(unittest.TestCase):
    """DEFECT 2：并发写者（线程 + 真锁文件）→ 单 meta、形状良好、一键不丢。"""

    def test_interleaved_thread_appends_yield_single_meta_wellformed_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            barrier = threading.Barrier(2)
            errors: list[BaseException] = []

            def writer(tag: str) -> None:
                try:
                    barrier.wait(timeout=10)
                    for i in range(15):
                        ok = ra._save_enrich_cache(
                            out, "injected",
                            [(f"{tag}-{i}", {"software_requirement_text": f"{tag}{i}"})])
                        if ok is not True:
                            raise AssertionError(f"save returned {ok!r}")
                except BaseException as exc:   # 线程内异常回传主线程断言
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(tag,)) for tag in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            self.assertEqual(errors, [])
            self.assertTrue(all(not thread.is_alive() for thread in threads))

            path = out / ra.ANALYZE_ENRICH_CACHE
            rows = read_jsonl_recover_torn_tail(path)   # 中段损坏会抛——形状必须良好
            metas = [r for r in rows if r.get("_meta")]
            self.assertEqual(len(metas), 1)             # 恰一个 meta 行（旧实现可写双 meta）
            self.assertTrue(rows[0].get("_meta"))       # 且在首行
            self.assertEqual(len(rows), 1 + 30)         # 一键一行，无交叉粘连/丢失
            loaded = ra._load_enrich_cache(out, "injected")
            self.assertEqual(set(loaded), {f"{tag}-{i}" for tag in ("a", "b") for i in range(15)})


class EnrichKeyContextEncodingTests(unittest.TestCase):
    """DEFECT 3：五段上下文 canonical JSON 数组编码——边界拼接不再碰撞。"""

    VOCAB = {"modules": ["计量"], "submodules_by_module": {"计量": []}}
    SOURCE = {"ai_req_id": "AI-1", "module": "计量",
              "description": "Store data.", "source_quote": "Store data."}

    def _key(self, ctx: dict, *, ownership: str = "software") -> str:
        _slim, _req, key = ra._software_prompt_parts(
            {"analysis_id": "SRA-001", "ownership": ownership},
            self.SOURCE, self.VOCAB, "injected", ctx)
        return key

    def test_adjacent_field_split_no_longer_collides(self) -> None:
        """旧 "".join 下 ("ab","c") 与 ("a","bc") 同键——一条的富化结果可被另一条错用。"""
        key_ab_c = self._key({"template_refs": "ab", "answers": "c", "section_context": ""})
        key_a_bc = self._key({"template_refs": "a", "answers": "bc", "section_context": ""})
        self.assertNotEqual(key_ab_c, key_a_bc)

    def test_answers_section_context_split_no_longer_collides(self) -> None:
        key_ab_c = self._key({"template_refs": "", "answers": "ab", "section_context": "c"})
        key_a_bc = self._key({"template_refs": "", "answers": "a", "section_context": "bc"})
        self.assertNotEqual(key_ab_c, key_a_bc)

    def test_frozen_ownership_change_still_changes_key(self) -> None:
        """冻结归属仍折进 key（0714 语义不回退）：专家改判 → 重富化。"""
        ctx = {"template_refs": "", "answers": "", "section_context": ""}
        self.assertNotEqual(self._key(ctx, ownership="software"),
                            self._key(ctx, ownership="co_design"))

    def test_identical_inputs_keep_the_same_key(self) -> None:
        ctx = {"template_refs": "参考", "answers": "答", "section_context": "条款"}
        self.assertEqual(self._key(dict(ctx)), self._key(dict(ctx)))
        # 空上下文与空上下文仍同键（缓存幂等不受影响）
        self.assertEqual(self._key({"template_refs": "", "answers": "", "section_context": ""}),
                         self._key({}))

    def test_context_change_still_changes_key(self) -> None:
        self.assertNotEqual(
            self._key({"template_refs": "", "answers": "", "section_context": ""}),
            self._key({"template_refs": "新模板参考行", "answers": "", "section_context": ""}))


class SaveFailureRetryTests(unittest.TestCase):
    """DEFECT 4：落盘失败如实返回 False；未落盘键下次 flush 重试；PermissionError 预算内重试。"""

    def _seeded_cache(self, out: Path) -> Path:
        path = out / ra.ANALYZE_ENRICH_CACHE
        _write_jsonl(path, [_meta_row("injected")])
        return path

    def test_save_returns_false_and_warns_when_append_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = self._seeded_cache(out)
            before = path.read_text(encoding="utf-8")
            with patch.object(ra, "_append_enrich_rows_with_retry",
                              side_effect=OSError("disk full")):
                with self.assertLogs("requirement_atomizer", level="WARNING"):
                    ok = ra._save_enrich_cache(out, "injected",
                                               [("k1", {"software_requirement_text": "一"})])
            self.assertFalse(ok)
            self.assertEqual(path.read_text(encoding="utf-8"), before)   # 文件未动

    def test_transient_permissionerror_on_append_retried_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            path = self._seeded_cache(out)
            real_open = Path.open
            attempts = {"n": 0}

            def flaky_open(self, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if mode == "a":
                    attempts["n"] += 1
                    if attempts["n"] == 1:
                        raise PermissionError(13, "transient sharing violation (test)")
                return real_open(self, *args, **kwargs)

            with patch.object(Path, "open", flaky_open):
                ok = ra._save_enrich_cache(out, "injected",
                                           [("k1", {"software_requirement_text": "一"})])
            self.assertTrue(ok)                                   # 预算内重试后成功
            self.assertEqual(attempts["n"], 2)
            self.assertEqual(ra._load_enrich_cache(out, "injected"),
                             {"k1": {"software_requirement_text": "一"}})

    def test_failed_flush_keeps_keys_unflushed_and_next_flush_persists(self) -> None:
        """端到端：前两次落盘失败 → 键保留未刷 → 第三次 flush 把全部三行补齐（零丢失）。"""
        real_save = ra._save_enrich_cache
        calls = {"n": 0}

        def flaky_save(out_dir, model, new_items):
            calls["n"] += 1
            if calls["n"] <= 2:
                return False                                      # 瞬态失败（不落盘）
            return real_save(out_dir, model, new_items)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 3)

            with patch.dict("os.environ", {ra.ANALYZE_BATCH_ENV: "1"}):   # 3 任务 → ≥3 次 flush
                with patch.object(ra, "_save_enrich_cache", side_effect=flaky_save):
                    ra.run_requirements_analysis(
                        out, route="openai_compatible",
                        chat=lambda s, u: {"items": [{"software_requirement_text": "成文。"}]})

            self.assertGreaterEqual(calls["n"], 3)
            rows = read_jsonl_recover_torn_tail(out / ra.ANALYZE_ENRICH_CACHE)
            item_rows = [r for r in rows if not r.get("_meta")]
            # 旧实现：前两键在失败时即被记为已刷 → 只落第三键（1 行）；新实现全部补齐
            self.assertEqual(len(item_rows), 3)
            loaded = ra._load_enrich_cache(out, "injected")
            self.assertEqual(len(loaded), 3)

    def test_final_in_loop_flush_failure_retried_by_post_loop_flush(self) -> None:
        """终局 flush（2026-08-15 P2）：循环内最后一次 flush 失败 → 循环后必须再补一次。
        旧实现只在逐 future 消费循环里 flush——最后一批失败即本 run 已付费键全部丢失,
        下个 run 重付费。单并发 3 任务 = 恰 3 次循环内 flush + 1 次循环后终局 flush,
        第 3 次（最后一次循环内）失败必须被第 4 次兜住（零丢失）。"""
        real_save = ra._save_enrich_cache
        calls = {"n": 0}

        def flaky_save(out_dir, model, new_items):
            calls["n"] += 1
            if calls["n"] == 3:                              # 最后一次循环内 flush 瞬态失败
                return False
            return real_save(out_dir, model, new_items)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _seed(out, 3)

            with patch.dict("os.environ", {ra.ANALYZE_BATCH_ENV: "1"}):
                with patch.object(ra, "_save_enrich_cache", side_effect=flaky_save):
                    ra.run_requirements_analysis(
                        out, route="openai_compatible", concurrency=1,
                        chat=lambda s, u: {"items": [{"software_requirement_text": "成文。"}]})

            self.assertEqual(calls["n"], 4)                  # 3 次循环内 + 1 次循环后终局
            rows = read_jsonl_recover_torn_tail(out / ra.ANALYZE_ENRICH_CACHE)
            item_rows = [r for r in rows if not r.get("_meta")]
            self.assertEqual(len(item_rows), 3)              # 旧实现：第 3 键丢失只剩 2 行
            self.assertEqual(len(ra._load_enrich_cache(out, "injected")), 3)


if __name__ == "__main__":
    unittest.main()
