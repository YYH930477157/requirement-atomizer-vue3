from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRUTH_PATH = REPO / "golden_sets" / "ws0_human_v2_en" / "truth.jsonl"
SCHEMA_PATH = REPO / "schemas" / "functional_truth.schema.json"


class TruthV2ArtifactTests(unittest.TestCase):
    """ws0_human_v2_en（英文重建真值，2026-09-08）工件不变量——可移植钉（不依赖机器本地 xlsx）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = [json.loads(line) for line in
                    TRUTH_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_artifact_exists_and_nonempty(self) -> None:
        self.assertGreater(len(self.rows), 100, "英文重建真值应保留 v1 行量级（189）")

    def test_schema_valid_every_row(self) -> None:
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for row in self.rows:
            with self.subTest(truth_id=row.get("truth_id")):
                errors = list(validator.iter_errors(row))
                self.assertEqual(errors, [])

    def test_ids_continuous_and_unique(self) -> None:
        ids = [row["truth_id"] for row in self.rows]
        self.assertEqual(len(set(ids)), len(ids), "truth_id 唯一")
        self.assertEqual(ids[0], "T-0001")
        self.assertEqual(ids[-1], f"T-{len(ids):04d}", "与 v1 对齐的连续编号")

    def test_domain_tags_present_and_valid(self) -> None:
        domains = {row.get("domain") for row in self.rows}
        self.assertTrue(domains <= {"b_track", "out_of_scope"}, f"非法域值: {domains}")
        self.assertIn("b_track", domains)
        self.assertIn("out_of_scope", domains)
        for row in self.rows:
            self.assertIn("rebuilt-2026-09-08", row.get("notes") or "",
                          "每行 notes 必须携带重建血统与域证据")

    def test_expected_text_is_english_not_chinese(self) -> None:
        """语言断层修复的核心钉：v2 锚定分析师 English Translation 列。"""
        for row in self.rows:
            text = row["expected_text"]
            cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
            self.assertEqual(cjk, 0, f"{row['truth_id']} 残留中文: {text[:40]}")


if __name__ == "__main__":
    unittest.main()
