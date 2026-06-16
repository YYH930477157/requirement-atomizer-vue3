from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

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

    def test_worker_stub_route_no_enrichment(self) -> None:
        from gui.pipeline_worker import AssembleSpecWorker
        from tests.test_assemble_spec import write_fixture

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            worker = AssembleSpecWorker(out_dir=out, formats=["md"], enrich_route="stub")
            finished: list[dict] = []
            worker.finished.connect(finished.append)
            worker.failed.connect(lambda m: self.fail(m))
            worker.run()
            self.assertTrue(finished)
            self.assertEqual(finished[0]["breakdown"]["enrich"]["route"], "stub")  # 不勾=stub、零网络

    def test_worker_passes_enrich_route_to_assembly(self) -> None:
        # 验证 GUI 接线：勾选 → worker→assemble→enrich_requirement_lists 收到 openai_compatible。
        # 富化引擎本身已在 tests/test_spec_enrich.py 用真 mock HTTP 全管道测过，此处只测透传。
        import spec_enrich
        from gui.pipeline_worker import AssembleSpecWorker
        from tests.test_assemble_spec import write_fixture

        seen: dict[str, Any] = {}

        def spy(requirement_lists, *, out_dir, route, pipeline_path=None):  # noqa: ANN001
            seen["route"] = route
            return {"enriched": 2, "rejected": 1, "failed": 0, "route": "openai_compatible"}

        orig = spec_enrich.enrich_requirement_lists
        spec_enrich.enrich_requirement_lists = spy
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                write_fixture(out)
                worker = AssembleSpecWorker(out_dir=out, formats=["md"], enrich_route="openai_compatible")
                finished: list[dict] = []
                worker.finished.connect(finished.append)
                worker.failed.connect(lambda m: self.fail(m))
                worker.run()
        finally:
            spec_enrich.enrich_requirement_lists = orig

        self.assertEqual(seen.get("route"), "openai_compatible")        # 透传到富化层
        self.assertTrue(finished)
        self.assertEqual(finished[0]["breakdown"]["enrich"]["route"], "openai_compatible")

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
