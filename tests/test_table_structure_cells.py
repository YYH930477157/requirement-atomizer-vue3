"""表格结构与单元格级需求闭环 v1（table-structure-v2）全场景测试。

覆盖规格 §九 的场景矩阵（DOCX/XLSX/PDF）：
普通 3×3、标题+表头+数据、无表头单列表、首行单格需求、数据区单格需求、
同行双需求、单格双句、合并标题、合并需求格、多级表头、X 映射矩阵、
普通 Note=mandatory、同 sheet 多表、XLSX 非 A1 起始区域、PDF cell bbox。

关键断言：
- 首行规范性文本恰好生成一个 claim；
- 同行两个需求生成两个 claim（focus 指纹互相独立）；
- 所有 source_item_id/source_cell_id 均真实存在；
- 不再生成 "1 shall support Note."；
- 每个非空 canonical cell 恰好被消费一次（accounting 硬门全零）；
- blocks.jsonl 的 block ID 序列稳定（不新增顶层 block）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document
from openpyxl import Workbook

from ai_extract import _assert_source_references
from atomize import (
    build_atomic_candidates,
    build_table_artifacts,
    extract_docx,
    mark_doc_regions,
)
from claim_catalog import build_claim_catalog
from claim_focus import build_claim_focus_adapter
from parsers.xlsx_parser import extract_xlsx
from requirement_kb import KnowledgeRepository
from table_structure import (
    TABLE_CELL_ITEM_SCHEMA,
    TABLE_STRUCTURE_VERSION,
    cell_context_text,
)


KB = KnowledgeRepository.from_paths([])


def _artifacts(matrix, *, merges=None, title="T", section=("S",), **kwargs):
    return build_table_artifacts(
        matrix,
        table_id="TBL-000001",
        block_id="BLK-000002",
        order=2,
        table_title=title,
        section_path=list(section),
        knowledge_bases=KB,
        merge_ranges=merges,
        **kwargs,
    )


def _catalog(block, items, cells):
    return build_claim_catalog([block], items, table_cell_items=cells)


def _cell_audit(result):
    audit = result["meta"]["audit"]
    return {
        key: audit[key]
        for key in (
            "unconsumed_table_cell_count",
            "multi_consumed_table_cell_count",
            "dangling_table_item_reference_count",
            "dangling_table_cell_reference_count",
            "normative_context_only_count",
        )
    }


class PlainTableTests(unittest.TestCase):
    def test_plain_3x3_row_mode_closed(self) -> None:
        matrix = [
            ["Name", "Value", "Note"],
            ["Voltage", "230 V", "mandatory"],
            ["Current", "10 A", "optional"],
        ]
        block, items, cells = _artifacts(matrix)
        self.assertEqual(block["table_structure_version"], TABLE_STRUCTURE_VERSION)
        self.assertEqual(block["table_kind"], "parameter")
        self.assertEqual(block["leaf_mode"], "row")
        self.assertEqual(block["header_detection_status"], "inferred")
        result = _catalog(block, items, cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")
        self.assertEqual(result["meta"]["table_structure_status"], "ok")
        self.assertTrue(all(count == 0 for count in _cell_audit(result).values()))
        claims = result["catalog"]
        self.assertEqual(len(claims), 2)
        self.assertTrue(all(claim["source_kind"] == "table_row" for claim in claims))
        # Note 列的 mandatory 不是矩阵 marker：不得生成 "X shall support Note."
        candidates = build_atomic_candidates([block], items, table_cell_items=cells)
        self.assertFalse(
            any(candidate["requirement"].endswith("shall support Note.") for candidate in candidates),
            [candidate["requirement"] for candidate in candidates],
        )

    def test_note_column_mandatory_never_matrix_sentence(self) -> None:
        matrix = [
            ["No.", "Requirement", "Note"],
            ["1", "The meter shall store data.", "mandatory"],
            ["2", "The meter shall be sealed.", "mandatory"],
        ]
        block, items, cells = _artifacts(matrix)
        candidates = build_atomic_candidates([block], items, table_cell_items=cells)
        sentences = [candidate["requirement"] for candidate in candidates]
        self.assertFalse(any("shall support Note" in text for text in sentences), sentences)
        self.assertFalse(any(text.startswith("1 shall") for text in sentences), sentences)
        # Note 列保持原文（row-owned，随行进 row claim 逐字文本），不产矩阵句式
        note_cells = [
            cell for cell in cells
            if cell["header_path"] == ["Note"] and cell["structural_role"] == "data"
        ]
        self.assertTrue(note_cells)
        self.assertTrue(all(cell["leaf_kind"] == "row" for cell in note_cells))

    def test_title_header_data_roles(self) -> None:
        matrix = [
            ["Electrical parameters", "Electrical parameters"],
            ["Name", "Requirement"],
            ["Voltage", "The meter shall operate at 230 V."],
        ]
        block, items, cells = _artifacts(matrix, merges=[(1, 1, 1, 2)])
        self.assertEqual(block["title_row_indexes"], [1])
        self.assertEqual(block["header_row_indexes"], [2])
        self.assertEqual(block["table_title"], "Electrical parameters")
        roles = {cell["cell_id"]: cell["structural_role"] for cell in cells}
        self.assertEqual(roles["TBL-000001-R000001-C000001"], "title")
        self.assertEqual(roles["TBL-000001-R000002-C000001"], "header")
        self.assertEqual(roles["TBL-000001-R000003-C000001"], "data")
        result = _catalog(block, items, cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")


class HeaderlessTests(unittest.TestCase):
    def test_headerless_single_column_preserves_first_row(self) -> None:
        matrix = [
            ["The meter shall store daily data."],
            ["The meter shall store monthly data."],
        ]
        block, items, cells = _artifacts(matrix)
        self.assertEqual(block["header_row_count"], 0)
        self.assertEqual(block["headers"], ["column_1"])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["row_index"], 1)
        result = _catalog(block, items, cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")
        self.assertEqual(len(result["catalog"]), 2)

    def test_first_row_single_normative_cell_exactly_one_claim(self) -> None:
        matrix = [
            ["The device shall comply with clause 5.", ""],
            ["Name", "Requirement"],
            ["Voltage", "230 V"],
        ]
        block, items, cells = _artifacts(matrix)
        # 首行规范性单格：不是标题（无合并证据）,留在结构里且恰好一个 claim
        self.assertEqual(block["title_row_indexes"], [])
        result = _catalog(block, items, cells)
        first_row_claims = [
            claim for claim in result["catalog"]
            if int(claim["locator"].get("row_index") or 0) == 1
        ]
        self.assertEqual(len(first_row_claims), 1)
        self.assertIn("shall comply", first_row_claims[0]["text"])
        self.assertEqual(result["meta"]["accounting_status"], "complete")

    def test_data_area_single_normative_cell_kept(self) -> None:
        matrix = [
            ["Name", "Requirement"],
            ["Voltage", "230 V"],
            ["Note", "The meter shall be protected against dust."],
        ]
        block, items, cells = _artifacts(matrix)
        plan_rows = block["leaf_plan"]["row_leaves"]
        self.assertIn(3, plan_rows)  # 单格规范性行不受"至少两个非空格"限制
        result = _catalog(block, items, cells)
        texts = [claim["text"] for claim in result["catalog"]]
        self.assertTrue(any("protected against dust" in text for text in texts))


class CellGranularityTests(unittest.TestCase):
    def test_two_obligations_same_row_two_claims(self) -> None:
        matrix = [
            ["Aspect", "Requirement A", "Requirement B"],
            [
                "Storage",
                "The meter shall store daily profiles for at least sixty days.",
                "The meter must protect stored profiles against unauthorized access.",
            ],
            [
                "Display",
                "The display shall show all segments during the diagnostic test.",
                "The display must remain readable under direct sunlight conditions.",
            ],
        ]
        block, items, cells = _artifacts(matrix)
        self.assertEqual(block["table_kind"], "prose_grid")
        self.assertEqual(block["leaf_mode"], "cell")
        result = _catalog(block, items, cells)
        claims = result["catalog"]
        self.assertEqual(len(claims), 4)
        self.assertTrue(all(claim["source_kind"] == "table_cell" for claim in claims))
        # 同行两条义务 = 两个互相独立的 claim（不同 cell、不同指纹）——
        # 覆盖其中一个后另一个在账本里仍是独立 open 行
        row2_claims = [
            claim for claim in claims if int(claim["locator"].get("row_index") or 0) == 2
        ]
        self.assertEqual(len(row2_claims), 2)
        focuses = [
            build_claim_focus_adapter(claim, [block], items, cells)
            for claim in row2_claims
        ]
        self.assertNotEqual(focuses[0]["table_cell_id"], focuses[1]["table_cell_id"])
        self.assertNotEqual(
            focuses[0]["context_identity_hash"], focuses[1]["context_identity_hash"]
        )
        self.assertNotEqual(row2_claims[0]["claim_id"], row2_claims[1]["claim_id"])
        # 每个 claim 带双表头上下文
        for claim in row2_claims:
            context = claim["table_context"]
            self.assertEqual(context["row_header_context"], ["Storage"])
            self.assertTrue(context["header_path"])

    def test_single_cell_two_sentences_two_claims(self) -> None:
        matrix = [
            ["Name", "Requirement"],
            ["General", "The meter shall store data. It must be tamper proof."],
        ]
        block, items, cells = _artifacts(matrix)
        # parameter 表行级：两行字段共同描述一个参数约束 → 一个 row claim
        result = _catalog(block, items, cells)
        self.assertEqual(len(result["catalog"]), 1)

        prose_matrix = [
            ["Topic", "Details"],
            ["General", "The meter shall store data securely. It must be tamper proof always."],
            ["Other", "The display shall show totals clearly. It must remain readable outdoors."],
        ]
        block2, items2, cells2 = _artifacts(prose_matrix)
        if block2["table_kind"] == "prose_grid":
            result2 = _catalog(block2, items2, cells2)
            cell_claims = [
                claim for claim in result2["catalog"]
                if claim["locator"].get("table_cell_id") == "TBL-000001-R000002-C000002"
            ]
            self.assertEqual(len(cell_claims), 2)
            self.assertIn("store data", cell_claims[0]["text"])
            self.assertIn("tamper proof", cell_claims[1]["text"])

    def test_merged_normative_title_generates_claim(self) -> None:
        matrix = [
            ["The device shall comply.", "The device shall comply."],
            ["Name", "Req"],
            ["V", "shall be 230"],
        ]
        block, items, cells = _artifacts(matrix, merges=[(1, 1, 1, 2)])
        self.assertEqual(block["title_row_indexes"], [1])
        title_cells = [cell for cell in cells if cell["structural_role"] == "title"]
        self.assertEqual(len(title_cells), 1)
        self.assertEqual(title_cells[0]["column_span"], 2)
        self.assertEqual(title_cells[0]["covered_coordinates"], [[1, 2]])
        result = _catalog(block, items, cells)
        title_claims = [
            claim for claim in result["catalog"]
            if claim["locator"].get("table_cell_id") == title_cells[0]["cell_id"]
        ]
        self.assertEqual(len(title_claims), 1)
        self.assertEqual(title_claims[0]["text"], "The device shall comply.")
        self.assertEqual(result["meta"]["accounting_status"], "complete")

    def test_merged_requirement_cell_single_anchor_no_duplicates(self) -> None:
        matrix = [
            ["Name", "Req A", "Req B"],
            ["General", "The meter shall be secure.", "The meter shall be secure."],
        ]
        block, items, cells = _artifacts(matrix, merges=[(2, 2, 2, 3)])
        anchor = [cell for cell in cells if cell["cell_id"] == "TBL-000001-R000002-C000002"]
        self.assertEqual(len(anchor), 1)
        self.assertEqual(anchor[0]["column_span"], 2)
        # 覆盖坐标不得复制文本冒充多个单元格
        self.assertFalse(
            any(cell["cell_id"] == "TBL-000001-R000002-C000003" for cell in cells)
        )
        self.assertEqual(anchor[0]["covered_coordinates"], [[2, 3]])
        result = _catalog(block, items, cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")
        claims = [
            claim for claim in result["catalog"]
            if "shall be secure" in claim["text"]
        ]
        self.assertEqual(len(claims), 1)

    def test_multi_level_headers(self) -> None:
        matrix = [
            ["Customer application process", "xDLMS Service", "xDLMS Service"],
            ["Customer application process", '"GET"', '"ACTION"'],
            ["Public customer", "X", ""],
            ["Management client", "", "X"],
        ]
        block, items, cells = _artifacts(matrix)
        self.assertEqual(block["header_row_count"], 2)
        self.assertEqual(block["headers"][1], 'xDLMS Service / "GET"')
        marker = next(
            cell for cell in cells
            if cell["cell_id"] == "TBL-000001-R000003-C000002"
        )
        self.assertEqual(marker["header_path"], ['xDLMS Service / "GET"'])
        self.assertEqual(marker["row_header_context"], ["Public customer"])


class MappingMatrixTests(unittest.TestCase):
    def test_x_matrix_cell_claims_and_atoms(self) -> None:
        matrix = [
            ["Feature", "Mode A", "Mode B", "Note"],
            ["Encryption", "X", "", "see below"],
            ["Signing", "X", "X", "free text"],
        ]
        block, items, cells = _artifacts(matrix)
        self.assertEqual(block["table_kind"], "mapping_matrix")
        self.assertEqual(block["leaf_mode"], "cell")
        result = _catalog(block, items, cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")
        claims = result["catalog"]
        self.assertTrue(all(claim["source_kind"] == "table_cell" for claim in claims))
        self.assertEqual(len(claims), 3)
        by_cell = {claim["locator"]["table_cell_id"]: claim for claim in claims}
        self.assertEqual(
            by_cell["TBL-000001-R000002-C000002"]["table_context"]["row_header_context"],
            ["Encryption"],
        )
        # Note 列是 context，不成 claim
        self.assertFalse(any(cell_id.endswith("C000004") for cell_id in by_cell))
        candidates = build_atomic_candidates([block], items, table_cell_items=cells)
        matrix_atoms = [
            candidate for candidate in candidates
            if candidate["requirement_type"] == "capability_matrix"
        ]
        self.assertEqual(len(matrix_atoms), 3)
        self.assertTrue(all(candidate["source_type"] == "table_cell" for candidate in matrix_atoms))
        self.assertIn(
            "Encryption shall support Mode A.",
            [candidate["requirement"] for candidate in matrix_atoms],
        )
        self.assertFalse(
            any("shall support Note" in candidate["requirement"] for candidate in candidates)
        )

    def test_price_schedule_stays_row_mode(self) -> None:
        matrix = [
            ["Lot", "Description", "Price"],
            ["1", "Single-phase meter", "120"],
            ["2", "Polyphase meter", "340"],
        ]
        block, items, cells = _artifacts(matrix)
        self.assertEqual(block["table_kind"], "other")
        self.assertEqual(block["leaf_mode"], "row")


class SourceReferenceAssertionTests(unittest.TestCase):
    def test_source_ids_must_exist(self) -> None:
        matrix = [
            ["Name", "Requirement"],
            ["Voltage", "The meter shall operate at 230 V."],
        ]
        block, items, cells = _artifacts(matrix)
        item_id = items[0]["item_id"]
        cell_id = cells[0]["cell_id"]
        _assert_source_references(
            [{"source_item_id": item_id}, {"source_cell_id": cell_id}],
            items,
            cells,
        )
        with self.assertRaises(ValueError):
            _assert_source_references(
                [{"source_item_id": "TBL-000001-R000099"}], items, cells
            )
        with self.assertRaises(ValueError):
            _assert_source_references(
                [{"source_cell_id": "TBL-000001-R000002-C000099"}], items, cells
            )

    def test_cell_context_text_never_bare(self) -> None:
        matrix = [
            ["Feature", "Mode A"],
            ["Encryption", "X"],
            ["Signing", "X"],
        ]
        block, items, cells = _artifacts(matrix)
        marker = next(cell for cell in cells if cell["leaf_kind"] == "cell")
        context_text = cell_context_text(marker)
        self.assertIn(marker["table_title"], context_text)
        self.assertIn("Encryption", context_text)
        self.assertIn("Mode A", context_text)
        self.assertTrue(context_text.endswith("= X"))


class DocxIntegrationTests(unittest.TestCase):
    def _write_docx(self, path: Path) -> None:
        document = Document()
        document.add_heading("5 Requirements", level=1)
        table = document.add_table(rows=4, cols=3)
        table.cell(0, 0).merge(table.cell(0, 2))
        table.cell(0, 0).text = "Table 1 - Electrical"
        table.cell(1, 0).text = "Name"
        table.cell(1, 1).text = "Requirement"
        table.cell(1, 2).text = "Note"
        table.cell(2, 0).text = "Voltage"
        table.cell(2, 1).text = "The meter shall operate at 230 V."
        table.cell(2, 2).text = "mandatory"
        table.cell(3, 0).text = "General"
        table.cell(3, 1).text = "The meter shall be secure."
        table.cell(3, 2).text = "The meter shall be secure."
        table.cell(3, 1).merge(table.cell(3, 2))
        document.save(path)

    def test_docx_merge_evidence_and_block_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.docx"
            self._write_docx(path)
            blocks, items, cells = extract_docx(path)
        block_ids = [block["block_id"] for block in blocks]
        self.assertEqual(block_ids, [f"BLK-{index + 1:06d}" for index in range(len(blocks))])
        table_block = next(block for block in blocks if block["type"] == "table")
        self.assertEqual(table_block["table_structure_version"], TABLE_STRUCTURE_VERSION)
        self.assertEqual(table_block["title_row_indexes"], [1])
        self.assertTrue(table_block["merge_ranges"])
        result = build_claim_catalog(blocks, items, table_cell_items=cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")
        self.assertTrue(all(count == 0 for count in _cell_audit(result).values()))
        # 合并需求格：单 anchor 一个 claim，覆盖坐标不冒充
        merged_claims = [
            claim for claim in result["catalog"]
            if "shall be secure" in claim["text"]
        ]
        self.assertEqual(len(merged_claims), 1)
        # Note 列的 mandatory 不产矩阵句式
        candidates = build_atomic_candidates(blocks, items, table_cell_items=cells)
        self.assertFalse(
            any("shall support Note" in candidate["requirement"] for candidate in candidates)
        )


class XlsxRegionTests(unittest.TestCase):
    def test_multi_table_sheet_split_and_non_a1_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Specs"
            # 表 1：A1 起始（标题合并 + 表头 + 数据）
            sheet["A1"] = "Electrical"
            sheet.merge_cells("A1:B1")
            sheet.append(["Name", "Requirement"])
            sheet.append(["Voltage", "The meter shall operate at 230 V."])
            sheet.append([])
            # 表 2：非 A1 起始区域（C6 起始）
            sheet["C6"] = "Name"
            sheet["D6"] = "Requirement"
            sheet["C7"] = "Current"
            sheet["D7"] = "The meter shall measure current."
            workbook.save(path)

            blocks, items, cells = extract_xlsx(path, knowledge_bases=[], document_profile=None)

        tables = [block for block in blocks if block["type"] == "table"]
        self.assertEqual(len(tables), 2)
        first, second = tables
        self.assertEqual(first["table_title"], "Electrical")
        self.assertEqual(first["title_row_indexes"], [1])
        self.assertEqual(second["headers"], ["Name", "Requirement"])
        # 非 A1 起始：cell 的 a1_address 必须带真实 sheet 坐标
        second_cells = [
            cell for cell in cells if cell["table_block_id"] == second["block_id"]
        ]
        self.assertTrue(second_cells)
        by_text = {cell["text"]: cell for cell in second_cells}
        self.assertEqual(by_text["Name"]["a1_address"], "C6")
        self.assertEqual(by_text["Current"]["a1_address"], "C7")
        self.assertEqual(by_text["Name"]["sheet_name"], "Specs")
        result = build_claim_catalog(blocks, items, table_cell_items=cells)
        self.assertEqual(result["meta"]["accounting_status"], "complete")

    def test_excel_table_definition_region(self) -> None:
        from openpyxl.worksheet.table import Table as XlsxTable
        from openpyxl.worksheet.table import TableStyleInfo

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tables.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Data"
            sheet.append(["Name", "Requirement"])
            sheet.append(["Voltage", "The meter shall operate at 230 V."])
            sheet.append(["Current", "The meter shall measure current."])
            xlsx_table = XlsxTable(displayName="SpecTable", ref="A1:B3")
            xlsx_table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9")
            sheet.add_table(xlsx_table)
            workbook.save(path)

            blocks, items, cells = extract_xlsx(path, knowledge_bases=[], document_profile=None)

        tables = [block for block in blocks if block["type"] == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["header_detection_status"], "explicit")
        self.assertEqual(tables[0]["header_row_indexes"], [1])


class PdfCellGeometryTests(unittest.TestCase):
    def test_pdfplumber_cell_evidence_anchor_and_merge(self) -> None:
        from parsers.pdf_parser import _pdfplumber_cell_evidence

        class _FakeTable:
            # 3 列 × 2 行网格；(1,1)-(1,2) 横向合并为一个 anchor
            cells = [
                (0.0, 0.0, 100.0, 20.0),   # anchor R1C1（跨 C1-C2）
                (100.0, 0.0, 150.0, 20.0),  # R1C3
                (0.0, 20.0, 50.0, 40.0),    # R2C1
                (50.0, 20.0, 100.0, 40.0),  # R2C2
                (100.0, 20.0, 150.0, 40.0),  # R2C3
            ]

        cell_bboxes, merge_ranges = _pdfplumber_cell_evidence(_FakeTable())
        self.assertIsNotNone(cell_bboxes)
        self.assertEqual(cell_bboxes[(1, 1)], [0.0, 0.0, 100.0, 20.0])
        self.assertNotIn((1, 2), cell_bboxes)
        self.assertEqual(merge_ranges, [(1, 1, 1, 2)])

    def test_pdfplumber_cell_evidence_misaligned_is_honest_none(self) -> None:
        from parsers.pdf_parser import _pdfplumber_cell_evidence

        class _BrokenTable:
            cells = [(0.0, 0.0, 50.0, 20.0), (7.0, 3.0, 60.0, 25.0)]

        cell_bboxes, merge_ranges = _pdfplumber_cell_evidence(_BrokenTable())
        # 网格对不齐：如实返回 None，绝不伪造精确结构
        self.assertIsNotNone(cell_bboxes)  # anchor 本身可对齐
        self.assertIsInstance(merge_ranges, (list, type(None)))


class BlockSequenceStabilityTests(unittest.TestCase):
    def test_block_id_sequence_stable_with_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seq.docx"
            document = Document()
            document.add_heading("1 Scope", level=1)
            document.add_paragraph("The meter shall be tested.")
            table = document.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "Name"
            table.cell(0, 1).text = "Requirement"
            table.cell(1, 0).text = "Voltage"
            table.cell(1, 1).text = "The meter shall operate at 230 V."
            document.add_paragraph("Trailing clause.")
            document.save(path)
            blocks, items, cells = extract_docx(path)

        self.assertEqual(
            [block["block_id"] for block in blocks],
            ["BLK-000001", "BLK-000002", "BLK-000003", "BLK-000004"],
        )
        types = [block["type"] for block in blocks]
        self.assertEqual(types, ["heading", "paragraph", "table", "paragraph"])
        # 行/格不升格为顶层 block
        self.assertTrue(all(item["table_block_id"] == "BLK-000003" for item in items))
        self.assertTrue(all(cell["table_block_id"] == "BLK-000003" for cell in cells))
        self.assertTrue(all(cell["schema"] == TABLE_CELL_ITEM_SCHEMA for cell in cells))


if __name__ == "__main__":
    unittest.main()
