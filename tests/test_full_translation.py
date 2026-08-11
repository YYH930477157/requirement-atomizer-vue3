from __future__ import annotations

import json
import os
import tempfile
import unittest
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
        summary: dict[str, int | str] = {
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

    def test_complex_merged_table_degrades_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = self._table_block([
                ["Item", "Description"],
                ["A", "Meter"],
                ["A", "Seal"],
            ], merges=[(2, 1, 3, 1)])
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

    def test_horizontal_merge_remains_structured_with_colspan(self) -> None:
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
            self.assertIn('<td colspan="2">Grand Total</td>', rendered)

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
