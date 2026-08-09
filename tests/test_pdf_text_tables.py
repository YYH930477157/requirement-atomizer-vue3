"""无画线表格重建 + 错行重排 + 标题归位 回归（2026-07-07，UNI 12007 真实案例驱动）。

合成词行直接喂检测器/分组器；真实 PDF 端到端由 ABNT 零误报门与 UNI 指标复验覆盖
（见提交信息），这里锁定各守卫与规则的行为语义。
"""
from __future__ import annotations

import unittest

from atomize import DEFAULT_DOCUMENT_PROFILE, SectionState, detect_heading
from parsers.pdf_parser import (
    _append_text_block,
    _detect_text_tables,
    _group_paragraphs,
    _merge_continuation_blocks,
    _refine_pdf_heading,
    _split_line_cells,
)
from requirement_kb import KnowledgeRepository
from source_spans import validate_source_alignment


def word(text: str, x0: float, x1: float, top: float) -> dict:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 8.0}


def line(top: float, *cells: tuple[str, float, float]) -> dict:
    words = [word(t, x0, x1, top) for t, x0, x1 in cells]
    return {
        "text": " ".join(t for t, _, _ in cells),
        "top": top,
        "bottom": top + 8.0,
        "x0": min(x0 for _, x0, _ in cells),
        "x1": max(x1 for _, _, x1 in cells),
        "words": words,
    }


