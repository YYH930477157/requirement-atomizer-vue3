"""确定性大纲权威（document-outline-v1）shadow 报告测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from document_outline import (
    BODY_SENTENCE_MIN_CHARS,
    DOCUMENT_OUTLINE_VERSION,
    build_outline_report,
    write_outline_report,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "portfolio"


def _heading(
    block_id: str,
    text: str,
    *,
    section_path: list[str] | None = None,
    order: int = 1,
) -> dict:
    path = list(section_path) if section_path is not None else [text]
    return {
        "block_id": block_id,
        "order": order,
        "type": "heading",
        "text": text,
        "section_path": path,
    }


def _paragraph(
    block_id: str,
    text: str,
    *,
    section_path: list[str],
    order: int = 2,
) -> dict:
    return {
        "block_id": block_id,
        "order": order,
        "type": "paragraph",
        "text": text,
        "section_path": list(section_path),
    }


def _by_id(report: dict, block_id: str) -> dict:
    for row in report["headings"]:
        if row["block_id"] == block_id:
            return row
    raise AssertionError(f"missing heading {block_id}")


class ObligationSentenceTests(unittest.TestCase):
    def test_numbered_obligation_sentence_is_demoted(self) -> None:
        blocks = [
            _heading(
                "H-OBL",
                "26 There shall be no change of original equipment manufacturer for this lot.",
            ),
        ]
        row = _by_id(build_outline_report(blocks), "H-OBL")
        self.assertEqual(row["verdict"], "demoted_body_sentence")
        self.assertTrue(any(item["kind"] == "obligation_sentence" for item in row["evidence"]))
        self.assertGreaterEqual(
            len("There shall be no change of original equipment manufacturer for this lot."),
            BODY_SENTENCE_MIN_CHARS,
        )

    def test_all_caps_technical_title_is_not_demoted(self) -> None:
        blocks = [
            _heading("H-CAPS", "2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)"),
        ]
        row = _by_id(build_outline_report(blocks), "H-CAPS")
        self.assertEqual(row["verdict"], "confirmed")
        self.assertTrue(any(item["kind"] == "all_caps_title" for item in row["evidence"]))
        self.assertFalse(any(item["kind"] == "obligation_sentence" for item in row["evidence"]))

    def test_noun_phrase_title_is_not_demoted(self) -> None:
        blocks = [
            _heading("H-NOUN", "2.2 Delivery Schedule"),
        ]
        row = _by_id(build_outline_report(blocks), "H-NOUN")
        self.assertEqual(row["verdict"], "confirmed")
        self.assertFalse(any(item["kind"] == "obligation_sentence" for item in row["evidence"]))

    def test_short_modal_title_is_not_demoted(self) -> None:
        blocks = [
            _heading("H-SHORT", "The meter shall."),
        ]
        row = _by_id(build_outline_report(blocks), "H-SHORT")
        self.assertEqual(row["verdict"], "confirmed")

    def test_truncated_wrap_still_demotes_inner_obligation_sentence(self) -> None:
        blocks = [
            _heading(
                "H-WRAP",
                "26. There shall be no change of Original Equipment Manufacturer (OEM) for this tender. Change of OEM at",
            ),
        ]
        row = _by_id(build_outline_report(blocks), "H-WRAP")
        self.assertEqual(row["verdict"], "demoted_body_sentence")


class TocEntryTests(unittest.TestCase):
    def test_leader_dots_and_page_number_are_toc(self) -> None:
        blocks = [
            _heading("H-TOC", "2.20 Control of disconnection ........ 12"),
        ]
        row = _by_id(build_outline_report(blocks), "H-TOC")
        self.assertEqual(row["verdict"], "toc_entry")
        self.assertTrue(any(item["kind"] == "toc_leader_page" for item in row["evidence"]))

    def test_spaced_leader_and_tab_page_are_toc(self) -> None:
        blocks = [
            _heading("H-DOTS", "Definitions . . . 8"),
            _heading("H-TAB", "References\t14", section_path=["References"]),
        ]
        report = build_outline_report(blocks)
        self.assertEqual(_by_id(report, "H-DOTS")["verdict"], "toc_entry")
        self.assertEqual(_by_id(report, "H-TAB")["verdict"], "toc_entry")

    def test_normal_title_is_not_toc(self) -> None:
        blocks = [
            _heading("H-OK", "2.20 Control of disconnection"),
        ]
        row = _by_id(build_outline_report(blocks), "H-OK")
        self.assertEqual(row["verdict"], "confirmed")
        self.assertFalse(any(item["kind"].startswith("toc_") for item in row["evidence"]))

    def test_first_page_tail_plus_later_duplicate_is_toc_evidence(self) -> None:
        blocks = [
            _heading("H-TOC", "Operating voltage ........ 21"),
            _paragraph("P-GAP", "gap", section_path=["body"], order=2),
            _heading(
                "H-BODY",
                "Operating voltage",
                section_path=["Operating voltage"],
                order=3,
            ),
        ]
        report = build_outline_report(blocks)
        toc = _by_id(report, "H-TOC")
        body = _by_id(report, "H-BODY")
        self.assertEqual(toc["verdict"], "toc_entry")
        self.assertTrue(any(item["kind"] == "toc_duplicate_title" for item in toc["evidence"]))
        self.assertEqual(body["verdict"], "confirmed")


class SwallowedAndCollisionTests(unittest.TestCase):
    def test_heading_in_middle_of_section_is_swallowed(self) -> None:
        path = ["2.2 Delivery Schedule"]
        blocks = [
            _heading("H-OWN", "2.2 Delivery Schedule", section_path=path, order=1),
            _paragraph("P-1", "Delivery is two months.", section_path=path, order=2),
            _heading(
                "H-SWALLOW",
                "2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)",
                section_path=path,
                order=3,
            ),
        ]
        report = build_outline_report(blocks)
        ids = {item["block_id"] for item in report["swallowed_headings"]}
        self.assertIn("H-SWALLOW", ids)
        self.assertNotIn("H-OWN", ids)
        self.assertEqual(_by_id(report, "H-SWALLOW")["verdict"], "confirmed")

    def test_first_heading_of_section_is_not_swallowed(self) -> None:
        blocks = [
            _heading("H-1", "1 Scope"),
            _paragraph("P-1", "This document applies.", section_path=["1 Scope"]),
        ]
        report = build_outline_report(blocks)
        self.assertEqual(report["swallowed_headings"], [])

    def test_section_id_collision_above_threshold(self) -> None:
        blocks = []
        for index in range(4):
            title = "2 20 Control of"
            blocks.append(_heading(
                f"H-COL-{index}",
                title,
                section_path=[title],
                order=index * 2 + 1,
            ))
            blocks.append(_paragraph(
                f"P-COL-{index}",
                f"Clause body {index}.",
                section_path=[title],
                order=index * 2 + 2,
            ))
        report = build_outline_report(blocks)
        self.assertEqual(len(report["section_id_collisions"]), 1)
        self.assertEqual(report["section_id_collisions"][0]["section_count"], 4)
        self.assertEqual(report["section_id_collisions"][0]["last_segment"], "2 20 Control of")

    def test_two_shared_tails_are_not_a_collision(self) -> None:
        title = "2 20 Control of"
        blocks = [
            _heading("H-A", title, section_path=[title], order=1),
            _paragraph("P-A", "a", section_path=[title], order=2),
            _heading("H-B", title, section_path=[title], order=3),
            _paragraph("P-B", "b", section_path=[title], order=4),
        ]
        report = build_outline_report(blocks)
        self.assertEqual(report["section_id_collisions"], [])


class NumberSequenceTests(unittest.TestCase):
    def test_sequence_regression_is_suspect_not_demotion(self) -> None:
        blocks = [
            _heading("H-2", "2 Scope"),
            _heading("H-1", "1 General"),
        ]
        report = build_outline_report(blocks)
        self.assertEqual(_by_id(report, "H-2")["verdict"], "confirmed")
        row = _by_id(report, "H-1")
        self.assertEqual(row["verdict"], "suspect")
        self.assertTrue(any(item["kind"] == "number_sequence_regression" for item in row["evidence"]))

    def test_legal_child_and_sibling_stay_confirmed(self) -> None:
        blocks = [
            _heading("H-1", "1 Scope"),
            _heading("H-11", "1.1 Terms"),
            _heading("H-12", "1.2 Symbols"),
            _heading("H-2", "2 Requirements"),
        ]
        report = build_outline_report(blocks)
        for block_id in ("H-1", "H-11", "H-12", "H-2"):
            self.assertEqual(_by_id(report, block_id)["verdict"], "confirmed", block_id)


class PortfolioFixtureTests(unittest.TestCase):
    def test_tender_pdf_pathology_pins(self) -> None:
        spec = json.loads((FIXTURE_DIR / "tender_pdf_pathology.json").read_text(encoding="utf-8"))
        report = build_outline_report(list(spec["blocks"]))
        oem = _by_id(report, "BLK-OEM-H")
        self.assertEqual(oem["verdict"], "demoted_body_sentence")
        swallowed_ids = {item["block_id"] for item in report["swallowed_headings"]}
        self.assertIn("BLK-SWALLOW-H", swallowed_ids)
        self.assertTrue(
            any("STATEMENT OF REQUIREMENTS" in item["text"] for item in report["swallowed_headings"])
        )
        caps = _by_id(report, "BLK-TECH-H")
        self.assertEqual(caps["verdict"], "confirmed")
        self.assertTrue(any(item["kind"] == "all_caps_title" for item in caps["evidence"]))
        self.assertEqual(_by_id(report, "BLK-DEL-H")["verdict"], "confirmed")
        self.assertEqual(report["summary"]["heading_count"], 7)
        self.assertEqual(report["summary"]["demoted_body_sentence"], 1)
        self.assertEqual(report["summary"]["confirmed"], 5)
        self.assertEqual(report["summary"]["suspect"], 1)
        self.assertEqual(report["summary"]["swallowed_heading_count"], 2)


class WriteOutlineReportTests(unittest.TestCase):
    def test_write_uses_governed_filename(self) -> None:
        from result_package import governed_artifact_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocks = [_heading("H-1", "1 Scope")]
            (root / "blocks.jsonl").write_text(
                json.dumps(blocks[0], ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report = write_outline_report(root)
            path = governed_artifact_path(
                root, "document_outline.json", category="pipeline", for_write=False,
            )
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["version"], DOCUMENT_OUTLINE_VERSION)
            self.assertEqual(report["summary"]["heading_count"], 1)

    def test_cli_outline_command_is_registered(self) -> None:
        from cli import parse_args

        args = parse_args(["outline", "--out", "tmp-out"])
        self.assertEqual(args.command, "outline")


if __name__ == "__main__":
    unittest.main()
