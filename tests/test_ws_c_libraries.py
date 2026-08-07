"""Tests for base_library, solution_library, and unified_requirement_retriever (WS-C)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from base_library import (
    BASE_LIBRARY_FILE,
    aggregate_candidates,
    base_library_candidate_id,
    build_base_library,
    confirm_base_library_candidate,
    load_candidates,
)
from solution_library import (
    SOLUTION_LIBRARY_FILE,
    aggregate_solution_entries,
    build_solution_library,
    collect_design_options,
    confirm_solution_library_entry,
    solution_library_entry_id,
)
from unified_requirement_retriever import (
    UnifiedRequirementRetriever,
    build_unified_retriever,
    unified_requirement_search,
)


class BaseLibraryTests(unittest.TestCase):
    def test_aggregate_candidates_dedupes_and_marks_draft(self):
        candidates = [
            {"title": "Foo", "module": "M1", "submodule": "S1", "description": "d1"},
            {"title": "Foo", "module": "M1", "submodule": "S1", "description": "d2"},
            {"title": "Bar", "module": "M2", "description": "d3"},
        ]
        aggregated = aggregate_candidates(candidates)
        self.assertEqual(len(aggregated), 2)
        self.assertEqual(aggregated[0]["lifecycle_state"], "draft")
        self.assertEqual(aggregated[0]["provenance"], "base_library")

    def test_unconfirmed_candidates_are_rejected_from_library(self):
        """C1 入库门禁：未确认候选不得进入 base_library.jsonl。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates_path = root / "base_library_candidates.jsonl"
            candidates_path.write_text(
                json.dumps({"title": "Unconfirmed", "module": "M"}, ensure_ascii=False) + "\n" +
                json.dumps({"title": "Confirmed", "module": "M"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            # Confirm only the second candidate
            cand = aggregate_candidates(load_candidates(root))[1]
            confirm_base_library_candidate(root, cand["base_library_candidate_id"], actor=" tester", reason="ok")
            build_base_library(root)
            lines = (root / BASE_LIBRARY_FILE).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["title"], "Confirmed")
            self.assertEqual(entry["lifecycle_state"], "confirmed")

    def test_confirm_requires_actor_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                confirm_base_library_candidate(root, "BASE-xxx", actor="", reason="x")
            with self.assertRaises(ValueError):
                confirm_base_library_candidate(root, "BASE-xxx", actor="x", reason="")


class SolutionLibraryTests(unittest.TestCase):
    def test_collect_design_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            func = {
                "requirements": [
                    {
                        "functional_requirement_id": "FR-1",
                        "objective": "Obj",
                        "module": "M",
                        "design_options": ["Option A", "Option B"],
                    }
                ]
            }
            (root / "functional_requirements.json").write_text(
                json.dumps(func, ensure_ascii=False), encoding="utf-8"
            )
            options = collect_design_options(root)
            self.assertEqual(len(options), 2)
            self.assertEqual(options[0]["option"], "Option A")

    def test_unconfirmed_solution_entries_hidden(self):
        """C2 方案库：未确认条目默认隐藏，不进入 solution_library.jsonl。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            func = {
                "requirements": [
                    {
                        "functional_requirement_id": "FR-1",
                        "objective": "Obj",
                        "module": "M",
                        "design_options": ["Option A"],
                    }
                ]
            }
            (root / "functional_requirements.json").write_text(
                json.dumps(func, ensure_ascii=False), encoding="utf-8"
            )
            entries = aggregate_solution_entries(collect_design_options(root))
            self.assertEqual(entries[0]["lifecycle_state"], "draft")
            # confirm then build
            confirm_solution_library_entry(
                root, entries[0]["solution_library_entry_id"], actor="tester", reason="useful"
            )
            build_solution_library(root)
            lines = (root / SOLUTION_LIBRARY_FILE).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["lifecycle_state"], "confirmed")


class UnifiedRetrieverTests(unittest.TestCase):
    def test_search_across_three_libraries(self):
        """C3：三库结果统一可检索，且带 library_source 标记。"""
        libraries = {
            "requirement": [
                {"objective": "Meter shall log event", "module": "Event", "behaviors": ["log"]},
            ],
            "base": [
                {"objective": "Event logger requirement", "module": "Event"},
            ],
            "solution": [
                {"option": "Circular event buffer", "module": "Event"},
            ],
        }
        retriever = UnifiedRequirementRetriever(libraries)
        results = retriever.search("event logger buffer", limit=10)
        self.assertGreaterEqual(len(results), 3)
        sources = {r.get("library_source") for r in results}
        self.assertTrue(sources >= {"requirement", "base", "solution"})

    def test_unified_search_with_env_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            req_path = root / "req.jsonl"
            base_path = root / "base.jsonl"
            sol_path = root / "sol.jsonl"
            req_path.write_text(
                json.dumps({"objective": "Foo requirement", "module": "M"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            base_path.write_text(
                json.dumps({"objective": "Foo base", "module": "M"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            sol_path.write_text(
                json.dumps({"option": "Foo solution", "module": "M"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            try:
                os.environ["RATOMIZER_REQUIREMENT_LIBRARY"] = str(req_path)
                os.environ["RATOMIZER_BASE_LIBRARY"] = str(base_path)
                os.environ["RATOMIZER_SOLUTION_LIBRARY"] = str(sol_path)
                result = unified_requirement_search("Foo", limit=10)
                self.assertEqual(result["matches"], 3)
                self.assertIn("requirement", result["source_counts"])
                self.assertIn("base", result["source_counts"])
                self.assertIn("solution", result["source_counts"])
            finally:
                os.environ.clear()
                os.environ.update(env)

    def test_build_unified_retriever_uses_literal_default(self):
        retriever = build_unified_retriever(library_paths={"requirement": None, "base": None})
        self.assertEqual(getattr(retriever, "retriever_kind", None), "unified-literal")


if __name__ == "__main__":
    unittest.main()
