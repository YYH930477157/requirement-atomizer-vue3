from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atomize import AtomizerInputError, DocumentProfile, build_atomic_candidates, mark_doc_regions, run_atomizer_pipeline
from parsers.pdf_parser import _starts_new_paragraph, extract_pdf


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class ExtractPdfE2ETests(unittest.TestCase):
    def run_cli(self, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{ROOT}{os.pathsep}{existing_pythonpath}"
        return subprocess.run(
            [sys.executable, "-m", "cli", *args],
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_extract_pdf_builds_blocks_tables_without_duplicating_table_text(self) -> None:
        input_path = FIXTURES / "sample_text_tables.pdf"

        blocks, table_items, table_cell_items = extract_pdf(input_path, knowledge_bases=[], document_profile=None)
        mark_doc_regions(blocks, table_items, table_cell_items=table_cell_items)
        candidates = build_atomic_candidates(
            blocks, table_items, include_regions={"body"},
            table_cell_items=table_cell_items,
        )

        headings = [block["text"] for block in blocks if block["type"] == "heading"]
        self.assertIn("1 Scope", headings)
        self.assertIn("5.1 Security requirements", headings)
        self.assertTrue(all("page_number" in block for block in blocks))
        self.assertTrue(all("page_number" in item for item in table_items))
        self.assertTrue(all(block.get("pdf_regions") for block in blocks))
        for block in blocks:
            region = block["pdf_regions"][0]
            self.assertEqual(region["page_number"], block["page_number"])
            self.assertEqual(len(region["bbox"]), 4)
            self.assertGreater(region["page_width"], 0)
            self.assertGreater(region["page_height"], 0)

        table_block = next(block for block in blocks if block["type"] == "table")
        self.assertEqual(table_block["table_title"], "Table 1 - Services xDLMS")
        self.assertEqual(table_block["headers"][1], "xDLMS Service / GET")
        self.assertEqual(table_block["headers"][2], "xDLMS Service / ACTION")

        matrix_item = next(item for item in table_items if item["matrix_facts"])
        self.assertEqual(matrix_item["matrix_facts"][0]["predicate_header"], "xDLMS Service / GET")

        paragraph_text = "\n".join(block["text"] for block in blocks if block["type"] == "paragraph")
        self.assertIn("The meter shall support xDLMS GET service.", paragraph_text)
        self.assertNotIn("Public customer", paragraph_text)
        self.assertNotIn("Management client", paragraph_text)

        noisy_texts = {block["text"] for block in blocks if block.get("noise")}
        self.assertIn("DLMS COSEM PDF SAMPLE", noisy_texts)
        self.assertIn("Copyright Sample Standard", noisy_texts)

        candidate_types = {candidate["requirement_type"] for candidate in candidates}
        self.assertIn("capability_matrix", candidate_types)
        self.assertTrue(any(candidate["source_type"] == "paragraph" for candidate in candidates))

    def test_extract_pdf_rejects_no_text_layer_pdf(self) -> None:
        input_path = FIXTURES / "sample_no_text_layer.pdf"

        with self.assertRaises(AtomizerInputError) as caught:
            extract_pdf(input_path, knowledge_bases=[], document_profile=None)

        message = str(caught.exception)
        self.assertIn("无文字层", message)
        self.assertIn(".docx", message)

    def test_pdf_paragraph_split_uses_injected_document_profile(self) -> None:
        previous = {"text": "Body text", "top": 100.0, "bottom": 110.0}
        appendix_caption = {"text": "Appendix Table 7 - Object map", "top": 114.0, "bottom": 124.0}
        custom_heading = {"text": "Conformance", "top": 114.0, "bottom": 124.0}
        default_profile = DocumentProfile()
        custom_profile = DocumentProfile(
            major_headings=("conformance",),
            caption_pattern=r"^appendix\s+table\s+\d+\b",
        )

        self.assertFalse(
            _starts_new_paragraph(previous, appendix_caption, page_height=1000, document_profile=default_profile)
        )
        self.assertTrue(
            _starts_new_paragraph(previous, appendix_caption, page_height=1000, document_profile=custom_profile)
        )
        self.assertFalse(
            _starts_new_paragraph(previous, custom_heading, page_height=1000, document_profile=default_profile)
        )
        self.assertTrue(
            _starts_new_paragraph(previous, custom_heading, page_height=1000, document_profile=custom_profile)
        )

    def test_page_word_memo_and_fallback_paths_produce_identical_output(self) -> None:
        """页词 memo（紧凑元组形）与超页数上限的回退路径必须产出逐字节一致的结果。

        回退触发方式：把 PDF_PAGE_WORD_MEMO_MAX_PAGES 压到 0 强制放弃 memo，
        主循环回到每页现抽的旧版 2x 行为。同时用 _extract_page_words 调用计数
        证明两条路径确实走了不同分支（memo=检测遍一遍；回退=检测+主循环两遍），
        避免"两条路径其实同路"的空通过。"""
        import pdfplumber
        from unittest import mock

        from parsers import pdf_parser

        input_path = FIXTURES / "sample_text_tables.pdf"
        with pdfplumber.open(input_path) as probe:
            page_count = len(probe.pages)
        self.assertGreaterEqual(page_count, 1)

        original_extract = pdf_parser._extract_page_words

        def run(threshold: int | None) -> tuple[tuple[list, list, list], int]:
            calls = {"count": 0}

            def counting(page: object, **kwargs: object) -> list[dict]:
                calls["count"] += 1
                return original_extract(page, **kwargs)

            with mock.patch.object(pdf_parser, "_extract_page_words", new=counting):
                if threshold is None:
                    result = extract_pdf(input_path, knowledge_bases=[], document_profile=None)
                else:
                    with mock.patch.object(pdf_parser, "PDF_PAGE_WORD_MEMO_MAX_PAGES", threshold):
                        result = extract_pdf(input_path, knowledge_bases=[], document_profile=None)
            return result, calls["count"]

        memo_result, memo_calls = run(None)
        fallback_result, fallback_calls = run(0)

        self.assertTrue(memo_result[0])   # 非空文档，等价断言不空转
        self.assertEqual(memo_calls, page_count)          # 检测遍一遍，主循环走 memo
        self.assertEqual(fallback_calls, 2 * page_count)  # memo 放弃，主循环每页现抽

        for memo_part, fallback_part in zip(memo_result, fallback_result):
            self.assertEqual(
                json.dumps(memo_part, ensure_ascii=False, sort_keys=True),
                json.dumps(fallback_part, ensure_ascii=False, sort_keys=True),
            )

    def test_run_atomizer_pipeline_dispatches_pdf_and_writes_manifest_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            manifest = run_atomizer_pipeline(FIXTURES / "sample_text_tables.pdf", out_dir)
            manifest_file = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            blocks = [json.loads(line) for line in (out_dir / "blocks.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(manifest["input_format"], "pdf")
        self.assertEqual(manifest_file["input_format"], "pdf")
        self.assertGreater(manifest["counts"]["blocks"], 0)
        self.assertGreater(manifest["counts"]["table_items"], 0)
        self.assertTrue(all("page_number" in block for block in blocks))
        self.assertTrue(all(block.get("pdf_regions") for block in blocks))

    def test_cli_scan_like_pdf_returns_input_error_with_docx_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(
                "atomize",
                str(FIXTURES / "sample_no_text_layer.pdf"),
                "--out",
                str(Path(tmp) / "out"),
                "--quiet",
            )

        self.assertEqual(result.returncode, 2)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["error"]["type"], "input_error")
        self.assertIn("无文字层", envelope["error"]["message"])
        self.assertIn(".docx", envelope["error"]["message"])


if __name__ == "__main__":
    unittest.main()
