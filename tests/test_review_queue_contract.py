"""Read-only contract for review-queue file destinations (design §4.2).

Zero behavior change: scans writer source and the frozen design table without
importing production writers (avoids lock / package side effects).
"""
from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = REPO_ROOT / "docs" / "review-queue-convergence-design-2026-08-27.md"


# Frozen from docs/review-queue-convergence-design-2026-08-27.md §4.2.
# destination_markers are phrases that must remain in the design table.
_FILE_DESTINATIONS = (
    {
        "filename": "review_states.jsonl",
        "writer_module": "review_state.py",
        "writer_symbols": ("def apply_expert_decision", '"review_states.jsonl"'),
        "destination_markers": ("先双写进队列", "再切只读投影"),
    },
    {
        "filename": "ai_review_states.jsonl",
        "writer_module": "ai_review_actions.py",
        "writer_symbols": ("def apply_ai_review_action", "AI_REVIEW_STATES"),
        "destination_markers": ("ai_review_states.jsonl", "同上"),
    },
    {
        "filename": "table_review_states.jsonl",
        "writer_module": "table_review_state.py",
        "writer_symbols": ("def apply_table_review_decision", "TABLE_REVIEW_STATES"),
        "destination_markers": ("冻结只读", "停止双写"),
    },
    {
        "filename": "table_review_events.jsonl",
        "writer_module": "table_review_state.py",
        "writer_symbols": ("def apply_table_review_decision", "TABLE_REVIEW_EVENTS"),
        "destination_markers": ("冻结只读", "停止双写"),
    },
    {
        "filename": "claim_structural_candidate_decisions.jsonl",
        "writer_module": "claim_structural_overrides.py",
        "writer_symbols": (
            "def confirm_structural_exclusion",
            "CLAIM_STRUCTURAL_CANDIDATE_DECISIONS",
        ),
        "destination_markers": ("投影保留",),
    },
    {
        "filename": "omission_states.jsonl",
        "writer_module": "omission_actions.py",
        "writer_symbols": ("def apply_omission_action", "OMISSION_STATES"),
        "destination_markers": ("subject_kind=omission",),
    },
    {
        "filename": "clarification_check_states.jsonl",
        "writer_module": "clarification_check_states.py",
        "writer_symbols": (
            "def apply_clarification_check_action",
            "CHECK_STATES_FILE",
        ),
        "destination_markers": ("subject_kind=clarification_internal",),
    },
    {
        "filename": "claim_review_events.jsonl",
        "writer_module": "claim_review_actions.py",
        "writer_symbols": ("def append_claim_review_events", "CLAIM_REVIEW_EVENTS"),
        "destination_markers": ("内核留下",),
    },
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ReviewQueueFileDestinationContractTests(unittest.TestCase):
    def test_design_doc_section_4_2_exists(self) -> None:
        text = _read_text(DESIGN_DOC)
        self.assertIn("## 4.2 旧文件归宿", text)
        self.assertIn("统一机械 ≠ 统一枚举", text)

    def test_each_state_file_has_writer_module_and_destination(self) -> None:
        design = _read_text(DESIGN_DOC)
        seen = set()
        for spec in _FILE_DESTINATIONS:
            filename = spec["filename"]
            with self.subTest(filename=filename):
                self.assertNotIn(filename, seen)
                seen.add(filename)
                writer_path = REPO_ROOT / spec["writer_module"]
                self.assertTrue(
                    writer_path.is_file(),
                    f"missing writer module {spec['writer_module']}",
                )
                source = _read_text(writer_path)
                filename_homes = source
                artifacts = REPO_ROOT / "claim_artifacts.py"
                if filename not in source and artifacts.is_file():
                    # claim_review_events.jsonl is named in claim_artifacts and
                    # imported by the writer.
                    filename_homes = source + "\n" + _read_text(artifacts)
                self.assertIn(
                    filename,
                    filename_homes,
                    f"{filename} not in {spec['writer_module']} "
                    "or its imported constant home",
                )
                for symbol in spec["writer_symbols"]:
                    self.assertIn(
                        symbol,
                        source,
                        f"{spec['writer_module']} missing {symbol!r}",
                    )
                self.assertIn(filename, design)
                for marker in spec["destination_markers"]:
                    self.assertIn(
                        marker,
                        design,
                        f"design §4.2 missing destination marker {marker!r} "
                        f"for {filename}",
                    )

    def test_contract_covers_the_eight_named_authorities(self) -> None:
        expected = {
            "review_states.jsonl",
            "ai_review_states.jsonl",
            "table_review_states.jsonl",
            "table_review_events.jsonl",
            "claim_structural_candidate_decisions.jsonl",
            "omission_states.jsonl",
            "clarification_check_states.jsonl",
            "claim_review_events.jsonl",
        }
        self.assertEqual({row["filename"] for row in _FILE_DESTINATIONS}, expected)


if __name__ == "__main__":
    unittest.main()
