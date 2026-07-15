"""2026-07-08 三视角审计修复的回归锁（护栏方向/默认值闭环/守恒审计）。

每个测试对应审计报告一条确认发现——名字里带审计编号,倒查病灶用。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class GuidanceDriftGuardTests(unittest.TestCase):
    """B2：developer_guidance/acceptance_criteria/assumptions 纳入漂移校验。"""

    def _source(self) -> dict:
        return {"source_quote": "The meter shall record events with timestamp.",
                "description": "", "requirement": ""}

    def test_fabricated_code_in_guidance_is_hard(self) -> None:
        from requirements_analysis_agent import validate_llm_item
        item = {"requirement": "Record events.",
                "developer_guidance": ["写入对象 0-0:96.11.0.255 的事件缓冲"]}
        issues = validate_llm_item(item, self._source())
        self.assertTrue(any(i.startswith("fabricated code") and "(guidance)" in i for i in issues))

    def test_template_codes_in_guidance_allowed_but_soft_flagged(self) -> None:
        """模板注入的公司做法进 guidance 是设计意图——不硬拒;但受保护编码不再无声放行,
        软标「template-sourced」随行可核（0714 批次二 E4 收紧,原无声放行契约作废）。"""
        from requirements_analysis_agent import validate_llm_item
        item = {"requirement": "Record events.",
                "developer_guidance": ["公司通用做法：事件对象 0-0:96.11.0.255，宏 EVT_STD"]}
        template = "模板说明：标准事件对象 0-0:96.11.0.255 宏 EVT_STD"
        issues = validate_llm_item(item, self._source(), template_text=template)
        self.assertFalse(any(i.startswith("fabricated code") for i in issues))   # 不硬拒
        self.assertTrue(any(i.startswith("template-sourced code in guidance") for i in issues))

    def test_fabricated_number_in_guidance_is_soft(self) -> None:
        from requirements_analysis_agent import validate_llm_item
        item = {"requirement": "Record events.",
                "acceptance_criteria": ["容量不少于 10000 条"]}
        issues = validate_llm_item(item, self._source())
        self.assertTrue(any(i.startswith("fabricated number in guidance") for i in issues))


class EnrichmentWarningTravelsTests(unittest.TestCase):
    """B1：软标必须随 item 落盘并在交付列可见（此前只进 run 级 issues，成文 xlsx 零标记）。"""

    def test_notes_text_renders_enrichment_warnings(self) -> None:
        from requirements_analysis_excel import _notes_text
        item = {"enrichment_warnings": ["fabricated number in guidance: 10000"],
                "developer_guidance": ["常规指引"]}
        notes = _notes_text(item)
        self.assertIn("⚠ 富化待核", notes)
        self.assertIn("10000", notes)

    def test_template_writer_notes_include_warnings(self) -> None:
        from template_writer import build_row_values
        item = {"module": "事件记录", "description": "d", "requirement": "r",
                "enrichment_warnings": ["fabricated number in guidance: 10000"]}
        row = build_row_values(item, 1)
        joined = " ".join(str(v) for v in row.values())
        self.assertIn("富化待核", joined)


class ExtractDeliveryGuardTests(unittest.TestCase):
    """B3/B4：threshold_table/sub_items 纳入漂移扫描；交付字段编码也查。"""

    def test_fabricated_code_in_dev_guidance_removed_and_hard(self) -> None:
        from ai_extract import _move_unsupported_delivery_items
        req = {"dev_guidance": ["读取 1-0:99.1.0.255 曲线对象"], "acceptance_criteria": []}
        ints, codes = _move_unsupported_delivery_items(req, "The meter shall store load profile data.")
        self.assertIn("1-0:99.1.0.255", codes)
        self.assertEqual(req["dev_guidance"], [])
        self.assertIn("无依据编码", req.get("notes") or "")

    def test_threshold_table_ints_visible_to_drift(self) -> None:
        from ai_extract import int_drift
        req = {"title": "限值", "description": "见表", "source_quote": "",
               "threshold_table": {"columns": ["档位", "限值"], "rows": [["A", "12345"]]},
               "acceptance_criteria": []}
        drift = int_drift(req, "The threshold applies to class A meters.")
        self.assertIn("12345", drift)

    def test_sub_items_codes_visible_to_drift(self) -> None:
        from ai_extract import code_drift
        req = {"title": "t", "description": "", "source_quote": "",
               "sub_items": [{"label": "a", "text": "对象 0-0:96.1.0.255 序列号"}],
               "acceptance_criteria": []}
        drift = code_drift(req, "The meter shall provide a serial number.")
        self.assertIn("0-0:96.1.0.255", drift)


class AdjudicationBankFilterTests(unittest.TestCase):
    """B5：漂移标记/可疑样本不进 few-shot 教材。"""

    def test_drift_marked_accept_not_harvested(self) -> None:
        from adjudication_bank import update_bank
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reqs = [{"ai_req_id": "AIR-1", "title": "t1", "module": "计量",
                     "notes": "数字漂移（待核）：10000", "description": "d"},
                    {"ai_req_id": "AIR-2", "title": "t2", "module": "计量",
                     "suspicion_reasons": ["漏值"], "description": "d"},
                    {"ai_req_id": "AIR-3", "title": "t3", "module": "计量", "description": "d"}]
            (out / "ai_requirements.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in reqs), encoding="utf-8")
            states = [{"ai_req_id": "AIR-1", "status": "accepted"},
                      {"ai_req_id": "AIR-2", "status": "accepted"},
                      {"ai_req_id": "AIR-3", "status": "accepted"}]
            (out / "ai_review_states.jsonl").write_text(
                "\n".join(json.dumps(s_, ensure_ascii=False) for s_ in states), encoding="utf-8")
            bank_path = out / "bank.json"
            update_bank(bank_path, out)
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
        self.assertNotIn("AIR-1", bank["accepted"])   # 漂移标记
        self.assertNotIn("AIR-2", bank["accepted"])   # suspicion 未清
        self.assertIn("AIR-3", bank["accepted"])      # 干净样本照收


class ClarificationFixTests(unittest.TestCase):
    """M9 键名 + H5 解析层审计信号。"""

    def test_obis_key_renders_in_question(self) -> None:
        from clarification_report import collect_questions
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "consistency_report.json").write_text(json.dumps({
                "obis_coreference": [{"obis": "1-0:1.8.0", "values_differ": True, "count": 2}],
            }, ensure_ascii=False), encoding="utf-8")
            entries = collect_questions(out)
        hits = [e for e in entries if "1-0:1.8.0" in e["question"]]
        self.assertTrue(hits, "OBIS 码必须出现在问题文本里（键名 obis 非 code）")

    def test_noise_ratio_audit_entry(self) -> None:
        from clarification_report import _parse_audit_entries, AUDIENCE_INTERNAL
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            blocks = ([{"block_id": f"N{i}", "text": "x" * 100, "noise": True,
                        "doc_region": "body"} for i in range(3)]
                      + [{"block_id": "B1", "text": "y" * 100, "noise": False,
                          "doc_region": "body"}])
            (out / "blocks.jsonl").write_text(
                "\n".join(json.dumps(b) for b in blocks), encoding="utf-8")
            entries = _parse_audit_entries(out)
        noise_entries = [e for e in entries if e["signal"] == "parse_audit:noise_char_ratio"]
        self.assertEqual(len(noise_entries), 1)
        self.assertEqual(noise_entries[0]["audience"], AUDIENCE_INTERNAL)

    def test_healthy_parse_no_audit_entries(self) -> None:
        from clarification_report import _parse_audit_entries
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            blocks = [{"block_id": f"B{i}", "text": "y" * 100, "noise": False,
                       "doc_region": "body"} for i in range(30)]
            (out / "blocks.jsonl").write_text(
                "\n".join(json.dumps(b) for b in blocks), encoding="utf-8")
            self.assertEqual(_parse_audit_entries(out), [])


class RegionGuardTests(unittest.TestCase):
    """H1：文档后部的裸 Scope 不再吞掉前半正文。"""

    def _blocks(self, scope_positions: list[int], total: int = 100) -> list[dict]:
        blocks = []
        for i in range(total):
            if i in scope_positions:
                blocks.append({"block_id": f"BLK-{i:06d}", "type": "heading",
                               "text": "Scope", "section_path": ["Scope"]})
            else:
                blocks.append({"block_id": f"BLK-{i:06d}", "type": "paragraph",
                               "text": f"body text {i}", "section_path": []})
        return blocks

    def test_late_scope_ignored(self) -> None:
        from atomize import mark_doc_regions
        blocks = self._blocks([5, 90])
        mark_doc_regions(blocks, [])
        # 第 6 块起就是 body（后部第 90 块的 Scope 不作数）
        self.assertEqual(blocks[10].get("doc_region"), "body")
        self.assertEqual(blocks[50].get("doc_region"), "body")

    def test_only_late_scope_falls_back_to_first(self) -> None:
        from atomize import mark_doc_regions
        blocks = self._blocks([80, 90])
        mark_doc_regions(blocks, [])
        self.assertEqual(blocks[85].get("doc_region"), "body")   # 回退第一个而非最后一个


class NoiseCapTests(unittest.TestCase):
    """M2/M3：重复行/©页脚判定只适用于短行——长正文段免疫误标。"""

    def test_long_paragraph_with_copyright_not_noise(self) -> None:
        from parsers.pdf_parser import _append_text_block
        from atomize import SectionState, DEFAULT_DOCUMENT_PROFILE
        from requirement_kb import KnowledgeRepository
        blocks: list[dict] = []
        long_text = ("The intellectual property notice © applies, see page 12 for details. "
                     "The device shall additionally record all tamper events with timestamps "
                     "and retain them for the full retention period defined by this clause.")
        _append_text_block(blocks, long_text, order=0, page_number=1,
                           sections=SectionState(),
                           knowledge_bases=KnowledgeRepository.from_paths([]),
                           repeated_noise=set(), last_caption=None,
                           profile=DEFAULT_DOCUMENT_PROFILE)
        self.assertFalse(blocks[0]["noise"])

    def test_short_copyright_footer_still_noise(self) -> None:
        from parsers.pdf_parser import _append_text_block
        from atomize import SectionState, DEFAULT_DOCUMENT_PROFILE
        from requirement_kb import KnowledgeRepository
        blocks: list[dict] = []
        _append_text_block(blocks, "UNI/TS 12007:2026 © UNI Page 23", order=0, page_number=1,
                           sections=SectionState(),
                           knowledge_bases=KnowledgeRepository.from_paths([]),
                           repeated_noise=set(), last_caption=None,
                           profile=DEFAULT_DOCUMENT_PROFILE)
        self.assertTrue(blocks[0]["noise"])


class StageReuseGuardTests(unittest.TestCase):
    """2026-07-09 评审修正：台账复用必须有出处证明——无条目/无路由记录不复用。"""

    def _prepare(self, tmp: str, entry: dict | None) -> Path:
        out = Path(tmp)
        (out / "ai_requirements.jsonl").write_text("{}\n", encoding="utf-8")
        (out / "merged_spec_requirements.json").write_text("{}", encoding="utf-8")
        if entry is not None:
            (out / "run_manifest.json").write_text(
                json.dumps({"stages": {"ai-extract": entry}}), encoding="utf-8")
        return out

    def test_files_without_ledger_entry_not_reusable(self) -> None:
        from desktop_tasks import stage_is_reusable
        with tempfile.TemporaryDirectory() as tmp:
            out = self._prepare(tmp, None)
            self.assertFalse(stage_is_reusable(out, "ai-extract", route="openai_compatible"))

    def test_routeless_entry_not_reusable_when_route_required(self) -> None:
        """旧 stub 跑的条目无 route 字段——开 LLM 重跑不得复用 stub 空产物。"""
        from desktop_tasks import stage_is_reusable, stage_producer
        with tempfile.TemporaryDirectory() as tmp:
            out = self._prepare(tmp, {"status": "ok", "producer": stage_producer("ai-extract")})
            self.assertFalse(stage_is_reusable(out, "ai-extract", route="openai_compatible"))

    def test_route_matching_entry_without_fingerprint_not_reusable(self) -> None:
        """manifest v2（0710）：route 匹配但缺输入指纹 → 不复用（正向可达性由
        test_desktop_tasks 的 test_stub_request_can_reuse_valid_openai_ai_extract_output 覆盖）。"""
        from desktop_tasks import stage_is_reusable, stage_producer
        with tempfile.TemporaryDirectory() as tmp:
            out = self._prepare(tmp, {"status": "ok", "route": "openai_compatible",
                                      "producer": stage_producer("ai-extract")})
            self.assertFalse(stage_is_reusable(out, "ai-extract", route="openai_compatible"))


class HardwareEnrichGuardTests(unittest.TestCase):
    """2026-07-09 评审修正：硬件翻译富化路径同样过漂移护栏。"""

    def test_fabricated_code_in_translation_rejected(self) -> None:
        from requirements_analysis import _llm_enrich_hardware_item
        source = {"source_quote": "The valve shall close on tamper detection.",
                  "description": "", "requirement": "", "title": ""}
        item = {"ownership": "hardware"}
        fake_chat = lambda s, u: {"items": [{
            "hardware_translation": "阀门在检测到窃动时关闭（对象 0-0:96.3.10.255）",
            "ownership_reason": "机械部件"}]}
        ok, issues = _llm_enrich_hardware_item(item, source, fake_chat, {}, "m")
        self.assertFalse(ok)
        self.assertTrue(any("无据编码" in i for i in issues))
        self.assertNotIn("hardware_translation", item)

    def test_faithful_translation_accepted(self) -> None:
        from requirements_analysis import _llm_enrich_hardware_item
        source = {"source_quote": "The valve shall close within 30 seconds.",
                  "description": "", "requirement": "", "title": ""}
        item = {"ownership": "hardware"}
        fake_chat = lambda s, u: {"items": [{
            "hardware_translation": "阀门须在 30 秒内关闭", "ownership_reason": "机械部件"}]}
        ok, _ = _llm_enrich_hardware_item(item, source, fake_chat, {}, "m")
        self.assertTrue(ok)
        self.assertEqual(item.get("hardware_translation"), "阀门须在 30 秒内关闭")


class AnnotationTermsOverrideTests(unittest.TestCase):
    """2026-07-09 评审建议：视图层回退标记词表按语料可覆盖（内置默认按 UNI 调优）。"""

    def test_out_dir_override_wins(self) -> None:
        import doc_annotation_export as dae
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "annotation_terms.json").write_text(json.dumps({
                "hardware": ["pressure sensor housing"],
            }, ensure_ascii=False), encoding="utf-8")
            terms = dae._load_annotation_terms(out)
        self.assertEqual(terms["hardware"], ("pressure sensor housing",))
        # 缺键回落内置默认
        self.assertEqual(terms["software_term"], dae._UNANALYZED_TERM_DEFAULTS["software_term"])

    def test_no_override_uses_defaults(self) -> None:
        import doc_annotation_export as dae
        with tempfile.TemporaryDirectory() as tmp:
            terms = dae._load_annotation_terms(Path(tmp))
        self.assertEqual(terms, dict(dae._UNANALYZED_TERM_DEFAULTS))


class DesignOptionsGuardTests(unittest.TestCase):
    """C1（0710 评审）：design_options 纳入漂移扫描——非规范候选也不得带无据编码/数字。"""

    def test_design_options_codes_visible_to_drift(self) -> None:
        from ai_extract import code_drift
        req = {"title": "t", "description": "", "source_quote": "",
               "design_options": ["用对象 1-0:99.2.0.255 做镜像缓存"], "acceptance_criteria": []}
        drift = code_drift(req, "The meter shall store data.")
        self.assertIn("1-0:99.2.0.255", drift)

    def test_move_unsupported_scrubs_option_numbers_keeps_terms(self) -> None:
        from ai_extract import _move_unsupported_delivery_items
        req = {"acceptance_criteria": [], "dev_guidance": [],
               "design_options": ["容量建议 20000 条", "可用环形缓冲实现归档"]}
        ints, codes = _move_unsupported_delivery_items(req, "The meter shall archive data.")
        self.assertIn("20000", ints)
        self.assertEqual(req["design_options"], ["可用环形缓冲实现归档"])   # 实现词条保留=该字段用途
        self.assertIn("无依据数字", req.get("notes") or "")


class CatalogTitleGuardTests(unittest.TestCase):
    """C2（0710 评审）：catalog-LLM 自由文本标题直达交付描述列——漂移即弃用回退确定性。"""

    def _rows(self) -> list[dict]:
        return [{"ai_req_id": "AIR-1", "title": "事件记录", "module": "事件记录",
                 "description": "The meter shall record tamper events.",
                 "source_quote": "The meter shall record tamper events.",
                 "functional_key": "事件记录"}]

    def test_unsafe_title_dropped(self) -> None:
        from functional_catalog import _title_is_source_safe
        self.assertFalse(_title_is_source_safe("事件记录（对象 0-0:96.11.0.255）", self._rows()))
        self.assertFalse(_title_is_source_safe("事件记录容量 65535 条", self._rows()))

    def test_safe_title_adopted(self) -> None:
        from functional_catalog import _title_is_source_safe
        self.assertTrue(_title_is_source_safe("窃动事件记录功能", self._rows()))


class SynthesisRouteHonestyTests(unittest.TestCase):
    """C3/C5（0710 评审）：route 按实际 merge_method 判定；确定性侧守恒记账。"""

    def _write_inputs(self, out: Path) -> None:
        rows = [{"ai_req_id": "AIR-1", "title": "事件记录", "module": "事件记录",
                 "description": "The meter shall record tamper events.",
                 "source_quote": "The meter shall record tamper events.", "status": "draft"},
                {"ai_req_id": "AIR-2", "title": "时钟同步", "module": "时钟",
                 "description": "The meter shall sync clock daily.",
                 "source_quote": "The meter shall sync clock daily.", "status": "draft"}]
        (out / "ai_requirements.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    def test_route_downgrades_when_llm_never_used(self) -> None:
        from functional_synthesis import run_functional_synthesis
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._write_inputs(out)
            # 注入的 chat 全程失败 → 每个模块回退确定性 → route 不得号称 llm
            def broken_chat(system: str, user: str) -> dict:
                raise RuntimeError("boom")
            payload_summary = run_functional_synthesis(out, route="openai_compatible", chat=broken_chat)
            data = json.loads((out / "functional_requirements.json").read_text(encoding="utf-8"))
        self.assertNotIn("llm", str(payload_summary["route"]))
        self.assertEqual(data["route_requested"], "openai_compatible")
        self.assertIn("provenance", data)
        self.assertTrue(str(data["provenance"].get("generated_at") or ""))

    def test_conservation_clean_on_normal_run(self) -> None:
        from functional_synthesis import run_functional_synthesis
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._write_inputs(out)
            run_functional_synthesis(out, route="stub")
            data = json.loads((out / "functional_requirements.json").read_text(encoding="utf-8"))
        conservation = data.get("conservation") or {}
        self.assertEqual(conservation.get("missing_source_ids"), [])
        self.assertEqual(conservation.get("duplicate_assignments"), [])


class SynthesizedConsumerValidationTests(unittest.TestCase):
    """C4（0710 评审）：requirements_analysis 消费 functional_requirements.json 前校验血统。"""

    def test_bad_producer_falls_back_to_atoms(self) -> None:
        from requirements_analysis import run_requirements_analysis
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = [{"ai_req_id": f"AIR-{i}", "title": f"t{i}", "module": "计量",
                     "description": "The meter shall measure.", "source_quote": "The meter shall measure.",
                     "status": "draft"} for i in range(2)]
            (out / "ai_requirements.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            (out / "functional_requirements.json").write_text(json.dumps({
                "producer": "someone-else/v1",
                "items": [{"ai_req_id": "X-1", "title": "异源", "module": "计量",
                           "description": "d", "source_quote": "q"}],
            }, ensure_ascii=False), encoding="utf-8")
            result = run_requirements_analysis(out, route="stub")
        # producer 异常 → 回退逐原子输入（2 条),而非采信异源 1 条
        self.assertEqual(int(result.get("analysis_count") or 0), 2)


class SemanticGateDenominatorTests(unittest.TestCase):
    """C6（0710 评审）：语义门用例缺 functional_count 必须响亮失败（自引分母恒真）。"""

    def test_missing_functional_count_fails(self) -> None:
        from semantic_quality import _catalog_case
        case = {"name": "x", "requirements": [
            {"ai_req_id": "A", "title": "事件记录", "module": "事件记录",
             "description": "The meter shall record events.", "source_quote": "q"}],
            "expected": {}}
        failures = _catalog_case(case)[0]
        self.assertTrue(any("functional_count" in f for f in failures))


class SynthesisConflictToClarificationTests(unittest.TestCase):
    """C10（0710 评审）：合成冲突标记必须上澄清清单（内部核对必答）。"""

    def test_conflict_flags_become_internal_questions(self) -> None:
        from clarification_report import collect_questions, AUDIENCE_INTERNAL
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "functional_requirements.json").write_text(json.dumps({
                "producer": "functional-synthesis-v5",
                "items": [{"title": "归档周期", "functional_key": "归档",
                           "source_ai_requirement_ids": ["AIR-9"],
                           "conflict_flags": ["同一功能存在未限定的冲突参数 30/60 min"]}],
            }, ensure_ascii=False), encoding="utf-8")
            entries = collect_questions(out)
        hits = [e for e in entries if e["signal"] == "synthesis:conflict_flag"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["audience"], AUDIENCE_INTERNAL)
        self.assertIn("30/60 min", hits[0]["question"])


class QualityAuditFieldsTests(unittest.TestCase):
    """C0：quality report 带字符收支审计。"""

    def test_audit_block_present(self) -> None:
        from output_writer import build_quality_report
        blocks = [{"block_id": "B1", "text": "hello", "noise": False, "doc_region": "body",
                   "type": "paragraph"},
                  {"block_id": "N1", "text": "footer", "noise": True, "doc_region": "body",
                   "type": "paragraph"}]
        report = build_quality_report(blocks, [], [], [], pattern_shadow={})
        audit = report.get("audit") or {}
        self.assertEqual(audit.get("noise_blocks"), 1)
        self.assertIn("region_block_counts", audit)
        self.assertIn("noise_char_ratio", audit)


if __name__ == "__main__":
    unittest.main()


class NumberedScopeBodyStartTests(unittest.TestCase):
    """EN 16314：body 起点容忍条款号前缀——"1 Scope" 也是 body 起点,封面/目录标 front_matter。"""

    def test_numbered_scope_marks_front_matter(self) -> None:
        from atomize import mark_doc_regions
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "EUROPEAN STANDARD EN 16314", "section_path": []},
            {"block_id": "B2", "type": "paragraph", "text": "Contents Page", "section_path": []},
            {"block_id": "B3", "type": "heading", "text": "1 Scope", "section_path": ["1 Scope"]},
            {"block_id": "B4", "type": "paragraph", "text": "This standard specifies things.", "section_path": ["1 Scope"]},
        ]
        mark_doc_regions(blocks, [])
        self.assertEqual(blocks[0]["doc_region"], "front_matter")
        self.assertEqual(blocks[1]["doc_region"], "front_matter")
        self.assertEqual(blocks[2]["doc_region"], "body")
        self.assertEqual(blocks[3]["doc_region"], "body")

    def test_exact_scope_still_matches(self) -> None:
        from atomize import mark_doc_regions
        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "cover", "section_path": []},
            {"block_id": "B2", "type": "heading", "text": "Scope", "section_path": ["Scope"]},
            {"block_id": "B3", "type": "paragraph", "text": "body", "section_path": ["Scope"]},
        ]
        mark_doc_regions(blocks, [])
        self.assertEqual(blocks[0]["doc_region"], "front_matter")
        self.assertEqual(blocks[1]["doc_region"], "body")


class RuledTocTableVetoTests(unittest.TestCase):
    """EN 16314：pdfplumber 把印刷目录抽成画线"真表"——文本表守卫全不经过该路径。
    多数行含点引导线+页码 → 整表回流段落（C2：未验收的表不占 bbox,内容不蒸发）。"""

    def test_toc_matrix_skipped(self) -> None:
        from parsers.pdf_parser import _skip_table_matrix
        matrix = [
            ["", "Foreword ................................................ 4"],
            ["1", "Scope ................................................... 6"],
            ["2", "Normative references .................................... 6"],
            ["3.1", "Terms and definitions ................................. 8"],
        ]
        self.assertTrue(_skip_table_matrix(matrix))

    def test_real_table_kept(self) -> None:
        from parsers.pdf_parser import _skip_table_matrix
        matrix = [
            ["Symbol", "Description", "Unit"],
            ["Qmax", "Maximum flow rate", "m3/h"],
            ["Pmax", "Maximum working pressure", "mbar"],
        ]
        self.assertFalse(_skip_table_matrix(matrix))

    def test_minor_leader_rows_do_not_veto(self) -> None:
        from parsers.pdf_parser import _skip_table_matrix
        matrix = [
            ["Item", "Value ......... 3"],
            ["Qmax", "10"],
            ["Pmax", "500"],
        ]
        self.assertFalse(_skip_table_matrix(matrix))


class ExtractRegionExclusionTests(unittest.TestCase):
    """EN 16314：B 轨抽取不吃封面/目录区块——目录条目不再变成空壳需求(11 条挂封面)。"""

    def test_front_matter_and_toc_excluded_body_kept(self) -> None:
        from extract_units import body_blocks
        blocks = [
            {"block_id": "B1", "text": "cover", "doc_region": "front_matter"},
            {"block_id": "B2", "text": "toc", "doc_region": "table_of_contents"},
            {"block_id": "B3", "text": "intro", "doc_region": "introduction"},
            {"block_id": "B4", "text": "body", "doc_region": "body"},
            {"block_id": "B5", "text": "legacy no region"},
        ]
        kept = [b["block_id"] for b in body_blocks(blocks)]
        self.assertEqual(kept, ["B3", "B4", "B5"])
