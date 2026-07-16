"""批次二（0714 整体 review 落地,续批次一）回归：

- S4 裁决重建防抖：连续裁决合并为一次 rebuild;delay<=0 退化同步;失败不丢裁决。
（S3 缓存 key 收窄 / S6 prompt 前缀重排 / E4 guidance 编码收紧 等在各自实现后追加于此。）
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
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

    def test_overlapping_rebuilds_are_serialized(self) -> None:
        from api_server import DeliverableRebuilder
        entered_first = threading.Event()
        entered_second = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        state_lock = threading.Lock()
        active = 0
        max_active = 0
        calls = 0

        def rebuild(_out: Path) -> None:
            nonlocal active, max_active, calls
            with state_lock:
                calls += 1
                call_no = calls
                active += 1
                max_active = max(max_active, active)
            if call_no == 1:
                entered_first.set()
                release_first.wait(timeout=2)
            else:
                entered_second.set()
            with state_lock:
                active -= 1

        rb = DeliverableRebuilder(delay_s=0)
        with patch("ai_extract.rebuild_merged_spec", side_effect=rebuild):
            first = threading.Thread(target=rb.schedule, args=(Path("A"),), daemon=True)
            first.start()
            self.assertTrue(entered_first.wait(timeout=1))

            def start_second() -> None:
                second_started.set()
                rb.schedule(Path("B"))

            second = threading.Thread(target=start_second, daemon=True)
            second.start()
            self.assertTrue(second_started.wait(timeout=1))
            self.assertFalse(entered_second.wait(timeout=0.1))
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)

        self.assertTrue(entered_second.is_set())
        self.assertEqual(max_active, 1)


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


class JsonModeDefaultTests(unittest.TestCase):
    """S6a：JSON 模式默认开 + 端点不支持记忆（不支持的端点只白发一次,不再逐次翻倍）。"""

    def setUp(self) -> None:
        import llm_client
        llm_client._reset_json_mode_memory()

    tearDown = setUp

    def test_default_on_sends_response_format(self) -> None:
        import os
        from tests.test_llm_client import MockOpenAIService, openai_response

        from llm_client import LLMClientConfig, chat_json
        with MockOpenAIService([{"body": openai_response({"ok": True})}]) as service:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RATOMIZER_LLM_JSON_SCHEMA", None)
                chat_json(LLMClientConfig(base_url=service.base_url, model="m", api_key_env="",
                                          timeout_s=2, max_retries=0), "s", "u")
        self.assertEqual(service.requests[0].get("response_format"), {"type": "json_object"})

    def test_env_zero_disables(self) -> None:
        import os
        from tests.test_llm_client import MockOpenAIService, openai_response

        from llm_client import LLMClientConfig, chat_json
        with MockOpenAIService([{"body": openai_response({"ok": True})}]) as service:
            with patch.dict(os.environ, {"RATOMIZER_LLM_JSON_SCHEMA": "0"}):
                chat_json(LLMClientConfig(base_url=service.base_url, model="m", api_key_env="",
                                          timeout_s=2, max_retries=0), "s", "u")
        self.assertNotIn("response_format", service.requests[0])

    def test_unsupported_endpoint_remembered(self) -> None:
        import os
        from tests.test_llm_client import MockOpenAIService, openai_response

        from llm_client import LLMClientConfig, chat_json
        with MockOpenAIService([
            {"status": 400, "body": {"error": "response_format unsupported"}},   # 首次探测 4xx
            {"body": openai_response({"ok": 1})},                                # 降级重发成功
            {"body": openai_response({"ok": 2})},                                # 第二次调用
        ]) as service:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RATOMIZER_LLM_JSON_SCHEMA", None)
                cfg = LLMClientConfig(base_url=service.base_url, model="m", api_key_env="",
                                      timeout_s=2, max_retries=0)
                chat_json(cfg, "s", "u")
                chat_json(cfg, "s", "u")
        self.assertEqual(len(service.requests), 3)
        self.assertIn("response_format", service.requests[0])
        self.assertNotIn("response_format", service.requests[1])   # 降级重发
        self.assertNotIn("response_format", service.requests[2])   # 已记住,不再探测

    def test_connection_error_does_not_mark_unsupported(self) -> None:
        import os
        from tests.test_llm_client import MockOpenAIService

        import llm_client
        from llm_client import LLMClientConfig, LLMConnectionError, chat_json
        with MockOpenAIService([{"status": 401, "body": {"error": "bad key"}}]) as service:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RATOMIZER_LLM_JSON_SCHEMA", None)
                with self.assertRaises(LLMConnectionError):
                    chat_json(LLMClientConfig(base_url=service.base_url, model="m", api_key_env="",
                                              timeout_s=2, max_retries=0), "s", "u")
        with llm_client._JSON_MODE_LOCK:
            self.assertEqual(llm_client._JSON_MODE_UNSUPPORTED, set())   # 连接类错误不定罪端点

    def test_unrelated_400_does_not_fallback_or_mark_unsupported(self) -> None:
        import llm_client
        from llm_client import LLMClientConfig, LLMResponseError, chat_json
        from tests.test_llm_client import MockOpenAIService

        with MockOpenAIService([
            {"status": 400, "body": {"error": "invalid max_tokens value"}},
        ]) as service:
            with self.assertRaises(LLMResponseError):
                chat_json(LLMClientConfig(base_url=service.base_url, model="m", api_key_env="",
                                          timeout_s=2, max_retries=0), "s", "u")
        self.assertEqual(len(service.requests), 1)
        with llm_client._JSON_MODE_LOCK:
            self.assertEqual(llm_client._JSON_MODE_UNSUPPORTED, set())

    def test_malformed_200_does_not_fallback_or_mark_unsupported(self) -> None:
        import llm_client
        from llm_client import LLMClientConfig, LLMResponseError, chat_json
        from tests.test_llm_client import MockOpenAIService

        with MockOpenAIService([{"body": ["not", "an", "object"]}]) as service:
            with self.assertRaises(LLMResponseError):
                chat_json(LLMClientConfig(base_url=service.base_url, model="m", api_key_env="",
                                          timeout_s=2, max_retries=0), "s", "u")
        self.assertEqual(len(service.requests), 1)
        with llm_client._JSON_MODE_LOCK:
            self.assertEqual(llm_client._JSON_MODE_UNSUPPORTED, set())


class GuidanceTemplateCodeTests(unittest.TestCase):
    """E4：guidance 里的模板来源受保护编码——从无声放行改软标随行（不硬拒但必须可见）。"""

    SOURCE = {"source_quote": "The meter shall log tamper events.",
              "description": "", "requirement": ""}

    def test_template_code_in_guidance_soft_flagged_not_rejected(self) -> None:
        from requirements_analysis_agent import validate_llm_item
        item = {"software_requirement_text": "记录篡改事件。",
                "developer_guidance": ["公司通用做法：写入 0-0:96.1.0.255 事件对象"]}
        issues = validate_llm_item(item, self.SOURCE,
                                   template_text="事件对象 0-0:96.1.0.255 固件宏 EVT_TAMPER")
        self.assertTrue(any(i.startswith("template-sourced code in guidance: 0-0:96.1.0.255")
                            for i in issues), issues)
        self.assertFalse(any(i.startswith("fabricated code") for i in issues))   # 软标不硬拒

    def test_soft_flag_lands_in_enrichment_warnings(self) -> None:
        from requirements_analysis import _apply_llm_item
        item = {"analysis_id": "SRA-001", "ownership": "software",
                "ownership_reason": "rule", "ownership_source": "rule"}
        llm_item = {"software_requirement_text": "记录篡改事件的软件逻辑。",
                    "developer_guidance": ["公司通用做法：写入 0-0:96.1.0.255 事件对象"]}
        ok, _ = _apply_llm_item(item, self.SOURCE, llm_item,
                                {"template_refs": "事件对象 0-0:96.1.0.255", "section_context": "",
                                 "doc_context": "", "exemplars": "", "answers": "", "siblings": ""})
        self.assertTrue(ok)                                        # 采纳(模板做法允许进指引)
        self.assertTrue(any("template-sourced code" in w
                            for w in item.get("enrichment_warnings") or []))   # 但软标随行可核

    def test_code_neither_in_source_nor_template_still_hard(self) -> None:
        from requirements_analysis_agent import validate_llm_item
        item = {"software_requirement_text": "记录篡改事件。",
                "developer_guidance": ["写入 1-0:99.98.0.255"]}
        issues = validate_llm_item(item, self.SOURCE, template_text="无关模板内容")
        self.assertTrue(any(i.startswith("fabricated code not in source: 1-0:99.98.0.255 (guidance)")
                            for i in issues), issues)


class CoverageCandidateTests(unittest.TestCase):
    """E3b：覆盖/遗漏统一口径——剔除实证假阳性,真 shall 条款保留。"""

    def _b(self, text: str, **kw) -> dict:
        base = {"block_id": "B", "text": text, "requirement_like": True,
                "noise": False, "type": "paragraph", "doc_region": "body"}
        base.update(kw)
        return base

    def test_real_shall_statement_kept(self) -> None:
        from merged_consistency import is_coverage_candidate
        self.assertTrue(is_coverage_candidate(
            self._b("The XDEV shall be connected to the meter during all tests.")))

    def test_false_positives_excluded(self) -> None:
        from merged_consistency import is_coverage_candidate
        self.assertFalse(is_coverage_candidate(
            self._b("EN 60950-1, Information technology equipment - Safety - Part 1: General requirements")))
        self.assertFalse(is_coverage_candidate(self._b("4.5.1 Requirements")))
        self.assertFalse(is_coverage_candidate(self._b("4.11 Safety Requirements")))
        self.assertFalse(is_coverage_candidate(
            self._b("This standard shall be given national status.", doc_region="front_matter")))
        self.assertFalse(is_coverage_candidate(
            self._b("4 General requirements", type="heading")))
        self.assertFalse(is_coverage_candidate(self._b("x", requirement_like=False)))
        self.assertFalse(is_coverage_candidate(self._b("x", noise=True)))

    def test_numbered_requirement_sentence_not_mistaken_for_heading(self) -> None:
        from merged_consistency import is_coverage_candidate
        # 编号开头但是完整句子（多词+句号）——不是标题,必须保留
        self.assertTrue(is_coverage_candidate(
            self._b("4.6.1 The XDEV shall close the valve within 5 s.")))

    def test_document_blocks_payload_carries_candidate_flag(self) -> None:
        import api_server
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            rows = [
                {"block_id": "B1", "order": 1, "text": "The meter shall log events.",
                 "requirement_like": True, "noise": False, "type": "paragraph",
                 "doc_region": "body", "section_path": ["4"]},
                {"block_id": "B2", "order": 2, "text": "4.5.1 Requirements",
                 "requirement_like": True, "noise": False, "type": "paragraph",
                 "doc_region": "body", "section_path": ["4"]},
            ]
            (out / "blocks.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
            payload = api_server.build_document_blocks(out)
        by_id = {b["block_id"]: b for b in payload["blocks"]}
        self.assertTrue(by_id["B1"]["coverage_candidate"])
        self.assertFalse(by_id["B2"]["coverage_candidate"])   # 编号短标题不再标"未覆盖"


class WatermarkStripTests(unittest.TestCase):
    """E3a：文字层版权水印串（IHS 类,反引号/逗号/破折号长串）确定性清除,防误伤。"""

    def test_real_watermark_sample_removed(self) -> None:
        from parsers.pdf_parser import _strip_watermark_runs
        sample = ("When --`,``,```,`,,```,`,`,,,```,,,-`-`,,`,,`,`,,`--- the manufacturer "
                  "declares that the meter is suitable")
        cleaned = _strip_watermark_runs(sample)
        self.assertNotIn("`", cleaned)
        self.assertIn("When", cleaned)
        self.assertIn("the manufacturer declares", cleaned)

    def test_whole_line_watermark_becomes_blank(self) -> None:
        from parsers.pdf_parser import _strip_watermark_runs
        self.assertEqual(_strip_watermark_runs("--`,``,```,`,,```,`,`,,,```,,,-`-`,,`,,`,`,,`---").strip(), "")

    def test_dash_rules_and_commas_untouched(self) -> None:
        from parsers.pdf_parser import _strip_watermark_runs
        self.assertEqual(_strip_watermark_runs("------------------"), "------------------")   # 纯破折号分隔线
        self.assertEqual(_strip_watermark_runs("a, b, c, d, e, f, g"), "a, b, c, d, e, f, g")
        self.assertEqual(_strip_watermark_runs("val -`, x"), "val -`, x")                     # 短串不动
        self.assertEqual(_strip_watermark_runs("IP67, class B - see 4.9"), "IP67, class B - see 4.9")


class ReviewInsightsEndpointTests(unittest.TestCase):
    """E5：裁决复盘建议接通消费端——此前 review_insights.json 全链零消费者。"""

    def test_missing_file_reports_unavailable(self) -> None:
        import api_server
        with tempfile.TemporaryDirectory() as td:
            payload = api_server.load_review_insights(Path(td))
        self.assertFalse(payload["available"])
        self.assertEqual(payload["suggestions"], [])

    def test_suggestions_surfaced(self) -> None:
        import api_server
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "review_insights.json").write_text(json.dumps({
                "suggestions": ["模块「时钟」被专家改为「预付费」共 3 次——考虑调整关键词边界。"],
                "decided_states": 12,
                "module_transitions": [{"from": "时钟", "to": "预付费", "count": 3}],
            }, ensure_ascii=False), encoding="utf-8")
            payload = api_server.load_review_insights(out)
        self.assertTrue(payload["available"])
        self.assertEqual(len(payload["suggestions"]), 1)
        self.assertIn("预付费", payload["suggestions"][0])
        self.assertEqual(payload["decided_states"], 12)

    def test_broken_json_tolerated(self) -> None:
        import api_server
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "review_insights.json").write_text("{broken", encoding="utf-8")
            payload = api_server.load_review_insights(out)
        self.assertFalse(payload["available"])

    def test_get_route_wired(self) -> None:
        import inspect

        import api_server
        src = inspect.getsource(api_server.RequirementAPIHandler.do_GET)
        self.assertIn('"/review-insights"', src)
        self.assertIn("load_review_insights", src)


class PromptPrefixOrderTests(unittest.TestCase):
    """S6b：分析 prompt 按稳定性降序——固定指令在前,条级内容后移(服务端前缀缓存)。"""

    def test_fixed_instructions_precede_variable_context(self) -> None:
        from requirements_analysis_agent import build_analysis_prompt, slim_vocabulary
        prompt = build_analysis_prompt(
            [{"ai_req_id": "AI-1", "module": "时钟", "ownership": "software"}],
            slim_vocabulary({"modules": ["时钟"]}, "时钟"),
            template_refs="【模板行】x",
            doc_context="【文档背景】表计类型:燃气表。",
            section_context="4.5 clause text", siblings="- 时钟同步需求")
        user = prompt["user"]
        fixed = user.index("请基于需求 JSON")
        specs = user.index("每个 item 的字段")
        doc = user.index("【文档背景】")
        clause = user.index("【所在条款原文")
        reqs = user.index("需求 JSON:")
        self.assertLess(fixed, specs)
        self.assertLess(specs, doc)          # 固定指令块整体在文档背景之前
        self.assertLess(doc, clause)         # 条级条款原文靠后
        self.assertLess(clause, reqs)        # 需求 JSON 收尾


if __name__ == "__main__":
    unittest.main()
