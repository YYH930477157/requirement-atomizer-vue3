from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tests.docx_fixtures import write_minimal_docx


ROOT = Path(__file__).resolve().parents[1]


class MockReviewService:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.requests: list[dict[str, Any]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                service.requests.append(body)
                if service.fail:
                    payload = {"error": "unavailable"}
                    status = 500
                else:
                    status = 200
                    payload = {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "decision": "accept",
                                            "risk": "low_risk",
                                            "confidence": 0.91,
                                            "review_notes": ["mock review"],
                                            "expert_questions": [],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                body_bytes = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> "MockReviewService":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def write_review_pipeline(path: Path, base_url: str) -> None:
    path.write_text(
        f"""
schema_version: "0.2"
pipeline_id: "cli_review_pipeline"
model_routes:
  default: "stub"
  openai_compatible:
    base_url: "{base_url}"
    model: "cli-mock-model"
    api_key_env: ""
    temperature: 0.0
    timeout_s: 2
    max_retries: 0
    concurrency: 2
review_scope:
  mode: all
  confidence_below: 0.75
  always_review_ambiguous: true
  always_review_source_types: ["paragraph", "table_row"]
  always_review_types: []
model_routing:
  low_risk:
    provider: "stub"
    model: "local-rule-reviewer"
  high_risk:
    provider: "stub"
    model: "local-strict-reviewer"
risk_policy:
  high_risk_types: []
  low_confidence_threshold: 0.75
""".strip()
        + "\n",
        encoding="utf-8",
    )


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

    def test_review_openai_route_reports_llm_review_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            write_minimal_docx(input_path)
            atomize = self.run_cli("run", str(input_path), "--out", str(out_dir), "--skip-review", "--quiet")
            self.assertEqual(atomize.returncode, 0, atomize.stderr)

            with MockReviewService() as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_review_pipeline(pipeline_path, service.base_url)
                result = self.run_cli(
                    "review",
                    "--out",
                    str(out_dir),
                    "--review-pipeline",
                    str(pipeline_path),
                    "--llm-route",
                    "openai_compatible",
                    "--review-scope",
                    "all",
                    "--quiet",
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["review"]["llm_reviewed"], 2)
        self.assertEqual(envelope["review"]["rule_stub"], 0)
        self.assertEqual(envelope["review"]["llm_failed"], 0)

    def test_review_openai_route_unavailable_returns_llm_error_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            rows = [
                {
                    "req_id": f"AREQ-{index:06d}",
                    "stable_req_id": f"SREQ-00000000000002{index:02X}",
                    "source_id": f"SRC-{index}",
                    "source_type": "paragraph",
                    "source_refs": [f"SRC-{index}"],
                    "section_path": ["Scope"],
                    "domain": "dlms_cosem",
                    "object": "",
                    "requirement_type": "event_definition",
                    "requirement": f"Requirement {index} shall be reviewed.",
                    "parameters": {},
                    "verification_method": "test",
                    "ambiguity": False,
                    "review_questions": [],
                    "confidence": 0.70,
                    "kb_matches": [],
                    "generated_by": "rule_based_atomizer_v1",
                }
                for index in range(6)
            ]
            with (out_dir / "atomic_requirements.jsonl").open("w", encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

            with MockReviewService(fail=True) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_review_pipeline(pipeline_path, service.base_url)
                result = self.run_cli(
                    "review",
                    "--out",
                    str(out_dir),
                    "--review-pipeline",
                    str(pipeline_path),
                    "--llm-route",
                    "openai_compatible",
                    "--review-scope",
                    "all",
                    "--quiet",
                )

        self.assertEqual(result.returncode, 4)
        envelope = json.loads(result.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "llm_error")

    def test_review_openai_route_small_batch_unavailable_returns_llm_error_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            rows = [
                {
                    "req_id": f"AREQ-{index:06d}",
                    "stable_req_id": f"SREQ-00000000000004{index:02X}",
                    "source_id": f"SRC-{index}",
                    "source_type": "paragraph",
                    "source_refs": [f"SRC-{index}"],
                    "section_path": ["Scope"],
                    "domain": "dlms_cosem",
                    "object": "",
                    "requirement_type": "event_definition",
                    "requirement": f"Requirement {index} shall be reviewed.",
                    "parameters": {},
                    "verification_method": "test",
                    "ambiguity": False,
                    "review_questions": [],
                    "confidence": 0.70,
                    "kb_matches": [],
                    "generated_by": "rule_based_atomizer_v1",
                }
                for index in range(2)
            ]
            with (out_dir / "atomic_requirements.jsonl").open("w", encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

            with MockReviewService(fail=True) as service:
                pipeline_path = tmp_path / "review_pipeline.yaml"
                write_review_pipeline(pipeline_path, service.base_url)
                result = self.run_cli(
                    "review",
                    "--out",
                    str(out_dir),
                    "--review-pipeline",
                    str(pipeline_path),
                    "--llm-route",
                    "openai_compatible",
                    "--review-scope",
                    "all",
                    "--quiet",
                )

        self.assertEqual(result.returncode, 4)
        envelope = json.loads(result.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["type"], "llm_error")

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
