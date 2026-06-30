from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ai_extract


class AssembleSectionsTests(unittest.TestCase):
    def test_groups_blocks_by_section_path(self) -> None:
        blocks = [
            {"block_id": "B1", "section_path": ["4 Requirements"], "text": "The meter shall do A."},
            {"block_id": "B2", "section_path": ["4 Requirements"], "text": "It shall also do B."},
            {"block_id": "B3", "section_path": ["5 Security"], "text": "Authentication is required."},
            {"block_id": "B4", "section_path": ["5 Security"], "text": ""},  # 空文本不计内容
        ]
        sections = ai_extract.assemble_sections(blocks)
        self.assertEqual(len(sections), 2)
        s0 = sections[0]
        self.assertEqual(s0["heading"], "4 Requirements")
        self.assertIn("do A", s0["text"])
        self.assertIn("do B", s0["text"])
        self.assertEqual(s0["block_ids"], ["B1", "B2"])

    def test_section_with_only_empty_text_dropped(self) -> None:
        blocks = [{"block_id": "B1", "section_path": ["Empty"], "text": "   "}]
        self.assertEqual(ai_extract.assemble_sections(blocks), [])


class ExtractDriftTests(unittest.TestCase):
    def test_obis_present_in_source_no_drift(self) -> None:
        req = {"description": "实现 OBIS 1-0:1.8.0.255 的有功电能", "source_quote": "active energy 1-0:1.8.0.255"}
        source = "The meter shall expose active energy import at OBIS 1-0:1.8.0.255."
        self.assertEqual(ai_extract.extract_drift(req, source), [])

    def test_fabricated_obis_is_drift(self) -> None:
        req = {"description": "实现 OBIS 0-0:96.99.99.255（原文没有）", "source_quote": ""}
        source = "The meter shall expose active energy import at OBIS 1-0:1.8.0.255."
        drift = ai_extract.extract_drift(req, source)
        self.assertIn("0-0:96.99.99.255", drift)


class ExtractSectionTests(unittest.TestCase):
    def _section(self) -> dict:
        return {"section_id": "5.3 Firmware upgrade", "heading": "5.3 Firmware upgrade",
                "text": "Firmware download shall only be carried out after authentication. "
                        "The new software shall be activated at a fixed date and time.",
                "block_ids": ["B10", "B11"]}

    def test_normalizes_and_keeps_clean_requirement(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "Firmware upgrade", "description": "固件升级须先认证再下载，按预定时间激活。",
                "type": "functional", "priority": "P1", "labels": ["升级", "安全"],
                "source_quote": "Firmware download shall only be carried out after authentication.",
                "acceptance_criteria": ["认证通过后才允许下载"]}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual(r["type"], "functional")
        self.assertEqual(r["priority"], "P1")
        self.assertEqual(r["labels"], ["升级", "安全"])
        self.assertEqual(r["extracted_by"], "ai_extract")
        self.assertEqual(r["source_block_ids"], ["B10", "B11"])
        self.assertNotIn("结构漂移", r["notes"])

    def test_fabricated_code_is_flagged_not_dropped(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "Bogus", "description": "固件升级走 OBIS 0-0:44.1.0.255（原文并无此码）。",
                "type": "functional", "priority": "P1", "labels": ["升级"], "source_quote": ""}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(len(reqs), 1)
        self.assertIn("结构漂移已拦截", reqs[0]["notes"])
        self.assertEqual(reqs[0]["status"], "draft")

    def test_invalid_type_priority_normalized(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "X", "description": "desc",
                                       "type": "bogus", "priority": "P9", "source_quote": "desc"}]}

        r = ai_extract.extract_section(self._section(), chat)[0]
        self.assertEqual(r["type"], "functional")
        self.assertEqual(r["priority"], "P2")


class CacheReproducibilityTests(unittest.TestCase):
    def test_rerun_hits_cache_and_is_stable(self) -> None:
        sections = [{"section_id": "S1", "heading": "S1", "text": "The meter shall do A.", "block_ids": ["B1"]}]
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return {"requirements": [{"title": "Do A", "description": "做 A", "type": "functional",
                                       "priority": "P1", "labels": ["计量"], "source_quote": "The meter shall do A."}]}

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            first = ai_extract.extract_all(sections, chat, model="m", cache_path=cache)
            second = ai_extract.extract_all(sections, chat, model="m", cache_path=cache)
            self.assertEqual(calls["n"], 1)  # 第二次命中缓存，未再调 LLM
            self.assertEqual(first, second)   # 同输入同输出（稳定）


