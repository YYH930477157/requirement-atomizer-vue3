from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import spec_export


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> None:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"stable_req_id": "O-CLOCK", "requirement_type": "cosem_object_instance",
         "object": "Clock", "domain": "time", "source_refs": ["TBL-1"], "section_path": ["Time"]},
        {"stable_req_id": "A-CLOCK", "requirement_type": "cosem_attribute_access",
         "object": "Clock.time", "source_refs": ["TBL-2"], "verification_method": "configuration_check"},
        {"stable_req_id": "ASM-1", "requirement_type": "association_security_matrix",
         "object": "ClientA", "source_refs": ["TBL-3"]},
        {"stable_req_id": "F-1", "requirement_type": "functional", "object": "Counter",
         "requirement": "The meter must reset to 0 per IEC 62056-5-3.", "source_refs": ["BLK-1"],
         "section_path": ["Behaviour"]},
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {"item_id": "TBL-1", "fields": {"Object/attribute name": "Clock", "CL": "8", "Value": "0-0:1.0.0.255"}},
        {"item_id": "TBL-2", "fields": {"#": "1", "Object/attribute name": "time", "Type": "octet-string",
                                         "Value": "00", "Access rights RC/PC/SC/LC": "R-/RW/--/R-"}},
        {"item_id": "TBL-3", "fields": {"Customer application process": "ClientA",
                                         "Server application process / Management Logical Device": "HLS"}},
    ])
    write_jsonl(out_dir / "blocks.jsonl", [
        {"block_id": "BLK-1", "type": "paragraph", "section_path": ["Behaviour"],
         "text": "The counter behaviour follows IEC 62056-5-3."},
        {"block_id": "BLK-2", "type": "heading", "section_path": ["Normative references"],
         "text": "IEC 62056-5-3, Electricity metering - Part 5-3: COSEM application layer"},
    ])


class SpecExportTests(unittest.TestCase):
    def test_exports_md_and_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            written = spec_export.export_spec(out, formats=["md", "docx"])
            self.assertEqual(set(written), {"dlms_cosem_spec.md", "dlms_cosem_spec.docx"})
            self.assertTrue((out / "dlms_cosem_spec.md").exists())
            self.assertTrue((out / "dlms_cosem_spec.docx").exists())

    def test_markdown_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            spec_export.export_spec(out, formats=["md"])
            md = (out / "dlms_cosem_spec.md").read_text(encoding="utf-8")

        self.assertIn("# DLMS/COSEM 实现规格", md)
        self.assertRegex(md, r"## .+（\d+）")                     # 功能域分组标题带计数
        self.assertRegex(md, r"### REQ-\d{3} ")                    # 需求条目
        self.assertIn("**溯源**", md)                              # 溯源段
        self.assertIn("| # | 属性 | 类型 |", md)                   # threshold 表渲染
        self.assertIn("附录 A：外部规范交叉引用", md)              # P4 附录
        self.assertIn("IEC 62056-5-3", md)                        # 外部规范被列出

    def test_docx_opens_with_headings_and_tables(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            spec_export.export_spec(out, formats=["docx"])
            document = Document(str(out / "dlms_cosem_spec.docx"))

        self.assertGreater(len(document.paragraphs), 0)
        self.assertGreater(len(document.tables), 0)               # 至少一个属性/矩阵表
        self.assertTrue(any("DLMS/COSEM 实现规格" in p.text for p in document.paragraphs))

    def test_unknown_format_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            with self.assertRaises(ValueError):
                spec_export.export_spec(out, formats=["pdf"])

    def test_reuses_existing_assembled_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # 预置一份最小装配 JSON，断言导出直接复用它（不依赖原子文件）
            (out / "dlms_cosem_spec_requirements.json").write_text(json.dumps({
                "meta": {"source": "preset", "extracted_at": "t", "target_standards": ["X"]},
                "requirements": [{"id": "REQ-001", "title": "T", "description": "D", "type": "functional",
                                  "priority": "P1", "status": "draft", "source_section": "S",
                                  "source_quote": "Q", "threshold_table": None,
                                  "acceptance_criteria": ["c1"], "labels": ["安全"], "notes": ""}],
                "analysis": {"total_count": 1, "by_priority": {"P1": 1}, "by_type": {"functional": 1},
                             "coverage_report": "rpt", "gaps": []},
            }, ensure_ascii=False), encoding="utf-8")
            spec_export.export_spec(out, formats=["md"])
            md = (out / "dlms_cosem_spec.md").read_text(encoding="utf-8")
        self.assertIn("preset", md)
        self.assertIn("## 安全（1）", md)


if __name__ == "__main__":
    unittest.main()
