"""2026-07-25 test7 实证四项修复测试：

1. 引句多段窗口跳过噪声块（页码/水印夹缝不再掐死整句匹配）；
2. extract_units 的 source_blocks 带 section_path（fallback 收窄真实生效）；
3. PDF 热区 section_fallback 只认原句匹配块（不再把回退 span 误标"关联·见NN"）；
4. 同块同页多区域合并为一个热区（清单并块后不再逐行刷屏）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from merged_consistency import match_source_quote_blocks


class NoiseTolerantWindowTests(unittest.TestCase):
    def test_blob_quote_matches_across_noise_blocks(self) -> None:
        """整段引句（无换行分隔）跨越页码/水印噪声块时应命中两侧正文块——
        test7 实证：引句各片段都在，但窗口被页码 "6" 掐死整句掉到 fallback。"""
        blocks = [
            {"block_id": "B80", "order": 1, "type": "paragraph",
             "text": "The wiring diagram of the meter must be indelibly marked."},
            {"block_id": "B81", "order": 2, "type": "paragraph", "text": "6", "noise": True},
            {"block_id": "B82", "order": 3, "type": "paragraph",
             "text": "Machine Translated by Google", "noise": True},
            {"block_id": "B83", "order": 4, "type": "paragraph",
             "text": "All terminals located on the electricity meter must be clearly marked."},
        ]
        quote = ("The wiring diagram of the meter must be indelibly marked. "
                 "All terminals located on the electricity meter must be clearly marked.")

        matched, method = match_source_quote_blocks(quote, blocks)

        self.assertEqual(matched, ["B80", "B83"])
        self.assertEqual(method, "multi_block")

    def test_non_noise_tiny_block_still_kills_window(self) -> None:
        """非噪声微块仍掐窗（页码豁免只给噪声块，不放宽短块守卫）。"""
        blocks = [
            {"block_id": "B80", "order": 1, "type": "paragraph",
             "text": "The wiring diagram of the meter must be indelibly marked."},
            {"block_id": "B81", "order": 2, "type": "paragraph", "text": "6"},
            {"block_id": "B83", "order": 3, "type": "paragraph",
             "text": "All terminals located on the electricity meter must be clearly marked."},
        ]
        quote = ("The wiring diagram of the meter must be indelibly marked. "
                 "All terminals located on the electricity meter must be clearly marked.")

        matched, _method = match_source_quote_blocks(quote, blocks)

        self.assertEqual(matched, [])


class SourceBlocksSectionPathTests(unittest.TestCase):
    def test_fallback_narrowing_works_on_real_section_shape(self) -> None:
        """extract_units 产出的 source_blocks 必须带 section_path——fallback 收窄
        按需求所属小节过滤 span（此前缺该字段，收窄静默失效成整单元 span）。"""
        import ai_extract

        section = {
            "block_ids": ["B1", "B2", "B3", "B4"],
            "source_blocks": [
                {"block_id": "B1", "text": "3.4.4 Marking of terminals",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
                {"block_id": "B2", "text": "- DAY1",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
                {"block_id": "B3", "text": "3.4.5 Screws",
                 "section_path": ["3", "3.4.5 Screws"]},
                {"block_id": "B4", "text": "The terminal box must be supplied with screws.",
                 "section_path": ["3", "3.4.5 Screws"]},
            ],
        }
        req = {"source_quote": "a paraphrased quote not in source",
               "source_section": "3.4.5 Screws", "notes": ""}

        ai_extract._map_requirement_source(req, section)

        self.assertEqual(req["source_block_ids"], ["B3", "B4"])
        self.assertEqual(req["source_mapping"], "section_fallback")

    def test_units_source_blocks_carry_section_path(self) -> None:
        """assemble_sections 真实产出路径：source_blocks 条目必须含 section_path。"""
        from extract_units import assemble_sections

        blocks = [
            {"block_id": "B1", "type": "heading", "text": "3.4.4 Marking of terminals",
             "section_path": ["3.4.4 Marking of terminals"]},
            {"block_id": "B2", "type": "paragraph", "text": "All terminals must be marked.",
             "section_path": ["3.4.4 Marking of terminals"]},
        ]
        sections = assemble_sections(blocks)

        flat = [row for section in sections for row in section.get("source_blocks") or []]
        self.assertTrue(flat)
        for row in flat:
            self.assertIn("section_path", row)


class PdfZoneFallbackScopeTests(unittest.TestCase):
    def test_section_fallback_covered_uses_quote_blocks_only(self) -> None:
        """热区语义：section_fallback 行的"关联"只认原句匹配块，回退 span 里的
        无关段落不得标 covered/关联（test7 "- DAY1 关联·见24" 同源问题）。"""
        import doc_annotation_export as dae

        blocks = [
            {"block_id": "B1", "type": "paragraph", "text": "The wiring diagram must be marked."},
            {"block_id": "B2", "type": "paragraph", "text": "Terminals: - RS485 - MPA"},
        ]
        requirements = [{
            "ai_req_id": "AIR-1",
            "anchor_block_id": "B1",
            "source_block_ids": ["B1", "B2"],
            "quote_block_ids": ["B1"],
            "source_mapping": "section_fallback",
        }]

        semantics = dae._pdf_block_semantics(blocks, requirements, set())
        by_id = {item["block_id"]: item for item in semantics}

        self.assertEqual(by_id["B1"]["kind"], "req")
        self.assertNotEqual(by_id["B2"].get("kind"), "covered")

    def test_multi_region_same_page_block_gets_one_zone(self) -> None:
        """同块同页多区域合并为一个热区（清单并块带 10 个行区域 → 一个"关联"标签）。"""
        import doc_annotation_export as dae

        regions = [
            {"page_number": 6, "bbox": (60, 100 + index * 20, 540, 116 + index * 20),
             "page_width": 600, "page_height": 800}
            for index in range(5)
        ]
        geometry = {"B1": regions}
        blocks = [{"block_id": "B1", "type": "paragraph", "text": "Terminals: - RS485"}]
        requirements = [{
            "ai_req_id": "AIR-1", "anchor_block_id": "B1",
            "source_block_ids": ["B1"], "quote_block_ids": ["B1"],
            "source_mapping": "multi_block",
        }]

        zones = dae._pdf_block_zones(blocks, requirements, geometry, {"B1"})

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["kind"], "req")
        rect = zones[0]["rect"]
        self.assertGreater(rect["height"], 10.0)   # 并集矩形覆盖全部行区域


if __name__ == "__main__":
    unittest.main()