class ExtractAllProgressTests(unittest.TestCase):
    def test_progress_events_and_failure_count(self) -> None:
        """每章节回调进度 + 失败章节计入 stats 不崩 —— 回归：AI 抽取零进度时界面像卡死。"""
        from llm_client import LLMConnectionError
        sections = [
            {"section_id": "S1", "heading": "S1", "text": "The meter shall do A.", "block_ids": ["B1"]},
            {"section_id": "S2", "heading": "S2", "text": "The meter shall do B.", "block_ids": ["B2"]},
        ]

        def chat(system: str, user: str) -> dict:
            if "do B" in user:  # 模拟某章节 LLM 调用失败（如 401/超时）
                raise LLMConnectionError("HTTP 401")
            return {"requirements": [{"title": "Do A", "description": "做 A", "type": "functional",
                                      "priority": "P1", "labels": ["计量"],
                                      "source_quote": "The meter shall do A."}]}

        events: list[dict] = []
        stats: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            flat = ai_extract.extract_all(sections, chat, model="m", cache_path=cache,
                                          progress_callback=events.append, stats=stats)
        # 初始 1 次 + 每章节完成各 1 次 = 至少 3 次回调，末次满 100%
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(events[-1]["stage"], "ai_extract")
        self.assertEqual(events[-1]["completed"], 2)
        self.assertEqual(events[-1]["total"], 2)
        self.assertEqual(events[-1]["percent"], 100)
        # 失败章节计入 stats、不抛；成功章节仍产 1 条需求
        self.assertEqual(stats["failed_sections"], 1)
        self.assertEqual(stats["total_sections"], 2)
        self.assertEqual(len(flat), 1)


class RouteTests(unittest.TestCase):
    def test_stub_route_produces_no_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(
                '{"block_id":"B1","section_path":["4"],"text":"The meter shall do A."}\n', encoding="utf-8")
            result = ai_extract.run_ai_extract(out, route="stub")
        self.assertEqual(result["route"], "stub")
        self.assertEqual(result["requirements"], 0)
        self.assertGreaterEqual(result["sections"], 1)

    def test_config_for_route_stub_is_none(self) -> None:
        self.assertIsNone(ai_extract.config_for_route("stub"))
        self.assertIsNone(ai_extract.config_for_route(None))

    def test_run_ai_extract_floors_max_tokens_for_reasoning_models(self) -> None:
        """推理模型 max_tokens 太小会截断 JSON → 整章节失败；run_ai_extract 须把预算抬到下限。"""
        from llm_client import LLMClientConfig
        captured: dict = {}

        def fake_chat_json(config, system, user):
            captured["max_tokens"] = config.max_tokens
            return {"requirements": []}

        low = LLMClientConfig(base_url="http://x", model="m", max_tokens=1024)
        orig_cfg = ai_extract.config_for_route
        orig_chat = ai_extract.chat_json
        ai_extract.config_for_route = lambda route, pipeline_path=None: low
        ai_extract.chat_json = fake_chat_json
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "blocks.jsonl").write_text(
                    '{"block_id":"B1","section_path":["4"],"text":"The meter shall do A."}\n',
                    encoding="utf-8")
                ai_extract.run_ai_extract(out, route="openai_compatible", merge_deterministic=False)
            self.assertEqual(captured["max_tokens"], ai_extract.AI_EXTRACT_MIN_MAX_TOKENS)
        finally:
            ai_extract.config_for_route = orig_cfg
            ai_extract.chat_json = orig_chat

    def test_resolve_concurrency_explicit_env_default_and_clamp(self) -> None:
        import os
        # 显式参数优先并夹取
        self.assertEqual(ai_extract.resolve_concurrency(2), 2)
        self.assertEqual(ai_extract.resolve_concurrency(99), ai_extract.MAX_CONCURRENCY)
        self.assertEqual(ai_extract.resolve_concurrency(0), 1)
        prior = os.environ.get(ai_extract.CONCURRENCY_ENV)
        try:
            os.environ[ai_extract.CONCURRENCY_ENV] = "3"
            self.assertEqual(ai_extract.resolve_concurrency(None), 3)  # 取环境变量
            os.environ[ai_extract.CONCURRENCY_ENV] = "bogus"
            self.assertEqual(ai_extract.resolve_concurrency(None), ai_extract.DEFAULT_CONCURRENCY)
            os.environ.pop(ai_extract.CONCURRENCY_ENV, None)
            self.assertEqual(ai_extract.resolve_concurrency(None), ai_extract.DEFAULT_CONCURRENCY)
        finally:
            if prior is None:
                os.environ.pop(ai_extract.CONCURRENCY_ENV, None)
            else:
                os.environ[ai_extract.CONCURRENCY_ENV] = prior

    def test_stub_route_still_produces_deterministic_merged_spec(self) -> None:
        """stub（LLM 关）下确定性引擎仍须照常产出 merged_spec —— 回归：早期 early-return 让 GUI 双引擎按钮零产出。"""
        original = ai_extract.load_or_build_deterministic
        # 确定性结构需求须带 threshold_table.rows，否则 merge_requirements 视为散文模板丢弃
        ai_extract.load_or_build_deterministic = lambda out_dir, *, source, extracted_at: [
            {"id": "DET-1", "title": "Register value", "description": "OBIS 1-0:1.8.0.255",
             "type": "数据需求", "priority": "P1", "labels": ["计量"],
             "source_section": "4 Data model", "source_quote": "", "notes": "",
             "acceptance_criteria": [], "status": "draft",
             "dependencies": [], "parent": None, "children": [],
             "threshold_table": {"columns": ["OBIS", "class_id"],
                                 "rows": [["1-0:1.8.0.255", "3"]]}},
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "blocks.jsonl").write_text(
                    '{"block_id":"B1","section_path":["4"],"text":"The meter shall do A."}\n',
                    encoding="utf-8")
                result = ai_extract.run_ai_extract(out, route="stub", merge_deterministic=True)
                self.assertEqual(result["route"], "stub")
                self.assertEqual(result["requirements"], 0)  # AI 行为引擎为空
                # 确定性引擎照常落盘
                self.assertIn("merged_spec_requirements.json", result["written"])
                self.assertIn("merged_spec.xlsx", result["written"])
                self.assertTrue((out / "merged_spec_requirements.json").exists())
                self.assertTrue((out / "merged_spec.xlsx").exists())
                self.assertEqual(result["merged"]["deterministic_structural"], 1)
                self.assertEqual(result["merged"]["ai_behavioral"], 0)
        finally:
            ai_extract.load_or_build_deterministic = original


