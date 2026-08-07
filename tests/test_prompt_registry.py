"""Tests for prompt_registry (WS-D1)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prompt_registry import (
    PROMPT_REGISTRY,
    is_registered,
    lint_directory,
    lint_source,
    registry_by_id,
    scan_prompt_version_constants,
)


class PromptRegistryTests(unittest.TestCase):
    def test_all_ids_unique(self):
        ids = [entry["id"] for entry in PROMPT_REGISTRY]
        self.assertEqual(len(ids), len(set(ids)), "prompt ids must be unique")

    def test_all_versions_unique(self):
        versions = [entry["version"] for entry in PROMPT_REGISTRY]
        self.assertEqual(len(versions), len(set(versions)), "prompt versions must be unique")

    def test_registry_covers_known_prompts(self):
        # Sanity check that core prompt versions from the codebase are registered.
        for version in (
            "ai-extract-v24",
            "ai-verify-v4",
            "analyze-llm-v7",
            "m2-review-v3",
            "llm-review-cache-v6",
            "enrich-v3",
            "translation-prompt-v1",
            "doc-map-prompt-v1",
            "reconcile-prompt-v1",
            "adjudicate-prompt-v1",
        ):
            self.assertTrue(is_registered(version), f"{version} should be registered")

    def test_registry_by_id(self):
        entry = registry_by_id("ai-extract")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["version"], "ai-extract-v24")
        self.assertIsNone(registry_by_id("does-not-exist"))

    def test_scan_prompt_version_constants(self):
        source = 'AI_EXTRACT_PROMPT_VERSION = "ai-extract-v24"\nOTHER = "foo"\n'
        found = scan_prompt_version_constants(source)
        self.assertEqual(found, [("AI_EXTRACT_PROMPT_VERSION", "ai-extract-v24")])

    def test_lint_source_catches_unregistered_prompt(self):
        """D1: lint 必须抓住故意未登记的 prompt 版本常量。"""
        source = 'SOME_NEW_PROMPT_VERSION = "some-prompt-v999"\n'
        issues = lint_source(source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["constant"], "SOME_NEW_PROMPT_VERSION")
        self.assertEqual(issues[0]["version"], "some-prompt-v999")
        self.assertEqual(issues[0]["reason"], "unregistered prompt version")

    def test_lint_source_allows_extra(self):
        source = 'TEST_PROMPT_VERSION = "test-prompt-v0"\n'
        issues = lint_source(source, extra_allowed={"test-prompt-v0"})
        self.assertEqual(issues, [])

    def test_lint_directory_catches_unregistered_file(self):
        """D1: 扫描目录时同样抓住未登记项。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "mod.py").write_text(
                'UNREGISTERED_PROMPT_VERSION = "unregistered-prompt-v1"\n',
                encoding="utf-8",
            )
            issues = lint_directory(tmp_path)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["version"], "unregistered-prompt-v1")

    def test_current_codebase_has_no_unregistered_prompts(self):
        """D1 契约：当前代码库中所有 prompt 版本常量均已登记。"""
        root = Path(__file__).resolve().parent.parent
        issues = lint_directory(
            root,
            excluded_constants={"PROMPT_REGISTRY_VERSION"},
            skip_dirs={"build", "dist", ".git", "__pycache__", "node_modules", ".worktrees"},
        )
        if issues:
            self.fail(f"unregistered prompt versions found: {issues}")


if __name__ == "__main__":
    unittest.main()
