"""批次三（0714 整体 review 落地,续批次一/二）回归：

- E6 裁决回灌抽取：样本库 few-shot 注入抽取 prompt;软背景不进指纹;护栏不放宽。
（E7 prompt v16 的锁在 test_ai_extract.PromptV5Tests;S7 余项/内容锁在各自实现后追加。）
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_extract


class ExtractExemplarRenderTests(unittest.TestCase):
    def _bank(self) -> dict:
        accepted = {}
        for i in range(6):
            accepted[f"AIR-{i:03d}"] = {"module": "时钟" if i % 2 else "预付费",
                                        "title": f"范例标题{i}"}
        return {"accepted": accepted}

    def test_module_diversity_and_cap(self) -> None:
        text = ai_extract.render_extract_exemplars(self._bank())
        lines = text.splitlines()
        self.assertLessEqual(len(lines), ai_extract.EXTRACT_EXEMPLARS_MAX)
        self.assertEqual(sum(1 for l in lines if l.startswith("-【时钟】")), 2)   # 每模块 ≤2
        self.assertEqual(sum(1 for l in lines if l.startswith("-【预付费】")), 2)

    def test_deterministic_order(self) -> None:
        a = ai_extract.render_extract_exemplars(self._bank())
        b = ai_extract.render_extract_exemplars(self._bank())
        self.assertEqual(a, b)

    def test_empty_bank_renders_nothing(self) -> None:
        self.assertEqual(ai_extract.render_extract_exemplars({}), "")
        self.assertEqual(ai_extract.render_extract_exemplars({"accepted": {}}), "")


class ExtractExemplarInjectionTests(unittest.TestCase):
    SECTION = {"section_id": "S1", "heading": "4.6 AFD2",
               "text": "The AFD shall close the valve.", "block_ids": []}

    def _chat_capture(self, captured: list) -> object:
        def chat(system: str, user: str) -> dict:
            captured.append(user)
            return {"requirements": []}
        return chat

    def test_exemplars_injected_with_no_copy_instruction(self) -> None:
        captured: list[str] = []
        ai_extract.extract_section(self.SECTION, self._chat_capture(captured),
                                   doc_context="【文档背景】燃气表",
                                   exemplars="-【预付费】购电余额扣减")
        user = captured[0]
        self.assertIn("专家已验收范例", user)
        self.assertIn("-【预付费】购电余额扣减", user)
        self.assertIn("不得搬运", user)
        self.assertLess(user.index("【文档背景】"), user.index("专家已验收范例"))
        self.assertLess(user.index("专家已验收范例"), user.index("当前章节"))

    def test_no_exemplars_prompt_unchanged(self) -> None:
        with_ex: list[str] = []
        without: list[str] = []
        ai_extract.extract_section(self.SECTION, self._chat_capture(without),
                                   doc_context="【文档背景】燃气表")
        ai_extract.extract_section(self.SECTION, self._chat_capture(with_ex),
                                   doc_context="【文档背景】燃气表", exemplars="")
        self.assertEqual(without[0], with_ex[0])      # 空注入=旧 prompt 逐字节一致

    def test_exemplars_do_not_touch_section_fingerprint(self) -> None:
        # 软背景不进指纹（S3 同理）：样本库更新不报废抽取缓存
        fp = ai_extract.section_fingerprint(self.SECTION, "m", "ctx")
        self.assertEqual(fp, ai_extract.section_fingerprint(self.SECTION, "m", "ctx"))
        import inspect
        src = inspect.getsource(ai_extract.section_fingerprint)
        self.assertNotIn("exemplar", src)

    def test_exemplar_code_borrowing_still_hard_blocked(self) -> None:
        """范例里的 OBIS 被搬进抽取产物 → 漂移基线（章节原文）照常拦截。"""
        captured: list[str] = []

        def chat(system: str, user: str) -> dict:
            captured.append(user)
            return {"requirements": [{
                "title": "阀门关闭", "description": "写入对象 0-0:96.3.10.255 关闭阀门。",
                "source_quote": "The AFD shall close the valve.",
                "type": "functional", "priority": "P1", "module": "阀门控制", "labels": ["阀门"],
            }]}

        results = ai_extract.extract_section(
            self.SECTION, chat,
            exemplars="-【阀门控制】阀门对象 0-0:96.3.10.255 关闭控制")
        self.assertEqual(len(results), 1)
        notes = str(results[0].get("notes") or "")
        self.assertIn("结构漂移已拦截", notes)          # 编码硬拦,不因范例注入而放行


class ApiPayloadMemoTests(unittest.TestCase):
    """S7b：GUI 装配路径按源文件签名 memo——刷新不再全量重读重 join;写入自然失效。"""

    def setUp(self) -> None:
        import api_server
        api_server._reset_payload_memo()

    tearDown = setUp

    def _seed(self, out: Path) -> None:
        (out / "blocks.jsonl").write_text(json.dumps({
            "block_id": "B1", "order": 1, "text": "The meter shall log events.",
            "requirement_like": True, "noise": False, "type": "paragraph",
            "doc_region": "body", "section_path": ["4"]}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        (out / "ai_requirements.jsonl").write_text(json.dumps({
            "ai_req_id": "AIR-1", "title": "事件记录", "module": "事件记录",
            "source_quote": "The meter shall log events.", "source_block_ids": ["B1"]},
            ensure_ascii=False) + "\n", encoding="utf-8")

    def test_repeat_calls_hit_memo(self) -> None:
        from unittest.mock import patch

        import api_server
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            with patch.object(api_server, "_build_ai_requirements_impl",
                              wraps=api_server._build_ai_requirements_impl) as impl:
                first = api_server.build_ai_requirements(out)
                second = api_server.build_ai_requirements(out)
            self.assertEqual(impl.call_count, 1)          # 第二次命中 memo
            self.assertEqual(first, second)

    def test_source_write_invalidates(self) -> None:
        from unittest.mock import patch

        import api_server
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            with patch.object(api_server, "_build_ai_requirements_impl",
                              wraps=api_server._build_ai_requirements_impl) as impl:
                api_server.build_ai_requirements(out)
                with (out / "ai_review_states.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ai_req_id": "AIR-1", "status": "accepted"}) + "\n")
                rows = api_server.build_ai_requirements(out)
            self.assertEqual(impl.call_count, 2)          # 裁决写入 → 签名变化 → 重算
            self.assertEqual(rows[0]["status"], "accepted")

    def test_returned_payload_mutation_isolated(self) -> None:
        import api_server
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            first = api_server.build_document_blocks(out)
            first["blocks"][0]["text"] = "被消费方原地改了"
            second = api_server.build_document_blocks(out)
            self.assertEqual(second["blocks"][0]["text"], "The meter shall log events.")


if __name__ == "__main__":
    unittest.main()
