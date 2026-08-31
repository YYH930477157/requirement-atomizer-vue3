# -*- coding: utf-8 -*-
"""binding_mismatches 归因诊断库（tools/binding_attribution.py）的判定测试。

覆盖：stub 判定、四类归因的信号→类别映射、镜像收集器与
``functional_extract.conservation_report`` 的逐条一致性（合成语料），以及 conservation v7 后「清单引句逐字锚定」不再进 binding_mismatches、
「叙述复述未声明条款」仍走 reason 2 的镜像一致性。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for entry in (str(_REPO), str(_REPO / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import binding_attribution as ba  # noqa: E402
import functional_extract as fe  # noqa: E402


def _signals(**overrides) -> dict:
    base = {
        "reason": "declared_section_has_no_local_obligation_coverage",
        "is_stub": False,
        "quote_present": True,
        "quote_in_home": False,
        "home_unit_in_quote": False,
        "quote_in_kept_other": False,
        "quote_in_dropped_only": False,
        "source_section_matches_quote_site": False,
        "covered_other_text_in_home": False,
        "narrative_covers_nonhome": False,
    }
    base.update(overrides)
    return base


class StubDetectionTests(unittest.TestCase):
    def test_stub_objective_literal_is_detected(self) -> None:
        self.assertTrue(ba.is_stub_item(
            {"objective": "实现7.5 Display，并满足来源条款。"}))

    def test_regular_objective_is_not_stub(self) -> None:
        self.assertFalse(ba.is_stub_item(
            {"objective": "The display shall show the tariff index."}))
        self.assertFalse(ba.is_stub_item({"objective": ""}))


class ClassifySignalsTests(unittest.TestCase):
    def test_stub_item_is_category_d(self) -> None:
        verdict = ba.classify_signals(_signals(is_stub=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_STUB)

    def test_quote_in_home_without_edge_is_category_b(self) -> None:
        verdict = ba.classify_signals(_signals(quote_in_home=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_CHECK_FALSE_POSITIVE)
        self.assertEqual(
            verdict["detail"],
            "quote_present_in_declared_clause_but_no_edge_formed")

    def test_quote_in_home_with_crossclause_overlap_stays_category_b(self) -> None:
        # 人工抽查实证：该子集混有吞并 heading 切分病理与重复文本，确定性信号
        # 不足以证明借位——保守归 (b) 并以独立 detail 标出供人工复核。
        verdict = ba.classify_signals(
            _signals(quote_in_home=True, narrative_covers_nonhome=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_CHECK_FALSE_POSITIVE)
        self.assertEqual(
            verdict["detail"],
            "quote_in_home_no_edge_with_crossclause_lexical_overlap")

    def test_quote_only_in_dropped_clause_is_category_c(self) -> None:
        verdict = ba.classify_signals(_signals(quote_in_dropped_only=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_CLAUSE_DRIFT)
        self.assertEqual(
            verdict["detail"], "quote_site_clause_left_conservation_baseline")

    def test_stale_boundary_declaration_is_category_c(self) -> None:
        verdict = ba.classify_signals(_signals(
            quote_in_kept_other=True, source_section_matches_quote_site=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_CLAUSE_DRIFT)
        self.assertEqual(
            verdict["detail"], "declared_blocks_follow_stale_clause_boundary")

    def test_declared_blocks_disagreeing_with_quote_site_is_category_a(self) -> None:
        verdict = ba.classify_signals(_signals(quote_in_kept_other=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_TRUE_BORROWING)
        self.assertEqual(
            verdict["detail"], "declared_blocks_disagree_with_quote_site")

    def test_unanchorable_quote_is_category_a(self) -> None:
        verdict = ba.classify_signals(_signals(quote_present=False))
        self.assertEqual(verdict["category"], ba.CATEGORY_TRUE_BORROWING)
        self.assertEqual(
            verdict["detail"], "quote_unanchorable_in_current_sections")

    def test_reason2_with_duplicated_text_is_category_b(self) -> None:
        verdict = ba.classify_signals(_signals(
            reason="narrative_covers_other_clauses_not_declared",
            covered_other_text_in_home=True))
        self.assertEqual(verdict["category"], ba.CATEGORY_CHECK_FALSE_POSITIVE)
        self.assertEqual(
            verdict["detail"],
            "covered_clause_text_duplicated_in_declared_clause")

    def test_reason2_plain_is_category_a(self) -> None:
        verdict = ba.classify_signals(_signals(
            reason="narrative_covers_other_clauses_not_declared"))
        self.assertEqual(verdict["category"], ba.CATEGORY_TRUE_BORROWING)
        self.assertEqual(
            verdict["detail"], "narrative_retells_undeclared_clause_obligations")


def _sections() -> list[dict]:
    return [
        {
            "section_id": "S1",
            "section_path": ["7 GENERAL", "7.5 Display"],
            "heading": "7.5 Display",
            "block_ids": ["B1"],
            "text": (
                "The meter shall record monthly energy usage totals. "
                "Display options:\n- Currency display\n- Tariff index display"
            ),
        },
        {
            "section_id": "S2",
            "section_path": ["7 GENERAL", "7.6 Backlight"],
            "heading": "7.6 Backlight",
            "block_ids": ["B2"],
            "text": (
                "The backlight shall turn off after sixty seconds of keypad "
                "inactivity."
            ),
        },
    ]


def _items() -> list[dict]:
    return [
        {
            # (b) 类最小复现：引句逐字取自 S1 的清单内容（无模态动词——永远
            # 成不了义务单元），叙述也不覆盖 S1 的模态句 → 三种建边方法全部
            # 失败 → reason 1 触发，尽管 FRE 内容确实属于声明条款。
            "functional_requirement_id": "FRE-LIST",
            "source_block_ids": ["B1"],
            "source_section": "7.5 Display",
            "objective": "Provide currency and tariff index display options.",
            "source_quote": "- Currency display\n- Tariff index display",
        },
        {
            # (a) 类：引句锚定 S2（source_quote 含 S2 义务单元 → 本地边成立、
            # 过 reason 1 闸），但叙述逐字复述 S1 的义务句且未声明 S1
            # → reason 2 触发。
            "functional_requirement_id": "FRE-BORROW",
            "source_block_ids": ["B2"],
            "source_section": "7.6 Backlight",
            "objective": (
                "The meter shall record monthly energy usage totals."
            ),
            "source_quote": (
                "The backlight shall turn off after sixty seconds of keypad "
                "inactivity."
            ),
        },
    ]


class CollectorMirrorTests(unittest.TestCase):
    """镜像收集器与 conservation_report 检查 3 在合成语料上逐条一致。"""

    def test_mirror_matches_conservation_report_and_classifies(self) -> None:
        sections = _sections()
        items = _items()
        report = fe.conservation_report(sections, items)
        report_pairs = [
            (str(mm.get("functional_requirement_id") or ""),
             str(mm.get("reason") or ""))
            for mm in (report["checks"]["evidence_presence"]
                       .get("binding_mismatches") or [])
        ]
        findings = ba.collect_binding_findings(sections, items)
        mirror_pairs = [
            (f["functional_requirement_id"], f["reason"]) for f in findings
        ]
        self.assertEqual(mirror_pairs, report_pairs)
        self.assertEqual(
            report_pairs,
            [
                ("FRE-BORROW",
                 "narrative_covers_other_clauses_not_declared"),
            ],
        )
        # conservation v7：FRE-LIST 引句逐字在声明条款内 → reason 1 不再误伤。
        self.assertNotIn(
            ("FRE-LIST", "declared_section_has_no_local_obligation_coverage"),
            report_pairs,
        )

        baseline_sections, _delegated = fe._conservation_baseline_sections(
            sections, out_dir=None, blocks=None)
        clause_units = [fe._obligation_index(s) for s in baseline_sections]
        verdicts = {}
        for finding in findings:
            item = items[finding["item_index"]]
            signals = ba.build_signals(
                finding, item=item,
                baseline_sections=baseline_sections,
                clause_units=clause_units,
                all_sections=sections,
            )
            verdicts[finding["functional_requirement_id"]] = (
                ba.classify_signals(signals))

        # FRE-LIST：v7 后不再进 binding_mismatches（引句逐字锚定豁免 reason 1）。
        self.assertNotIn("FRE-LIST", verdicts)
        # FRE-BORROW：叙述复述未声明条款义务 → (a) 真借位。
        self.assertEqual(
            verdicts["FRE-BORROW"]["category"], ba.CATEGORY_TRUE_BORROWING)


class SectionIdentityKeyTests(unittest.TestCase):
    def test_identity_key_uses_block_ids_not_section_id(self) -> None:
        # SBD 语料 337/358 chunk 撞名同一 section_id——身份键必须走 block_ids。
        s1 = {"section_id": "2 20 Control of", "block_ids": ["B1", "B2"]}
        s2 = {"section_id": "2 20 Control of", "block_ids": ["B9"]}
        self.assertNotEqual(
            ba.section_identity_key(s1), ba.section_identity_key(s2))
        self.assertEqual(ba.section_identity_key(s1), ("B1", "B2"))


if __name__ == "__main__":
    unittest.main()
