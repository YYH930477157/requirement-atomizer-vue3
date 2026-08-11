from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

import full_translation as ft
from api_server import ANNOTATION_TRANSLATION_GUARDS_VERSION, translation_key
from doc_annotation_export import _active_translation_strategy_version
from result_package import initialize_result_package, resolve_analysis_root


SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schemas" / "document_translation.schema.json")
    .read_text(encoding="utf-8")
)


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


if __name__ == "__main__":
    unittest.main()