class MergeSectionsTests(unittest.TestCase):
    def test_small_sections_merged_to_target(self) -> None:
        sections = [
            {"section_id": "A", "heading": "A", "text": "x" * 100, "block_ids": ["b1"]},
            {"section_id": "B", "heading": "B", "text": "y" * 100, "block_ids": ["b2"]},
            {"section_id": "C", "heading": "C", "text": "z" * 100, "block_ids": ["b3"]},
        ]
        merged = ai_extract.merge_sections(sections, target_chars=260)
        # 100+标题 累加，260 上限 → 前两段并一个，第三段单独 → 2 个单元
        self.assertEqual(len(merged), 2)
        # block 溯源不丢
        all_ids = [bid for m in merged for bid in m["block_ids"]]
        self.assertEqual(sorted(all_ids), ["b1", "b2", "b3"])
        # 合并文本含各小节标题
        self.assertIn("## A", merged[0]["text"])
        self.assertIn("## B", merged[0]["text"])

    def test_oversized_section_is_split_under_target(self) -> None:
        """超大源章节须被拆成 ≤target 的多块（防 LLM 输出 JSON 截断）——回归：8987 字整块导致 40/48 失败。"""
        paras = "\n".join(f"段落{i} " + "字" * 200 for i in range(20))  # ~4200 字，单章节
        sections = [{"section_id": "S1", "heading": "H", "text": paras, "block_ids": ["b1", "b2"]}]
        merged = ai_extract.merge_sections(sections, target_chars=2800)
        self.assertGreater(len(merged), 1)  # 被拆开
        for m in merged:
            self.assertLessEqual(len(m["text"]), 2800)  # 每块有界
            self.assertEqual(m["block_ids"], ["b1", "b2"])  # 同段 block 溯源保留

    def test_split_text_bounds_and_is_lossless(self) -> None:
        text = "\n".join(f"line{i} " + "a" * 100 for i in range(60))  # ~6500 字
        chunks = ai_extract._split_text(text, 2800)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 2800 for c in chunks))
        # 去掉拆分边界换行后内容无损
        self.assertEqual("".join(c.replace("\n", "") for c in chunks), text.replace("\n", ""))

    def test_split_handles_single_overlong_line(self) -> None:
        chunks = ai_extract._split_text("x" * 9000, 2800)  # 无换行长行须硬切
        self.assertTrue(all(len(c) <= 2800 for c in chunks))
        self.assertEqual("".join(chunks), "x" * 9000)

    def test_split_carries_full_drift_source(self) -> None:
        """拆分后漂移 baseline 须用整章原文：同章另一片段里的 OBIS 不算漂移（假阳性误伤）。"""
        # 前 4000 字无码，末尾段落含真实 OBIS 码 → 被拆到靠后的片段
        text = ("安全描述文字。" * 600) + "\n该对象对应 OBIS 0-0:96.7.16.255。"
        merged = ai_extract.merge_sections(
            [{"section_id": "S", "heading": "安全", "text": text, "block_ids": ["b1"]}],
            target_chars=2800)
        self.assertGreater(len(merged), 1)  # 确实被拆分
        # 早期片段 text 不含该码，但 drift_source 须是整章原文 → 含码
        early = merged[0]
        self.assertNotIn("0-0:96.7.16.255", early["text"])
        self.assertIn("0-0:96.7.16.255", early["drift_source"])

    def test_cross_fragment_code_not_falsely_flagged_as_drift(self) -> None:
        """回归：LLM 在不含码的片段里引用同章另一片段的 OBIS 码，不得被判结构漂移。"""
        # 构造一个超大章节：前半段无码，后半段含真实 OBIS，拆分后早期片段不含码
        real_text = ("安全章节描述文字。" * 400) + "\n事件对象 OBIS 0-0:96.7.16.255。"
        merged = ai_extract.merge_sections(
            [{"section_id": "S", "heading": "安全", "text": real_text, "block_ids": ["b1"]}],
            target_chars=2800)
        early = merged[0]
        self.assertNotIn("0-0:96.7.16.255", early["text"])  # 早期片段确不含码

        # LLM 对早期片段抽取时引用了同章另一片段里的真实码 → 不应判漂移
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "事件上报", "description": "采用 OBIS 0-0:96.7.16.255 上报安全事件。",
                "type": "functional", "priority": "P1", "labels": ["事件记录"],
                "source_quote": "security event"}]}

        reqs = ai_extract.extract_section(early, chat)
        self.assertEqual(len(reqs), 1)
        self.assertNotIn("结构漂移已拦截", reqs[0]["notes"])  # 同章真实码不算漂移

    def test_cross_fragment_fabricated_code_still_flagged(self) -> None:
        """护栏仍须拦住真正的无中生有：LLM 凭空编的码（整章都没有）仍判结构漂移。"""
        real_text = ("安全章节描述文字。" * 400)  # 整章不含任何 OBIS 码
        merged = ai_extract.merge_sections(
            [{"section_id": "S", "heading": "安全", "text": real_text, "block_ids": ["b1"]}],
            target_chars=2800)

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "伪造", "description": "走 OBIS 0-0:96.99.99.255（原文并无此码）。",
                "type": "functional", "priority": "P1", "labels": ["事件记录"],
                "source_quote": ""}]}

        reqs = ai_extract.extract_section(merged[0], chat)
        self.assertEqual(len(reqs), 1)
        self.assertIn("结构漂移已拦截", reqs[0]["notes"])
        self.assertEqual(reqs[0]["status"], "draft")


