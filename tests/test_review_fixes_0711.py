"""2026-07-11 评审修复回归测试。

覆盖本轮评审发现的 12 项问题：
- P0 #1 conflict-count 恒 0（requirement_schema 读者认双标记串）
- P0 #2 open_questions 漂移盲区（requirements_analysis_agent）
- P1 #3 catalog_key 不查（functional_catalog）
- P1 #4 PDF 单元格容差外丢弃（pdf_parser._assemble_rows 兜底）
- P1 #5 PDF 行级误并需求（pdf_parser._starts_new_paragraph 需求标志词护栏）
- P2 #7 Retry-After 无上限（llm_client._retry_delay 封顶 60）
- P2 #8 llm_trace 全文落盘（llm_client._truncate_for_trace）
- P2 #9 run_manifest 非原子写（desktop_tasks._atomic_write_json）
- P2 #10 守恒上浮顶层（functional_synthesis）
- P2 #11 MODULE_TO_SHEET 漂移检查（template_writer.module_mapping_drift）
- P2 #12 CJK 短词假朋友（requirements_analysis_rules）
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


# --- P0 #1: conflict-count 恒 0 -------------------------------------------------

class ConflictCountReaderTests(unittest.TestCase):
    def _doc(self, notes: str) -> dict:
        import requirement_schema as rs
        reqs = [{"id": "REQ-001", "type": "functional", "priority": "P1", "labels": ["安全"],
                 "source_section": "s", "notes": notes}]
        return rs.make_doc(reqs, source="x", extracted_at="t")

    def test_ai_extract_drift_note_now_counts_as_conflict(self) -> None:
        """AI 抽取主路径写「结构漂移已拦截（编码…）」——旧读者只认「编码漂移」→ 恒漏。"""
        doc = self._doc("结构漂移已拦截（编码，原文未见）：0-0:96.1.7")
        self.assertEqual(len(doc["analysis"]["conflicts"]), 1)
        self.assertIn("1", doc["analysis"]["coverage_report"][-3:] + doc["analysis"]["coverage_report"])

    def test_behavior_spec_drift_note_still_counts(self) -> None:
        """behavior-spec 路径写「编码漂移（已标记待核…）」——不能因修了 AI 路径而回退。"""
        doc = self._doc("编码漂移（已标记待核，文本保留）：0-0:96.1.7")
        self.assertEqual(len(doc["analysis"]["conflicts"]), 1)

    def test_clean_note_not_counted(self) -> None:
        doc = self._doc("普通 note，无漂移")
        self.assertEqual(len(doc["analysis"]["conflicts"]), 0)


# --- P0 #2: open_questions 漂移盲区 ----------------------------------------------

class OpenQuestionsDriftScanTests(unittest.TestCase):
    def test_fabricated_obis_in_open_questions_is_caught(self) -> None:
        """open_questions 是 LLM 可写、直达 Excel「待确认」列——编造 OBIS 必须被扫到。"""
        from requirements_analysis_agent import validate_llm_item
        source = {"source_quote": "见 0-0:96.1.0", "description": "", "requirement": ""}
        item = {"open_questions": ["这个 0-0:96.1.7 是否适用？"],  # 96.1.7 不在源文
                "software_requirement_text": "", "hardware_dependency": "",
                "ownership_reason": "", "developer_guidance": [], "design_options": [],
                "acceptance_criteria": [], "assumptions": []}
        issues = validate_llm_item(item, source)
        self.assertTrue(any("fabricated code" in i for i in issues),
                        f"open_questions 里的伪造 OBIS 应被检出，实际 issues={issues}")


# --- P1 #3: catalog_key 不查 ----------------------------------------------------

class CatalogKeyGuardTests(unittest.TestCase):
    """catalog_key 守卫复用 _title_is_source_safe（P1 #3 修复的本质）。

    直接测守卫函数对 catalog_key 的判定，避免 LLM 分组路径的 exactly-once 复杂前置。
    """
    def test_fabricated_code_in_catalog_key_rejected(self) -> None:
        """catalog_key 含组内源文没有的码 → 守卫应返回 False（functional_key 不采用）。"""
        from functional_catalog import _title_is_source_safe
        group = [{"title": "安全关联", "description": "OBIS 0-0:96.1.0", "source_quote": "...",
                  "functional_key": "安全:安全关联"}]
        self.assertFalse(_title_is_source_safe("事件 0-0:96.99.9 管理", group))

    def test_clean_catalog_key_accepted(self) -> None:
        from functional_catalog import _title_is_source_safe
        group = [{"title": "安全关联", "description": "建立 HLS 关联", "source_quote": "...",
                  "functional_key": "安全:安全关联"}]
        self.assertTrue(_title_is_source_safe("安全-关联管理", group))


# --- P1 #4: PDF 单元格容差外不丢 -------------------------------------------------

class PdfCellFallbackTests(unittest.TestCase):
    def test_cell_outside_tolerance_is_not_dropped(self) -> None:
        """偏移单元格成为单例锚点后，经过稀疏列校验仍不得丢失。"""
        from parsers.pdf_parser import _assemble_rows, _validate_text_table
        columns = [100.0, 200.0, 300.0, 999.0]
        region = [
            {"cells": [{"x0": 100.0, "text": "A"}, {"x0": 200.0, "text": "B"},
                       {"x0": 300.0, "text": "C"}]},
            {"cells": [{"x0": 100.0, "text": "D"}, {"x0": 200.0, "text": "E"},
                       {"x0": 300.0, "text": "F"},
                       {"x0": 999.0, "text": "0-0:96.1.0"}]},
            {"cells": [{"x0": 100.0, "text": "G"}, {"x0": 200.0, "text": "H"},
                       {"x0": 300.0, "text": "I"}]},
        ]
        rows = _assemble_rows(region, columns)
        validated = _validate_text_table(rows, region_lines=3, page_candidate_lines=3)
        self.assertIsNotNone(validated)
        all_text = " ".join(" ".join(r) for r in validated or [])
        self.assertIn("0-0:96.1.0", all_text, "容差外的单元格不应被丢弃")


# --- P1 #5: PDF 行级误并需求 ----------------------------------------------------

class PdfLineMergeGuardTests(unittest.TestCase):
    def _doc_profile(self):
        from parsers.pdf_parser import DocumentProfile
        return DocumentProfile()

    def test_two_requirement_lines_not_merged(self) -> None:
        """两行都含 shall 标志词 → 即使前行无句终标点 + 下行小写开头，也判为新段。"""
        from parsers.pdf_parser import _starts_new_paragraph
        prev = {"text": "the meter shall support the following", "top": 100.0, "bottom": 112.0}
        line = {"text": "read access shall be granted to PC", "top": 126.0, "bottom": 138.0}
        self.assertTrue(_starts_new_paragraph(prev, line, page_height=800.0,
                                              document_profile=self._doc_profile()))

    def test_genuine_continuation_still_merged(self) -> None:
        """单行需求 + 其续行（下行无 shall）仍并入同段（不破坏续行豁免）。"""
        from parsers.pdf_parser import _starts_new_paragraph
        prev = {"text": "the meter shall support the", "top": 100.0, "bottom": 112.0}
        line = {"text": "following access rights", "top": 126.0, "bottom": 138.0}
        self.assertFalse(_starts_new_paragraph(prev, line, page_height=800.0,
                                               document_profile=self._doc_profile()))


# --- P2 #7: Retry-After 封顶 ----------------------------------------------------

class RetryAfterCapTests(unittest.TestCase):
    def test_huge_retry_after_capped_at_60(self) -> None:
        from llm_client import _retry_delay
        self.assertLessEqual(_retry_delay(5, "3600"), 60.0)

    def test_small_retry_after_respected(self) -> None:
        from llm_client import _retry_delay
        self.assertAlmostEqual(_retry_delay(5, "5"), 5.0)

    def test_no_retry_after_uses_exponential(self) -> None:
        from llm_client import _retry_delay
        self.assertEqual(_retry_delay(3, None), 8.0)  # 2**3


# --- P2 #8: trace 截断 ----------------------------------------------------------

class TraceTruncationTests(unittest.TestCase):
    def test_long_content_truncated(self) -> None:
        from llm_client import _truncate_for_trace
        long = "x" * 5000
        out = _truncate_for_trace([{"role": "user", "content": long}])
        self.assertLess(len(out[0]["content"]), 2200)  # 2000 + 截断标记
        self.assertIn("truncated", out[0]["content"])

    def test_role_and_usage_preserved(self) -> None:
        from llm_client import _truncate_for_trace
        out = _truncate_for_trace([{"role": "user", "content": "short"}])
        self.assertEqual(out[0]["role"], "user")

    def test_nested_response_content_truncated(self) -> None:
        from llm_client import _truncate_for_trace
        value = {"choices": [{"message": {
            "content": "x" * 5000,
            "reasoning_content": "r" * 5000,
        }}]}
        out = _truncate_for_trace(value)
        message = out["choices"][0]["message"]
        self.assertLess(len(message["content"]), 2200)
        self.assertLess(len(message["reasoning_content"]), 2200)
        self.assertIn("truncated", message["content"])
        self.assertIn("truncated", message["reasoning_content"])

    def test_full_mode_when_env_set(self) -> None:
        from llm_client import _truncate_for_trace
        long = "x" * 5000
        with mock.patch.dict(os.environ, {"RATOMIZER_LLM_TRACE_FULL": "1"}):
            out = _truncate_for_trace(long)
        self.assertEqual(out, long)


# --- P2 #9: 原子写 run_manifest --------------------------------------------------

class AtomicManifestWriteTests(unittest.TestCase):
    def test_manifest_written_atomically(self) -> None:
        from desktop_tasks import update_run_manifest, RUN_MANIFEST
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            update_run_manifest(out_dir, "test_stage", "ok", route="stub", outputs=[])
            manifest = out_dir / RUN_MANIFEST
            self.assertTrue(manifest.exists())
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["stages"]["test_stage"]["status"], "ok")
            # 崩溃测试：写一个坏 JSON 再写，update_run_manifest 应能覆盖恢复（读时吞 JSONDecodeError）
            manifest.write_text("{broken", encoding="utf-8")
            update_run_manifest(out_dir, "test_stage", "ok", route="stub", outputs=[])
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["stages"]["test_stage"]["status"], "ok")


# --- P2 #10: 守恒上浮顶层 --------------------------------------------------------

class ConservationSurfaceTests(unittest.TestCase):
    def test_conservation_in_top_level_result(self) -> None:
        """run_functional_synthesis 返回值应带 conservation 摘要（ok/missing/duplicates）。"""
        from functional_synthesis import run_functional_synthesis
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            (out_dir / "ai_requirements.jsonl").write_text(
                json.dumps({"title": "t", "source_quote": "q", "source_section": "s",
                            "module": "安全", "description": "d", "source_block_ids": ["B1"]},
                           ensure_ascii=False) + "\n", encoding="utf-8")
            result = run_functional_synthesis(out_dir, route="stub")
        self.assertIn("conservation", result)
        self.assertIn("ok", result["conservation"])
        self.assertTrue(result["conservation"]["ok"], f"干净跑应守恒，实际={result['conservation']}")


# --- P2 #11: MODULE_TO_SHEET 漂移检查 -------------------------------------------

class ModuleMappingDriftTests(unittest.TestCase):
    def test_drift_check_returns_lists(self) -> None:
        from template_writer import module_mapping_drift
        unmapped, extra = module_mapping_drift()
        self.assertIsInstance(unmapped, list)
        self.assertIsInstance(extra, list)


# --- P2 #12: CJK 短词假朋友 ------------------------------------------------------

class CjkFalseFriendTests(unittest.TestCase):
    def test_clock_in_hardware_part_context_not_software(self) -> None:
        """「时钟计数器型号」含短词"时钟"，但上下文是硬件件描述→不应判软件信号。"""
        from requirements_analysis_rules import classify_ownership
        # 仅含硬件上下文里的短 CJK 词
        req = {"title": "时钟计数器型号", "description": "", "requirement": "",
               "module": "", "source_quote": "", "labels": []}
        result = classify_ownership(req)
        # 不应因"时钟"命中而给 software + rule（应走默认 software 但 source=default，或命中硬件词）
        # 关键断言：假朋友护栏生效 → ownership_source 不是 "rule" 命中 software_term
        # 若同时有硬件词则判 hardware；这里无硬件词，应走默认（source=rule, reason=No...matched）
        self.assertNotIn("时钟", result.get("ownership_reason", ""))

    def test_real_clock_domain_still_software(self) -> None:
        """真正的时钟功能需求（无硬件上下文）仍正常判 software。"""
        from requirements_analysis_rules import classify_ownership
        req = {"title": "时钟同步", "description": "meter shall sync clock", "requirement": "",
               "module": "时钟", "source_quote": "", "labels": []}
        result = classify_ownership(req)
        self.assertEqual(result["ownership"], "software")


if __name__ == "__main__":
    unittest.main()
