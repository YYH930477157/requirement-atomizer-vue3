from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.docx_fixtures import write_minimal_docx


ROOT = Path(__file__).resolve().parents[1]


class CliContractTests(unittest.TestCase):
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

    def test_run_happy_path_writes_clean_stdout_json_and_logs_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            write_minimal_docx(input_path)

            result = self.run_cli("run", str(input_path), "--out", str(out_dir))
            atomic_exists = (out_dir / "atomic_requirements.jsonl").exists()
            review_exists = (out_dir / "llm_review_results.jsonl").exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["tool"], "requirement-atomizer")
        self.assertEqual(envelope["schema_version"], "1.0")
        self.assertEqual(envelope["command"], "run")
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["manifest"]["counts"]["atomic_requirements"], 2)
        self.assertEqual(envelope["quality_summary"]["atomic_requirements"], 2)
        self.assertIn("timing_ms", envelope)
        self.assertIn("extracting docx", result.stderr)
        self.assertTrue(atomic_exists)
        self.assertTrue(review_exists)

    def test_run_quiet_keeps_stdout_json_and_suppresses_info_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            write_minimal_docx(input_path)

            result = self.run_cli("run", str(input_path), "--out", str(out_dir), "--quiet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertEqual(result.stderr, "")

    def test_run_full_pipeline_works_from_non_repo_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            launch_cwd = tmp_path / "launcher"
            launch_cwd.mkdir()
            write_minimal_docx(input_path)

            result = self.run_cli("run", str(input_path), "--out", str(out_dir), "--quiet", cwd=launch_cwd)

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["command"], "run")
        self.assertEqual(envelope["review"]["reviews"], 2)

    def test_run_rejects_invalid_export_format_before_pipeline_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            write_minimal_docx(input_path)

            result = self.run_cli("run", str(input_path), "--out", str(out_dir), "--export", "xlsx", "--quiet")

            manifest_exists = (out_dir / "manifest.json").exists()

        self.assertEqual(result.returncode, 2)
        envelope = json.loads(result.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "input_error")
        self.assertIn("Unsupported export format", envelope["error"]["message"])
        self.assertFalse(manifest_exists)

    def test_run_export_writes_markdown_and_utf8_sig_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            write_minimal_docx(input_path)

            result = self.run_cli("run", str(input_path), "--out", str(out_dir), "--export", "md,csv", "--quiet")

            csv_path = out_dir / "requirements_export.csv"
            md_path = out_dir / "requirements_export.md"
            csv_bytes = csv_path.read_bytes()
            md_exists = md_path.exists()
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f))

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["exports"], ["requirements_export.md", "requirements_export.csv"])
        self.assertTrue(md_exists)
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            header,
            [
                "req_id",
                "stable_req_id",
                "requirement_type",
                "domain",
                "object",
                "requirement",
                "condition",
                "verification_method",
                "confidence",
                "ambiguity",
                "review_status",
                "source_refs",
                "section_path",
            ],
        )

    def test_missing_input_returns_input_error_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("run", str(Path(tmp) / "missing.docx"), "--out", str(Path(tmp) / "out"), "--quiet")

        self.assertEqual(result.returncode, 2)
        envelope = json.loads(result.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "input_error")
        self.assertIn("Input file does not exist", envelope["error"]["message"])

    def test_non_docx_input_returns_input_error_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "input.txt"
            input_path.write_text("not a docx", encoding="utf-8")

            result = self.run_cli("atomize", str(input_path), "--out", str(tmp_path / "out"), "--quiet")

        self.assertEqual(result.returncode, 2)
        envelope = json.loads(result.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "input_error")
        self.assertIn("Only .docx input is supported", envelope["error"]["message"])

    def test_version_matches_version_module(self) -> None:
        from version import __version__

        result = self.run_cli("--version")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), __version__)


if __name__ == "__main__":
    unittest.main()
