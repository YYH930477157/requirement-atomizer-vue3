from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import ANY, patch

from llm_pipeline import write_jsonl


class DesktopTaskTests(unittest.TestCase):
    def test_run_pipeline_task_uses_default_kbs_when_not_supplied(self) -> None:
        from desktop_tasks import run_pipeline_task

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            input_path.write_text("placeholder", encoding="utf-8")
            out_dir.mkdir()

            with (
                patch("desktop_tasks.default_kb_paths") as default_kb_paths,
                patch("desktop_tasks.run_atomizer_pipeline") as atomize,
            ):
                default_kb_paths.return_value = [root / "default-a.json", root / "default-b.json"]
                atomize.return_value = {"counts": {"atomic_requirements": 0}}
                write_jsonl(out_dir / "atomic_requirements.jsonl", [])

                run_pipeline_task(input_path, out_dir, skip_review=True)

        atomize.assert_called_once()
        self.assertEqual(atomize.call_args.kwargs["kb_paths"], [root / "default-a.json", root / "default-b.json"])

    def test_run_pipeline_task_writes_outputs_and_review_summary(self) -> None:
        from desktop_tasks import run_pipeline_task

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            input_path.write_text("placeholder", encoding="utf-8")
            out_dir.mkdir()

            with patch("desktop_tasks.run_atomizer_pipeline") as atomize, patch("desktop_tasks.run_review_pipeline") as review:
                atomize.return_value = {
                    "input": str(input_path),
                    "output_dir": str(out_dir),
                    "counts": {"atomic_requirements": 2},
                }
                review.return_value = {"reviews": 2, "accepted": 1, "expert_pending": 1}
                write_jsonl(
                    out_dir / "atomic_requirements.jsonl",
                    [
                        {"stable_req_id": "SREQ-1", "requirement_type": "functional", "confidence": 0.9},
                        {"stable_req_id": "SREQ-2", "requirement_type": "security", "confidence": 0.7},
                    ],
                )
                write_jsonl(
                    out_dir / "review_states.jsonl",
                    [
                        {"requirement_id": "SREQ-1", "status": "accepted"},
                        {"requirement_id": "SREQ-2", "status": "expert_pending"},
                    ],
                )

                payload = run_pipeline_task(input_path, out_dir, skip_review=False)

        self.assertEqual(payload["kind"], "pipeline")
        self.assertEqual(payload["manifest"]["counts"]["atomic_requirements"], 2)
        self.assertEqual(payload["review"]["reviews"], 2)
        self.assertEqual(payload["summary"]["counts"]["requirements"], 2)
        self.assertEqual(payload["summary"]["status_counts"]["accepted"], 1)
        atomize.assert_called_once()
        review.assert_called_once_with(out_dir.resolve(), route=None, scope=None, llm_review_limit=0, progress_callback=ANY)

    def test_main_run_command_passes_kb_and_domain_pack_to_pipeline(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            kb_path = root / "kb.json"
            domain_pack = root / "domain_packs" / "dlms_cosem"
            input_path.write_text("placeholder", encoding="utf-8")
            kb_path.write_text("{}", encoding="utf-8")
            domain_pack.mkdir(parents=True)

            with patch("desktop_tasks.run_pipeline_task") as run_pipeline:
                run_pipeline.return_value = {"kind": "pipeline", "out_dir": str(out_dir), "summary": {}}

                with redirect_stdout(io.StringIO()):
                    exit_code = desktop_tasks.main([
                        "run",
                        "--input",
                        str(input_path),
                        "--out",
                        str(out_dir),
                        "--chunk-chars",
                        "1200",
                        "--kb",
                        str(kb_path),
                        "--domain-pack",
                        str(domain_pack),
                    ])

        self.assertEqual(exit_code, 0)
        run_pipeline.assert_called_once_with(
            input_path,
            out_dir,
            skip_review=False,
            llm_route=None,
            review_scope=None,
            llm_review_limit=0,
            chunk_chars=1200,
            kb_paths=[kb_path],
            domain_pack_dir=domain_pack,
        )

    def test_export_task_returns_written_files(self) -> None:
        from desktop_tasks import export_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.export_requirements") as export_requirements:
                export_requirements.return_value = ["requirements_export.csv", "requirements_export.md"]

                payload = export_task(out_dir, ["csv", "md"])

        self.assertEqual(payload["kind"], "export")
        self.assertEqual(payload["written"], ["requirements_export.csv", "requirements_export.md"])
        export_requirements.assert_called_once_with(out_dir.resolve(), formats=["csv", "md"])

    def test_assemble_task_writes_json_and_exports_formats(self) -> None:
        from desktop_tasks import ASSEMBLED_JSON, assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.assemble") as assemble, patch("desktop_tasks.export_spec") as export_spec:
                assemble.return_value = ({"requirements": [{"id": "REQ-1"}], "analysis": {"total_count": 1}}, {"安全": 1})
                export_spec.return_value = ["dlms_cosem_spec_requirements.md"]

                payload = assemble_task(out_dir, formats=["md"])

            assembled = json.loads((out_dir / ASSEMBLED_JSON).read_text(encoding="utf-8"))

        self.assertEqual(payload["kind"], "assemble")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(assembled["requirements"][0]["id"], "REQ-1")
        self.assertIn(str(out_dir / ASSEMBLED_JSON), payload["written"])
        self.assertIn(str(out_dir / "dlms_cosem_spec_requirements.md"), payload["written"])
        export_spec.assert_called_once()

    def test_compose_task_writes_engineering_requirement_outputs(self) -> None:
        from desktop_tasks import compose_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with (
                patch("desktop_tasks.compose_engineering_requirements") as compose,
                patch("desktop_tasks.write_engineering_requirements") as write_outputs,
            ):
                compose.return_value = {
                    "analysis": {"requirement_functions": 2, "dlms_objects": 3},
                    "requirement_functions": [{}, {}],
                    "dlms_objects": [{}, {}, {}],
                }
                write_outputs.return_value = [
                    "engineering_requirements/engineering_requirements.json",
                    "engineering_requirements/requirement_functions.md",
                    "engineering_requirements/dlms_objects.md",
                ]

                payload = compose_task(out_dir)

        self.assertEqual(payload["kind"], "compose")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["analysis"]["dlms_objects"], 3)
        self.assertIn("engineering_requirements/requirement_functions.md", payload["written"])
        compose.assert_called_once_with(out_dir.resolve())
        write_outputs.assert_called_once_with(out_dir.resolve(), compose.return_value)

    def test_main_compose_command_runs_engineering_composer(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.compose_task") as compose:
                compose.return_value = {"kind": "compose", "out_dir": str(out_dir), "count": 1, "written": []}

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main(["compose", "--out", str(out_dir)])

        self.assertEqual(exit_code, 0)
        compose.assert_called_once_with(out_dir)
        self.assertEqual(json.loads(stdout.getvalue())["kind"], "compose")


if __name__ == "__main__":
    unittest.main()
