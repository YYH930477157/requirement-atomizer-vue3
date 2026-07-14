"""批次二（0714 整体 review 落地,续批次一）回归：

- S4 裁决重建防抖：连续裁决合并为一次 rebuild;delay<=0 退化同步;失败不丢裁决。
（S3 缓存 key 收窄 / S6 prompt 前缀重排 / E4 guidance 编码收紧 等在各自实现后追加于此。）
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DeliverableRebuilderTests(unittest.TestCase):
    def test_burst_schedules_coalesce_to_one_rebuild(self) -> None:
        from api_server import DeliverableRebuilder
        calls: list[Path] = []
        rb = DeliverableRebuilder(delay_s=0.08)
        with patch.object(DeliverableRebuilder, "_rebuild", side_effect=calls.append):
            for _ in range(5):                      # 连续 5 次裁决
                rb.schedule(Path("X"))
            time.sleep(0.3)
        self.assertEqual(len(calls), 1)             # 合并为一次重建
        self.assertEqual(calls[0], Path("X"))

    def test_zero_delay_rebuilds_synchronously(self) -> None:
        from api_server import DeliverableRebuilder
        calls: list[Path] = []
        rb = DeliverableRebuilder(delay_s=0)
        with patch.object(DeliverableRebuilder, "_rebuild", side_effect=calls.append):
            rb.schedule(Path("A"))
            rb.schedule(Path("A"))
        self.assertEqual(len(calls), 2)             # 旧同步语义

    def test_flush_forces_pending_rebuild(self) -> None:
        from api_server import DeliverableRebuilder
        calls: list[Path] = []
        rb = DeliverableRebuilder(delay_s=60)       # 长延迟,不 flush 就不会跑
        with patch.object(DeliverableRebuilder, "_rebuild", side_effect=calls.append):
            rb.schedule(Path("B"))
            rb.flush()
        self.assertEqual(calls, [Path("B")])

    def test_flush_without_pending_is_noop(self) -> None:
        from api_server import DeliverableRebuilder
        calls: list[Path] = []
        rb = DeliverableRebuilder(delay_s=60)
        with patch.object(DeliverableRebuilder, "_rebuild", side_effect=calls.append):
            rb.flush()
        self.assertEqual(calls, [])

    def test_rebuild_failure_swallowed(self) -> None:
        from api_server import DeliverableRebuilder
        rb = DeliverableRebuilder(delay_s=0)
        with patch("ai_extract.rebuild_merged_spec", side_effect=RuntimeError("boom")):
            rb.schedule(Path(tempfile.gettempdir()))   # 不抛出（裁决不因重建失败而失败）

    def test_handler_uses_debounced_rebuilder(self) -> None:
        """源锁：POST 处理器走 _rebuilder().schedule,不再内联同步 rebuild_merged_spec。"""
        import inspect

        import api_server
        src = inspect.getsource(api_server.RequirementAPIHandler.handle_ai_review_action)
        self.assertIn("_rebuilder().schedule", src)
        self.assertNotIn("rebuild_merged_spec(self.output_dir)", src)


if __name__ == "__main__":
    unittest.main()
