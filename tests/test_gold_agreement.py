"""Tests for golden_sets/gold_functional_v1/tools/agreement.py (WS0 D3 一致率算法).

Covers the four acceptance points named in the T1 brief: Dice matching, conflict-pair exemption,
exact-set (strict-equality) transcription fields, and per-field (non-aggregated) reporting; plus the
§1 protocol-compliance precheck. All mechanical, zero LLM.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GOLD_TOOLS = _REPO / "golden_sets" / "gold_functional_v1" / "tools"
for _p in (_REPO, _GOLD_TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import agreement as agree  # noqa: E402


def _entry(eid, section, coords, *, objective="obj", conflict_with=None, **fields):
    anchor = {"section": section, "coordinates": list(coords)}
    if conflict_with is not None:
        anchor["conflict_with"] = conflict_with
    entry = {"entry_id": eid, "doc_ref": "D1", "objective": objective, "source_anchor": anchor}
    entry.update(fields)
    return entry


class DiceMatchingTests(unittest.TestCase):
    def test_perfect_agreement_is_one(self):
        a = [_entry("A1", "4.1", ["BLK-1"]), _entry("A2", "4.2", ["BLK-2"])]
        b = [_entry("B1", "4.1", ["BLK-1"]), _entry("B2", "4.2", ["BLK-2"])]
        report = agree.compute(a, b)
        self.assertEqual(report["entry_agreement_dice"], 1.0)
        self.assertTrue(report["freeze_pass"])
        self.assertEqual(report["counts"]["matched"], 2)

    def test_half_match_dice_is_half(self):
        # 2 vs 2 but only one anchor-overlapping pair → Dice = 2*1/(2+2) = 0.5
        a = [_entry("A1", "4.1", ["BLK-1"]), _entry("A2", "9.9", ["BLK-X"])]
        b = [_entry("B1", "4.1", ["BLK-1"]), _entry("B2", "9.9", ["BLK-Y"])]
        report = agree.compute(a, b)
        self.assertEqual(report["entry_agreement_dice"], 0.5)
        self.assertFalse(report["freeze_pass"])
        self.assertEqual(report["counts"]["matched"], 1)

    def test_match_requires_same_section_and_shared_coordinate(self):
        # same coordinate but different section → no match
        a = [_entry("A1", "4.1", ["BLK-1"])]
        b = [_entry("B1", "4.2", ["BLK-1"])]
        self.assertEqual(agree.match(a, b), [])
        # same section but disjoint coordinates → no match
        a2 = [_entry("A1", "4.1", ["BLK-1"])]
        b2 = [_entry("B1", "4.1", ["BLK-2"])]
        self.assertEqual(agree.match(a2, b2), [])
        # both → match
        self.assertEqual(agree.match(a, [_entry("B1", "4.1", ["BLK-1"])]), [(0, 0)])

    def test_greedy_pairs_by_largest_overlap(self):
        # A1 overlaps B1 on 2 coords and B2 on 1; greedy gives A1↔B1, A2 (only BLK-9) unmatched.
        a = [_entry("A1", "4.1", ["BLK-1", "BLK-2"]), _entry("A2", "4.1", ["BLK-9"])]
        b = [_entry("B1", "4.1", ["BLK-1", "BLK-2"]), _entry("B2", "4.1", ["BLK-9"])]
        pairs = agree.match(a, b)
        self.assertIn((0, 0), pairs)
        self.assertEqual(len(pairs), 2)  # A2↔B2 also pair on BLK-9


class ConflictExemptionTests(unittest.TestCase):
    def test_conflict_with_entries_exempted_from_both(self):
        # "标记不消解" convention: a conflict pair cross-references BOTH ways. Both AC and AC-PEER
        # declare conflict_with → both exempted from the agreement denominator (WS0 §2/§5).
        a = [
            _entry("A1", "4.1", ["BLK-1"]),
            _entry("AC", "4.1", ["BLK-1"], conflict_with="AC-PEER"),
            _entry("AC-PEER", "4.1", ["BLK-1"], conflict_with="AC"),
        ]
        b = [_entry("B1", "4.1", ["BLK-1"])]
        report = agree.compute(a, b)
        # exempted: A drops AC and AC-PEER (both carry conflict_with), leaving A1 only.
        self.assertEqual(report["counts"]["expert_a"], 1)
        self.assertEqual(report["counts"]["expert_b"], 1)
        self.assertEqual(report["entry_agreement_dice"], 1.0)

    def test_one_sided_conflict_target_is_not_exempted(self):
        # Only the entry that DECLARES conflict_with is exempted; a non-declaring peer is kept
        # (a one-sided mark is a malformed pair — protocol compliance flags it elsewhere).
        a = [
            _entry("A1", "4.1", ["BLK-1"]),
            _entry("AC", "4.1", ["BLK-1"], conflict_with="AC-PEER"),
            _entry("AC-PEER", "4.1", ["BLK-1"]),  # does not declare conflict_with → kept
        ]
        b = [_entry("B1", "4.1", ["BLK-1"])]
        report = agree.compute(a, b)
        self.assertEqual(report["counts"]["expert_a"], 2)  # A1 + AC-PEER remain


class ExactSetFieldsTests(unittest.TestCase):
    def test_data_constraints_single_value_mismatch_scores_zero(self):
        # protected field uses strict set equality, NOT Dice — one value differs → 0.0
        a = [_entry("A1", "4.1", ["BLK-1"], data_constraints=["15 min", "230 V"])]
        b = [_entry("B1", "4.1", ["BLK-1"], data_constraints=["15 min", "240 V"])]
        report = agree.compute(a, b)
        self.assertEqual(report["field_agreement"]["data_constraints"], 0.0)

    def test_data_constraints_identical_scores_one(self):
        a = [_entry("A1", "4.1", ["BLK-1"], data_constraints=["15 min", "230 V"])]
        b = [_entry("B1", "4.1", ["BLK-1"], data_constraints=["230 V", "15 min"])]  # order无关
        report = agree.compute(a, b)
        self.assertEqual(report["field_agreement"]["data_constraints"], 1.0)

    def test_related_dlms_objects_strict_set(self):
        a = [_entry("A1", "4.1", ["BLK-1"], related_dlms_objects=["class 3", "0.0.96.1.0"])]
        b = [_entry("B1", "4.1", ["BLK-1"], related_dlms_objects=["class 3", "1.0.96.1.0"])]
        report = agree.compute(a, b)
        self.assertEqual(report["field_agreement"]["related_dlms_objects"], 0.0)

    def test_behaviors_use_dice_not_strict(self):
        # list fields use Dice — partial overlap gives a partial score, not 0/1
        a = [_entry("A1", "4.1", ["BLK-1"], behaviors=["record energy", "detect fraud"])]
        b = [_entry("B1", "4.1", ["BLK-1"], behaviors=["record energy", "raise event", "detect fraud"])]
        report = agree.compute(a, b)
        # Dice = 2*2/(2+3) = 0.8
        self.assertAlmostEqual(report["field_agreement"]["behaviors"], 0.8, places=4)


class ObjectiveNormalizationTests(unittest.TestCase):
    def test_trailing_punctuation_and_whitespace_ignored(self):
        a = [_entry("A1", "4.1", ["BLK-1"], objective="Record billing data。")]
        b = [_entry("B1", "4.1", ["BLK-1"], objective="record  billing data.")]
        report = agree.compute(a, b)
        # norm folds whitespace + strips trailing punctuation; but case differs (Record vs record)
        # — norm does NOT casefold objective. So these differ unless identical after norm.
        # Use identical case to prove normalization alone:
        a2 = [_entry("A1", "4.1", ["BLK-1"], objective="Record billing data。")]
        b2 = [_entry("B1", "4.1", ["BLK-1"], objective="Record  billing data.")]
        rep2 = agree.compute(a2, b2)
        self.assertEqual(rep2["field_agreement"]["objective"], 1.0)


class PerFieldReportingTests(unittest.TestCase):
    def test_fields_reported_separately_not_aggregated(self):
        a = [_entry("A1", "4.1", ["BLK-1"], behaviors=["x"], data_constraints=["1 V"])]
        b = [_entry("B1", "4.1", ["BLK-1"], behaviors=["x"], data_constraints=["1 V"])]
        report = agree.compute(a, b)
        # every scored field appears as its own key; there is no single averaged "field_agreement" scalar
        for field in ("objective", "behaviors", "preconditions", "variants",
                      "exceptions", "data_constraints", "related_dlms_objects"):
            self.assertIn(field, report["field_agreement"])
        self.assertNotIn("average", report["field_agreement"])
        self.assertNotIn("overall", report["field_agreement"])


class ProtocolComplianceTests(unittest.TestCase):
    def test_missing_objective_flagged_and_excluded(self):
        bad = {"entry_id": "A0", "doc_ref": "D1", "source_anchor": {"section": "4.1", "coordinates": ["BLK-1"]}}
        good = [_entry("A1", "4.1", ["BLK-1"])]
        report = agree.compute([bad] + good, good)
        violations = report["violations"]["expert_a"]
        self.assertTrue(any(v["entry_id"] == "A0" and "missing_objective" in v["reasons"] for v in violations))
        # bad entry excluded from the agreement denominator
        self.assertEqual(report["counts"]["expert_a"], 1)

    def test_missing_anchor_section_flagged(self):
        bad = {"entry_id": "A0", "doc_ref": "D1", "objective": "x",
               "source_anchor": {"coordinates": ["BLK-1"]}}
        report = agree.compute([bad], [_entry("B1", "4.1", ["BLK-1"])])
        self.assertTrue(any("missing_anchor_section" in v["reasons"]
                            for v in report["violations"]["expert_a"]))

    def test_conflict_with_missing_target_flagged(self):
        bad = _entry("A0", "4.1", ["BLK-1"], conflict_with="NO-SUCH-PEER")
        report = agree.compute([bad], [_entry("B1", "4.1", ["BLK-1"])])
        self.assertTrue(any("conflict_with_target_missing" in v["reasons"]
                            for v in report["violations"]["expert_a"]))


class DiceZeroDenominatorTests(unittest.TestCase):
    def test_both_empty_is_one(self):
        report = agree.compute([], [])
        self.assertEqual(report["entry_agreement_dice"], 1.0)

    def test_empty_list_field_dice_is_one(self):
        a = [_entry("A1", "4.1", ["BLK-1"])]  # no behaviors field
        b = [_entry("B1", "4.1", ["BLK-1"])]
        report = agree.compute(a, b)
        self.assertEqual(report["field_agreement"]["behaviors"], 1.0)


class SchemaConformanceTests(unittest.TestCase):
    """The committed synthetic fixtures must conform to gold_functional_entry.schema.json.

    Proves the schema is valid JSON Schema AND that the self-proof fixtures are schema-clean
    (so the consumption chain runs on well-formed entries, not ad-hoc dicts).
    """

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema  # noqa: F401
            cls.has_jsonschema = True
        except ImportError:
            cls.has_jsonschema = False
        cls.schema_path = _GOLD_TOOLS.parent / "schema" / "gold_functional_entry.schema.json"
        cls.fixtures_path = _GOLD_TOOLS.parent / "fixtures" / "synthetic_truth.jsonl"

    def test_fixtures_conform_to_schema(self):
        if not self.has_jsonschema:
            self.skipTest("jsonschema not installed")
        import jsonschema
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        entries = [json.loads(line) for line in self.fixtures_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(entries), 3)
        for entry in entries:
            jsonschema.validate(entry, schema)  # raises on violation

    def test_schema_rejects_entry_missing_anchor(self):
        if not self.has_jsonschema:
            self.skipTest("jsonschema not installed")
        import jsonschema
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        bad = {"entry_id": "X", "doc_ref": "D", "objective": "o"}  # no source_anchor
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)

    def test_schema_rejects_empty_coordinates(self):
        if not self.has_jsonschema:
            self.skipTest("jsonschema not installed")
        import jsonschema
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        bad = {"entry_id": "X", "doc_ref": "D", "objective": "o",
               "source_anchor": {"section": "4.1", "coordinates": []}}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


if __name__ == "__main__":
    unittest.main()
