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

    def test_template_codes_in_guidance_allowed(self) -> None:
        """模板注入的公司做法进 guidance 是设计意图——基线含 template_text 不误杀。"""
        from requirements_analysis_agent import validate_llm_item
        item = {"requirement": "Record events.",
                "developer_guidance": ["公司通用做法：事件对象 0-0:96.11.0.255，宏 EVT_STD"]}
        template = "模板说明：标准事件对象 0-0:96.11.0.255 宏 EVT_STD"
        issues = validate_llm_item(item, self._source(), template_text=template)
        self.assertFalse(any("guidance" in i for i in issues))

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
