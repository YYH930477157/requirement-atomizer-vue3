"""义务基线碎片过滤（conservation v6）：lead-in/悬空片段不是独立可测义务，
从义务基线剔除并审计计数（不静默）——SBD 实测两边各 21 条假义务
（"shall include:"、"will be issued and"、"must be authenticated" 类），
污染 obligation_coverage 的信号。

判据（确定性、保守）：
- 悬空连接尾：单元以 ":" 结尾，或剥离尾标点（.,;）后以 and/or/that/which 结尾；
- 主语缺失短单元：以 shall/will/must/should/may 开头且拉丁词数 <6（仅对含
  拉丁文的单元生效——CJK 单元无空格分词，不适用该规则，宁漏勿错）。
带主语的完整义务（"The meter shall …"）一律保留。
"""
from __future__ import annotations

import unittest

import functional_extract as fe


def _section(text: str) -> dict:
    return {"section_id": "4.1", "section_path": ["4.1"], "heading": "4.1",
            "text": text, "block_ids": ["B1"]}


class ObligationFragmentFilterTests(unittest.TestCase):
    def test_fragments_excluded_from_obligation_index(self) -> None:
        text = (
            "shall include:\n"
            "The meter shall record all load profiles.\n"
            "will be issued and\n"
            "must be authenticated"
        )
        rows = fe._obligation_index(_section(text))
        sentences = [row["sentence"] for row in rows]
        # 单元由模态词切分、不含主语（既有语义）——断言模态起头的完整单元
        self.assertIn("shall record all load profiles.", sentences)
        self.assertNotIn("shall include:", sentences)
        self.assertNotIn("will be issued and", sentences)
        self.assertNotIn("must be authenticated", sentences)

    def test_subject_led_leadin_is_kept(self) -> None:
        rows = fe._obligation_index(_section("The meter shall include: tariff data."))
        self.assertTrue(rows, "带主语的完整句不是碎片，必须保留")

    def test_long_connector_tail_excluded(self) -> None:
        rows = fe._obligation_index(_section("will be issued and"))
        self.assertEqual(rows, [], "内容词<2 的悬空连接尾是碎片")

    def test_compound_predicate_tail_is_kept(self) -> None:
        """复合谓语的模态切分残留（"shall log events and [shall send alarms]"）
        内容词充足，不是碎片——过滤不得误杀（守恒夹具回归形态）。"""
        rows = fe._obligation_index(
            _section("The meter shall log events and shall send alarms."))
        sentences = [row["sentence"] for row in rows]
        self.assertEqual(sentences, ["shall log events and", "shall send alarms."])

    def test_cjk_units_bypass_latin_short_rule(self) -> None:
        rows = fe._obligation_index(_section("电表应支持远程拉闸功能。"))
        self.assertTrue(rows, "CJK 义务单元不走拉丁短词规则，不得被误剔")

    def test_conservation_reports_fragment_audit_count(self) -> None:
        sections = [_section(
            "shall include:\nThe meter shall record all load profiles.")]
        report = fe.conservation_report(sections, [], blocks=[])
        check = (report.get("checks") or {}).get("obligation_coverage") or {}
        self.assertEqual(check.get("fragment_units_excluded"), 1)
        uncovered = [row["sentence"] for row in check.get("uncovered_obligations") or []]
        self.assertNotIn("shall include:", uncovered)
        self.assertTrue(
            uncovered, "剔除碎片后真实义务仍在基线（此处无 item，应报 uncovered）")


if __name__ == "__main__":
    unittest.main()
