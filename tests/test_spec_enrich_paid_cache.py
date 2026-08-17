from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from paid_cache_store import PAID_CACHE_STORE_VERSION, PaidCacheStore
from spec_enrich import append_cache, read_cache

LEGACY_ROW = {
    "fingerprint": "fp-legacy", "model": "deepseek-chat",
    "prompt_version": "enrich-v3", "guards_version": "enrich-guards-v4",
    "description": "旧顶层行缓存", "enriched": True, "note": "富化（结构字段未变）",
    "blue_book_origin": "",
}


class SpecEnrichPaidCacheMigrationTests(unittest.TestCase):
    def test_legacy_rows_still_hit_after_migration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spec_enrich_cache.jsonl"
            path.write_text(json.dumps(LEGACY_ROW, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            cache = read_cache(path)
            self.assertIn("fp-legacy", cache)
            self.assertEqual(cache["fp-legacy"]["description"], "旧顶层行缓存")

    def test_new_rows_roundtrip_and_mixed_file_reads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spec_enrich_cache.jsonl"
            path.write_text(json.dumps(LEGACY_ROW, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            append_cache(path, [{
                "fingerprint": "fp-new", "model": "deepseek-v4-flash",
                "prompt_version": "enrich-v3", "guards_version": "enrich-guards-v4",
                "description": "新行经 PaidCacheStore", "enriched": True,
                "note": "富化（结构字段未变）", "blue_book_origin": "",
            }])
            cache = read_cache(path)
            # 双形态同文件可读；新行解包成旧形态，命中语义不变
            self.assertEqual(cache["fp-legacy"]["description"], "旧顶层行缓存")
            self.assertEqual(cache["fp-new"]["description"], "新行经 PaidCacheStore")
            self.assertEqual(cache["fp-new"]["model"], "deepseek-v4-flash")
            # 文件行是 paid-cache-store 形态（success 嵌套 payload）
            rows = [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines() if line.strip()]
            new_row = next(r for r in rows if r.get("fingerprint") == "fp-new")
            self.assertEqual(new_row["schema"], PAID_CACHE_STORE_VERSION)
            self.assertTrue(new_row["success"])
            self.assertEqual(new_row["payload"]["description"], "新行经 PaidCacheStore")

    def test_same_fingerprint_last_wins_no_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spec_enrich_cache.jsonl"
            append_cache(path, [{"fingerprint": "fp", "description": "v1",
                                  "enriched": True, "note": "", "model": "m"}])
            append_cache(path, [{"fingerprint": "fp", "description": "v2",
                                  "enriched": True, "note": "", "model": "m"}])
            cache = read_cache(path)
            self.assertEqual(cache["fp"]["description"], "v2")
            rows = [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)

    def test_torn_tail_still_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spec_enrich_cache.jsonl"
            append_cache(path, [{"fingerprint": "fp", "description": "ok",
                                  "enriched": True, "note": "", "model": "m"}])
            with open(path, "a", encoding="utf-8") as handle:
                handle.write('{"fingerprint": "fp2", "succ')
            cache = read_cache(path)
            self.assertIn("fp", cache)
            self.assertNotIn("fp2", cache)

    def test_empty_append_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spec_enrich_cache.jsonl"
            append_cache(path, [])
            self.assertFalse(path.exists())


class PaidCacheStorePrimitiveTests(unittest.TestCase):
    def test_record_many_single_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = PaidCacheStore(Path(td), "pc.jsonl")
            store.record_many([
                ("fp-1", {"v": 1}, None),
                ("fp-2", {"v": 2}, {"model": "m"}),
            ])
            self.assertIsNotNone(store.lookup("fp-1"))
            self.assertIsNotNone(store.lookup("fp-2"))
            self.assertEqual(store.telemetry.writes, 2)
            rows = [json.loads(line) for line in
                    (Path(td) / "pc.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            self.assertEqual(len(rows), 2)

    def test_from_file_writes_exact_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            resolved = Path(td) / "nested" / "spec_enrich_cache.jsonl"
            store = PaidCacheStore.from_file(resolved)
            store.record("fp", {"description": "x"})
            self.assertTrue(resolved.is_file())
            self.assertIsNotNone(store.lookup("fp"))
            # 重复写同指纹仍 last-wins（from_file 路径同样去重）
            store.record("fp", {"description": "y"})
            self.assertEqual(store.lookup("fp")["payload"]["description"], "y")


if __name__ == "__main__":
    unittest.main()
