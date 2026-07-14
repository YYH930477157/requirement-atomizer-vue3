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


class CacheKeyNarrowingTests(unittest.TestCase):
    """S3：软背景（doc_context/siblings/exemplars）进 prompt 不进 key——背景漂移不再
    整库报废缓存(test18 事故);有据基底(条款原文/答复/模板参考/词表/归属)仍严格折 key。"""

    SOURCE = {"ai_req_id": "AI-1", "module": "计量",
              "description": "The meter shall store data.",
              "source_quote": "The meter shall store data."}
    ITEM = {"analysis_id": "SRA-001", "ownership": "software",
            "ownership_reason": "rule", "ownership_source": "rule"}
    VOCAB = {"modules": ["计量"], "submodules_by_module": {"计量": []}}

    def _key(self, **ctx_overrides) -> str:
        from requirements_analysis import _software_prompt_parts
        ctx = {"template_refs": "", "exemplars": "", "answers": "",
               "doc_context": "", "section_context": "", "siblings": ""}
        ctx.update(ctx_overrides)
        return _software_prompt_parts(dict(self.ITEM), self.SOURCE, self.VOCAB, "m", ctx)[2]

    def test_soft_background_changes_keep_key(self) -> None:
        base = self._key()
        self.assertEqual(base, self._key(doc_context="【文档背景】术语表变了"))
        self.assertEqual(base, self._key(siblings="- 新增了一条相邻需求标题"))
        self.assertEqual(base, self._key(exemplars="- 【计量】新范例"))

    def test_grounding_basis_changes_invalidate_key(self) -> None:
        base = self._key()
        self.assertNotEqual(base, self._key(section_context="4.3 new clause text"))
        self.assertNotEqual(base, self._key(answers="问：上限？答：500"))
        self.assertNotEqual(base, self._key(template_refs="【模板行】新参考"))

    def test_ownership_still_invalidates_key(self) -> None:
        from requirements_analysis import _software_prompt_parts
        ctx = {"template_refs": "", "exemplars": "", "answers": "",
               "doc_context": "", "section_context": "", "siblings": ""}
        k_sw = _software_prompt_parts(dict(self.ITEM), self.SOURCE, self.VOCAB, "m", ctx)[2]
        k_cd = _software_prompt_parts(dict(self.ITEM, ownership="co_design"),
                                      self.SOURCE, self.VOCAB, "m", ctx)[2]
        self.assertNotEqual(k_sw, k_cd)

    def test_doc_context_drift_reuses_cache_without_new_call(self) -> None:
        from requirements_analysis import _llm_enrich_item
        calls: list[str] = []
        cache: dict = {}

        def chat(system: str, user: str) -> dict:
            calls.append(user)
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。"}]}

        ctx1 = {"doc_context": "【文档背景】版本甲", "siblings": "- 甲"}
        ctx2 = {"doc_context": "【文档背景】版本乙", "siblings": "- 乙"}
        _llm_enrich_item(dict(self.ITEM), self.SOURCE, self.VOCAB, chat, cache, "m", context=ctx1)
        ok, _ = _llm_enrich_item(dict(self.ITEM), self.SOURCE, self.VOCAB, chat, cache, "m", context=ctx2)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)          # 背景漂移 → 命中缓存,零新调用


if __name__ == "__main__":
    unittest.main()
