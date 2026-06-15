from __future__ import annotations

import importlib.util
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = importlib.util.find_spec("PySide6")

SAMPLE_DOC = {
    "meta": {"source": "sample"},
    "analysis": {"total_count": 2},
    "requirements": [
        {
            "id": "REQ-001", "title": "Clock", "description": "实现时钟对象。",
            "priority": "P1", "labels": ["时钟"], "source_section": "4.1",
            "source_quote": "Clock shall be defined.",
            "threshold_table": {"description": "属性", "columns": ["#", "属性"], "rows": [["1", "time"]]},
            "acceptance_criteria": ["读取 logical_name"],
        },
        {
            "id": "REQ-002", "title": "Security Setup", "description": "实现安全设置。",
            "priority": "P0", "labels": ["安全"], "source_section": "5.2",
            "source_quote": "Security setup shall exist.", "threshold_table": None,
            "acceptance_criteria": [],
        },
    ],
}


@unittest.skipIf(pyside6 is None, "PySide6 not installed")
class SpecBrowserDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_groups_by_domain_and_populates_sections(self) -> None:
        from gui.spec_view import SpecBrowserDialog

        dlg = SpecBrowserDialog(SAMPLE_DOC)
        domains = [d for d, _ in dlg.groups]
        self.assertIn("时钟", domains)
        self.assertIn("安全", domains)
        self.assertEqual(dlg.section_list.count(), len(dlg.groups))
        # 切到每个段都不应崩（含 threshold_table 渲染）
        for row in range(dlg.section_list.count()):
            dlg.show_section(row)
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
