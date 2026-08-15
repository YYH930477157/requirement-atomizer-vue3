from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import run_smoke


class RunSmokeTests(unittest.TestCase):
    def test_repository_manifest_has_expected_baseline_shape(self) -> None:
        modules = run_smoke.load_modules(run_smoke.DEFAULT_MANIFEST)
        suite = run_smoke.build_suite(modules)
        self.assertEqual(len(modules), 90)
        # 1766 = 1720 基线 + 三轮未合并改进波新增测试（效率/效果改造、审查反馈修复、
        # 专家复核修复；含页词 memo、造码 str 平价、fold 公平、journal 重试等）。
        self.assertEqual(suite.countTestCases(), 1766)

    def test_manifest_rejects_duplicates_and_non_test_modules(self) -> None:
        for content in ("tests.test_atomize\ntests.test_atomize\n", "atomize\n"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "smoke.txt"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    run_smoke.load_modules(path)


if __name__ == "__main__":
    unittest.main()
