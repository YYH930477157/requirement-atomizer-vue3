"""审计 H8：append_llm_review_cache 共享状态纪律——锁内追加 + fsync + PermissionError 重试
（模式对齐 decide_trace._append_with_retry；此前锁外裸追加，并发批可能丢行/撕裂）。
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_pipeline import append_llm_review_cache


class AppendLlmReviewCacheTests(unittest.TestCase):
    def test_concurrent_appends_lose_no_rows(self) -> None:
        """两线程并发追加同一缓存文件：100 行全量保留、逐行可解析（无丢行/撕裂）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_review_cache.jsonl"

            def worker(tag: str) -> None:
                rows = [{"stable_req_id": f"{tag}-{i}", "review": {}} for i in range(50)]
                append_llm_review_cache(path, rows)

            threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 100)
        ids = {json.loads(line)["stable_req_id"] for line in lines}   # 撕裂行会让 json.loads 抛错
        self.assertEqual(len(ids), 100)

    def test_permission_error_retried_then_succeeds(self) -> None:
        """Windows 读者短暂占用 → PermissionError 重试后成功（对齐 decide_trace 模式）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_review_cache.jsonl"
            real_open = Path.open
            state = {"failed": 0}

            def flaky_open(self_path: Path, *args: object, **kwargs: object):
                if self_path == path and state["failed"] == 0:
                    state["failed"] += 1
                    raise PermissionError("simulated transient reader lock")
                return real_open(self_path, *args, **kwargs)

            with patch.object(Path, "open", flaky_open):
                count = append_llm_review_cache(path, [{"stable_req_id": "x", "review": {}}])
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(count, 1)
        self.assertEqual(state["failed"], 1)   # 确实走过一次重试
        self.assertEqual(json.loads(lines[0])["stable_req_id"], "x")

    def test_empty_rows_write_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_review_cache.jsonl"
            self.assertEqual(append_llm_review_cache(path, []), 0)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
