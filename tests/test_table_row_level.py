"""Phase 2 表格行级化测试（docs/table-granularity-plan.md）。

封堵一:chunk 表头重复 + 行级溯源
封堵二:参数表去重(llm_narrative/merge_trace)
封堵三:澄清按表块聚合(row_details)
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_extract import classify_table_kind
from atomize import render_table_text
from extract_units import assemble_sections, merge_sections


def _big_param_block(*, rows: int = 40, block_id: str = "BLK-BIG") -> dict:
    headers = ["No.", "Parameter", "Value", "Unit"]
    data_rows = [
        [f"{i}.", f"Parameter number {i} description", f"{100 + i}", "V"]
        for i in range(1, rows + 1)
    ]
    return {
        "block_id": block_id,
        "type": "table",
        "headers": headers,
        "data_rows": data_rows,
        "text": render_table_text(headers, data_rows),
        "section_path": ["5. Technical Requirements", "5.1 Parameters"],
        "requirement_like": True,
        "noise": False,
    }


def _terms_block() -> dict:
    return {
        "block_id": "BLK-T",
        "type": "table",
        "headers": ["No.", "Term", "Definition"],
        "data_rows": [
            ["1.", "Firmware", "Software that processes information."],
            ["2.", "Data", "Information from measuring instruments."],
            ["3.", "Unit", "A thing being measured."],
        ],
        "text": "No. | Term | Definition\n1. | Firmware | Software\n2. | Data | Info\n3. | Unit | Thing",
        "section_path": ["3. Terms and Definitions"],
        "requirement_like": True,
        "noise": False,
    }


class HeaderRepeatTests(unittest.TestCase):
    """封堵一-A:超大参数表切多 chunk 时,每个 chunk 首行注入表头渲染行。"""

    def test_assemble_records_parameter_table_header_line(self) -> None:
        block = _big_param_block(rows=3)
        sections = assemble_sections([block])
        self.assertEqual(len(sections), 1)
        self.assertEqual(
            sections[0]["_table_header_lines"],
            ["No. | Parameter | Value | Unit"],
        )

    def test_non_parameter_table_records_no_header_line(self) -> None:
        # 术语表(definition)非 parameter → 不记表头(不会触发切分注入)
        sections = assemble_sections([_terms_block()])
        self.assertEqual(sections[0]["_table_header_lines"], [])

    def test_oversize_table_chunks_each_contain_header(self) -> None:
        block = _big_param_block(rows=60)  # 足够大,必被切多 chunk
        sections = assemble_sections([block])
        units = merge_sections(sections, target_chars=400, unit_mode="clause")
        self.assertGreaterEqual(len(units), 2, "大参数表应被切分成多个 chunk")
        header = "No. | Parameter | Value | Unit"
        for unit in units:
            # 每个 chunk 文本都必须含表头行(LLM 上下文:不能有无列名的裸数据)
            self.assertIn(header, unit["text"], "chunk 缺表头上下文")

    def test_oversize_table_second_chunk_starts_with_header(self) -> None:
        block = _big_param_block(rows=60)
        sections = assemble_sections([block])
        units = merge_sections(sections, target_chars=400, unit_mode="clause")
        header = "No. | Parameter | Value | Unit"
        # 第 2 个及之后的 chunk 首行必须是表头(第 1 chunk 含原始表头/标题)
        for unit in units[1:]:
            first_line = unit["text"].split("\n", 1)[0]
            self.assertEqual(
                first_line, header,
                f"非首 chunk 应以表头行开头,实得: {first_line!r}",
            )

    def test_small_table_not_split_keeps_single_unit(self) -> None:
        block = _big_param_block(rows=3)
        sections = assemble_sections([block])
        units = merge_sections(sections, target_chars=4000, unit_mode="clause")
        self.assertEqual(len(units), 1)


class RowSourceTraceTests(unittest.TestCase):
    """封堵一-B:行级溯源(source_row_index/source_item_id)。"""

    def test_parameter_table_source_block_has_rows(self) -> None:
        from ai_extract import _row_render_line

        block = _big_param_block(rows=3)
        sections = assemble_sections([block])
        sb = sections[0]["source_blocks"][0]
        self.assertEqual(sb["block_id"], "BLK-BIG")
        rows = sb.get("rows")
        self.assertIsNotNone(rows, "parameter 表 source_block 应带行级明细 rows")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["row_index"], 1)
        self.assertTrue(rows[0]["item_id"].endswith("-R000001"))
        # 表头行不在 rows(只数据行;表头不产 source_block)
        self.assertNotIn("No. | Parameter", [r["text"] for r in rows])

    def test_map_source_annotates_row_index(self) -> None:
        from ai_extract import _map_requirement_source, _row_render_line

        block = _big_param_block(rows=3)
        section = assemble_sections([block])[0]
        # 引句 = 第 2 行渲染(逐字)
        quote = _row_render_line(block["headers"], block["data_rows"][1])
        req = {"source_quote": quote, "source_section": "5.1 Parameters"}
        _map_requirement_source(req, section)
        self.assertEqual(req["source_block_ids"], ["BLK-BIG"])
        self.assertEqual(req.get("source_row_index"), 2)
        self.assertEqual(req.get("source_item_id"), "BLK-BIG-R000002")

    def test_map_source_no_row_index_for_paragraph(self) -> None:
        from ai_extract import _map_requirement_source

        para_block = {
            "block_id": "BLK-P",
            "type": "paragraph",
            "text": "The meter shall operate at 230 V nominal.",
            "section_path": ["5. Technical Requirements"],
        }
        section = assemble_sections([para_block])[0]
        req = {"source_quote": "The meter shall operate at 230 V nominal.", "source_section": "5"}
        _map_requirement_source(req, section)
        self.assertNotIn("source_row_index", req)
        self.assertNotIn("source_item_id", req)


class RowDedupTests(unittest.TestCase):
    """封堵二:参数表 LLM 叙述需求并入同行确定性展开行(llm_narrative/merge_trace)。"""

    def test_llm_overlapping_row_merged_into_prow(self) -> None:
        from ai_extract import _merge_llm_into_deterministic_rows

        prow = {
            "ai_req_id": "PROW-DET-BLK-1-R0001",
            "source_quote": "1. | Rated voltage | 230 | V",
            "description": "1. | Rated voltage | 230 | V",
            "source_block_ids": ["BLK-1"],
        }
        llm_req = {
            "ai_req_id": "AIR-9",
            "source_quote": "1. | Rated voltage | 230 | V",  # 同行渲染
            "description": "The meter shall support rated voltage of 230 V.",
            "source_block_ids": ["BLK-1"],
        }
        result = _merge_llm_into_deterministic_rows([prow, llm_req])
        ids = [r.get("ai_req_id") for r in result]
        self.assertIn("PROW-DET-BLK-1-R0001", ids)
        self.assertNotIn("AIR-9", ids)  # LLM 并入,不独立成行
        prow_out = next(r for r in result if r["ai_req_id"] == "PROW-DET-BLK-1-R0001")
        self.assertEqual(
            prow_out.get("llm_narrative"),
            "The meter shall support rated voltage of 230 V.",
        )
        trace = prow_out.get("merge_trace") or []
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["llm_requirement_id"], "AIR-9")
        self.assertEqual(trace[0]["merged_into"], "PROW-DET-BLK-1-R0001")

    def test_llm_non_overlapping_kept(self) -> None:
        from ai_extract import _merge_llm_into_deterministic_rows

        prow = {
            "ai_req_id": "PROW-DET-BLK-1-R0001",
            "source_quote": "1. | Rated voltage | 230 | V",
            "source_block_ids": ["BLK-1"],
        }
        llm_req = {
            "ai_req_id": "AIR-9",
            "source_quote": "The enclosure shall provide IP54 protection.",  # 不命中任何行
            "description": "Enclosure protection requirement.",
            "source_block_ids": ["BLK-1"],
        }
        result = _merge_llm_into_deterministic_rows([prow, llm_req])
        ids = [r.get("ai_req_id") for r in result]
        self.assertIn("AIR-9", ids)  # 未命中 → 保留
        self.assertEqual(len(result), 2)

    def test_no_prow_returns_unchanged(self) -> None:
        from ai_extract import _merge_llm_into_deterministic_rows

        llm_req = {"ai_req_id": "AIR-1", "source_quote": "x" * 30, "source_block_ids": ["BLK-1"]}
        result = _merge_llm_into_deterministic_rows([llm_req])
        self.assertEqual(result, [llm_req])

    def test_short_row_fallback_exact_match(self) -> None:
        from ai_extract import _merge_llm_into_deterministic_rows

        # 短行渲染(compact <12):行渲染 == LLM 引句 compact → 命中(边界补充2)
        prow = {
            "ai_req_id": "PROW-DET-BLK-1-R0001",
            "source_quote": "a | b | c",
            "source_block_ids": ["BLK-1"],
        }
        llm_req = {
            "ai_req_id": "AIR-9",
            "source_quote": "a | b | c",  # 精确相等
            "description": "short row",
            "source_block_ids": ["BLK-1"],
        }
        result = _merge_llm_into_deterministic_rows([prow, llm_req])
        self.assertNotIn("AIR-9", [r.get("ai_req_id") for r in result])


class ClarificationAggregationTests(unittest.TestCase):
    """封堵三:PROW-DET 行级 suspicion 按表块聚合(row_details);LLM suspicion 逐条。"""

    @staticmethod
    def _prow(rid: str, block: str, quote: str, row_index: int | None = None) -> dict:
        return {
            "ai_req_id": rid,
            "source_quote": quote,
            "title": quote[:20],
            "source_block_ids": [block],
            "source_section": "5.1 Parameters",
            "source_mapping": "deterministic_fallback",
            "suspicion_reasons": ["参数表行确定性展开"],
            "source_row_index": row_index,
        }

    @staticmethod
    def _collect(reqs: list[dict]) -> list[dict]:
        from clarification_report import collect_questions

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ai_requirements.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in reqs) + "\n",
                encoding="utf-8",
            )
            return collect_questions(Path(tmp))

    def test_same_table_rows_aggregate_into_one(self) -> None:
        reqs = [
            self._prow(f"PROW-DET-BLK-1-R{i:04d}", "BLK-1", f"row line number {i} content here", i)
            for i in range(1, 4)
        ]
        questions = self._collect(reqs)
        self.assertEqual(len(questions), 1, "同表块 3 行应聚合为 1 条汇总")
        self.assertIn("3 行待核", questions[0]["question"])
        details = questions[0].get("row_details") or []
        self.assertEqual(len(details), 3)

    def test_different_tables_aggregate_separately(self) -> None:
        reqs = [
            self._prow("PROW-DET-BLK-1-R0001", "BLK-1", "row one long enough content", 1),
            self._prow("PROW-DET-BLK-2-R0001", "BLK-2", "row two long enough content", 1),
        ]
        questions = self._collect(reqs)
        self.assertEqual(len(questions), 2)

    def test_llm_suspicion_not_aggregated(self) -> None:
        llm_req = {
            "ai_req_id": "AIR-1",
            "source_quote": "The meter shall provide IP54 protection.",
            "title": "IP54",
            "source_block_ids": ["BLK-9"],
            "source_section": "5.2 Enclosure",
            "suspicion_reasons": ["编码漂移"],
        }
        questions = self._collect([llm_req])
        # LLM suspicion 逐条(非 deterministic_fallback → 不聚合,无 row_details)
        self.assertEqual(len(questions), 1)
        self.assertNotIn("row_details", questions[0].get("evidence", {}))


if __name__ == "__main__":
    unittest.main()
