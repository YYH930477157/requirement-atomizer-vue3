"""Synthetic-case unit tests for the agent-eval-v2 category judges.

Dataset-level regression (baselines vs manifest) lives in test_agent_eval.py; this file
pins judge semantics on hand-built cases so a future refactor cannot silently flip a
pass predicate.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import agent_eval


def _case(
    case_id: str,
    category: str,
    text: str,
    context: str = "",
    expected: dict | None = None,
) -> dict:
    merged = {"verdict": "x", "rationale": "r", "forbidden": [], "must_ask_questions": []}
    merged.update(expected or {})
    return {
        "case_id": case_id,
        "category": category,
        "source": {
            "doc_ref": "SYNTH",
            "block_ids": ["S-1"],
            "origin": "real",
            "curated_by": "test",
            "curated_at": "2026-07-22",
        },
        "input": {"text": text, "context": context},
        "expected": merged,
    }


class HallucinationJudgeTests(unittest.TestCase):
    def test_fabricated_code_caught_by_drift(self) -> None:
        case = _case(
            "hallucination-901", "hallucination",
            "The meter shall support remote firmware update.",
            "Rejected candidate: The update is performed through OBIS 0-0:44.1.0.255.",
            {"forbidden": ["0-0:44.1.0.255"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertTrue(detail["passed"])
        self.assertIn("0-0:44.1.0.255", detail["caught_by_guards"])

    def test_unit_token_matched_via_atoms(self) -> None:
        case = _case(
            "hallucination-902", "hallucination",
            "The meter shall detect leakage at 5 l/h.",
            "Rejected candidate: Leakage is detected at 1 l/h.",
            {"forbidden": ["1 l/h"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertTrue(detail["passed"])

    def test_guard_silence_is_honest_fail(self) -> None:
        case = _case(
            "hallucination-903", "hallucination",
            "The meter shall record events.",
            "Rejected candidate: Events are stored without any identifier changes.",
            {"forbidden": ["0-0:44.1.0.255"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertFalse(detail["passed"])
        self.assertEqual(detail["missed_forbidden"], ["0-0:44.1.0.255"])

    def test_foreign_standard_ref_caught(self) -> None:
        case = _case(
            "hallucination-904", "hallucination",
            "The product shall be tested per EN ISO 6270-1.",
            "Rejected candidate: The product shall be certified to IEC 62053-22.",
            {"detector": "foreign_standard_refs", "forbidden": ["IEC 62053-22"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertTrue(detail["passed"])

    def test_same_root_standard_ref_is_not_foreign(self) -> None:
        case = _case(
            "hallucination-905", "hallucination",
            "The product shall be tested per EN ISO 6270-1.",
            "Rejected candidate: The product shall be tested per ISO 6270-1.",
            {"detector": "foreign_standard_refs", "forbidden": ["ISO 6270-1"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertFalse(detail["passed"])

    def test_opposed_qualifier_merge_prevented(self) -> None:
        case = _case(
            "hallucination-906", "hallucination",
            "The replaceable battery shall support field replacement. "
            "The sealed backup battery is non-replaceable.",
            "Rejected merge: All batteries shall be field replaceable.",
            {"detector": "opposed_qualifiers", "forbidden": ["All batteries shall be field replaceable"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertTrue(detail["passed"])
        self.assertTrue(detail["merge_prevented"])

    def test_neutral_merge_is_not_prevented(self) -> None:
        case = _case(
            "hallucination-907", "hallucination",
            "The meter shall store each entry with its timestamp.",
            "Rejected merge: Entries shall be stored with timestamps.",
            {"detector": "opposed_qualifiers", "forbidden": ["timestamps"]},
        )
        detail = agent_eval._hallucination_case(case, set())
        self.assertFalse(detail["passed"])


class MustAskJudgeTests(unittest.TestCase):
    def test_vague_acceptance_fires_and_routes(self) -> None:
        case = _case(
            "must-ask-901", "must_ask",
            "The device shall work correctly under all conditions.",
            "",
            {"detector": "vague_acceptance", "forbidden": [], "must_ask_questions": ["q"]},
        )
        detail = agent_eval._must_ask_case(case, set())
        self.assertEqual(detail["judge"], "auto")
        self.assertTrue(detail["detector_fired"])
        self.assertTrue(detail["policy_route_ok"])
        self.assertTrue(detail["passed"])

    def test_declared_detector_silence_is_fail(self) -> None:
        case = _case(
            "must-ask-902", "must_ask",
            "Recovery time shall not exceed 5 s after a power outage.",
            "",
            {"detector": "vague_acceptance", "forbidden": [], "must_ask_questions": ["q"]},
        )
        detail = agent_eval._must_ask_case(case, set())
        self.assertFalse(detail["passed"])
        self.assertFalse(detail["detector_fired"])

    def test_values_left_behind_fires(self) -> None:
        text = "The meter shall record the supported demand intervals."
        context = text + " Supported intervals are 1, 5, 15, 30 and 60 minutes."
        case = _case(
            "must-ask-903", "must_ask", text, context,
            {"detector": "values_left_behind", "forbidden": [], "must_ask_questions": ["q"]},
        )
        detail = agent_eval._must_ask_case(case, set())
        self.assertTrue(detail["passed"])
        self.assertTrue(detail["detector_fired"])

    def test_values_left_behind_requires_verbatim_quote(self) -> None:
        case = _case(
            "must-ask-904", "must_ask",
            "A paraphrased requirement that never appears in the source.",
            "The source says intervals are 1, 5, 15, 30 and 60 minutes.",
            {"detector": "values_left_behind", "forbidden": [], "must_ask_questions": ["q"]},
        )
        detail = agent_eval._must_ask_case(case, set())
        self.assertFalse(detail["passed"])
        self.assertIn("not verbatim", detail["reason"])

    def test_manual_case_excluded_from_denominator(self) -> None:
        manual = _case(
            "must-ask-905", "must_ask",
            "The load profile shall be recorded periodically.",
            "",
            {"forbidden": ["15-minute interval"], "must_ask_questions": ["q"]},
        )
        auto = _case(
            "must-ask-906", "must_ask",
            "The device shall work correctly under all conditions.",
            "",
            {"detector": "vague_acceptance", "forbidden": [], "must_ask_questions": ["q"]},
        )
        report = agent_eval.evaluate_cases([manual, auto])
        self.assertEqual(report["must_ask"]["evaluated"], 1)
        self.assertEqual(report["must_ask"]["manual_case_ids"], ["must-ask-905"])
        self.assertEqual(report["must_ask"]["passed"], 1)

    def test_forbidden_default_leak_is_fail(self) -> None:
        case = _case(
            "must-ask-907", "must_ask",
            "The load profile shall be recorded periodically.",
            "15-minute interval configuration",
            {"forbidden": ["15-minute interval"], "must_ask_questions": ["q"]},
        )
        detail = agent_eval._must_ask_case(case, set())
        self.assertEqual(detail["leaked_forbidden"], ["15-minute interval"])
        self.assertFalse(detail["passed"])


class GroupingJudgeTests(unittest.TestCase):
    def test_same_period_pair_merges_and_scores(self) -> None:
        a = _case(
            "grouping-901", "grouping",
            "The meter shall record the load profile every 15 minutes.",
            "Load profile recording",
            {"group_key": "lp"},
        )
        b = _case(
            "grouping-902", "grouping",
            "The meter shall record the load profile in 15-minute intervals.",
            "Load profile recording",
            {"group_key": "lp"},
        )
        c = _case(
            "grouping-903", "grouping",
            "The meter shall detect removal of the terminal cover.",
            "Terminal cover event",
            {"group_key": "tc"},
        )
        report = agent_eval.evaluate_cases([a, b, c])
        self.assertEqual(report["grouping"]["passed"], 3)
        methods = {
            tuple(pair["pair"]): pair["merge_method"]
            for pair in report["grouping_pairs"]
            if pair["merged"]
        }
        self.assertIn(("grouping-901", "grouping-902"), methods)

    def test_different_period_pair_is_not_merged(self) -> None:
        # 审核人 2026-07-23 裁定：15 min × 30 min 是两条独立曲线（period_variant 分家）
        a = _case(
            "grouping-906", "grouping",
            "The meter shall record the load profile every 15 minutes.",
            "Load profile recording",
            {"group_key": "lp15"},
        )
        b = _case(
            "grouping-907", "grouping",
            "The meter shall record the load profile every 30 minutes.",
            "Load profile recording",
            {"group_key": "lp30"},
        )
        report = agent_eval.evaluate_cases([a, b])
        self.assertEqual(report["grouping"]["passed"], 2)
        self.assertFalse(any(pair["merged"] for pair in report["grouping_pairs"]))

    def test_unmerged_same_key_pair_is_honest_fail(self) -> None:
        a = _case(
            "grouping-904", "grouping",
            "The meter shall capture load-profile values at the configured integration period.",
            "Load profile behavior",
            {"group_key": "lp"},
        )
        b = _case(
            "grouping-905", "grouping",
            "The terminal-cover event shall be stored in the event log.",
            "Terminal cover log",
            {"group_key": "lp"},
        )
        report = agent_eval.evaluate_cases([a, b])
        self.assertEqual(report["grouping"]["passed"], 0)
        self.assertEqual(
            sorted(report["grouping"]["failed_case_ids"]),
            ["grouping-904", "grouping-905"],
        )


class DetectorSchemaTests(unittest.TestCase):
    def _write_case(self, root: Path, case: dict) -> None:
        case_dir = root / "cases" / case["category"]
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / f"{case['case_id']}.json").write_text(
            json.dumps(case, ensure_ascii=False), encoding="utf-8"
        )

    def test_unknown_detector_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = _case(
                "must-ask-908", "must_ask", "text", "",
                {"detector": "bogus", "must_ask_questions": ["q"]},
            )
            self._write_case(root, case)
            with self.assertRaises(agent_eval.AgentEvalValidationError):
                agent_eval.load_cases(root)

    def test_cross_category_detector_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = _case(
                "must-ask-909", "must_ask", "text", "",
                {"detector": "code_drift", "must_ask_questions": ["q"]},
            )
            self._write_case(root, case)
            with self.assertRaises(agent_eval.AgentEvalValidationError):
                agent_eval.load_cases(root)

    def test_valid_detector_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = _case(
                "hallucination-908", "hallucination",
                "The product shall be tested per EN ISO 6270-1.",
                "Rejected candidate: certified to IEC 62053-22.",
                {
                    "verdict": "reject",
                    "detector": "foreign_standard_refs",
                    "forbidden": ["IEC 62053-22"],
                },
            )
            self._write_case(root, case)
            cases = agent_eval.load_cases(root)
            self.assertEqual(len(cases), 1)


class ReportShapeTests(unittest.TestCase):
    def test_baselines_and_reviewed_flags(self) -> None:
        case = _case(
            "hallucination-909", "hallucination",
            "The meter shall support remote firmware update.",
            "Rejected candidate: The update is performed through OBIS 0-0:44.1.0.255.",
            {"verdict": "reject", "forbidden": ["0-0:44.1.0.255"]},
        )
        report = agent_eval.evaluate_cases([case], reviewed_ids={"hallucination-909"})
        self.assertEqual(report["hallucination"]["runner_version"], "agent-eval-v2")
        self.assertEqual(report["hallucination"]["passed"], 1)
        self.assertEqual(report["schema_only_categories"], [])
        self.assertEqual(report["unreviewed_case_ids"], [])
        self.assertTrue(report["hallucination_details"][0]["reviewed"])


if __name__ == "__main__":
    unittest.main()
