from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_pipeline import write_jsonl


class DesktopTaskTests(unittest.TestCase):
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
        review.assert_called_once_with(out_dir.resolve())

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


if __name__ == "__main__":
    unittest.main()
