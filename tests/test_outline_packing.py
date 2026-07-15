"""目录子树打包回归(0715 抽取质量重构,通用规则)。

双线对比实证的病根:两级族键+族内纯字数贪心把深层 Requirements/Test 兄弟切进不同
单元 → 模型对孤立测试片段过度演绎(内容缺陷率 58% vs 主体 18%)。本套锁:
整子树优先/要求测试绑定/插入伪标题免疫/微单元折叠/无编号回退/顺序保持。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract_units import (
    DEFAULT_MERGE_CHARS,
    merge_sections,
    outline_path,
    pack_by_outline,
)


def sec(heading: str, chars: int = 300, sid: str | None = None) -> dict:
    return {"section_id": sid or heading, "heading": heading,
            "section_path": [heading], "text": "x" * chars,
            "block_ids": [f"B-{heading}"], "source_blocks": []}


def headings_of(unit: dict) -> str:
    return unit.get("text") or ""


class OutlinePathTests(unittest.TestCase):
    def test_numeric_and_annex_paths(self) -> None:
        self.assertEqual(outline_path(sec("7.13.4.3.1 Test")), (7, 13, 4, 3, 1))
        self.assertEqual(outline_path(sec("Annex A")), ("A",))
        self.assertEqual(outline_path(sec("A.1.2 Procedure")), ("A", 1, 2))
        self.assertIsNone(outline_path(sec("General prose heading")))


class FamilyBindingTests(unittest.TestCase):
    def test_requirement_and_test_siblings_never_separated(self) -> None:
        # 深层族:父子树超预算必须下钻,但 x.y.1 Requirements + x.y.2 Test 绑定不拆
        sections = [
            sec("4.12 Immunity", 40),
            sec("4.12.1 General", 200),
            sec("4.12.2 Permanent magnetic fields", 40),
            sec("4.12.2.1 Requirements", 2000),
            sec("4.12.2.2 Test", 2000),
            sec("4.12.3 Electrostatic discharge", 40),
            sec("4.12.3.1 Requirements", 2000),
            sec("4.12.3.2 Test", 2000),
        ]
        units = pack_by_outline(sections, target_chars=2800)
        for u in units:
            text = headings_of(u)
            for fam in ("4.12.2", "4.12.3"):
                if f"{fam}.2 Test" in text:
                    self.assertIn(f"{fam}.1 Requirements", text,
                                  f"{fam} 的 Test 与 Requirements 被拆开")

    def test_whole_subtree_packed_when_it_fits(self) -> None:
        sections = [sec("6 Power system", 100), sec("6.1 General", 400),
                    sec("6.2 Battery", 400), sec("6.3 Battery life", 400)]
        units = pack_by_outline(sections, target_chars=2800)
        self.assertEqual(len(units), 1)          # 整子树装得下 → 一个单元

    def test_oversized_family_stays_within_double_target(self) -> None:
        sections = [sec(f"5.{i} Clause", 1500) for i in range(1, 9)]
        units = pack_by_outline(sections, target_chars=2800)
        self.assertTrue(all(len(u["text"]) <= 2800 * 2 + 10 for u in units))
        self.assertGreater(len(units), 1)


class InterloperImmunityTests(unittest.TestCase):
    def test_garbage_heading_between_siblings_absorbed(self) -> None:
        # 实证场景:水印行被解析成"16 章"插在 4.12.2.1/4.12.2.2 之间
        sections = [
            sec("4.12.2 Permanent magnetic fields", 40),
            sec("4.12.2.1 Requirements", 2000),
            sec("16 --garbage watermark line--", 60),
            sec("4.12.2.2 Test", 2000),
            sec("4.12.3 Next clause", 300),
        ]
        units = pack_by_outline(sections, target_chars=2800)
        for u in units:
            if "4.12.2.2 Test" in u["text"]:
                self.assertIn("4.12.2.1 Requirements", u["text"])   # 夹层不再拆散兄弟
                self.assertIn("garbage watermark", u["text"])       # 夹层内容原位保留

    def test_large_interloper_not_absorbed(self) -> None:
        # 大块异前缀内容不是夹层,是真正的结构断点——绝不吞
        sections = [
            sec("4.1 Clause", 500),
            sec("9 Real big other chapter", 3000),
            sec("4.2 Clause", 500),
        ]
        units = pack_by_outline(sections, target_chars=2800)
        big = next(u for u in units if "Real big other chapter" in u["text"])
        self.assertNotIn("4.1 Clause", big["text"])


class TinyUnitFoldTests(unittest.TestCase):
    def test_tiny_stub_folds_into_previous(self) -> None:
        sections = [sec("4.1 Clause", 2600), sec("15 valve under test", 30)]
        units = pack_by_outline(sections, target_chars=2800)
        self.assertEqual(len(units), 1)
        self.assertIn("valve under test", units[0]["text"])
        self.assertIn("B-15 valve under test", units[0]["block_ids"])   # 溯源随并


class CompatibilityTests(unittest.TestCase):
    def test_unnumbered_prose_falls_back_to_greedy(self) -> None:
        sections = [sec("Foreword", 1000), sec("Introduction", 1000), sec("Background", 1000)]
        units = pack_by_outline(sections, target_chars=2800)
        self.assertEqual(len(units), 2)          # 旧贪心:1000+1000 | 1000

    def test_document_order_preserved(self) -> None:
        sections = [sec(f"{i} Chapter", 2600) for i in range(1, 6)]
        units = pack_by_outline(sections, target_chars=2800)
        order = [u["heading"] for u in units]
        self.assertEqual(order, sorted(order, key=lambda h: int(h.split(" ")[0])))

    def test_merge_sections_clause_mode_uses_outline_packing(self) -> None:
        sections = [
            sec("4.6 Clause B", 40),
            sec("4.6.1 Requirements", 2000),
            sec("4.6.2 Test", 2000),
        ]
        units = merge_sections(sections, target_chars=2800)
        self.assertEqual(len(units), 1)          # 族整体一个单元(2×target 内)
        self.assertIn("4.6.1 Requirements", units[0]["text"])
        self.assertIn("4.6.2 Test", units[0]["text"])

    def test_chapter_mode_unchanged(self) -> None:
        sections = [sec("4.1 A", 1000), sec("4.2 B", 1000), sec("5.1 C", 1000)]
        units = merge_sections(sections, target_chars=2800, unit_mode="chapter")
        self.assertEqual(len(units), 2)          # 章 4 一单元、章 5 一单元


if __name__ == "__main__":
    unittest.main()