def detect(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    return _detect_text_tables(
        lines, page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE, defrag=False)


class CellSplitTests(unittest.TestCase):
    def test_bimodal_gaps_split_into_cells(self) -> None:
        """真表格行：格内间隙小、格间间隙大 → 按列切开。"""
        ln = line(100, ("U32", 40, 60), ("Whole", 150, 175), ("binary", 178, 205), ("4(32)", 300, 325))
        cells = _split_line_cells(ln["words"])
        self.assertEqual([c["text"] for c in cells], ["U32", "Whole binary", "4(32)"])

    def test_uniform_loose_tracking_stays_one_cell(self) -> None:
        """宽词距 prose（ABNT 前言页实测误报源）：间隙均匀大 → 自适应阈值整行归一格。"""
        xs = 40
        cells_in = []
        for w in ("Standards", "whose", "content", "is", "in", "responsibility", "the"):
            cells_in.append((w, xs, xs + len(w) * 5))
            xs += len(w) * 5 + 9   # 均匀 9pt 词距
        ln = line(100, *cells_in)
        cells = _split_line_cells(ln["words"])
        self.assertEqual(len(cells), 1)


class TextTableDetectTests(unittest.TestCase):
    def _table_lines(self) -> list[dict]:
        return [
            line(100, ("U32", 40, 60), ("Whole binary", 150, 220), ("4(32)", 300, 330)),
            line(115, ("String", 40, 70), ("Sequence", 150, 200), ("L(8*L)", 300, 335)),
            line(130, ("Struct", 40, 68), ("Ordered set", 150, 210), ("L(8*L)", 300, 335)),
            line(145, ("Date", 40, 58), ("Date format", 150, 215), ("12", 300, 312)),
        ]

    def test_aligned_columns_detected(self) -> None:
        tables, remaining = detect(self._table_lines())
        self.assertEqual(len(tables), 1)
        matrix = tables[0]["matrix"]
        self.assertEqual(len(matrix), 4)
        self.assertEqual(matrix[0][0], "U32")
        self.assertEqual(matrix[3][:2], ["Date", "Date format"])
        self.assertEqual(remaining, [])   # 全部行被消费

    def test_wrap_line_merges_into_previous_row(self) -> None:
        """包裹续行（单格、对齐已知列、无首列内容）并入上一逻辑行。"""
        lines = self._table_lines()
        lines.insert(2, line(123, ("of bytes", 150, 195),))
        tables, _ = detect(lines)
        self.assertEqual(len(tables), 1)
        matrix = tables[0]["matrix"]
        self.assertEqual(len(matrix), 4)   # 续行不新增逻辑行
        self.assertIn("Sequence of bytes", matrix[1][1])

    def test_enumerated_list_not_a_table(self) -> None:
        """枚举列表（a)/b)/c) + 缩进正文两列对齐）是最高频误报源，行级先验排除。"""
        lines = [
            line(100, ("a)", 40, 48), ("steel pipes;", 60, 130)),
            line(115, ("b)", 40, 48), ("copper pipes;", 60, 140)),
            line(130, ("c)", 40, 48), ("plastic pipes.", 60, 138)),
        ]
        tables, remaining = detect(lines)
        self.assertEqual(tables, [])
        self.assertEqual(len(remaining), 3)

    def test_dash_bullet_list_not_a_table(self) -> None:
        """破折号列表（真实误报 p22）。"""
        lines = [
            line(100, ("-", 40, 44), ("your authentication code must be consistent;", 60, 340)),
            line(115, ("-", 40, 44), ("its numbering must be included within limits;", 60, 335)),
            line(130, ("-", 40, 44), ("must be the first to be received.", 60, 300)),
        ]
        tables, _ = detect(lines)
        self.assertEqual(tables, [])

    def test_toc_not_a_table(self) -> None:
        """目录（标题 + 纯整数页码列）：TOC veto 不依赖点引导线。"""
        lines = [
            line(100, ("Scope", 40, 80), ("5", 520, 526)),
            line(115, ("Normative references", 40, 160), ("12", 518, 528)),
            line(130, ("Terms and definitions", 40, 165), ("23", 518, 528)),
            line(145, ("System architecture", 40, 155), ("41", 518, 528)),
        ]
        tables, _ = detect(lines)
        self.assertEqual(tables, [])

    def test_bilingual_two_column_page_not_a_table(self) -> None:
        """双语对照/伪两栏：两列都是长句 → 无 ≥2 个短键列，拒。"""
        lines = [
            line(100 + i * 15,
                 (f"The device shall perform verification step {i} correctly", 40, 280),
                 (f"Il dispositivo deve eseguire la verifica {i} correttamente", 300, 545))
            for i in range(8)
        ]
        tables, _ = detect(lines)
        self.assertEqual(tables, [])

    def test_heading_line_never_consumed(self) -> None:
        """标题行进表格会腐蚀 section_path：先验排除。"""
        lines = [line(85, ("4.1 System architecture", 40, 200))] + self._table_lines()
        tables, remaining = detect(lines)
        self.assertEqual(len(tables), 1)
        self.assertTrue(any("4.1 System architecture" in ln["text"] for ln in remaining))


class ReflowTests(unittest.TestCase):
    def _group(self, lines: list[dict]) -> list[str]:
        paras = _group_paragraphs(
            lines, page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE)
        return [p["text"] for p in paras]

    def test_continuation_exempts_gap_split(self) -> None:
        """错行：前行无句终标点 + 当前行小写开头 + 间距 <26 → 同段（机翻行距不齐）。"""
        texts = self._group([
            line(100, ("The device shall record the", 70, 300)),
            line(118, ("measurement in the event log.", 70, 310)),   # gap 10 → 本来就同段
            line(150, ("It must also", 70, 150)),
            line(172, ("notify the operator.", 70, 200)),            # gap 14 → 豁免合并
        ])
        self.assertEqual(len(texts), 2)
        self.assertIn("It must also notify the operator.", texts[1])

    def test_terminal_punctuation_still_splits(self) -> None:
        texts = self._group([
            line(100, ("The first requirement ends here.", 70, 300)),
            line(122, ("the second one starts lowercase", 70, 290)),   # gap 14：有句终标点不豁免
        ])
        self.assertEqual(len(texts), 2)

    def test_list_items_always_split(self) -> None:
        """列表项必自成段（不论行距多小）。"""
        texts = self._group([
            line(100, ("The following apply:", 70, 200)),
            line(110, ("a) steel pipes;", 70, 170)),
            line(120, ("b) copper pipes.", 70, 175)),
        ])
        self.assertEqual(len(texts), 3)

    def test_outdented_lowercase_transition_starts_a_new_paragraph(self) -> None:
        """A lowercase transition after an indented list continuation keeps the PDF break."""
        texts = self._group([
            line(100, ("- closed locations with condensing or", 40, 320)),
            line(112, ("with non-condensing humidity,", 60, 220)),
            line(134, ("or, if specified by the manufacturer:", 40, 240)),
        ])

        self.assertEqual(texts, [
            "- closed locations with condensing or with non-condensing humidity,",
            "or, if specified by the manufacturer:",
        ])

    def test_body_after_short_list_item_starts_a_new_paragraph(self) -> None:
        """A short list item followed by an aligned lowercase body line is not reflowed."""
        texts = self._group([
            line(100, ("- locations liable to temporary saturation,", 40, 250)),
            line(122, ("and in locations with electromagnetic disturbances", 40, 330)),
            line(134, ("corresponding to those likely to be found.", 40, 280)),
        ])

        self.assertEqual(texts, [
            "- locations liable to temporary saturation,",
            "and in locations with electromagnetic disturbances corresponding to those likely to be found.",
        ])

    def test_hyphen_dehyphenation(self) -> None:
        texts = self._group([
            line(100, ("The require-", 70, 160)),
            line(110, ("ments shall apply.", 70, 200)),
        ])
        self.assertEqual(texts, ["The requirements shall apply."])


class HeadingRefineTests(unittest.TestCase):
    def _refine(self, text: str):
        heading = detect_heading(text, "", document_profile=DEFAULT_DOCUMENT_PROFILE)
        assert heading is not None, "夹具前提：detect_heading 命中"
        return _refine_pdf_heading(heading, text, DEFAULT_DOCUMENT_PROFILE)

    def test_bare_large_int_degraded(self) -> None:
        """"100 litres and up…" 表格行被数字正则误判成标题 → 降级段落。"""
        text = "100 litres and up to 200 litres are classified as VpC1 in every case"
        self.assertIsNone(detect_heading(text, "", document_profile=DEFAULT_DOCUMENT_PROFILE))
        # Keep the PDF layer defensive for callers that already classified a line.
        heading, _, body = _refine_pdf_heading(
            (1, text), text, DEFAULT_DOCUMENT_PROFILE)
        self.assertIsNone(heading)
        self.assertIsNone(body)

    def test_short_heading_untouched(self) -> None:
        heading, text, body = self._refine("4.1 System architecture")
        self.assertIsNotNone(heading)
        self.assertEqual(text, "4.1 System architecture")
        self.assertIsNone(body)

    def test_glued_heading_split(self) -> None:
        """标题+正文粘连（机翻高频）→ 拆成标题块 + 段落块。"""
        raw = ("4.2.7 Service: Software Update The service must allow the MGW software "
               "to be updated remotely and record every attempt")
        heading, title, body = self._refine(raw)
        self.assertIsNotNone(heading)
        self.assertEqual(title, "4.2.7 Service: Software Update")
        self.assertTrue(body and body.startswith("The service must"))

    def test_glued_heading_split_partitions_raw_source_between_blocks(self) -> None:
        repaired = (
            "4.2.7 Service: Software Update The service must allow remote updates "
            "and record every attempt"
        )
        # raw 与 repaired 的差异必须是 defrag 可重放的变换（侧级重放门）：原夹具的
        # "ser vice"→"service" 超出保守修复器能力（整段重放也复现不了），改用
        # clean_text 同构的空白折叠差异——同样钉住 raw 在两块间的划分
        raw = (
            "4.2.7 Service: Software Update   The  service must allow remote updates "
            "and record every attempt"
        )
        blocks: list[dict] = []

        _append_text_block(
            blocks,
            repaired,
            order=0,
            page_number=1,
            sections=SectionState(),
            knowledge_bases=KnowledgeRepository.from_paths([]),
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            raw_text=raw,
            text_repair_checked=True,
        )

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["raw_text"] + blocks[1]["raw_text"], raw)
        self.assertNotEqual(blocks[0]["raw_text"], raw)
        self.assertNotEqual(blocks[1]["raw_text"], raw)
        for block in blocks:
            validate_source_alignment(
                block["raw_text"], block["text"], block["source_alignment"])

    def test_unsplittable_long_text_degraded(self) -> None:
        raw = "5.5.2 " + "clock synchronization data " * 8   # >160 且找不到句首拆点
        heading, _, body = self._refine(raw.strip())
        self.assertIsNone(heading)
        self.assertIsNone(body)


