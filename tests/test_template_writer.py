"""模板成文器回归：分析结果按 V2.3.x 格式追加进对应模块 sheet（模板=格式，非问题库）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

import template_writer as tw


def make_template(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "时钟需求"
    ws.append(["关闭", "序号", "子模块", "描述", "需求模版", "需求", "说明、示例、注意事项",
               "是否客户需求", "客户需求章节", "驱动/硬件相关"])
    ws.append(["", 1, "时钟", "历法：", "公历", "公历", "", "", "", ""])
    ws.append(["", 2, "时钟", "夏令时：", "支持", "支持", "", "", "", ""])
    ws2 = wb.create_sheet("事件需求")
    ws2.append(["关闭", "序号", "子模块", "描述", "需求模版", "需求", "说明、示例、注意事项",
                "是否客户需求", "客户需求章节", "驱动/硬件相关"])
    wb.save(path)


def item(module: str, desc: str, *, ownership: str = "software", seq_hint: int = 0,
         text: str = "", section: str = "7.9") -> dict:
    return {
        "analysis_id": f"AN-{seq_hint:03d}", "module": module, "submodule": module,
        "description": desc, "requirement": text or f"{desc} 原始正文",
        "software_requirement_text": text, "developer_guidance": ["实现要点甲"],
        "acceptance_criteria": [], "open_questions": [], "notes": [],
        "threshold_table": None, "ownership": ownership, "source_quote": "quoted words",
        "source_section": section,
    }


class TargetSheetTests(unittest.TestCase):
    def test_module_routes_to_sheet(self) -> None:
        names = ["时钟需求", "事件需求"]
        self.assertEqual(tw.target_sheet({"module": "时钟"}, names), "时钟需求")
        self.assertEqual(tw.target_sheet({"module": "事件记录"}, names), "事件需求")

    def test_submodule_fallback_then_fallback_sheet(self) -> None:
        names = ["时钟需求"]
        self.assertEqual(tw.target_sheet({"module": "未映射", "submodule": "时钟"}, names), "时钟需求")
        self.assertEqual(tw.target_sheet({"module": "安全"}, names), tw.FALLBACK_SHEET)


class AppendTests(unittest.TestCase):
    def test_appends_rows_with_continued_seq_and_full_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            out = Path(td) / "written.xlsx"
            make_template(template)
            items = [item("时钟", "时钟精度要求", text="时钟精度须优于 5 s/天", seq_hint=1)]
            report = tw.append_analysis_to_template(template, items, out)

            wb = load_workbook(out)
            ws = wb["时钟需求"]
            self.assertEqual(ws.cell(row=4, column=2).value, 3)              # 序号接着 2 继续
            self.assertEqual(ws.cell(row=4, column=3).value, "时钟")
            self.assertEqual(ws.cell(row=4, column=4).value, "时钟精度要求")
            self.assertEqual(ws.cell(row=4, column=6).value, "时钟精度须优于 5 s/天")
            self.assertIn("实现要点甲", str(ws.cell(row=4, column=7).value))  # 说明含研发指引
            self.assertEqual(ws.cell(row=4, column=8).value, "是")
            self.assertEqual(ws.cell(row=4, column=9).value, "7.9")
            self.assertEqual(ws.cell(row=2, column=6).value, "公历")          # 模板已有行原样
            self.assertEqual(report["appended_by_sheet"], {"时钟需求": 1})

    def test_hardware_skipped_codesign_marked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            out = Path(td) / "written.xlsx"
            make_template(template)
            items = [item("时钟", "硬件 RTC 选型", ownership="hardware", seq_hint=1),
                     item("时钟", "温补校准", ownership="co_design", seq_hint=2)]
            report = tw.append_analysis_to_template(template, items, out)
            self.assertEqual(report["skipped_hardware"], 1)                  # 硬件独占不进列表
            ws = load_workbook(out)["时钟需求"]
            self.assertEqual(ws.cell(row=4, column=4).value, "温补校准")
            self.assertEqual(ws.cell(row=4, column=10).value, "是")          # 协同标驱动/硬件相关

    def test_compliance_is_defensively_excluded_from_software_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            out = Path(td) / "written.xlsx"
            make_template(template)
            compliance = item("测试合规", "型式证书", seq_hint=1)
            compliance["source_requirement_type"] = "compliance"

            report = tw.append_analysis_to_template(template, [compliance], out)

            self.assertEqual(report["appended_total"], 0)
            self.assertEqual(report["skipped_compliance"], 1)
            self.assertNotIn(tw.FALLBACK_SHEET, load_workbook(out).sheetnames)

    def test_unmapped_module_lands_in_fallback_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            out = Path(td) / "written.xlsx"
            make_template(template)
            tw.append_analysis_to_template(template, [item("安全", "HLS 认证", seq_hint=1)], out)
            wb = load_workbook(out)
            self.assertIn(tw.FALLBACK_SHEET, wb.sheetnames)
            ws = wb[tw.FALLBACK_SHEET]
            self.assertEqual(ws.cell(row=2, column=4).value, "HLS 认证")

    def test_formula_neutralized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            out = Path(td) / "written.xlsx"
            make_template(template)
            evil = item("时钟", "=1+1 注入", text="=HYPERLINK() 也不行", seq_hint=1)
            tw.append_analysis_to_template(template, [evil], out)
            ws = load_workbook(out)["时钟需求"]
            self.assertNotEqual(ws.cell(row=4, column=4).data_type, "f")
            self.assertNotEqual(ws.cell(row=4, column=6).data_type, "f")

    def test_notes_column_inherits_hardware_dependency(self) -> None:
        """审计 P1-b：template_writer 走 _notes_text——硬件依赖（含待澄清标注）自动落成文列。"""
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            out = Path(td) / "written.xlsx"
            make_template(template)
            row = item("时钟", "温补校准", ownership="co_design", seq_hint=1)
            row["hardware_dependency"] = "需温补晶振"
            tw.append_analysis_to_template(template, [row], out)
            ws = load_workbook(out)["时钟需求"]
            self.assertIn("硬件依赖：需温补晶振", str(ws.cell(row=4, column=7).value))


class RunWriterTests(unittest.TestCase):
    def test_end_to_end_reads_analysis_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            template = out / "t.xlsx"
            make_template(template)
            payload = {"route": "openai_compatible",
                       "items": [item("时钟", "时钟精度要求", text="精度 5 s/天", seq_hint=1),
                                 item("事件记录", "失压事件记录", seq_hint=2)]}
            (out / "engineering_analysis.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            report = tw.run_writer(out, template)

            self.assertEqual(report["appended_total"], 2)
            self.assertEqual(report["appended_by_sheet"],
                             {"时钟需求": 1, "事件需求": 1})
            self.assertTrue((out / tw.WRITTEN_WORKBOOK).exists())
            saved = json.loads((out / tw.WRITER_REPORT).read_text(encoding="utf-8"))
            self.assertEqual(saved["analysis_route"], "openai_compatible")

    def test_missing_analysis_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "t.xlsx"
            make_template(template)
            with self.assertRaises(FileNotFoundError):
                tw.run_writer(Path(td), template)


class PendingPresentationTests(unittest.TestCase):
    """v3（Task4）：待核行红字 + 「守恒待核」清单 sheet；干净工作簿零漂移。"""

    def test_pending_row_is_red_and_sheet_lists_fre(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tpl = root / "tpl.xlsx"
            make_template(tpl)
            row = item("事件记录", "记录事件", text="电表应记录事件", seq_hint=1)
            row["functional_requirement_id"] = "F1"
            row["conservation_pending"] = {"classes": ["binding"]}
            out = root / "软件需求列表-成文.xlsx"
            report = tw.append_analysis_to_template(tpl, [row], out)
            wb = load_workbook(out)
            self.assertIn("守恒待核", wb.sheetnames)
            ws = wb["事件需求"]
            # 追加行 = 模板表头后第一条新数据（事件需求夹具无样例数据行）
            notes_cell = ws.cell(row=2, column=7)
            self.assertIn("⚠待核", str(notes_cell.value or ""))
            self.assertEqual(str(notes_cell.font.color.rgb), "FFFF0000")
            body_cell = ws.cell(row=2, column=6)
            self.assertTrue(str(body_cell.value or "").strip())
            self.assertEqual(str(body_cell.font.color.rgb), "FFFF0000")
            seq_cell = ws.cell(row=2, column=2)
            self.assertEqual(str(seq_cell.font.color.rgb), "FFFF0000")
            pending = wb["守恒待核"]
            blob = " ".join(
                str(c or "") for r in pending.iter_rows(values_only=True) for c in r)
            self.assertIn("F1", blob)
            self.assertIn("不得作为已验收交付", blob)
            self.assertGreater(
                int((report.get("conservation_pending_export") or {}).get(
                    "pending_sheet_rows") or 0), 0)

    def test_gap_rows_rendered_without_fre_rows(self) -> None:
        """零 FRE 缺口只进清单 sheet，不进需求 sheet（appended_total 不变）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tpl = root / "tpl.xlsx"
            make_template(tpl)
            row = item("事件记录", "记录事件", text="电表应记录事件", seq_hint=1)
            row["functional_requirement_id"] = "F1"
            gaps = [{"category": "clause_gap", "reason": "条款块无任何功能需求声明",
                     "section_id": "4.9", "functional_requirement_id": "",
                     "token": "", "detail": "Spare"}]
            out = root / "out.xlsx"
            report = tw.append_analysis_to_template(tpl, [row], out, gap_rows=gaps)
            self.assertEqual(report["appended_total"], 1, "缺口不追加需求行")
            wb = load_workbook(out)
            self.assertIn("守恒待核", wb.sheetnames)
            pending = wb["守恒待核"]
            data = [
                r for r in pending.iter_rows(min_row=3, values_only=True)
                if r and any(c not in (None, "") for c in r)
            ]
            self.assertTrue(data, "清单应有缺口数据行")
            # 与 FRE 行同形：类别=人读标签，原因=机键（不得把 clause_gap 给人看）
            self.assertEqual(data[0][0], "条款缺口")
            self.assertEqual(data[0][1], "clause_gap")
            blob = " ".join(str(c or "") for r in data for c in r)
            self.assertIn("4.9", blob)
            block = report["conservation_pending_export"]
            self.assertEqual(block["gap_rows"], 1)
            # 该条目未挂 pending——清单只有缺口行；marked_rows=0 但 sheet 存在
            self.assertEqual(block["pending_sheet_rows"], 1)
            self.assertEqual(block["marked_rows"], 0)

    def test_clean_workbook_has_no_pending_sheet_or_red_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tpl = root / "tpl.xlsx"
            make_template(tpl)
            out = root / "out.xlsx"
            report = tw.append_analysis_to_template(
                tpl, [item("时钟", "历法", text="公历", seq_hint=1)], out)
            wb = load_workbook(out)
            self.assertNotIn("守恒待核", wb.sheetnames)
            self.assertIsNone(report.get("conservation_pending_export"))
            clock = wb["时钟需求"]
            # 模板样例行（row 2）不得被涂红
            sample = clock.cell(row=2, column=6)
            color = sample.font.color
            rgb = getattr(color, "rgb", None) if color is not None else None
            self.assertNotEqual(str(rgb or ""), "FFFF0000")


if __name__ == "__main__":
    unittest.main()