class DriftSeverityTests(unittest.TestCase):
    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S",
                "text": "The device shall support a serial interface for data export.",
                "block_ids": ["b1"]}

    def test_fabricated_int_is_soft_flagged_and_kept(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "Serial", "description": "支持 RS-485 串行接口导出数据。",
                                       "type": "functional", "priority": "P1", "labels": ["通信协议"],
                                       "source_quote": "shall support a serial interface for data export"}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(len(reqs), 1)  # 软标不丢弃
        self.assertIn("数字漂移", reqs[0]["notes"])
        self.assertNotIn("结构漂移已拦截", reqs[0]["notes"])  # 485 不是受保护编码

    def test_fabricated_obis_is_hard_flagged(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "Bogus", "description": "走 OBIS 0-0:96.7.16.255 上报。",
                                       "type": "functional", "priority": "P1", "labels": ["事件记录"],
                                       "source_quote": "data export"}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(reqs[0]["status"], "draft")
        self.assertIn("结构漂移已拦截（编码", reqs[0]["notes"])


class EnsureDomainLabelsTests(unittest.TestCase):
    def test_free_labels_get_a_metering_domain_prepended(self) -> None:
        from spec_excel import METERING_DOMAINS
        reqs = [{"title": "固件升级安全", "description": "固件升级须认证并保证安全。",
                 "source_quote": "firmware upgrade authentication", "labels": ["AFD", "firmware"]}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertTrue(any(l in set(METERING_DOMAINS) for l in reqs[0]["labels"]))
        # 原自由标签保留
        self.assertIn("AFD", reqs[0]["labels"])

    def test_existing_domain_label_untouched(self) -> None:
        reqs = [{"title": "x", "description": "y", "source_quote": "z", "labels": ["计量", "AFD"]}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"], ["计量", "AFD"])


class MergeRequirementsTests(unittest.TestCase):
    def test_keeps_structural_drops_template_adds_ai(self) -> None:
        det = [
            {"title": "对象X", "threshold_table": {"description": "属性访问表", "columns": ["#"], "rows": [["1"]]}},
            {"title": "确定性模板行为", "threshold_table": None},  # 纯散文模板 → 丢
        ]
        ai = [{"title": "AI行为需求", "threshold_table": None, "extracted_by": "ai_extract"}]
        merged = ai_extract.merge_requirements(det, ai)
        titles = [r["title"] for r in merged]
        self.assertIn("对象X", titles)        # 确定性结构（OBIS 权威）保留
        self.assertIn("AI行为需求", titles)    # AI 行为加入
        self.assertNotIn("确定性模板行为", titles)  # 确定性散文模板丢弃（AI 替代）
        self.assertEqual(merged[0]["extracted_by"], "deterministic")


class BuildSkillDocTests(unittest.TestCase):
    def test_builds_skill_format_doc(self) -> None:
        reqs = [
            {"title": "A", "description": "desc A", "type": "functional", "priority": "P1",
             "status": "draft", "source_section": "1", "source_quote": "q", "threshold_table": None,
             "acceptance_criteria": [], "dependencies": [], "parent": None, "children": [],
             "labels": ["计量"], "notes": ""},
        ]
        doc = ai_extract.build_skill_doc(reqs, source="doc.pdf", extracted_at="2026-01-01T00:00:00")
        self.assertIn("meta", doc)
        self.assertIn("requirements", doc)
        self.assertIn("analysis", doc)
        self.assertEqual(doc["requirements"][0]["id"], "REQ-001")
        self.assertEqual(doc["analysis"]["total_count"], 1)


class ModuleClassificationTests(unittest.TestCase):
    """LLM 受控模块分类（按域分组的首要领域来源）。"""

    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S", "text": "t", "block_ids": []}

    def test_normalize_captures_module(self) -> None:
        r = ai_extract.normalize_requirement(
            {"title": "X", "description": "d", "module": "计量", "source_quote": "d"}, self._section())
        self.assertEqual(r["module"], "计量")

    def test_module_vocab_superset_and_prompt(self) -> None:
        for m in ("附加功能", "机械结构", "计量精度", "数据存储", "测试合规", "其它"):
            self.assertIn(m, ai_extract.MODULE_VOCAB)
        self.assertIn("module", ai_extract.SYSTEM_PROMPT)
        self.assertIn("附加功能", ai_extract.SYSTEM_PROMPT)

    def test_valid_llm_module_becomes_primary_domain(self) -> None:
        reqs = [{"module": "计量", "labels": ["gas meter", "measurement"],
                 "title": "", "description": "", "source_quote": ""}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"][0], "计量")        # LLM 模块作首要领域
        self.assertIn("gas meter", reqs[0]["labels"])          # 自由标签保留为补充

    def test_other_module_respected_not_remapped(self) -> None:
        reqs = [{"module": "其它", "labels": ["AFD"],
                 "title": "mechanical connector", "description": "", "source_quote": ""}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"][0], "其它")         # 尊重 LLM "无贴切"，不塞通信协议

    def test_invalid_or_missing_module_falls_back_to_map_labels(self) -> None:
        reqs = [
            {"module": "乱填XX", "labels": [], "title": "voltage sag threshold",
             "description": "", "source_quote": ""},
            {"module": "", "labels": [], "title": "firmware upgrade image",
             "description": "", "source_quote": ""},
        ]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"][0], "门限范围")     # map_labels 关键词兜底
        self.assertEqual(reqs[1]["labels"][0], "升级")


if __name__ == "__main__":
    unittest.main()
