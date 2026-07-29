"""影印支路几何回填（doc_annotation_export v11）：docx/xlsx 无页号块的全局文本匹配。

STO 实证缺陷链：同页假设（docx 块无 page_number）→ 82 页文档仅 8 块有区；
合并单元格展开重复 → 包含匹配全灭；单调游标窗口 → 一次错配全链错位。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from doc_annotation_export import (
    _dedupe_merged_cells,
    _geometry_match_text,
    _resolve_pdf_geometry,
)


def _region(page: int) -> dict:
    return {
        "page_number": page,
        "bbox": [72.0, 72.0, 520.0, 720.0],
        "page_width": 595.32,
        "page_height": 841.92,
    }


def _parsed_block(block_id: str, page: int, text: str) -> dict:
    return {"block_id": block_id, "page_number": page, "text": text,
            "pdf_regions": [_region(page)]}


class MergedCellDedupeTests(unittest.TestCase):
    def test_consecutive_duplicate_cells_collapse(self) -> None:
        line = "3.1.1 | 3.1.1 | Requirement text | Requirement text | Body"
        self.assertEqual(
            _dedupe_merged_cells(line),
            "3.1.1 | Requirement text | Body",
        )

    def test_match_text_collapses_duplicate_words(self) -> None:
        # api 侧 normalize_text 吞掉行界后,行界两侧同值单元格变连写重复——词级折叠兜底
        text = "design of IPUE 3.1.1 3.1.1 Requirement for the degree"
        self.assertEqual(
            _geometry_match_text(text),
            "design of IPUE 3.1.1 Requirement for the degree",
        )


class FacsimileGeometryTests(unittest.TestCase):
    def _docx_block(self, block_id: str, text: str) -> dict:
        # docx 块：无 page_number、无 pdf_regions（影印支路的几何全部要回填）
        return {"block_id": block_id, "page_number": None, "text": text}

    def _resolve(self, blocks: list[dict], parsed: list[dict]) -> dict:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            fake_pdf = Path(handle.name)
            handle.write(b"%PDF-1.4 fake")
        try:
            with mock.patch(
                "parsers.pdf_parser.extract_pdf", return_value=(parsed, [])
            ):
                return _resolve_pdf_geometry(fake_pdf, blocks, cache_path=None)
        finally:
            fake_pdf.unlink(missing_ok=True)

    def test_global_exact_match_without_page_number(self) -> None:
        blocks = [self._docx_block("B1", "The meter shall log events.")]
        parsed = [_parsed_block("P1", 4, "The meter shall log events.")]

        geo = self._resolve(blocks, parsed)

        self.assertEqual(len(geo["B1"]), 1)
        self.assertEqual(geo["B1"][0]["page_number"], 4)

    def test_large_table_prefix_anchor(self) -> None:
        # 大表块（>8000 字符）全串包含永远失败,前缀 80 字符锚定生效
        row_text = "1. | Rated voltage | The meter shall operate at 230 V."
        big_text = "No. | Parameter | Requirement\n" + (row_text + "\n") * 400
        blocks = [self._docx_block("BT", big_text)]
        parsed = [
            _parsed_block("P7", 15, "1. | Rated voltage | The meter shall operate at 230 V."),
            _parsed_block("P8", 99, "Completely unrelated content about nothing."),
        ]

        geo = self._resolve(blocks, parsed)

        self.assertTrue(geo["BT"])
        self.assertEqual(geo["BT"][0]["page_number"], 15)

    def test_fuzzy_requires_margin_no_guess(self) -> None:
        # 两个候选都 ≥0.72 且边际 <0.05 → 宁缺不猜,不落区
        blocks = [self._docx_block("B2", "The meter shall provide a display for measured values.")]
        parsed = [
            _parsed_block("P1", 3, "The meter shall provide a display for measured results."),
            _parsed_block("P2", 8, "The meter shall provide a display for measured readings."),
        ]

        geo = self._resolve(blocks, parsed)

        self.assertNotIn("B2", geo)

    def test_fuzzy_clear_winner_gets_zone(self) -> None:
        blocks = [self._docx_block("B3", "The meter shall provide a display for measured values.")]
        parsed = [
            _parsed_block("P1", 3, "The meter shall provide a display for measured values."),
            _parsed_block("P2", 8, "Totally different sentence with no overlap at all."),
        ]

        geo = self._resolve(blocks, parsed)

        self.assertEqual(geo["B3"][0]["page_number"], 3)


if __name__ == "__main__":
    unittest.main()
