from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from paid_cache_store import PAID_CACHE_STORE_VERSION, PaidCacheStore


class PaidCacheStoreTests(unittest.TestCase):
    def _store(self, out_dir: Path) -> PaidCacheStore:
        return PaidCacheStore(out_dir, "paid_cache_test.jsonl")

    def test_record_then_lookup_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            store = self._store(out_dir)
            store.record("fp-1", {"items": [1, 2]}, meta={"model": "deepseek-v4-flash"})
            hit = store.lookup("fp-1")
            self.assertIsNotNone(hit)
            self.assertEqual(hit["payload"], {"items": [1, 2]})
            self.assertEqual(hit["schema"], PAID_CACHE_STORE_VERSION)
            self.assertIsNone(store.lookup("fp-2"))
            snapshot = store.telemetry.snapshot()
            self.assertEqual(snapshot["hits"], 1)
            self.assertEqual(snapshot["misses"], 1)
            self.assertEqual(snapshot["writes"], 1)

    def test_failure_is_never_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            store = self._store(out_dir)
            store.record_failure("fp-fail", "truncation")
            self.assertIsNone(store.lookup("fp-fail"))
            self.assertEqual(store.telemetry.dropped_not_successful, 1)
            # 失败指纹不落盘
            path = out_dir / "paid_cache_test.jsonl"
            self.assertFalse(path.is_file())

    def test_record_replaces_same_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            store = self._store(out_dir)
            store.record("fp-1", {"v": 1})
            store.record("fp-1", {"v": 2})
            hit = store.lookup("fp-1")
            self.assertEqual(hit["payload"], {"v": 2})
            rows = [json.loads(line) for line in
                    (out_dir / "paid_cache_test.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            self.assertEqual(len(rows), 1)

    def test_torn_tail_recovered_and_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            store = self._store(out_dir)
            store.record("fp-1", {"ok": True})
            path = out_dir / "paid_cache_test.jsonl"
            # 模拟崩溃撕裂尾行（半行 JSON）
            with open(path, "a", encoding="utf-8") as handle:
                handle.write('{"fingerprint": "fp-2", "success": tru')
            hit = store.lookup("fp-1")
            self.assertIsNotNone(hit)               # 撕裂行不阻断读取
            self.assertIsNone(store.lookup("fp-2"))
            self.assertGreaterEqual(store.telemetry.recovered_torn_tail_lines, 1)
            # 修好的文件不再含撕裂行
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)

    def test_empty_fingerprint_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            with self.assertRaises(ValueError):
                store.record("", {"x": 1})
            with self.assertRaises(ValueError):
                store.lookup("")

    def test_new_store_instance_reads_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self._store(out_dir).record("fp-1", {"a": 1})
            reloaded = self._store(out_dir)
            hit = reloaded.lookup("fp-1")
            self.assertEqual(hit["payload"], {"a": 1})


if __name__ == "__main__":
    unittest.main()
