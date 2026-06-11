from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = importlib.util.find_spec("PySide6")


@unittest.skipIf(pyside6 is None, "PySide6 not installed")
class GuiWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_pipeline_worker_emits_stage_and_finished_manifest(self) -> None:
        from gui.pipeline_worker import PipelineWorker
        from tests.docx_fixtures import write_minimal_docx

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal.docx"
            out_dir = tmp_path / "out"
            write_minimal_docx(input_path)
            worker = PipelineWorker(input_path=input_path, out_dir=out_dir)
            stages: list[str] = []
            finished: list[dict] = []
            failures: list[str] = []
            worker.stage.connect(stages.append)
            worker.finished.connect(finished.append)
            worker.failed.connect(failures.append)

            worker.run()

        self.assertEqual(failures, [])
        self.assertTrue(any("extracting docx" in stage for stage in stages))
        self.assertEqual(finished[0]["manifest"]["counts"]["atomic_requirements"], 2)


if __name__ == "__main__":
    unittest.main()
