"""requirements_analysis_excel 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path

from openpyxl import load_workbook

from requirements_analysis_excel import write_software_requirements_xlsx


class SheetTitleTests(unittest.TestCase):
    def test_sheet_titles_are_unique_and_excel_safe(self) -> None:
        long = "A" * 40
        items = [
            {"ownership": "software", "module": long + "x", "description": "one"},
            {"ownership": "software", "module": long + "y", "description": "two"},
        ]

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                write_software_requirements_xlsx(items, tmp_path / "software.xlsx")

            assert not [w for w in caught if "Title is more than 31 characters" in str(w.message)]
            wb = load_workbook(tmp_path / "software.xlsx", data_only=True)
            assert len(set(wb.sheetnames)) == 2
            assert all(len(name) <= 31 for name in wb.sheetnames)

    def test_sheet_titles_are_unique_case_insensitively(self) -> None:
        items = [
            {"ownership": "software", "module": "a" * 31, "description": "one"},
            {"ownership": "software", "module": "A" * 31, "description": "two"},
        ]

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                write_software_requirements_xlsx(items, tmp_path / "software.xlsx")

            assert not [w for w in caught if "Title is more than 31 characters" in str(w.message)]
            wb = load_workbook(tmp_path / "software.xlsx", data_only=True)
            lowered = [name.casefold() for name in wb.sheetnames]
            assert len(set(lowered)) == 2
            assert all(len(name) <= 31 for name in wb.sheetnames)


class CellSafetyTests(unittest.TestCase):
    def test_formula_injection_is_neutralized(self) -> None:
        """交付研发的工作簿零活公式（spec-data-integrity 同一红线；此前缺 formula_safe 被复引入）。"""
        items = [{
            "ownership": "software", "module": "计量",
            "description": '=HYPERLINK("http://evil.example/x","点我")',
            "requirement": "+A1+A2",
            "developer_guidance": ["-2+3+cmd|' /C calc'!A0"],
        }]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "software.xlsx"
            write_software_requirements_xlsx(items, path)
            wb = load_workbook(path)
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        assert cell.data_type != "f", f"live formula at {ws.title}!{cell.coordinate}"
                        if isinstance(cell.value, str):
                            assert not cell.value.startswith("=")

    def test_control_characters_are_scrubbed(self) -> None:
        """PDF 文本层常见控制字符（\\x0b 等）会让 openpyxl 抛 IllegalCharacterError——写入前剥离。"""
        items = [{
            "ownership": "software", "module": "计量",
            "description": "before\x0bafter\x00tail",
            "source_quote": "quote\x0ehere",
        }]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "software.xlsx"
            write_software_requirements_xlsx(items, path)  # 不抛即胜一半
            wb = load_workbook(path)
            texts = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]
            assert any("beforeafter" in t for t in texts)  # 控制字符被剥、正文保留


if __name__ == "__main__":
    unittest.main()
