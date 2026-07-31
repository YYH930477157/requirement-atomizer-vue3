"""表格行级热区（doc_annotation_export v12）：docx/xlsx 影印支路的行级几何与行热区。

背景：影印支路整表是单块（无页号），v11 只回填块级几何——表格在影印页上不可点。
v12 对齐原生 PDF 表格的行粒度体验：行级几何（_resolve_pdf_geometry row_geometry
出参）→ 行热区（_pdf_block_zones 带 row_index）→ 行卡片数据（_pdf_context_records
"<block_id>#R<row_index>" 键）。分组标题行/稀疏行不发区（与 spot_extract 同口径）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import doc_annotation_export
from doc_annotation_export import (
    _pdf_block_zones,
    _pdf_context_records,
    _resolve_pdf_geometry,
)


def _region(page: int, top: float = 72.0, bottom: float = 100.0) -> dict:
    return {
        "page_number": page,
        "bbox": [72.0, top, 520.0, bottom],
        "page_width": 595.32,
        "page_height": 841.92,
    }


def _parsed_block(block_id: str, page: int, text: str, *, top: float = 72.0) -> dict:
    return {"block_id": block_id, "page_number": page, "text": text,
            "pdf_regions": [_region(page, top=top, bottom=top + 28.0)]}


def _table_block(block_id: str = "BT", **overrides) -> dict:
    block = {
        "block_id": block_id, "type": "table", "page_number": None,
        "headers": ["No.", "Term", "Definition"],
        "data_rows": [
            ["SECTION A", "SECTION A", "SECTION A"],   # 分组标题行（全同值）→ 跳过
            ["9.", "", ""],                              # 稀疏行（非空 <2）→ 跳过
            ["1.", "Overvoltage", "The maximum voltage value recorded in any channel."],
            ["2.", "Firmware", "Software that processes information coming from hardware."],
        ],
        "text": ("No. | Term | Definition\n"
                 "1. | Overvoltage | The maximum voltage value recorded in any channel.\n"
                 "2. | Firmware | Software that processes information coming from hardware."),
    }
    block.update(overrides)
    return block


def _fake_pdf() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    handle.write(b"%PDF-1.4 fake")
    handle.close()
    return Path(handle.name)


class TableRowGeometryTests(unittest.TestCase):
    def _resolve(self, blocks: list[dict], parsed: list[dict], *,
                 cache_path: Path | None = None) -> tuple[dict, dict]:
        fake_pdf = _fake_pdf()
        rows: dict = {}
        try:
            with mock.patch("parsers.pdf_parser.extract_pdf", return_value=(parsed, [], [])):
                geometry = _resolve_pdf_geometry(fake_pdf, blocks, cache_path=cache_path,
                                                 row_geometry=rows)
        finally:
            fake_pdf.unlink(missing_ok=True)
        return geometry, rows

    def test_group_header_and_sparse_rows_skipped(self) -> None:
        parsed = [
            _parsed_block("P1", 6, "1. | Overvoltage | The maximum voltage value recorded in any channel."),
            _parsed_block("P2", 7, "Page chunk. 2. | Firmware | Software that processes information coming from hardware. More."),
        ]
        _geometry, rows = self._resolve([_table_block()], parsed)

        self.assertEqual(sorted(rows["BT"]), [3, 4])          # 行号 1-based,分组/稀疏行跳过
        self.assertEqual(rows["BT"][3][0]["page_number"], 6)  # 全局精确
        self.assertEqual(rows["BT"][4][0]["page_number"], 7)  # 行 ⊂ 大解析块（包含）

    def test_prefix_prefilter_then_fuzzy_coverage(self) -> None:
        # 行归一化后 ≥80 字符；候选共享前 80 字符前缀但尾部措辞不同——全串包含失败,
        # 前缀预筛命中后覆盖率 ≥0.72 落区
        tail_a = "The meter shall record voltage dips with a duration longer than one second in the event log."
        tail_b = "The meter shall record voltage dips with a duration longer than one second in the audit trail."
        row = ["12.", "Event recording", tail_a]
        block = _table_block(data_rows=[row])
        parsed = [
            _parsed_block("P1", 9, f"12. | Event recording | {tail_b}"),
            _parsed_block("P2", 3, "Totally unrelated content about firmware updates and hardware."),
        ]
        _geometry, rows = self._resolve([block], parsed)

        self.assertEqual(sorted(rows["BT"]), [1])
        self.assertEqual(rows["BT"][1][0]["page_number"], 9)

    def test_fuzzy_requires_margin_no_guess(self) -> None:
        # 两个候选覆盖率都 ≥0.72 且边际 <0.05 → 宁缺不猜,不落区
        tail_a = "The meter shall record voltage dips with a duration longer than one second in the event log."
        tail_b = "The meter shall record voltage dips with a duration longer than one second in the event list."
        tail_c = "The meter shall record voltage dips with a duration longer than one second in the event book."
        block = _table_block(data_rows=[["12.", "Event recording", tail_a]])
        parsed = [
            _parsed_block("P1", 9, f"12. | Event recording | {tail_b}"),
            _parsed_block("P2", 11, f"12. | Event recording | {tail_c}"),
        ]
        _geometry, rows = self._resolve([block], parsed)

        self.assertNotIn("BT", rows)

    def test_paged_table_block_not_row_matched(self) -> None:
        # 有页号的表格块（原生 PDF 路径）已是细粒度,不重复计算行几何
        block = _table_block(page_number=6)
        parsed = [_parsed_block("P1", 6, "1. | Overvoltage | The maximum voltage value recorded in any channel.")]
        _geometry, rows = self._resolve([block], parsed)

        self.assertNotIn("BT", rows)

    def test_hyphen_wrap_in_pdf_text_layer_folded(self) -> None:
        # 转换 PDF 文本层换行拆连字符词（"self- diagnostics"）,docx 单元格是
        # "self-diagnostics"——行级匹配折叠 "- "→"-"（STO 实证参数表落空主因）,
        # 块级 _geometry_match_text 不受影响（v11 行为/缓存不动）
        row = ["7.", "Self-diagnostics",
               "The IPUE must perform self-diagnostics ensuring daily testing of memory."]
        block = _table_block(data_rows=[row])
        parsed = [
            _parsed_block("P1", 14, "7. | Self- diagnostics | The IPUE must perform self- diagnostics ensuring daily testing of memory."),
        ]
        _geometry, rows = self._resolve([block], parsed)

        self.assertEqual(sorted(rows["BT"]), [1])
        self.assertEqual(rows["BT"][1][0]["page_number"], 14)

    _PARSED = [
        _parsed_block("P1", 6, "1. | Overvoltage | The maximum voltage value recorded in any channel."),
        _parsed_block("P2", 7, "Page chunk. 2. | Firmware | Software that processes information coming from hardware. More."),
    ]

    def test_row_geometry_cache_roundtrip(self) -> None:
        parsed = self._PARSED
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "document_pdf_geometry.json"
            _geometry, rows = self._resolve([_table_block()], parsed, cache_path=cache)
            self.assertIn("BT", rows)
            payload = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 5)   # v5：table-structure-v2 cell 级（v4 旧缓存不得复用）
            self.assertEqual(sorted(payload["row_geometry"]["BT"]), ["3", "4"])  # JSON 键为字符串

            # 第二跑：解析器不得再被调用（缓存直供）,行号键恢复为 int
            fake_pdf = _fake_pdf()
            rows2: dict = {}
            try:
                with mock.patch(
                    "parsers.pdf_parser.extract_pdf",
                    side_effect=AssertionError("must not re-parse"),
                ):
                    # 注意：缓存命中要求 source_sha256 一致——重写同内容假 PDF
                    fake_pdf.write_bytes(b"%PDF-1.4 fake")
                    _resolve_pdf_geometry(fake_pdf, [_table_block()], cache_path=cache,
                                          row_geometry=rows2)
            finally:
                fake_pdf.unlink(missing_ok=True)
            self.assertEqual(sorted(rows2["BT"]), [3, 4])
            self.assertEqual(rows2["BT"][3][0]["page_number"], 6)

    def test_legacy_cache_without_row_geometry_backfilled(self) -> None:
        # 旧 v3 缓存（无 row_geometry 字段）：请求行几何时重算一次并回写,之后缓存直供;
        # 不请求行几何的调用方照旧命中缓存（向后兼容,不必 bump version）
        parsed = self._PARSED
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "document_pdf_geometry.json"
            fake_pdf = _fake_pdf()
            fake_pdf.write_bytes(b"%PDF-1.4 fake")
            try:
                with mock.patch(
                    "parsers.pdf_parser.extract_pdf", return_value=(parsed, [], [])
                ) as extractor:
                    # 第一跑不带行几何 → 旧格式缓存（无 row_geometry 字段）
                    _resolve_pdf_geometry(fake_pdf, [_table_block()], cache_path=cache)
                    self.assertNotIn("row_geometry", json.loads(cache.read_text(encoding="utf-8")))
                    # 第二跑带行几何 → 旧缓存缺字段,重算并回写
                    rows: dict = {}
                    _resolve_pdf_geometry(fake_pdf, [_table_block()], cache_path=cache,
                                          row_geometry=rows)
                    self.assertEqual(extractor.call_count, 2)
                    self.assertIn("BT", rows)
                    self.assertIn("row_geometry", json.loads(cache.read_text(encoding="utf-8")))
                    # 第三跑带行几何 → 缓存直供
                    rows3: dict = {}
                    _resolve_pdf_geometry(fake_pdf, [_table_block()], cache_path=cache,
                                          row_geometry=rows3)
                    self.assertEqual(extractor.call_count, 2)
                    self.assertEqual(sorted(rows3["BT"]), [3, 4])
            finally:
                fake_pdf.unlink(missing_ok=True)


class TableRowZoneTests(unittest.TestCase):
    def _row_geometry(self, *pages: int) -> dict:
        return {"BT": {3: [_region(page, top=100.0 + 30 * i, bottom=126.0 + 30 * i)
                           for i, page in enumerate(pages)]}}

    def test_req_row_verbatim_quote(self) -> None:
        reqs = [{
            "ai_req_id": "AIR-1",
            "source_quote": "1. | Overvoltage | The maximum voltage value recorded in any channel.",
            "description": "", "title": "过电压",
            "source_block_ids": ["BT"], "anchor_block_id": "BT",
        }]
        zones = _pdf_block_zones([_table_block()], reqs, {}, set(),
                                 row_geometry=self._row_geometry(6))

        row_zones = [z for z in zones if z.get("row_index") is not None]
        self.assertEqual(len(row_zones), 1)
        self.assertEqual(row_zones[0]["kind"], "req")
        self.assertEqual(row_zones[0]["req_id"], "AIR-1")
        self.assertEqual(row_zones[0]["req_ids"], ["AIR-1"])
        self.assertEqual(row_zones[0]["row_index"], 3)
        self.assertEqual(row_zones[0]["page"], 6)

    def test_covered_row_by_key_cell(self) -> None:
        reqs = [{
            "ai_req_id": "AIR-2",
            "source_quote": "别的块的句子,不含整行",
            "description": "记录越限：The maximum voltage value recorded in any channel. 并告警",
            "title": "过电压记录",
            "source_block_ids": ["BT", "OTHER"], "anchor_block_id": "OTHER",
        }]
        zones = _pdf_block_zones([_table_block()], reqs, {}, set(),
                                 row_geometry=self._row_geometry(6))

        row_zones = [z for z in zones if z.get("row_index") == 3]
        self.assertEqual(row_zones[0]["kind"], "covered")
        self.assertEqual(row_zones[0]["req_ids"], ["AIR-2"])

    def test_unreferenced_row_is_context(self) -> None:
        zones = _pdf_block_zones([_table_block()], [], {}, set(),
                                 row_geometry=self._row_geometry(6))

        row_zones = [z for z in zones if z.get("row_index") is not None]
        self.assertEqual(len(row_zones), 1)
        self.assertEqual(row_zones[0]["kind"], "context")
        self.assertNotIn("req_id", row_zones[0])
        self.assertNotIn("req_ids", row_zones[0])

    def test_table_block_itself_gets_no_zone(self) -> None:
        # 整表块本身仍不发区（非锚定/非来源时）——只有数据行发区
        zones = _pdf_block_zones([_table_block()], [], {}, set(),
                                 row_geometry=self._row_geometry(6))
        self.assertTrue(all(z.get("row_index") is not None for z in zones))

    def test_same_page_regions_union_and_multi_page(self) -> None:
        row_geometry = {"BT": {3: [_region(6, top=100.0, bottom=128.0),
                                   _region(6, top=140.0, bottom=168.0),
                                   _region(7, top=80.0, bottom=108.0)]}}
        zones = _pdf_block_zones([_table_block()], [], {}, set(), row_geometry=row_geometry)

        self.assertEqual(len(zones), 2)   # 同页两区域合并,跨页各一区
        by_page = {z["page"]: z for z in zones}
        self.assertAlmostEqual(by_page[6]["rect"]["top"], 100.0 / 841.92 * 100, places=2)
        self.assertAlmostEqual(by_page[6]["rect"]["height"], (168.0 - 100.0) / 841.92 * 100, places=2)
        self.assertAlmostEqual(by_page[7]["rect"]["top"], 80.0 / 841.92 * 100, places=2)


class TableRowContextRecordTests(unittest.TestCase):
    def _zones(self) -> list[dict]:
        rect = {"left": 12.0, "top": 10.0, "width": 70.0, "height": 3.0}
        return [
            {"block_id": "BT", "row_index": 3, "page": 6, "rect": rect, "kind": "covered",
             "req_ids": ["AIR-2"]},
            {"block_id": "BT", "row_index": 4, "page": 7, "rect": rect, "kind": "context"},
            {"block_id": "BT", "row_index": 99, "page": 8, "rect": rect, "kind": "context"},
        ]

    def test_row_records_keyed_by_block_and_row(self) -> None:
        records = _pdf_context_records([_table_block()], self._zones())

        self.assertNotIn("BT", records)               # 整表块本身无记录
        self.assertNotIn("BT#R99", records)           # 越界行号如实跳过
        covered = records["BT#R3"]
        self.assertEqual(covered["kind"], "covered")
        self.assertEqual(covered["covered_req_ids"], ["AIR-2"])
        self.assertEqual(covered["page"], 6)
        self.assertEqual(covered["row_index"], 3)
        self.assertEqual(
            covered["text"],
            "1. | Overvoltage | The maximum voltage value recorded in any channel.",
        )
        context = records["BT#R4"]
        self.assertEqual(context["kind"], "context")
        self.assertEqual(context["page"], 7)
        self.assertEqual(context["translation"], "")   # 查不到翻译如实空串,不编

    def test_row_translation_from_active_translations(self) -> None:
        text = "2. | Firmware | Software that processes information coming from hardware."
        key = doc_annotation_export._translation_key(text)
        with mock.patch.dict(doc_annotation_export._active_translations,
                             {key: "处理来自硬件的信息的软件。"}, clear=False):
            records = _pdf_context_records([_table_block()], self._zones())

        self.assertEqual(records["BT#R4"]["translation"], "处理来自硬件的信息的软件。")


if __name__ == "__main__":
    unittest.main()
