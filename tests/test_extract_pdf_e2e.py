from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atomize import AtomizerInputError, build_atomic_candidates, mark_doc_regions, run_atomizer_pipeline
from parsers.pdf_parser import extract_pdf


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

        blocks, table_items = extract_pdf(input_path, knowledge_bases=[], document_profile=None)
        mark_doc_regions(blocks, table_items)
        candidates = build_atomic_candidates(blocks, table_items, include_regions={"body"})

        headings = [block["text"] for block in blocks if block["type"] == "heading"]
        self.assertIn("1 Scope", headings)
        self.assertIn("5.1 Security requirements", headings)
        self.assertTrue(all("page_number" in block for block in blocks))
        self.assertTrue(all("page_number" in item for item in table_items))

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
