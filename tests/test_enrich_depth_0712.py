"""2026-07-12 富化深度升级回归（W1 上下文/基线、W2 输出要求、W3 富化上墙、W4 归属原因）。

用户反馈"分析不如把需求粘给聊天 AI":根因=富化 prompt 无文档背景/条款原文、
好内容只落 xlsx 不进批注视图、归属原因软件件全链路不可见。测试按工作包编号可倒查。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from requirements_analysis_agent import build_analysis_prompt, slim_vocabulary, validate_llm_item


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


class W1BaselineTests(unittest.TestCase):
    """漂移基线口径:条款原文=有据补全;背景整数软豁免;遗漏分母永不扩(防稀释)。"""

    SOURCE = {"source_quote": "The meter shall store 12 months of data.",
              "description": "存储 12 个月数据。", "requirement": ""}

    def test_code_only_in_doc_context_still_fabricated(self) -> None:
        item = {"software_requirement_text": "写入对象 0-0:96.1.0.255。"}
        issues = validate_llm_item(item, self.SOURCE,
                                   context_text="术语表提到 0-0:96.1.0.255")
        self.assertTrue(any(i.startswith("fabricated code") for i in issues))

    def test_code_and_number_in_section_context_are_grounded(self) -> None:
        item = {"software_requirement_text": "按 7.13.4.5.1 的要求,阀门运行 4000 次循环,对象 0-0:96.3.10.255。"}
        issues = validate_llm_item(item, self.SOURCE,
                                   section_context="7.13.4.5.1 requires 4000 cycles for valve 0-0:96.3.10.255")
        self.assertFalse(any("fabricated" in i for i in issues))

    def test_missing_source_number_still_reported_despite_section_context(self) -> None:
        # 防稀释关键回归:遗漏检测分母=本条自身,即便条款原文里也有 12
        item = {"software_requirement_text": "存储周期性数据。"}
        issues = validate_llm_item(item, self.SOURCE,
                                   section_context="the meter stores 12 months of data")
        self.assertTrue(any("source number 12 missing" in i for i in issues))

    def test_context_int_soft_exempt(self) -> None:
        item = {"software_requirement_text": "依据 EN 13757 实现通信。存储 12 个月数据。"}
        issues = validate_llm_item(item, self.SOURCE,
                                   context_text="目标标准:EN 13757")
        self.assertFalse(any("fabricated number" in i for i in issues))

    def test_context_int_exempt_in_guidance_too(self) -> None:
        item = {"software_requirement_text": "存储 12 个月数据。",
                "developer_guidance": ["对齐 EN 13757 传输层"]}
        issues = validate_llm_item(item, self.SOURCE, context_text="EN 13757")
        self.assertFalse(any("guidance" in i for i in issues))


class W1PromptTests(unittest.TestCase):
    def test_prompt_contains_context_blocks_and_slim_vocab(self) -> None:
        vocab = {"modules": ["时钟", "计量"], "submodules_by_module": {"时钟": ["夏令时"], "计量": ["电能"]}}
        prompt = build_analysis_prompt(
            [{"ai_req_id": "AI-1", "module": "时钟"}], slim_vocabulary(vocab, "时钟"),
            doc_context="【文档背景】表计类型:燃气表。",
            section_context="4.5 AFD1 Requirements ...", siblings="- 时钟同步需求")
        user = prompt["user"]
        self.assertIn("【文档背景】", user)
        self.assertIn("【所在条款原文", user)
        self.assertIn("同模块相邻需求标题", user)
        self.assertIn("连贯的自然段成文", user)          # W2 输出要求
        self.assertIn("夏令时", user)                     # 本模块 submodule 保留
        self.assertNotIn("电能", user)                    # 他模块 submodule 不再全量注入

    def test_slim_vocabulary_shape(self) -> None:
        vocab = {"modules": ["A", "B"], "submodules_by_module": {"A": ["a1"], "B": ["b1"]}}
        slim = slim_vocabulary(vocab, "A")
        self.assertEqual(slim, {"module": "A", "submodules": ["a1"], "modules": ["A", "B"]})


class W1PipelineTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            {"ai_req_id": "AI-1", "title": "数据存储", "module": "数据存储",
             "description": "The meter shall store 12 months of data.",
             "source_quote": "The meter shall store 12 months of data.",
             "source_block_ids": ["B2"]},
        ])
        _write_jsonl(out / "blocks.jsonl", [
            {"block_id": "B1", "order": 1, "type": "heading", "text": "4.3 Storage",
             "section_path": ["4.3 Storage"], "noise": False},
            {"block_id": "B2", "order": 2, "type": "paragraph",
             "text": "The meter shall store 12 months of data.",
             "section_path": ["4.3 Storage"], "noise": False},
            {"block_id": "B3", "order": 3, "type": "paragraph",
             "text": "Data shall survive power loss for 10 years.",
             "section_path": ["4.3 Storage"], "noise": False},
        ])

    def test_prompt_carries_doc_and_section_context(self) -> None:
        from requirements_analysis import run_requirements_analysis
        captured: list[str] = []

        def chat(system: str, user: str) -> dict:
            captured.append(user)
            return {"items": [{"software_requirement_text": "存储 12 个月数据,掉电保持 10 年。"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enriched"], 1)
            self.assertTrue(captured)
            self.assertIn("【所在条款原文", captured[0])
            self.assertIn("survive power loss", captured[0])   # 条款族相邻块进上下文
            self.assertIn("【文档背景】", captured[0])
            # 条款原文里的 10 进有据基线 → 未被拒且无软标
            payload = json.loads((out / "engineering_analysis.json").read_text(encoding="utf-8"))
            self.assertNotIn("enrichment_warnings", payload["items"][0])

    def test_blocks_missing_degrades_gracefully(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            self.assertNotIn("【所在条款原文", user)
            return {"items": [{"software_requirement_text": "存储 12 个月数据。"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "ai_requirements.jsonl", [
                {"ai_req_id": "AI-1", "title": "数据存储", "module": "数据存储",
                 "description": "The meter shall store 12 months of data.",
                 "source_quote": "The meter shall store 12 months of data.",
                 "source_block_ids": ["B2"]},
            ])
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enriched"], 1)

    def test_context_change_invalidates_cache_key(self) -> None:
        from requirements_analysis import _enrich_key
        req = {"ai_req_id": "AI-1"}
        k1 = _enrich_key(req, "m", "ctxA")
        k2 = _enrich_key(req, "m", "ctxB")
        self.assertNotEqual(k1, k2)


class W2FloorTests(unittest.TestCase):
    def test_analyze_floor_raised(self) -> None:
        from llm_client import PURPOSE_MIN_TOKENS
        self.assertEqual(PURPOSE_MIN_TOKENS["analyze"], 8192)


class W3MergeTests(unittest.TestCase):
    def _seed_air(self, out: Path) -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            {"ai_req_id": "AIR-1", "title": "T1", "description": "d1", "module": "计量",
             "source_quote": "q1", "source_block_ids": ["B1"]},
            {"ai_req_id": "AIR-2", "title": "T2", "description": "d2", "module": "计量",
             "source_quote": "q2", "source_block_ids": ["B2"]},
        ])
        _write_jsonl(out / "blocks.jsonl", [
            {"block_id": "B1", "order": 1, "type": "paragraph", "text": "q1", "section_path": [], "noise": False},
            {"block_id": "B2", "order": 2, "type": "paragraph", "text": "q2", "section_path": [], "noise": False},
        ])

    def _analysis(self, items: list[dict], producer: str = "requirements_analysis") -> dict:
        return {"schema_version": "requirements-analysis/v1",
                "provenance": {"producer": producer, "version": "analyze-llm-v5"},
                "items": items}

    def test_join_expands_one_to_many_first_wins(self) -> None:
        from api_server import build_ai_requirements
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed_air(out)
            (out / "engineering_analysis.json").write_text(json.dumps(self._analysis([
                {"analysis_id": "ANREQ-000001", "analysis_source": "llm",
                 "software_requirement_text": "合并后的富化正文。",
                 "developer_guidance": ["指引A"], "acceptance_criteria": ["验收A"],
                 "ownership": "software", "ownership_reason": "含 DLMS 数据处理",
                 "source_requirement_ids": ["AIR-1", "AIR-2"]},
                {"analysis_id": "ANREQ-000002", "analysis_source": "llm",
                 "software_requirement_text": "后到者不得覆盖。",
                 "source_requirement_ids": ["AIR-1"]},
            ]), ensure_ascii=False), encoding="utf-8")
            rows = {r["ai_req_id"]: r for r in build_ai_requirements(out)}
            self.assertEqual(rows["AIR-1"]["analysis_software_requirement_text"], "合并后的富化正文。")
            self.assertEqual(rows["AIR-2"]["analysis_software_requirement_text"], "合并后的富化正文。")
            self.assertEqual(rows["AIR-1"]["analysis_dev_guidance"], ["指引A"])
            self.assertEqual(rows["AIR-1"]["analysis_ownership_reason"], "含 DLMS 数据处理")

    def test_missing_or_alien_analysis_keeps_view_unchanged(self) -> None:
        from api_server import build_ai_requirements
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed_air(out)
            rows = build_ai_requirements(out)
            self.assertFalse(any(k.startswith("analysis_") for k in rows[0]))
            # 坏 JSON
            (out / "engineering_analysis.json").write_text("{broken", encoding="utf-8")
            rows = build_ai_requirements(out)
            self.assertFalse(any(k.startswith("analysis_") for k in rows[0]))
            # 异源 producer
            (out / "engineering_analysis.json").write_text(json.dumps(
                self._analysis([{"analysis_id": "X", "software_requirement_text": "alien",
                                 "source_requirement_ids": ["AIR-1"]}], producer="someone_else"),
                ensure_ascii=False), encoding="utf-8")
            rows = build_ai_requirements(out)
            self.assertFalse(any(k.startswith("analysis_") for k in rows[0]))

    def test_html_renders_enriched_narrative_and_warnings(self) -> None:
        import doc_annotation_export as dae
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed_air(out)
            (out / "engineering_analysis.json").write_text(json.dumps(self._analysis([
                {"analysis_id": "ANREQ-000001", "analysis_source": "llm",
                 "software_requirement_text": "富化正文第一段。\n第二段。",
                 "developer_guidance": ["指引A"],
                 "enrichment_warnings": ["数字待核 42"],
                 "ownership": "software", "ownership_reason": "含数据处理逻辑",
                 "source_requirement_ids": ["AIR-1"]},
            ]), ensure_ascii=False), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            self.assertIn("富化(LLM)", rendered)
            self.assertIn("富化正文第一段。", rendered)
            self.assertIn("为什么判为", rendered)
            self.assertIn("含数据处理逻辑", rendered)
            self.assertIn("⚠ 富化待核", rendered)

    def test_xlsx_notes_carry_acceptance_and_ownership(self) -> None:
        from requirements_analysis_excel import _notes_text
        item = {"acceptance_criteria": ["按 4.2 验证"], "ownership": "software",
                "ownership_reason": "Matched software rule term: dlms",
                "ownership_reason_source": "llm"}
        notes = _notes_text(item)
        self.assertIn("验收建议：按 4.2 验证", notes)
        self.assertIn("归属判定：软件（依据：Matched software rule term: dlms，LLM 判定）", notes)


class W4OwnershipReasonTests(unittest.TestCase):
    def _seed(self, out: Path, quote: str = "The meter shall record events via DLMS.") -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            {"ai_req_id": "AI-1", "title": "事件记录", "module": "事件记录",
             "description": quote, "source_quote": quote, "source_block_ids": ["B1"]},
        ])

    def test_llm_reason_adopted_for_software(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "记录事件并通过 DLMS 上报。",
                               "ownership": "software",
                               "ownership_reason": "纯数据处理与协议上报逻辑,无硬件依赖"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            run_requirements_analysis(out, route="openai_compatible", chat=chat)
            item = json.loads((out / "engineering_analysis.json").read_text(encoding="utf-8"))["items"][0]
            # 病灶回归锁:旧恒真 guard 下这里永远是规则串
            self.assertEqual(item["ownership_reason"], "纯数据处理与协议上报逻辑,无硬件依赖")
            self.assertEqual(item["ownership_reason_source"], "llm")

    def test_reason_with_fabricated_code_rejects_whole_enrichment(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "记录事件。",
                               "ownership_reason": "涉及对象 0-0:96.7.0.255 故判软件"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enriched"], 0)
            item = json.loads((out / "engineering_analysis.json").read_text(encoding="utf-8"))["items"][0]
            self.assertTrue(item["ownership_reason"].startswith("Matched"))   # 保留规则原因

    def test_inconsistent_llm_ownership_keeps_rule_reason(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "记录事件并通过 DLMS 上报。",
                               "ownership": "hardware",
                               "ownership_reason": "这是机械部件"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            run_requirements_analysis(out, route="openai_compatible", chat=chat)
            item = json.loads((out / "engineering_analysis.json").read_text(encoding="utf-8"))["items"][0]
            self.assertNotEqual(item["ownership_reason"], "这是机械部件")
            self.assertNotEqual(item.get("ownership_reason_source"), "llm")

    def test_reviewer_override_reason_not_clobbered(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "软件侧适配驱动。",
                               "ownership_reason": "LLM 想改写的原因"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            _write_jsonl(out / "ai_review_states.jsonl", [
                {"ai_req_id": "AI-1", "ownership_override": "co_design", "reason": "专家改判"}])
            run_requirements_analysis(out, route="openai_compatible", chat=chat)
            item = json.loads((out / "engineering_analysis.json").read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(item["ownership_source"], "reviewer_override")
            self.assertNotEqual(item.get("ownership_reason"), "LLM 想改写的原因")

    def test_api_rows_carry_reason_for_all_classes(self) -> None:
        from api_server import build_ai_requirements
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_jsonl(out / "ai_requirements.jsonl", [
                {"ai_req_id": "AI-SW", "title": "s", "description": "firmware shall compute tariffs",
                 "source_quote": "firmware shall compute tariffs", "source_block_ids": ["B1"]},
                {"ai_req_id": "AI-HW", "title": "h", "description": "the valve is a mechanical device",
                 "source_quote": "the valve is a mechanical device", "source_block_ids": ["B2"]},
            ])
            _write_jsonl(out / "blocks.jsonl", [])
            for row in build_ai_requirements(out):
                self.assertTrue(str(row.get("ownership_reason") or "").strip(),
                                f"{row['ai_req_id']} 缺归属原因")
                self.assertTrue(row.get("ownership_source"))
