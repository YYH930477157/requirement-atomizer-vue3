from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden_sets" / "abnt_nbr_16968_v5" / "golden_summary.json"
CURRENT_OUTPUT = ROOT / "out" / "abnt_nbr_16968_atomizer_v5"


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class GoldenRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        if not CURRENT_OUTPUT.exists():
            self.skipTest(f"Golden output directory not found: {CURRENT_OUTPUT}")
        self.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.manifest = json.loads((CURRENT_OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        self.quality = json.loads((CURRENT_OUTPUT / "quality_report.json").read_text(encoding="utf-8"))
        self.atomic = read_jsonl(CURRENT_OUTPUT / "atomic_requirements.jsonl")

    def test_manifest_counts_match_golden_baseline(self) -> None:
        for key, expected in self.golden["counts"].items():
            if key == "cosem_object_instances":
                continue
            self.assertEqual(self.manifest["counts"].get(key), expected, key)

    def test_requirement_type_distribution_matches_golden_baseline(self) -> None:
        actual = Counter(row["requirement_type"] for row in self.atomic)
        self.assertEqual(dict(actual), self.golden["requirement_type_counts"])

    def test_source_type_distribution_matches_golden_baseline(self) -> None:
        actual = Counter(row["source_type"] for row in self.atomic)
        self.assertEqual(dict(actual), self.golden["source_type_counts"])

    def test_quality_coverage_matches_golden_baseline(self) -> None:
        self.assertEqual(self.quality["coverage"], self.golden["coverage"])

    def test_representative_requirements_are_present(self) -> None:
        for expected in self.golden["representative_requirements"]:
            matches = [
                row
                for row in self.atomic
                if row.get("requirement_type") == expected["requirement_type"]
                and row.get("object") == expected["object"]
                and expected["requirement_contains"] in row.get("requirement", "")
            ]
            self.assertTrue(matches, expected)


if __name__ == "__main__":
    unittest.main()
