"""WS2 原子级下钻判定器（functional_drilldown）机制测试。

纪律：LLM 不参与"是否下钻"决策——全部信号确定性。验收面：三类结构信号 + 三类质量信号、
阈值配置项、子原子确定性切分回填、批量 apply。
"""
from __future__ import annotations

import unittest

import functional_drilldown as fd


def _item(**kw) -> dict:
    base = {"functional_requirement_id": "F1", "objective": "x"}
    base.update(kw)
    return base


def _section(text: str, block_ids: list[str] | None = None) -> dict:
    return {"text": text, "heading": "h", "block_ids": block_ids or ["B1"], "section_path": ["4.1"]}


class StructuralSignalsTests(unittest.TestCase):
    def test_multi_behavior_fires_on_two_modal_actions(self) -> None:
        sig = fd.multi_behavior_signal("The meter shall collect data and shall report events.")
        self.assertTrue(sig["fired"])
        self.assertGreaterEqual(sig["modal_action_count"], 2)

    def test_multi_behavior_quiet_on_single(self) -> None:
        sig = fd.multi_behavior_signal("The meter shall log.")
        self.assertFalse(sig["fired"])

    def test_multi_behavior_chinese_modals(self) -> None:
        sig = fd.multi_behavior_signal("表具应采集电压，并应上报事件。")
        self.assertTrue(sig["fired"])

    def test_multi_condition_fires_on_branch(self) -> None:
        sig = fd.multi_condition_signal("If import then forward; otherwise discard.")
        self.assertTrue(sig["fired"])

    def test_multi_condition_chinese(self) -> None:
        sig = fd.multi_condition_signal("如果发生故障，则记录；否则忽略。")
        self.assertTrue(sig["fired"])

    def test_parameter_matrix_fires_on_multi_rows(self) -> None:
        section = _section("see table", block_ids=["T1"])
        table_items = [{"table_block_id": "T1"} for _ in range(3)]
        sig = fd.parameter_matrix_signal(section, threshold=2, table_items=table_items)
        self.assertTrue(sig["fired"])
        self.assertEqual(sig["row_count"], 3)

    def test_parameter_matrix_quiet_without_evidence(self) -> None:
        sig = fd.parameter_matrix_signal(_section("text"), threshold=2, table_items=None)
        self.assertFalse(sig["fired"])  # 宁漏勿猜


class QualitySignalsTests(unittest.TestCase):
    def test_ambiguity_signal(self) -> None:
        self.assertTrue(fd.ambiguity_signal({"ambiguity": True})["fired"])
        self.assertFalse(fd.ambiguity_signal({})["fired"])

    def test_conflict_signal(self) -> None:
        self.assertTrue(fd.conflict_signal({"conflict_flags": ["c1"]})["fired"])
        self.assertFalse(fd.conflict_signal({"conflict_flags": []})["fired"])

    def test_review_challenge_signal(self) -> None:
        self.assertTrue(fd.review_challenge_signal({"reason": "逐句质疑"})["fired"])
        self.assertFalse(fd.review_challenge_signal({"reason": "ok"})["fired"])
        self.assertFalse(fd.review_challenge_signal(None)["fired"])


class DecideTests(unittest.TestCase):
    def test_drill_when_structural_signal_fires(self) -> None:
        decision = fd.decide_drilldown(
            _item(), _section("shall collect and shall report."),
        )
        self.assertTrue(decision["drill"])
        fired_names = [s["name"] for s in decision["signals"] if s.get("fired")]
        self.assertIn("multi_behavior", fired_names)
        self.assertGreater(decision["subatom_count"], 0)

    def test_no_drill_when_quiet(self) -> None:
        decision = fd.decide_drilldown(_item(), _section("The meter shall log."))
        self.assertFalse(decision["drill"])
        self.assertEqual(decision["subatom_count"], 0)

    def test_drill_subatoms_inherit_parent_block_ids(self) -> None:
        decision = fd.decide_drilldown(
            _item(), _section("The meter shall collect. It shall report.", block_ids=["B9"]),
        )
        self.assertTrue(decision["drill"])
        for sub in decision["subatoms"]:
            self.assertEqual(sub["source_block_ids"], ["B9"])

    def test_thresholds_are_configurable(self) -> None:
        # 阈值抬高到 3 → 两行为不再触发
        decision = fd.decide_drilldown(
            _item(), _section("shall collect and shall report."),
            thresholds={"multi_behavior": 3, "multi_condition": 99, "matrix_rows": 99},
        )
        self.assertFalse(decision["drill"])


class ApplyBatchTests(unittest.TestCase):
    def test_apply_backfills_drilled_subatoms(self) -> None:
        items = [
            _item(functional_requirement_id="F1"),
            _item(functional_requirement_id="F2"),
        ]
        sections_by_id = {
            "F1": _section("shall collect and shall report.", ["B1"]),
            "F2": _section("simple clause.", ["B2"]),
        }
        report = fd.apply_drilldown(items, sections_by_id)
        self.assertEqual(report["item_count"], 2)
        self.assertEqual(report["drilled_count"], 1)
        self.assertIn("drilled_subatoms", items[0])
        self.assertNotIn("drilled_subatoms", items[1])
        self.assertGreater(report["total_subatoms"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