class ContinuationBlockMergeTests(unittest.TestCase):
    def _block(self, bid: str, text: str, *, btype: str = "paragraph", noise: bool = False,
               page_number: int | None = None) -> dict:
        return {"block_id": bid, "type": btype, "text": text, "noise": noise,
                "page_number": page_number,
                "section_path": ["4.1"], "requirement_like": False,
                "domain_tags": [], "kb_matches": []}

    def test_cross_page_continuation_merges_past_noise(self) -> None:
        """跨页断句：中间隔页脚噪声块也要接上（页内 gap 豁免够不着的场景）。"""
        kb = KnowledgeRepository.from_paths([])
        blocks = [
            self._block("B1", "The device shall record the", page_number=1),
            self._block("N1", "UNI/TS 12007 © UNI Page 5", noise=True, page_number=1),
            self._block("B2", "measurement in the event log.", page_number=2),
        ]
        merged = _merge_continuation_blocks(blocks, kb)
        self.assertEqual(len(merged), 2)   # B2 并入 B1，噪声块保留
        self.assertEqual(merged[0]["text"], "The device shall record the measurement in the event log.")
        validate_source_alignment(
            merged[0]["raw_text"], merged[0]["text"], merged[0]["source_alignment"])
        self.assertTrue(merged[0]["raw_to_repaired_spans"])

    def test_cross_page_continuation_preserves_raw_trailing_characters(self) -> None:
        kb = KnowledgeRepository.from_paths([])
        first = self._block("B1", "The device shall record the", page_number=1)
        second = self._block("B2", "measurement in the log.", page_number=2)
        first["raw_text"] = "The device shall record the  "
        second["raw_text"] = "meas urement in the log."
        expected_raw = first["raw_text"] + " " + second["raw_text"]

        merged = _merge_continuation_blocks([first, second], kb)

        self.assertEqual(merged[0]["raw_text"], expected_raw)
        validate_source_alignment(
            merged[0]["raw_text"], merged[0]["text"], merged[0]["source_alignment"])

    def test_same_page_paragraph_break_is_not_merged_back(self) -> None:
        kb = KnowledgeRepository.from_paths([])
        blocks = [
            self._block("B1", "- locations liable to temporary saturation,", page_number=6),
            self._block("B2", "and in locations with electromagnetic disturbances.", page_number=6),
        ]

        merged = _merge_continuation_blocks(blocks, kb)

        self.assertEqual([block["text"] for block in merged], [
            "- locations liable to temporary saturation,",
            "and in locations with electromagnetic disturbances.",
        ])

    def test_heading_between_blocks_no_merge(self) -> None:
        kb = KnowledgeRepository.from_paths([])
        blocks = [
            self._block("B1", "The device shall record the"),
            self._block("H1", "4.2 Services", btype="heading"),
            self._block("B2", "measurement in the event log."),
        ]
        merged = _merge_continuation_blocks(blocks, kb)
        self.assertEqual(len(merged), 3)


if __name__ == "__main__":
    unittest.main()
