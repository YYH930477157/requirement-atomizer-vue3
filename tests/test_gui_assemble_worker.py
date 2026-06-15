from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = importlib.util.find_spec("PySide6")


@unittest.skipIf(pyside6 is None, "PySide6 not installed")
class AssembleSpecWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_worker_assembles_and_writes_outputs(self) -> None:
        from gui.pipeline_worker import AssembleSpecWorker
        from tests.test_assemble_spec import write_fixture

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            worker = AssembleSpecWorker(out_dir=out)
            stages: list[str] = []
            finished: list[dict] = []
            failures: list[str] = []
            worker.stage.connect(stages.append)
            worker.finished.connect(finished.append)
            worker.failed.connect(failures.append)

            worker.run()

            self.assertEqual(failures, [])
            self.assertTrue(finished)
            payload = finished[0]
            self.assertEqual(payload["kind"], "assemble")
            self.assertGreater(payload["count"], 0)
            # 机器格式 JSON 落盘（喂公司工具链）
            self.assertTrue((out / "dlms_cosem_spec_requirements.json").exists())
            # 人读导出 Excel + Word + Markdown 落盘
            self.assertTrue((out / "dlms_cosem_spec.xlsx").exists())
            self.assertTrue((out / "dlms_cosem_spec.docx").exists())
            self.assertTrue((out / "dlms_cosem_spec.md").exists())
            written_names = {Path(p).name for p in payload["written"]}
            self.assertEqual(
                written_names,
                {
                    "dlms_cosem_spec_requirements.json",
                    "dlms_cosem_spec.xlsx",
                    "dlms_cosem_spec.docx",
                    "dlms_cosem_spec.md",
                },
            )

    def test_worker_md_only_skips_docx(self) -> None:
        from gui.pipeline_worker import AssembleSpecWorker
        from tests.test_assemble_spec import write_fixture

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            worker = AssembleSpecWorker(out_dir=out, formats=["md"])
            finished: list[dict] = []
            failures: list[str] = []
            worker.finished.connect(finished.append)
            worker.failed.connect(failures.append)

            worker.run()

            self.assertEqual(failures, [])
            self.assertTrue((out / "dlms_cosem_spec.md").exists())
            self.assertFalse((out / "dlms_cosem_spec.docx").exists())


if __name__ == "__main__":
    unittest.main()
