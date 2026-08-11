from __future__ import annotations

import ast
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path

from context_submit import submit_with_context


ROOT = Path(__file__).resolve().parent.parent
CONCURRENT_LLM_MODULES = (
    "ai_extract.py",
    "requirements_analysis.py",
    "llm_pipeline.py",
    "spec_enrich.py",
    "doc_annotation_export.py",
)


class ContextSubmitTests(unittest.TestCase):
    def test_submit_propagates_independent_context_to_worker(self) -> None:
        stage = ContextVar("stage", default="default")
        token = stage.set("full_translation")
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = submit_with_context(executor, stage.get)
                stage.set("caller_changed")
                self.assertEqual(future.result(), "full_translation")
        finally:
            stage.reset(token)

    def test_concurrent_llm_modules_do_not_submit_without_context(self) -> None:
        violations: list[str] = []
        for relative in CONCURRENT_LLM_MODULES:
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr == "submit":
                    violations.append(f"{relative}:{node.lineno}")
        self.assertEqual(violations, [], f"bare thread-pool submit calls: {violations}")


if __name__ == "__main__":
    unittest.main()
