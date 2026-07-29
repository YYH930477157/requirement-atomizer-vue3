"""清单段合并（_merge_list_item_blocks）测试。

真实背景（test6 招标 PDF）："Terminals:" + 9 个端子清单行被切成 10 个 5-8 字符微块，
微块过不了锚点匹配的 12 字符门槛，清单中段无法锚定/显示覆盖。并段只并同页同小节的
连续名词式短清单项；枚举型需求行（requirement_like）不并。
"""
from __future__ import annotations

import unittest

from parsers.pdf_parser import _merge_list_item_blocks
from requirement_kb.repository import KnowledgeRepository
from source_spans import source_alignment_is_approved, validate_source_alignment


KB = KnowledgeRepository(entries=[], infos=[])


def _block(bid: str, text: str, *, page: int = 6, section: list[str] | None = None,
           req_like: bool = False, noise: bool = False, btype: str = "paragraph") -> dict:
    return {
        "block_id": bid, "type": btype, "text": text,
        "section_path": section if section is not None else ["3.4.4 Marking"],
        "page_number": page, "requirement_like": req_like, "noise": noise,
        "pdf_regions": [{"page": page, "id": bid}],
    }


class ListItemMergeTests(unittest.TestCase):
    def test_repaired_members_keep_independent_replay_provenance(self) -> None:
        first = _block("B1", "- Highest threshold")
        first.update({
            "raw_text": "- H ighest threshold",
            "text_repair_checked": True,
            "text_repair_version": "pdf-text-repair-v4",
            "text_repairs": [{"rule": "wordlist_fragment_repair"}],
        })
        second = _block("B2", "- Lowest threshold")
        second.update({
            "raw_text": "- L owest threshold",
            "text_repair_checked": True,
            "text_repair_version": "pdf-text-repair-v4",
            "text_repairs": [{"rule": "wordlist_fragment_repair"}],
        })

        merged = _merge_list_item_blocks([first, second], KB)

        self.assertEqual(len(merged), 1)
        for member in merged[0]["list_items"]:
            self.assertTrue(member["text_repair_checked"])
            self.assertTrue(source_alignment_is_approved(
                member["raw_text"], member["text"], member["source_alignment"]
            ))

    def test_intro_and_bullet_run_merge_into_one_anchorable_block(self) -> None:
        blocks = [
            _block("B1", "Terminals:"),
            _block("B2", "- RS485"),
            _block("B3", "- MPA"),
            _block("B4", "- +AA"),
            _block("B5", "- Auxiliary power supply"),
            _block("B6", "The meter shall record events.", req_like=True),
        ]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["block_id"], "B1")
        self.assertIn("- +AA", merged[0]["text"])
        self.assertIn("Terminals:", merged[0]["text"])
        self.assertTrue(merged[0]["text"].endswith("- Auxiliary power supply"))
        self.assertEqual(len(merged[0]["pdf_regions"]), 5)
        self.assertEqual(
            [(item["block_id"], item["role"]) for item in merged[0]["list_items"]],
            [("B1", "intro"), ("B2", "item"), ("B3", "item"),
             ("B4", "item"), ("B5", "item")],
        )
        for item in merged[0]["list_items"]:
            locator = item["locator"]
            raw_locator = item["raw_locator"]
            self.assertEqual(
                merged[0]["text"][locator["start"]:locator["end"]], item["text"])
            self.assertEqual(
                merged[0]["raw_text"][raw_locator["start"]:raw_locator["end"]],
                item["raw_text"],
            )
        validate_source_alignment(
            merged[0]["raw_text"], merged[0]["text"], merged[0]["source_alignment"])
        self.assertTrue(merged[0]["raw_to_repaired_spans"])
        self.assertTrue(all(item["raw_to_repaired_spans"] for item in merged[0]["list_items"]))
        self.assertEqual(merged[1]["block_id"], "B6")

    def test_run_without_intro_merges(self) -> None:
        blocks = [
            _block("B0", "All terminals must be marked.", req_like=True),
            _block("B2", "- RS485"),
            _block("B3", "- MPA"),
        ]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]["block_id"], "B2")
        self.assertEqual(merged[1]["text"], "- RS485\n- MPA")

    def test_requirement_like_enumerations_are_not_merged(self) -> None:
        blocks = [
            _block("B1", "a) The meter shall record events.", req_like=True),
            _block("B2", "b) The meter shall store profiles.", req_like=True),
        ]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual([b["block_id"] for b in merged], ["B1", "B2"])

    def test_single_item_does_not_merge(self) -> None:
        blocks = [_block("B1", "- RS485"), _block("B2", "Normal paragraph.")]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual(len(merged), 2)

    def test_page_boundary_stops_the_run(self) -> None:
        blocks = [
            _block("B1", "- RS485", page=6),
            _block("B2", "- MPA", page=7),
        ]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual(len(merged), 2)

    def test_section_boundary_stops_the_run(self) -> None:
        blocks = [
            _block("B1", "- RS485", section=["3.4.4 Marking"]),
            _block("B2", "- MPA", section=["3.4.5 Screws"]),
        ]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual(len(merged), 2)

    def test_heading_and_noise_are_not_absorbed(self) -> None:
        blocks = [
            _block("B0", "Machine Translated by Google", noise=True),
            _block("B1", "- RS485"),
            _block("B2", "- MPA"),
        ]

        merged = _merge_list_item_blocks(blocks, KB)

        self.assertEqual(len(merged), 2)
        self.assertTrue(merged[0]["noise"])


if __name__ == "__main__":
    unittest.main()
