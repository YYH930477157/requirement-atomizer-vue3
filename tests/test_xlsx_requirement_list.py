"""Tests for xlsx_requirement_list.py (A6)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from xlsx_requirement_list import (
    BASE_LIBRARY_CANDIDATES_FILE,
    XLSX_REQUIREMENT_LIST_SWITCH,
    extract_requirement_list_candidates,
    requirement_list_enabled,
    write_base_library_candidates,
)


class RequirementListDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_requirement_list_xlsx(self) -> Path:
        path = Path(self.tmpdir.name) / "reqs.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "系统需求"
        ws.append(["子模块", "描述", "需求模版"])
        ws.append(["计量", "电表应支持事件记录", "The meter shall support event logging"])
        ws.append(["显示", "屏幕应显示当前时间", "The display shall show current time"])
        wb.save(path)
        wb.close()
        return path

    def _make_param_matrix_xlsx(self) -> Path:
        path = Path(self.tmpdir.name) / "params.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "参数矩阵"
        ws.append(["Parameter", "Value", "Unit"])
        ws.append(["Voltage", "230", "V"])
        wb.save(path)
        wb.close()
        return path

    def test_detects_requirement_list_rows(self):
        path = self._make_requirement_list_xlsx()
        candidates = extract_requirement_list_candidates(path)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["title"], "电表应支持事件记录")
        self.assertEqual(candidates[0]["module"], "系统需求")

    def test_param_matrix_returns_empty(self):
        path = self._make_param_matrix_xlsx()
        candidates = extract_requirement_list_candidates(path)
        self.assertEqual(candidates, [])

    def test_write_candidates(self):
        out_dir = Path(self.tmpdir.name)
        candidates = [{"title": "T", "description": "D", "module": "M"}]
        path = write_base_library_candidates(out_dir, candidates)
        self.assertEqual(path.name, BASE_LIBRARY_CANDIDATES_FILE)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        loaded = json.loads(lines[0])
        self.assertEqual(loaded["title"], "T")

    def test_switch_default_off(self):
        os.environ.pop(XLSX_REQUIREMENT_LIST_SWITCH, None)
        self.assertFalse(requirement_list_enabled())
        os.environ[XLSX_REQUIREMENT_LIST_SWITCH] = "1"
        self.assertTrue(requirement_list_enabled())


if __name__ == "__main__":
    unittest.main()
