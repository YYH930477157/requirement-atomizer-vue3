from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import jsonschema

import full_translation as ft
from ai_extract import _row_render_line as shared_row_render_line
from api_server import ANNOTATION_TRANSLATION_GUARDS_VERSION, translation_key
from atomize import build_table_artifacts
from doc_annotation_export import _active_translation_strategy_version
from requirement_kb import KnowledgeRepository
from result_package import initialize_result_package, resolve_analysis_root


SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "document_translation.schema.json")
    .read_text(encoding="utf-8")
)
KB = KnowledgeRepository.from_paths([])


class _TableMarkupParser(HTMLParser):
    """DOM 级解析双语表 HTML：行（含 thead/tbody 归属、class、单元格属性与文本）+ 题注。

    只为网格不变量断言服务——子串断言看不见 rowspan 吞掉译文行格槽这类结构错位。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[dict]] = []
        self.figcaptions: list[str] = []
        self._table: list[dict] | None = None
        self._section = ""
        self._row: dict | None = None
        self._cell: dict | None = None
        self._caption: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._table = []
        elif tag in ("thead", "tbody"):
            self._section = tag
        elif tag == "figcaption":
            self._caption = []
        elif tag == "tr" and self._table is not None:
            self._row = {"section": self._section, "attrs": dict(attrs), "cells": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"tag": tag, "attrs": dict(attrs), "text": []}

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            self._row["cells"].append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._table.append({
                "section": self._row["section"],
                "attrs": self._row["attrs"],
                "cells": [
                    {
                        "tag": cell["tag"],
                        "attrs": cell["attrs"],
                        "text": "".join(cell["text"]),
                    }
                    for cell in self._row["cells"]
                ],
            })
            self._row = None
        elif tag in ("thead", "tbody"):
            self._section = ""
        elif tag == "figcaption" and self._caption is not None:
            self.figcaptions.append("".join(self._caption))
            self._caption = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
        elif self._caption is not None:
            self._caption.append(data)


class FullTranslationTests(unittest.TestCase):
    def _write_inputs(self, root: Path) -> None:
        rows = [
            {"block_id": "BLK-1", "block_type": "paragraph", "text": "CLASS 1) meters shall comply."},
            {"block_id": "BLK-2", "block_type": "paragraph", "text": "CLASS 1) meters shall comply."},
            {"block_id": "BLK-3", "block_type": "image", "text": ""},
        ]
        (root / "blocks.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        (root / "quality_report.json").write_text('{"quality_report_version":"1.0"}\n', encoding="utf-8")

    def _write_blocks(self, root: Path, blocks: list[dict]) -> None:
        (root / "blocks.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in blocks),
            encoding="utf-8",
        )
        (root / "quality_report.json").write_text(
            '{"quality_report_version":"1.0"}\n', encoding="utf-8"
        )

    def _table_block(
        self,
        matrix: list[list[str]],
        *,
        block_id: str = "BLK-TABLE",
        title: str = "",
        merges: list[tuple[int, int, int, int]] | None = None,
    ) -> dict:
        block, _items, _cells = build_table_artifacts(
            matrix,
            table_id=f"TBL-{block_id}",
            block_id=block_id,
            order=1,
            table_title=title,
            section_path=["Price Schedule"],
            knowledge_bases=KB,
            merge_ranges=[] if merges is None else merges,
        )
        return block

    @staticmethod
    def _accepted_entry(source: str, translation: str | None = None) -> dict:
        return {
            "translation": translation or f"中文译文：{source}",
            "rejected": False,
            "status": "accepted",
            "model": "mock-model",
            "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
            "strategy_version": _active_translation_strategy_version(),
        }

    @staticmethod
    def _summary(**overrides: int | str) -> dict:
        summary: dict[int | str] = {
            "route": "openai_compatible",
            "model": "mock-model",
            "cached": 0,
            "translated": 0,
            "rejected": 0,
            "unresolved": 0,
            "batch_calls": 0,
            "failed_calls": 0,
        }
        summary.update(overrides)
        return summary

    def _parse_first_table(self, rendered: str) -> list[dict]:
        parser = _TableMarkupParser()
        parser.feed(rendered)
        self.assertEqual(len(parser.tables), 1)
        return parser.tables[0]

    @staticmethod
    def _source_rows(rows: list[dict], *, section: str | None = None) -> list[dict]:
        return [
            row for row in rows
            if "source-row" in str(row["attrs"].get("class") or "")
            and (section is None or row["section"] == section)
        ]

    def _assert_bilingual_grid(self, rows: list[dict], *, width: int) -> None:
        """DOM 级网格不变量：无 rowspan；每行 colspan 总和恒等于表宽；
        源/译文行严格成对交替、每对覆盖同一网格宽度（同一物理行的两个视图）。"""
        self.assertTrue(rows)
        self.assertEqual(len(rows) % 2, 0)
        expect_source = True
        for row in rows:
            cells = row["cells"]
            self.assertTrue(cells)
            for cell in cells:
                self.assertNotIn("rowspan", cell["attrs"])
            coverage = sum(int(cell["attrs"].get("colspan") or 1) for cell in cells)
            self.assertEqual(coverage, width)
            classes = str(row["attrs"].get("class") or "")
            self.assertIn("source-row" if expect_source else "translation-row", classes)
            expect_source = not expect_source
        for source, translation in zip(rows[::2], rows[1::2]):
            self.assertEqual(
                sum(int(cell["attrs"].get("colspan") or 1) for cell in source["cells"]),
                sum(int(cell["attrs"].get("colspan") or 1) for cell in translation["cells"]),
            )

    def test_writes_one_schema_valid_disposition_per_block_and_reuses_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_inputs(root)
            source = "CLASS 1) meters shall comply."
            key = translation_key(source)
            entry = {
                "translation": "1级电表应符合要求。",
                "rejected": False,
                "status": "accepted",
                "model": "mock-model",
                "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
                "strategy_version": _active_translation_strategy_version(),
            }
            summary = {"route": "openai_compatible", "model": "mock-model", "cached": 1,
                       "translated": 0, "rejected": 0, "unresolved": 0,
                       "batch_calls": 0, "failed_calls": 0}
            with patch("doc_annotation_export.generate_annotation_translations", return_value=summary), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value={key: entry}):
                payload = ft.run_full_translation(root)

            rows = [json.loads(line) for line in (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["status"] for row in rows], ["translated", "translated", "skipped"])
            self.assertEqual(rows[0]["provenance"]["translation_key"], rows[1]["provenance"]["translation_key"])
            for row in rows:
                jsonschema.Draft202012Validator(SCHEMA).validate(row)
            self.assertEqual(payload["quality"]["coverage_percent"], 100.0)
            quality = json.loads((root / "quality_report.json").read_text(encoding="utf-8"))
            self.assertTrue(quality["full_translation"]["meets_99_percent"])
            self.assertTrue((root / ft.DOCUMENT_TRANSLATION_HTML).exists())
            self.assertTrue((root / ft.CLARIFICATION_BILINGUAL_HTML).exists())

    def test_feature_switch_records_controlled_skips_without_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_inputs(root)
            with patch.dict(os.environ, {ft.FULL_TRANSLATION_ENV: "0"}), \
                    patch("doc_annotation_export.generate_annotation_translations") as generate:
                payload = ft.run_full_translation(root)
            generate.assert_not_called()
            rows = [json.loads(line) for line in (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["status"] for row in rows], ["skipped", "skipped", "skipped"])
            self.assertEqual(rows[0]["reason"], "feature_disabled")
            self.assertFalse(payload["quality"]["enabled"])

    def test_package_v1_writes_governed_pipeline_not_result_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "result"
            source = base / "source.docx"
            source.write_bytes(b"fixture")
            initialize_result_package(
                root,
                input_path=source,
                requested_stages=["full-translation"],
            )
            analysis_root = resolve_analysis_root(root)
            self._write_inputs(analysis_root)
            with patch.dict(os.environ, {ft.FULL_TRANSLATION_ENV: "0"}):
                ft.run_full_translation(analysis_root)
            self.assertTrue((analysis_root / ft.DOCUMENT_TRANSLATIONS).exists())
            self.assertTrue((analysis_root / ft.DOCUMENT_TRANSLATION_HTML).exists())
            self.assertFalse((root / ft.DOCUMENT_TRANSLATIONS).exists())
            self.assertFalse((root / ft.DOCUMENT_TRANSLATION_HTML).exists())

    def test_regular_table_renders_bilingual_rows_with_physical_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description", "Quantity"],
                ["A", "Meter", "Two"],
                ["B", "Seal", "Four"],
            ], title="Price Schedule")
            block["data_rows"][0][1] = " Meter "
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            captured: dict[str, tuple[str, str]] = {}

            def generate(_root: Path, *, route: str, texts: dict, chat=None) -> dict:
                captured.update(texts)
                return self._summary(cached=len(texts))

            with patch("doc_annotation_export.generate_annotation_translations", side_effect=generate), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                payload = ft.run_full_translation(root)

            ledger = [json.loads(line) for line in
                      (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(ledger), 1)
            row = ledger[0]
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            self.assertEqual(row["record_kind"], "table")
            data_units = [unit for unit in row["table"]["rows"] if unit["role"] == "data"]
            self.assertEqual([unit["row_index"] for unit in data_units], [2, 3])
            self.assertEqual(
                data_units[0]["source_text"],
                shared_row_render_line(block["headers"], block["data_rows"][0]),
            )
            self.assertNotIn(block["text"], [text for _owner, text in captured.values()])
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            self.assertIn('<figure class="doc-table">', rendered)
            self.assertIn("<thead>", rendered)
            self.assertIn("<tbody>", rendered)
            self.assertIn('class="source-row"', rendered)
            self.assertIn('class="translation-row"', rendered)
            self.assertEqual(payload["quality"]["table_rows"]["counts"]["translated"], 3)

    def test_synthetic_headers_never_enter_translation_input_or_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback = {
                "block_id": "BLK-FALLBACK",
                "type": "table",
                "table_id": "TBL-FALLBACK",
                "headers": ["column_1", "column_2"],
                "header_rows": [["The device shall apply.", ""]],
                "header_row_indexes": [1],
                "data_rows": [["Alpha", "Beta"]],
                "header_detection_status": "fallback",
                "merge_ranges": [],
                "text": "The device shall apply. | \nAlpha | Beta",
            }
            mixed = {
                "block_id": "BLK-MIXED",
                "type": "table",
                "table_id": "TBL-MIXED",
                "headers": ["Item", "column_2", "column_3"],
                "header_rows": [["Item", "column_2", "column_3"]],
                "header_row_indexes": [1],
                "data_rows": [["Gamma", "Delta", "Epsilon"]],
                "header_detection_status": "inferred",
                "merge_ranges": [],
                "text": "Item | column_2 | column_3\nGamma | Delta | Epsilon",
            }
            self._write_blocks(root, [fallback, mixed])
            captured: dict[str, tuple[str, str]] = {}

            def generate(_root: Path, *, route: str, texts: dict, chat=None) -> dict:
                captured.update(texts)
                return self._summary(unresolved=len(texts))

            with patch("doc_annotation_export.generate_annotation_translations", side_effect=generate), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value={}):
                payload = ft.run_full_translation(root)

            corpus = "\n".join(text for _owner, text in captured.values())
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            self.assertNotRegex(corpus, r"column_\d+")
            self.assertNotRegex(rendered, r"column_\d+")
            self.assertIn("无表头（结构未识别）", rendered)
            self.assertIn("The device shall apply.", corpus)
            fallback_row = next(
                row for row in (
                    json.loads(line) for line in
                    (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()
                ) if row["block_id"] == "BLK-FALLBACK"
            )
            fallback_data = [
                unit for unit in fallback_row["table"]["rows"] if unit["role"] == "data"
            ]
            self.assertEqual([unit["row_index"] for unit in fallback_data], [1, 2])
            self.assertEqual(payload["quality"]["table_rows"]["header_fallback_tables"], 1)

    def test_duplicate_table_rows_share_cache_key_and_second_run_is_cache_only(self) -> None:
        calls: list[str] = []

        def chat(_system: str, user: str) -> dict:
            calls.append(user)
            numbered = json.loads(user.rsplit("原文条目 JSON:\n", 1)[1])
            return {
                "items": [
                    {"id": item["id"], "translation": f"中文译文：{item['text']}"}
                    for item in numbered
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Description", "Category"],
                ["Meter", "Required"],
                ["Meter", "Required"],
            ])
            self._write_blocks(root, [block])
            first = ft.run_full_translation(root, chat=chat)
            first_rows = [json.loads(line) for line in
                          (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()]
            data_units = [unit for unit in first_rows[0]["table"]["rows"] if unit["role"] == "data"]
            self.assertEqual(data_units[0]["translation_key"], data_units[1]["translation_key"])
            self.assertEqual(first["translations"]["total_markers"], 2)
            self.assertEqual(len(calls), 1)

            second = ft.run_full_translation(root, chat=chat)
            self.assertEqual(second["translations"]["cached"], 2)
            self.assertEqual(second["translations"]["translated"], 0)
            self.assertEqual(second["translations"]["batch_calls"], 0)
            self.assertEqual(len(calls), 1)

    def test_failed_table_row_is_not_disguised_and_rolls_up_to_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description"],
                ["A", "Meter"],
                ["B", "Seal"],
            ])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"][:-1]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(unresolved=1)), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                payload = ft.run_full_translation(root)

            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            failed = [unit for unit in row["table"]["rows"] if unit["status"] == "failed"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["translation"], "")
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["reason"], "table_rows_failed:1")
            self.assertEqual(payload["quality"]["table_rows"]["counts"]["failed"], 1)

    def test_vertical_merge_grid_valid_without_rowspan_continuation_inherits_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description"],
                ["A", "Meter"],
                ["A", "Seal"],
            ], merges=[(2, 1, 3, 1)])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=len(sidecar))), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            self.assertEqual(row["record_kind"], "table")
            self.assertEqual(row["table"]["merge_ranges"], [[2, 1, 3, 1]])
            data_units = [unit for unit in row["table"]["rows"] if unit["role"] == "data"]
            # 续行从有效矩阵继承锚文本（共享内容哈希 → 一条缓存翻译复用）。
            self.assertEqual([unit["source_text"] for unit in data_units], ["A | Meter", "A | Seal"])
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            # 交错双语布局里 rowspan 会吞掉译文行的格槽（下方所有行错位）——全表禁用。
            self.assertNotIn("rowspan=", rendered)
            self.assertNotIn("复杂表按原文展示", rendered)
            rows = self._parse_first_table(rendered)
            self._assert_bilingual_grid(rows, width=2)
            body_sources = self._source_rows(rows, section="tbody")
            self.assertEqual(len(body_sources), 2)
            anchor_cells = body_sources[0]["cells"]
            continuation_cells = body_sources[1]["cells"]
            # 每个物理行都渲染完整列集（此前续行省略被覆盖列 → 网格破洞）。
            self.assertEqual(len(anchor_cells), 2)
            self.assertEqual(len(continuation_cells), 2)
            # 续行的被覆盖列显示继承的锚文本，并带延续证据标记。
            self.assertEqual(continuation_cells[0]["text"], "A")
            self.assertEqual(continuation_cells[0]["attrs"].get("data-inherited"), "1")
            self.assertNotIn("data-inherited", anchor_cells[0]["attrs"])
            self.assertEqual(continuation_cells[1]["text"], "Seal")

    def test_2d_merge_inherits_at_anchor_column_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 2D 合并（行 2-3 × 列 1-2）锚 "A B"：docx 物理网格形状（覆盖格为空）。
            block = self._table_block([
                ["Item", "Description", "Note"],
                ["A B", "", "x"],
                ["", "", "y"],
            ], merges=[(2, 1, 3, 2)])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            data_units = [unit for unit in plan["units"] if unit["role"] == "data"]
            self.assertEqual([unit["row_index"] for unit in data_units], [2, 3])
            # 锚行：锚文本只在锚列出现一次，横向覆盖列保持空（与纯横向合并同口径）；
            # 此前 2D 合并被当纯纵向喂 inherit_merged_text，锚行横向铺满 "A B | A B | x"。
            self.assertEqual(data_units[0]["source_text"], "A B |  | x")
            # 续行：锚列继承锚文本，横向覆盖列不继承。
            self.assertEqual(data_units[1]["source_text"], "A B |  | y")
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=len(sidecar))), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            ledger_data = [unit for unit in row["table"]["rows"] if unit["role"] == "data"]
            # 账本每行的锚文本恰好一次（LLM 输入同源，不重复付费）。
            self.assertEqual(
                [unit["source_text"] for unit in ledger_data], ["A B |  | x", "A B |  | y"]
            )
            for unit in ledger_data:
                self.assertEqual(unit["source_text"].count("A B"), 1)
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            rows = self._parse_first_table(rendered)
            self._assert_bilingual_grid(rows, width=3)
            body_sources = self._source_rows(rows, section="tbody")
            self.assertEqual(len(body_sources), 2)
            anchor_cells = body_sources[0]["cells"]
            continuation_cells = body_sources[1]["cells"]
            # 锚行：文本一次；横向覆盖列空标留证（data-merge-covered）。
            self.assertEqual([cell["text"] for cell in anchor_cells], ["A B", "", "x"])
            self.assertEqual(anchor_cells[1]["attrs"].get("data-merge-covered"), "1")
            self.assertNotIn("data-inherited", anchor_cells[0]["attrs"])
            # 续行：锚列继承锚文本并带 data-inherited 证据；横向覆盖列不铺锚文本。
            self.assertEqual(continuation_cells[0]["text"], "A B")
            self.assertEqual(continuation_cells[0]["attrs"].get("data-inherited"), "1")
            self.assertEqual(continuation_cells[1]["text"], "")
            self.assertEqual(continuation_cells[2]["text"], "y")

    def test_conflicting_merge_geometry_degrades_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = {
                "block_id": "BLK-CONFLICT",
                "type": "table",
                "table_id": "TBL-CONFLICT",
                "headers": ["Item", "Description", "Qty"],
                "header_rows": [["Item", "Description", "Qty"]],
                "header_row_indexes": [1],
                "title_row_indexes": [],
                "data_rows": [["A", "Meter", "Two"], ["B", "Seal", "Four"]],
                "rows": 3,
                "header_detection_status": "inferred",
                # 两个 range 在 (2..3, 2) 相交 —— 几何自相矛盾。
                "merge_ranges": [[2, 1, 3, 2], [2, 2, 3, 3]],
                "text": "Item | Description | Qty\nA | Meter | Two\nB | Seal | Four",
            }
            self._write_blocks(root, [block])
            source = block["text"]
            sidecar = {translation_key(source): self._accepted_entry(source)}
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=1)), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            self.assertEqual(row["record_kind"], "complex_table")
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            self.assertIn("复杂表按原文展示", rendered)
            self.assertNotIn('<figure class="doc-table">', rendered)

    def test_nested_tables_still_degrade_honestly(self) -> None:
        plan = ft._regular_table_plan({
            "block_id": "BLK-NESTED",
            "type": "table",
            "table_id": "TBL-NESTED",
            "headers": ["Item"],
            "header_rows": [["Item"]],
            "header_row_indexes": [1],
            "title_row_indexes": [],
            "data_rows": [["A"]],
            "rows": 2,
            "header_detection_status": "inferred",
            "merge_ranges": [],
            "nested_tables": [{"table_id": "TBL-INNER"}],
            "text": "Item\nA",
        })
        self.assertIsNone(plan)

    def test_stacked_title_rows_each_produce_title_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = {
                "block_id": "BLK-TITLES",
                "type": "table",
                "table_id": "TBL-TITLES",
                "table_title": "Main Title",
                "title_row_indexes": [1, 2],
                "title_rows": [["Main Title", "", ""], ["Subtitle Line", "", ""]],
                "headers": ["Item", "Description", "Qty"],
                "header_rows": [["Item", "Description", "Qty"]],
                "header_row_indexes": [3],
                "data_rows": [["A", "Meter", "Two"]],
                "rows": 4,
                "header_detection_status": "inferred",
                "merge_ranges": [[1, 1, 1, 3], [2, 1, 2, 3]],
                "text": "Item | Description | Qty\nA | Meter | Two",
            }
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            title_units = [unit for unit in plan["units"] if unit["role"] == "title"]
            # 题注单元（table_title）保持不变 + 每个物理标题行各一个单元。
            self.assertEqual(
                [(unit["unit_id"], unit["row_index"], unit["source_text"]) for unit in title_units],
                [
                    ("BLK-TITLES:title", None, "Main Title"),
                    ("BLK-TITLES:title-row:1", 1, "Main Title"),
                    ("BLK-TITLES:title-row:2", 2, "Subtitle Line"),
                ],
            )
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=len(sidecar))), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            self.assertIn("Subtitle Line", rendered)
            self.assertIn("中文译文：Subtitle Line", rendered)

    def test_stacked_titles_render_once_in_document_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = {
                "block_id": "BLK-TITLES",
                "type": "table",
                "table_id": "TBL-TITLES",
                "table_title": "Main Title",
                "title_row_indexes": [1, 2],
                "title_rows": [["Main Title", "", ""], ["Subtitle Line", "", ""]],
                "headers": ["Item", "Description", "Qty"],
                "header_rows": [["Item", "Description", "Qty"]],
                "header_row_indexes": [3],
                "data_rows": [["A", "Meter", "Two"]],
                "rows": 4,
                "header_detection_status": "inferred",
                "merge_ranges": [[1, 1, 1, 3], [2, 1, 2, 3]],
                "text": "Item | Description | Qty\nA | Meter | Two",
            }
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=len(sidecar))), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            parser = _TableMarkupParser()
            parser.feed(rendered)
            self.assertEqual(len(parser.tables), 1)
            rows = parser.tables[0]
            # 与题注同文的主标题只在 figcaption 出现一次（正文物理行去重跳过）。
            self.assertEqual(len(parser.figcaptions), 1)
            self.assertIn("Main Title", parser.figcaptions[0])
            self.assertEqual(rendered.count(">Main Title<"), 1)
            self.assertEqual(rendered.count(">Subtitle Line<"), 1)
            # 副标题物理在表头行之前 → 渲染在 thead 顶部、列表头行之前（文档序；
            # 此前它被排进 tbody，显示在表头之后）。
            thead_rows = [row for row in rows if row["section"] == "thead"]
            self.assertEqual(len(thead_rows), 4)
            self.assertEqual(thead_rows[0]["cells"][0]["text"], "Subtitle Line")
            self.assertEqual(int(thead_rows[0]["cells"][0]["attrs"].get("colspan") or 0), 3)
            self.assertEqual(
                [cell["text"] for cell in thead_rows[2]["cells"]],
                ["Item", "Description", "Qty"],
            )
            body_rows = [row for row in rows if row["section"] == "tbody"]
            self.assertEqual(len(body_rows), 2)
            self.assertEqual(
                [cell["text"] for cell in body_rows[0]["cells"]],
                ["A", "Meter", "Two"],
            )
            self._assert_bilingual_grid(rows, width=3)

    def test_title_row_after_header_renders_in_tbody_after_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = {
                "block_id": "BLK-TITLE-AFTER",
                "type": "table",
                "table_id": "TBL-TITLE-AFTER",
                "table_title": "Lead Title",
                "title_row_indexes": [1, 3],
                "title_rows": [["Lead Title", "", ""], ["Trailing Note", "", ""]],
                "headers": ["Item", "Description", "Qty"],
                "header_rows": [["Item", "Description", "Qty"]],
                "header_row_indexes": [2],
                "data_rows": [["A", "Meter", "Two"]],
                "rows": 4,
                "header_detection_status": "inferred",
                "merge_ranges": [[1, 1, 1, 3], [3, 1, 3, 3]],
                "text": "Item | Description | Qty\nA | Meter | Two",
            }
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=len(sidecar))), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            rows = self._parse_first_table(rendered)
            # 首标题行与题注同文 → 只留 figcaption；表头之后的尾注行落 tbody。
            self.assertEqual(rendered.count(">Lead Title<"), 1)
            self.assertEqual(rendered.count(">Trailing Note<"), 1)
            thead_rows = [row for row in rows if row["section"] == "thead"]
            self.assertEqual(len(thead_rows), 2)
            self.assertEqual(
                [cell["text"] for cell in thead_rows[0]["cells"]],
                ["Item", "Description", "Qty"],
            )
            body_rows = [row for row in rows if row["section"] == "tbody"]
            self.assertEqual(len(body_rows), 4)
            self.assertEqual(body_rows[0]["cells"][0]["text"], "Trailing Note")
            self.assertEqual(int(body_rows[0]["cells"][0]["attrs"].get("colspan") or 0), 3)
            self.assertEqual(
                [cell["text"] for cell in body_rows[2]["cells"]],
                ["A", "Meter", "Two"],
            )
            self._assert_bilingual_grid(rows, width=3)

    def test_looks_translatable_accepts_any_letter_script(self) -> None:
        # 目标语是中文：拉丁/西里尔等任意非 CJK 字母文字都需要翻译（STO 俄标不能整表跳过）；
        # 纯数字/符号与已是中文的文本仍然不进翻译管线。
        self.assertTrue(ft._looks_translatable("Voltage shall be measured"))
        self.assertTrue(ft._looks_translatable("Напряжение сети должно измеряться"))
        self.assertFalse(ft._looks_translatable("1 2 3 | X | 0.5"))
        self.assertFalse(ft._looks_translatable("电压等级与电流"))

    def test_looks_translatable_requires_non_cjk_majority(self) -> None:
        # 非 CJK 字母 ≥3 且 ≥ CJK 字符数（旧拉丁版的广义化比率）：俄文等整段外文
        # （CJK≈0）照译；中文为主、只夹缩写的文本（目标语已是中文）跳过——此前
        # 只看 non_cjk>=3，"电压ABC等级" 这类 3 字母缩写混排也被送进 LLM。
        self.assertTrue(ft._looks_translatable("Напряжение сети"))
        self.assertFalse(ft._looks_translatable("电压ABC等级"))
        # 边界（有意钉住）：3 个非 CJK 字母 vs 2 个 CJK 字符 → non_cjk>=cjk 成立 → 可译。
        self.assertTrue(ft._looks_translatable("电压ABC"))
        self.assertFalse(ft._looks_translatable("1 2 3 | X | 0.5"))

    def test_atomize_table_block_carries_stacked_title_rows_end_to_end(self) -> None:
        matrix = [
            ["Main Title", "", ""],
            ["Subtitle Line", "", ""],
            ["Item", "Description", "Qty"],
            ["A", "Meter", "Two"],
        ]
        block, _items, _cells = build_table_artifacts(
            matrix,
            table_id="TBL-000001",
            block_id="BLK-000010",
            order=10,
            table_title="Main Title",
            section_path=["Annex"],
            knowledge_bases=KB,
            merge_ranges=[[1, 1, 1, 3], [2, 1, 2, 3]],
        )
        # atomize 生产端：title_rows 载荷与 title_row_indexes 逐行对齐，副标题不再只活在矩阵里。
        self.assertEqual(block["title_row_indexes"], [1, 2])
        self.assertEqual(
            block["title_rows"],
            [["Main Title", "", ""], ["Subtitle Line", "", ""]],
        )
        plan = ft._regular_table_plan(block)
        self.assertIsNotNone(plan)
        assert plan is not None
        title_units = [unit for unit in plan["units"] if unit["role"] == "title"]
        self.assertEqual(
            [unit["unit_id"] for unit in title_units],
            ["BLK-000010:title", "BLK-000010:title-row:1", "BLK-000010:title-row:2"],
        )

    def test_xlsx_flat_filled_merged_title_row_text_appears_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # xlsx 形矩阵：全宽合并标题行的覆盖格带锚文本（_region_matrix 扁平填充）。
            block = self._table_block([
                ["Safety requirements", "Safety requirements", "Safety requirements"],
                ["Item", "Description", "Quantity"],
                ["A", "Meter", "Two"],
            ], title="Safety requirements", merges=[(1, 1, 1, 3)])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            title_units = [unit for unit in plan["units"] if unit["role"] == "title"]
            # 塌缩后物理标题行与 table_title 同文 → 标题文本在每个单元里恰好一次
            # （此前 "Safety requirements | Safety requirements | Safety requirements"
            # 三份拼接进 LLM 输入与账本）。
            self.assertEqual(len(title_units), 2)
            for unit in title_units:
                self.assertEqual(unit["source_text"], "Safety requirements")
            captured: dict[str, tuple[str, str]] = {}

            def generate(_root: Path, *, route: str, texts: dict, chat=None) -> dict:
                captured.update(texts)
                return self._summary(cached=len(texts))

            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations", side_effect=generate), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            corpus = "\n".join(text for _owner, text in captured.values())
            self.assertNotIn("Safety requirements | Safety requirements", corpus)
            ledger_row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            ledger_titles = [
                unit["source_text"] for unit in ledger_row["table"]["rows"]
                if unit["role"] == "title"
            ]
            self.assertEqual(ledger_titles, ["Safety requirements", "Safety requirements"])
            # 与题注同文（塌缩后成立）→ 题注去重生效：标题只在 figcaption 出现一次
            # （此前三份拼接串 ≠ table_title，去重失效，正文再渲染一遍）。
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            parser = _TableMarkupParser()
            parser.feed(rendered)
            self.assertEqual(len(parser.figcaptions), 1)
            self.assertIn("Safety requirements", parser.figcaptions[0])
            self.assertEqual(rendered.count(">Safety requirements<"), 1)

    def test_all_empty_data_row_creates_no_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description"],
                ["A", "Meter"],
                ["", ""],
                ["B", "Seal"],
            ])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            assert plan is not None
            data_units = [unit for unit in plan["units"] if unit["role"] == "data"]
            self.assertEqual([unit["row_index"] for unit in data_units], [2, 4])
            captured: dict[str, tuple[str, str]] = {}

            def generate(_root: Path, *, route: str, texts: dict, chat=None) -> dict:
                captured.update(texts)
                return self._summary(unresolved=len(texts))

            with patch("doc_annotation_export.generate_annotation_translations", side_effect=generate), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value={}):
                ft.run_full_translation(root)

            corpus = "\n".join(text for _owner, text in captured.values())
            self.assertNotIn("|  |", corpus)

    def test_pure_number_row_is_skipped_with_nothing_translatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description"],
                ["1", "2"],
                ["A", "Meter"],
            ])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
                if unit["source_text"] != "1 | 2"
            }
            captured: dict[str, tuple[str, str]] = {}

            def generate(_root: Path, *, route: str, texts: dict, chat=None) -> dict:
                captured.update(texts)
                return self._summary(cached=len(texts))

            with patch("doc_annotation_export.generate_annotation_translations", side_effect=generate), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                payload = ft.run_full_translation(root)

            self.assertNotIn("1 | 2", captured)
            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            numeric = [unit for unit in row["table"]["rows"] if unit["source_text"] == "1 | 2"]
            self.assertEqual(len(numeric), 1)
            self.assertEqual(numeric[0]["status"], "skipped")
            self.assertEqual(numeric[0]["reason"], "nothing_translatable")
            self.assertEqual(numeric[0]["translation"], "")
            counts = payload["quality"]["table_rows"]["counts"]
            self.assertEqual(counts["translated"], 2)  # 表头 + "A | Meter"
            self.assertEqual(counts["skipped"], 1)
            self.assertEqual(payload["quality"]["table_rows"]["eligible_rows"], 2)

    def test_stale_guards_cache_entry_is_not_reported_translated(self) -> None:
        source = "The meter shall comply with the standard."
        unit = {
            "unit_id": "BLK-X:data:1",
            "role": "data",
            "row_index": 2,
            "source_cells": [source],
            "source_text": source,
        }
        entry = self._accepted_entry(source)
        entry["guards_version"] = "annotation-translation-guards-v0"
        disposition = ft._unit_disposition(
            unit, enabled=True,
            sidecar={translation_key(source): entry},
            translation_summary={"route": "openai_compatible"},
        )
        self.assertEqual(disposition["status"], "failed")
        self.assertEqual(disposition["reason"], "guards_version_mismatch")
        self.assertEqual(disposition["translation"], "")

    def test_lettered_header_cleaning_extends_beyond_j(self) -> None:
        self.assertEqual(ft._clean_header("(k) Total Price"), "Total Price")
        self.assertEqual(ft._clean_header("(z) Tail Column"), "Tail Column")
        self.assertEqual(ft._clean_header("(a) Item No"), "Item No")

    def test_eleven_column_lettered_header_row_is_cleaned_in_units(self) -> None:
        letters = [chr(ord("a") + offset) for offset in range(11)]
        header_row = [f"({letter}) Col {letter.upper()}" for letter in letters]
        block = {
            "block_id": "BLK-LETTERED",
            "type": "table",
            "table_id": "TBL-LETTERED",
            "headers": [f"Col {letter.upper()}" for letter in letters],
            "header_rows": [header_row],
            "header_row_indexes": [1],
            "title_row_indexes": [],
            "data_rows": [["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta",
                           "Eta", "Theta", "Iota", "Kappa", "Lambda"]],
            "rows": 2,
            "header_detection_status": "explicit",
            "merge_ranges": [],
            "text": " | ".join(header_row),
        }
        plan = ft._regular_table_plan(block)
        self.assertIsNotNone(plan)
        assert plan is not None
        header_units = [unit for unit in plan["units"] if unit["role"] == "header"]
        self.assertEqual(len(header_units), 1)
        self.assertNotIn("(k)", header_units[0]["source_text"])
        self.assertIn("Col K", header_units[0]["source_text"])

    def test_version_constants_and_schema_pin_v3(self) -> None:
        self.assertEqual(ft.FULL_TRANSLATION_VERSION, "full-translation-v3")
        self.assertEqual(ft.DOCUMENT_TRANSLATION_SCHEMA_VERSION, "document-translation/v3")
        self.assertEqual(SCHEMA["properties"]["schema_version"]["const"],
                         ft.DOCUMENT_TRANSLATION_SCHEMA_VERSION)
        self.assertEqual(SCHEMA["properties"]["provenance"]["properties"]["producer"]["const"],
                         ft.FULL_TRANSLATION_VERSION)

    def test_row_render_line_import_is_hoisted_without_cycle(self) -> None:
        # ai_extract（及其传递依赖）不得引入 full_translation —— 顶层导入才无环。
        code = (
            "import sys, ai_extract; "
            "sys.exit(0 if 'full_translation' not in sys.modules else 1)"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True)
        self.assertEqual(
            result.returncode, 0,
            f"ai_extract transitively imports full_translation: {result.stderr.decode('utf-8', 'replace')}",
        )
        self.assertIs(ft._row_render_line, ft._shared_row_render_line)

    def test_horizontal_merge_row_keeps_full_grid_and_marks_covered_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description", "Quantity"],
                ["A", "Meter", "Two"],
                ["Grand Total", "", ""],
            ], merges=[(3, 1, 3, 2)])
            self._write_blocks(root, [block])
            plan = ft._regular_table_plan(block)
            self.assertIsNotNone(plan)
            assert plan is not None
            sidecar = {
                translation_key(unit["source_text"]): self._accepted_entry(unit["source_text"])
                for unit in plan["units"]
            }
            with patch("doc_annotation_export.generate_annotation_translations",
                       return_value=self._summary(cached=len(sidecar))), \
                    patch("doc_annotation_export._read_translation_sidecar", return_value=sidecar):
                ft.run_full_translation(root)

            row = json.loads(
                (root / ft.DOCUMENT_TRANSLATIONS).read_text(encoding="utf-8").splitlines()[0]
            )
            jsonschema.Draft202012Validator(SCHEMA).validate(row)
            self.assertEqual(row["record_kind"], "table")
            self.assertEqual(row["table"]["merge_ranges"], [[3, 1, 3, 2]])
            rendered = (root / ft.DOCUMENT_TRANSLATION_HTML).read_text(encoding="utf-8")
            rows = self._parse_first_table(rendered)
            self._assert_bilingual_grid(rows, width=3)
            merged_cells = self._source_rows(rows, section="tbody")[-1]["cells"]
            # 译文行是整行级条幅、无法逐格镜像 colspan 结构 → 源文行同样不用
            # colspan：每行完整列集，合并文本只在最左格出现一次，覆盖列空标留证。
            self.assertEqual(
                [cell["attrs"].get("colspan") for cell in merged_cells],
                [None, None, None],
            )
            self.assertEqual(merged_cells[0]["text"], "Grand Total")
            self.assertEqual(merged_cells[1]["attrs"].get("data-merge-covered"), "1")
            self.assertEqual(merged_cells[1]["text"], "")
            source_cell_texts = [
                cell["text"]
                for source_row in self._source_rows(rows)
                for cell in source_row["cells"]
            ]
            self.assertEqual(source_cell_texts.count("Grand Total"), 1)

    def test_inline_lettered_composite_headers_are_explicit_and_clean(self) -> None:
        block = self._table_block([
            ["(a) Item No", "(b) Description", "(c) Quantity"],
            ["One", "Meter", "Two"],
        ])
        self.assertEqual(block["header_detection_status"], "explicit")
        self.assertEqual(block["header_row_indexes"], [1])
        self.assertEqual(block["headers"], ["Item No", "Description", "Quantity"])
        self.assertTrue(any("lettered_composite_header:inline" in item
                            for item in block["header_detection_evidence"]))

    def test_stacked_lettered_composite_headers_use_label_row(self) -> None:
        block = self._table_block([
            ["(a)", "(b)", "(c)"],
            ["Item No", "Description", "Quantity"],
            ["One", "Meter", "Two"],
        ])
        self.assertEqual(block["header_detection_status"], "explicit")
        self.assertEqual(block["header_row_indexes"], [1, 2])
        self.assertEqual(block["headers"], ["Item No", "Description", "Quantity"])
        self.assertTrue(any("lettered_composite_header:stacked" in item
                            for item in block["header_detection_evidence"]))

    def test_lettered_header_detector_rejects_short_or_normative_sequences(self) -> None:
        short = self._table_block([
            ["(a) Item", "(b) Description"],
            ["One", "Meter"],
        ], block_id="BLK-SHORT")
        normative = self._table_block([
            ["(a) The contract clause shall apply.", "", ""],
            ["One", "Meter", "Two"],
        ], block_id="BLK-NORMATIVE")
        self.assertFalse(any("lettered_composite_header" in item
                             for item in short["header_detection_evidence"]))
        self.assertFalse(any("lettered_composite_header" in item
                             for item in normative["header_detection_evidence"]))
        self.assertEqual(normative["header_detection_status"], "ambiguous")


if __name__ == "__main__":
    unittest.main()
