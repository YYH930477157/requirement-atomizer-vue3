from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atomize import build_atomic_candidates, mark_doc_regions, run_atomizer_pipeline
from parsers.xlsx_parser import extract_xlsx
from tests.xlsx_fixtures import write_synthetic_xlsx


ROOT = Path(__file__).resolve().parents[1]


class ExtractXlsxE2ETests(unittest.TestCase):
    def run_cli(self, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(ROOT) if not existing_pythonpath else f"{ROOT}{os.pathsep}{existing_pythonpath}"
        return subprocess.run(
            [sys.executable, "-m", "cli", *args],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_extract_xlsx_preserves_sheet_sections_tables_and_value_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "synthetic_standard.xlsx"
            write_synthetic_xlsx(input_path)

            blocks, table_items = extract_xlsx(input_path, knowledge_bases=[], document_profile=None)
            mark_doc_regions(blocks, table_items)
            candidates = build_atomic_candidates(blocks, table_items, include_regions={"body"})

        headings = [block for block in blocks if block["type"] == "heading"]
        self.assertEqual([block["text"] for block in headings], ["Requirements", "Capability Matrix", "Mixed Types"])
        self.assertTrue(all(block.get("doc_region") == "body" for block in blocks))
        self.assertTrue(all(item.get("doc_region") == "body" for item in table_items))

        requirement_item = next(item for item in table_items if item["table_title"] == "Requirements" and item["row_index"] == 2)
        self.assertTrue(requirement_item["requirement_like"])
        self.assertEqual(requirement_item["fields"]["Requirement"], "The meter shall support xDLMS GET service.")

        matrix_block = next(block for block in blocks if block.get("table_title") == "Capability Matrix")
        self.assertEqual(matrix_block["header_row_count"], 2)
        self.assertEqual(matrix_block["headers"][1], "xDLMS Service / GET")
        self.assertEqual(matrix_block["headers"][2], "xDLMS Service / ACTION")
        matrix_item = next(item for item in table_items if item["table_title"] == "Capability Matrix" and item["matrix_facts"])
        self.assertEqual(matrix_item["matrix_facts"][0]["predicate_header"], "xDLMS Service / GET")

        mixed_item = next(item for item in table_items if item["table_title"] == "Mixed Type Values" and item["fields"].get("Label") == "Integer float")
        self.assertEqual(mixed_item["fields"]["Value"], "42")
        date_item = next(item for item in table_items if item["fields"].get("Label") == "Date value")
        self.assertEqual(date_item["fields"]["Value"], "2026-06-12")
        bool_item = next(item for item in table_items if item["fields"].get("Label") == "Boolean value")
        self.assertEqual(bool_item["fields"]["Value"], "TRUE")
        formula_item = next(item for item in table_items if item["fields"].get("Label") == "Formula value")
        self.assertEqual(formula_item["fields"]["Formula"], "42")

        candidate_types = {candidate["requirement_type"] for candidate in candidates}
        self.assertIn("capability_matrix", candidate_types)
        self.assertTrue(any(candidate["source_type"] == "table_row" for candidate in candidates))

    def test_run_atomizer_pipeline_dispatches_xlsx_and_writes_manifest_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "synthetic_standard.xlsx"
            out_dir = tmp_path / "out"
            write_synthetic_xlsx(input_path)

            manifest = run_atomizer_pipeline(input_path, out_dir)
            manifest_file = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            blocks = [json.loads(line) for line in (out_dir / "blocks.jsonl").read_text(encoding="utf-8").splitlines()]
            atomic_exists = (out_dir / "atomic_requirements.jsonl").exists()
            quality_exists = (out_dir / "quality_report.json").exists()

        self.assertEqual(manifest["input_format"], "xlsx")
        self.assertEqual(manifest_file["input_format"], "xlsx")
        self.assertGreater(manifest["counts"]["blocks"], 0)
        self.assertGreater(manifest["counts"]["table_items"], 0)
        self.assertTrue(atomic_exists)
        self.assertTrue(quality_exists)
        self.assertTrue(all(block.get("doc_region") == "body" for block in blocks))

    def test_cli_run_accepts_xlsx_and_reports_manifest_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "synthetic_standard.xlsx"
            out_dir = tmp_path / "out"
            write_synthetic_xlsx(input_path)

            result = self.run_cli("run", str(input_path), "--out", str(out_dir), "--skip-review", "--quiet")

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["manifest"]["input_format"], "xlsx")

    def test_unsupported_excel_and_unknown_formats_are_input_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            xls_path = tmp_path / "legacy.xls"
            txt_path = tmp_path / "input.txt"
            xls_path.write_bytes(b"legacy excel")
            txt_path.write_text("not a supported document", encoding="utf-8")

            xls_result = self.run_cli("atomize", str(xls_path), "--out", str(tmp_path / "xls-out"), "--quiet")
            txt_result = self.run_cli("atomize", str(txt_path), "--out", str(tmp_path / "txt-out"), "--quiet")

        self.assertEqual(xls_result.returncode, 2)
        xls_envelope = json.loads(xls_result.stdout)
        self.assertEqual(xls_envelope["error"]["type"], "input_error")
        self.assertIn("save it as .xlsx", xls_envelope["error"]["message"])
        self.assertIn(".docx, .xlsx, .pdf", xls_envelope["error"]["message"])

        self.assertEqual(txt_result.returncode, 2)
        txt_envelope = json.loads(txt_result.stdout)
        self.assertEqual(txt_envelope["error"]["type"], "input_error")
        self.assertIn("Supported formats: .docx, .xlsx, .pdf", txt_envelope["error"]["message"])


if __name__ == "__main__":
    unittest.main()
