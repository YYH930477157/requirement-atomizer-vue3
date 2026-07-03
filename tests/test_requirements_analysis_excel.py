import warnings
from pathlib import Path

from openpyxl import load_workbook

from requirements_analysis_excel import write_software_requirements_xlsx


def test_software_workbook_sheet_titles_are_unique_and_excel_safe(tmp_path: Path):
    long = "A" * 40
    items = [
        {"ownership": "software", "module": long + "x", "description": "one"},
        {"ownership": "software", "module": long + "y", "description": "two"},
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        write_software_requirements_xlsx(items, tmp_path / "software.xlsx")

    assert not [w for w in caught if "Title is more than 31 characters" in str(w.message)]
    wb = load_workbook(tmp_path / "software.xlsx", data_only=True)
    assert len(set(wb.sheetnames)) == 2
    assert all(len(name) <= 31 for name in wb.sheetnames)


def test_software_workbook_sheet_titles_are_unique_case_insensitively(tmp_path: Path):
    items = [
        {"ownership": "software", "module": "a" * 31, "description": "one"},
        {"ownership": "software", "module": "A" * 31, "description": "two"},
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        write_software_requirements_xlsx(items, tmp_path / "software.xlsx")

    assert not [w for w in caught if "Title is more than 31 characters" in str(w.message)]
    wb = load_workbook(tmp_path / "software.xlsx", data_only=True)
    lowered = [name.casefold() for name in wb.sheetnames]
    assert len(set(lowered)) == 2
    assert all(len(name) <= 31 for name in wb.sheetnames)
