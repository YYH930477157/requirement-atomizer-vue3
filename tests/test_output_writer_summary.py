from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from output_writer import write_summary


class WriteSummaryGuidanceTests(unittest.TestCase):
    def test_next_step_points_to_functional_review_not_atoms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            write_summary(
                path,
                {
                    "input": "doc.docx",
                    "generated_at": "2026-08-27T00:00:00Z",
                    "counts": {
                        "blocks": 1,
                        "chunks": 1,
                        "table_items": 0,
                        "atomic_requirements": 0,
                        "llm_tasks": 0,
                    },
                },
                Counter(),
                Counter(),
            )
            text = path.read_text(encoding="utf-8")

        self.assertIn("功能需求", text)
        self.assertIn("软件需求列表-成文.xlsx", text)
        self.assertNotIn("Review `atomic_requirements.jsonl` first.", text)
        self.assertNotIn("llm_tasks.jsonl", text)


if __name__ == "__main__":
    unittest.main()
