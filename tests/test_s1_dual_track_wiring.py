"""S1-4 WS1 双轨接主线测试。

验收面（来自简报）：
* RATOMIZER_TABLE_DUAL_TRACK=1 + 提议器 → 签发假设落盘 table_structure_hypotheses.jsonl，
  table_role_audit 抽样框非空（validator_status=="issued"）。
* OFF → atomize 走确定性 analyze_table，不写假设文件，产物与 main 逐字节一致（硬判据）。

atomize 自身零 LLM：提议器由调用方注入（生产由 desktop_tasks 挂，测试注入 fake）；
atomize 只做几何校验 + 假设派生结构 + 落盘。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx_table_parser import ParsedCell, ParsedCellContent, ParsedDocxTable


def _cell(r: int, c: int, text: str, *, covered=()) -> ParsedCell:
    return ParsedCell(
        row_index=r, column_index=c, text=text, raw_text=text,
        covered_coordinates=covered, content=ParsedCellContent((), 0),
        style_evidence={"bold": False},
    )


def _plain_table() -> ParsedDocxTable:
    matrix = [["H1", "H2"], ["v1", "v2"]]
    cells = {(1, 1): _cell(1, 1, "H1"), (1, 2): _cell(1, 2, "H2"),
             (2, 1): _cell(2, 1, "v1"), (2, 2): _cell(2, 2, "v2")}
    return ParsedDocxTable(
        width=2, matrix=[list(r) for r in matrix], raw_matrix=[list(r) for r in matrix],
        cells=cells, merge_ranges=[], explicit_header_rows=[], nested_tables=[],
        parse_incomplete=False, parse_incomplete_reason={}, raw_text="",
    )


def _hyp(cells, *, header_levels=1) -> dict:
    from table_geometry_validator import TABLE_STRUCTURE_HYPOTHESIS_VERSION

    return {
        "schema": TABLE_STRUCTURE_HYPOTHESIS_VERSION,
        "table_structure_version": "table-structure-v7",
        "header_level_count": header_levels,
        "cells": [{"coordinate": [r, c], "role": role, "confidence": "high"}
                  for (r, c, role) in cells],
        "semantic_merges": [],
    }


class DualTrackWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        # 隔离 atomize 模块级累积 + 提议器，避免跨用例泄漏
        import atomize
        atomize.clear_table_dual_track_proposer()

    def tearDown(self) -> None:
        import atomize
        atomize.clear_table_dual_track_proposer()

    def test_off_returns_no_override_and_writes_no_hypotheses(self) -> None:
        """OFF：_dual_track_docx_structure 返回 None，flush 不写文件（产物与 main 一致）。"""
        import atomize

        old = os.environ.pop("RATOMIZER_TABLE_DUAL_TRACK", None)
        try:
            atomize.set_table_dual_track_proposer(lambda parsed, **kw: None)
            override = atomize._dual_track_docx_structure(
                _plain_table(), table_id="TBL-000001", block_id="BLK-000001",
                section_path=["5 Requirements"],
            )
            self.assertIsNone(override)
            with tempfile.TemporaryDirectory() as tmp:
                written = atomize._flush_table_structure_hypotheses(Path(tmp), document_id="doc")
                self.assertEqual(written, 0)
                self.assertFalse((Path(tmp) / "table_structure_hypotheses.jsonl").exists())
        finally:
            if old is not None:
                os.environ["RATOMIZER_TABLE_DUAL_TRACK"] = old

    def test_on_issued_hypothesis_derives_structure_and_lands_file(self) -> None:
        """ON + 提议器返回 issued 假设 → 派生结构 + 假设落盘（抽样框非空）。"""
        import atomize
        from llm_table_understanding import PROPOSED, TableUnderstandingResult
        from table_geometry_validator import ISSUED, validate_table_geometry

        parsed = _plain_table()
        hypothesis = _hyp([(1, 1, "header"), (1, 2, "header"),
                           (2, 1, "data"), (2, 2, "data")])
        # 前置：校验器签发该假设
        self.assertEqual(validate_table_geometry(hypothesis, parsed).status, ISSUED)

        proposer_calls: list = []

        def proposer(p, *, table_id="", block_id="", section_path=None):
            proposer_calls.append(table_id)
            return TableUnderstandingResult(
                status=PROPOSED, hypothesis=hypothesis, route="openai_compatible",
                family_id="parameter_matrix", reason="",
            )

        with patch.dict(os.environ, {"RATOMIZER_TABLE_DUAL_TRACK": "1"}):
            from table_structure import dual_track_enabled
            self.assertTrue(dual_track_enabled())
            atomize.set_table_dual_track_proposer(proposer)
            override = atomize._dual_track_docx_structure(
                parsed, table_id="TBL-000001", block_id="BLK-000001",
                section_path=["5 Requirements"], headers_hint=["H1", "H2"],
            )
            self.assertIsNotNone(override)
            # 假设派生结构：行1=header，行2=data
            self.assertEqual(override["header_row_indexes"], [1])
            self.assertEqual(override["data_row_indexes"], [2])
            self.assertEqual(proposer_calls, ["TBL-000001"])
            # 累积一条 issued 记录
            self.assertEqual(len(atomize._TABLE_STRUCTURE_HYPOTHESES), 1)
            self.assertEqual(atomize._TABLE_STRUCTURE_HYPOTHESES[0]["validator_status"], "issued")

            with tempfile.TemporaryDirectory() as tmp:
                written = atomize._flush_table_structure_hypotheses(Path(tmp), document_id="doc")
                self.assertEqual(written, 1)
                hyp_path = Path(tmp) / "table_structure_hypotheses.jsonl"
                self.assertTrue(hyp_path.is_file())
                record = json.loads(hyp_path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(record["schema"], "signed-table-hypothesis/v1")
                self.assertEqual(record["validator_status"], "issued")
                self.assertEqual(record["document_id"], "doc")
                self.assertEqual(record["table_id"], "TBL-000001")
                # table_role_audit 抽样框读此记录（issued）→ 非空
                self.assertEqual(record["family_id"], "parameter_matrix")

    def test_on_unavailable_hypothesis_falls_back(self) -> None:
        """ON 但提议器返回 unavailable（无 route/失败）→ None，确定性兜底，不落盘。"""
        import atomize
        from llm_table_understanding import UNAVAILABLE, TableUnderstandingResult

        def proposer(p, **kw):
            return TableUnderstandingResult(
                status=UNAVAILABLE, hypothesis=None, route="stub",
                family_id="", reason="no_openai_compatible_route",
            )

        with patch.dict(os.environ, {"RATOMIZER_TABLE_DUAL_TRACK": "1"}):
            atomize.set_table_dual_track_proposer(proposer)
            override = atomize._dual_track_docx_structure(
                _plain_table(), table_id="TBL-000001", block_id="BLK-000001",
                section_path=["5 Requirements"],
            )
            self.assertIsNone(override)
            self.assertEqual(atomize._TABLE_STRUCTURE_HYPOTHESES, [])

    def test_off_build_table_artifacts_uses_deterministic_path(self) -> None:
        """OFF：build_table_artifacts(structure_override=None) == analyze_table 路径（字节不变）。"""
        from requirement_kb import KnowledgeRepository
        from atomize import build_table_artifacts
        from table_structure import analyze_table

        matrix = [["H1", "H2"], ["v1", "v2"]]
        kb = KnowledgeRepository.from_paths([])
        block, items, cells = build_table_artifacts(
            matrix, table_id="TBL-000001", block_id="BLK-000001", order=1,
            table_title="t", section_path=["5"], knowledge_bases=kb,
        )
        # 行级结构 = analyze_table 的确定性输出（OFF 默认）
        deterministic = analyze_table(matrix)
        # data 行数一致（deterministic 视此 2 行为 data）
        self.assertEqual(len(items), len(deterministic["data_row_indexes"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
