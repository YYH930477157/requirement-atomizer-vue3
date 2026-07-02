"""API server 安全回归。

锁定 token 校验用常量时间比较（防时序侧信道），并保留：无配置 token 时放行、
token 不匹配时拒绝。可独立运行，无网络/LLM 依赖。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import api_server
import ai_review_actions


class TokenIsValidTests(unittest.TestCase):
    def test_no_expected_token_allows_through(self) -> None:
        # 未配置 token（本地无鉴权场景）→ 任意请求放行
        self.assertTrue(api_server.token_is_valid("", {api_server.TOKEN_HEADER: "x"}, {}))
        self.assertTrue(api_server.token_is_valid("", {}, {}))

    def test_matching_header_token_accepted(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: token}
        self.assertTrue(api_server.token_is_valid(token, headers, {}))

    def test_mismatching_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: "wrong"}
        self.assertFalse(api_server.token_is_valid(token, headers, {}))

    def test_missing_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        self.assertFalse(api_server.token_is_valid(token, {}, {}))

    def test_comparison_uses_constant_time_function(self) -> None:
        """S1 回归：token 须走 hmac.compare_digest，而非字符串 == 短路。

        解析源码确认比较路径常量时间：compare_digest 的核心约束是『两串等长才比较内容、
        否则恒为 False 但耗时与内容无关』；等长内容相同须接受、不同须拒绝。
        """
        import inspect
        src = inspect.getsource(api_server.token_is_valid)
        self.assertIn("compare_digest", src)  # 实现里含常量时间比较
        self.assertNotIn("== expected_token", src)  # 不再裸用 == 比较整串

    def test_equal_length_but_different_token_rejected(self) -> None:
        # compare_digest 对等长但内容不同的串恒 False（也是 == 短路会误判的场景）
        token = "aaaaaaaaaaaaaaaa"
        headers = {api_server.TOKEN_HEADER: "aaaaaaaaaaaaaaab"}  # 同长度末字节不同
        self.assertFalse(api_server.token_is_valid(token, headers, {}))


class AiReviewActionsTests(unittest.TestCase):
    def _req(self) -> dict:
        return {"source_section": "3.1.7", "source_quote": "meter shall measure",
                "title": "计量器具定义", "module": "计量"}

    def test_ai_req_id_stable_and_content_based(self) -> None:
        a = ai_review_actions.ai_req_id(self._req())
        b = ai_review_actions.ai_req_id(dict(self._req()))  # 同内容 → 同 ID
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("AIR-"))
        other = ai_review_actions.ai_req_id({**self._req(), "source_quote": "different"})
        self.assertNotEqual(a, other)  # 内容变 → ID 变

    def test_apply_and_read_latest_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rid = ai_review_actions.ai_req_id(self._req())
            ai_review_actions.apply_ai_review_action(out, rid, "needs_discussion", reason="待议")
            ai_review_actions.apply_ai_review_action(out, rid, "accepted",
                                                     module_override="计量精度", reason="改归精度")
            states = ai_review_actions.read_ai_review_states(out)
            self.assertEqual(states[rid]["status"], "accepted")            # 最近覆盖
            self.assertEqual(states[rid]["module_override"], "计量精度")

    def test_invalid_status_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ai_review_actions.apply_ai_review_action(Path(tmp), "AIR-x", "bogus")


class AiRequirementsEndpointTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        (out / "blocks.jsonl").write_text(
            json.dumps({"block_id": "BLK-2", "order": 2, "text": "B", "section_path": ["4"],
                        "page_number": 1, "type": "paragraph", "kb_matches": [1, 2, 3]}) + "\n" +
            json.dumps({"block_id": "BLK-1", "order": 1, "text": "A", "section_path": ["3"],
                        "page_number": 1, "type": "heading", "kb_matches": []}) + "\n",
            encoding="utf-8")
        doc = {"requirements": [
            {"id": "REQ-001", "title": "T1", "description": "d1", "module": "计量",
             "source_section": "4", "source_quote": "q1", "source_block_ids": ["BLK-2"],
             "acceptance_criteria": ["c1"], "labels": ["计量"]},
        ]}
        (out / "merged_spec_requirements.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_document_blocks_sorted_and_trimmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            result = api_server.build_document_blocks(out)
            self.assertEqual(result["count"], 2)
            self.assertEqual([b["block_id"] for b in result["blocks"]], ["BLK-1", "BLK-2"])  # 按 order
            self.assertNotIn("kb_matches", result["blocks"][0])  # 重负载字段被裁掉

    def test_anchor_block_id_precise_to_quote_paragraph(self) -> None:
        text_by_block = {
            "BLK-1": "Some intro paragraph without the requirement.",
            "BLK-2": "The meter shall measure volume accurately.",
            "BLK-3": "Other unrelated text.",
        }
        # 精确落到引用句所在的那一小段
        req = {"source_quote": "the meter shall measure volume",
               "source_block_ids": ["BLK-1", "BLK-2", "BLK-3"]}
        self.assertEqual(api_server.anchor_block_id(req, text_by_block), "BLK-2")
        # 引用跨到下一块（尾部超出本段）→ 前缀兜底仍落本段
        req2 = {"source_quote": "The meter shall measure volume accurately and store 12 months",
                "source_block_ids": ["BLK-1", "BLK-2"]}
        self.assertEqual(api_server.anchor_block_id(req2, text_by_block), "BLK-2")
        # 无匹配 → 回退 source_block_ids 首块
        req3 = {"source_quote": "totally nonexistent", "source_block_ids": ["BLK-3", "BLK-1"]}
        self.assertEqual(api_server.anchor_block_id(req3, text_by_block), "BLK-3")
        # 无 quote/无 span → 空
        self.assertEqual(api_server.anchor_block_id({}, text_by_block), "")

    def test_view_prefers_raw_ai_requirements_over_merged(self) -> None:
        """merged 会剔除 rejected（裁决回流交付物），批注视图须读原始文件——被拒条目仍可见、可反悔。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)  # merged 里 1 条
            raw = [
                {"title": "T1", "description": "d1", "module": "计量", "source_section": "4",
                 "source_quote": "q1", "source_block_ids": ["BLK-2"], "labels": ["计量"]},
                {"title": "T2", "description": "d2", "module": "显示", "source_section": "5",
                 "source_quote": "q2", "source_block_ids": ["BLK-1"], "labels": ["显示"]},
            ]
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                for r in raw:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 2)  # 读 raw（2 条），而非 merged（1 条）

    def test_ai_requirements_carry_id_anchor_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 1)
            rid = rows[0]["ai_req_id"]
            self.assertTrue(rid.startswith("AIR-"))
            self.assertEqual(rows[0]["source_block_ids"], ["BLK-2"])      # 锚点保留
            self.assertEqual(rows[0]["module_effective"], "计量")
            self.assertEqual(rows[0]["status"], "draft")                  # 未裁决
            # 裁决（改模块）后再读，module_effective 走 override
            ai_review_actions.apply_ai_review_action(out, rid, "accepted", module_override="计量精度")
            rows2 = api_server.build_ai_requirements(out)
            self.assertEqual(rows2[0]["status"], "accepted")
            self.assertEqual(rows2[0]["module_effective"], "计量精度")


if __name__ == "__main__":
    unittest.main()
