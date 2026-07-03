from pathlib import Path

from openpyxl import Workbook

from requirements_analysis_template import (
    extract_template_vocabulary,
    fallback_template_vocabulary,
)


def test_extracts_sheet_modules_and_submodules(tmp_path: Path):
    path = tmp_path / "template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "时钟需求"
    ws.append(["关闭", "序号", "子模块", "描述", "需求"])
    ws.append(["", 1, "时钟", "夏令时：", "支持"])
    ws.append(["", 2, "时钟同步", "时区：", "东八区"])
    ws.append(["", 3, "时钟", "重复：", "忽略"])
    ws2 = wb.create_sheet("协议栈需求")
    ws2.append(["关闭", "序号", "子模块", "描述", "需求"])
    ws2.append(["", 1, "通信口1", "通信方式：", "Optical"])
    wb.save(path)

    vocab = extract_template_vocabulary(path)

    assert "时钟需求" in vocab["modules"]
    assert vocab["submodules_by_module"]["时钟需求"] == ["时钟", "时钟同步"]
    assert vocab["submodules_by_module"]["协议栈需求"] == ["通信口1"]


def test_fallback_vocabulary_contains_core_modules():
    vocab = fallback_template_vocabulary()

    assert "系统需求" in vocab["modules"]
    assert "协议栈需求" in vocab["modules"]
