from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import run_smoke


class RunSmokeTests(unittest.TestCase):
    def test_repository_manifest_has_expected_baseline_shape(self) -> None:
        modules = run_smoke.load_modules(run_smoke.DEFAULT_MANIFEST)
        suite = run_smoke.build_suite(modules)
        self.assertEqual(len(modules), 91)
        # 1820 = 1792 + 23（队列收敛第 2 步） + 3（功能产物 governed/API 回归）
        #        + 1（任务 D 闭环：保留丢失 data_constraints 回归钉）
        #        + 1（2026-09-09 review 修复：parse 不声明轨道的 CLI 契约钉）
        self.assertEqual(suite.countTestCases(), 1820)

    def test_manifest_rejects_duplicates_and_non_test_modules(self) -> None:
        for content in ("tests.test_atomize\ntests.test_atomize\n", "atomize\n"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "smoke.txt"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    run_smoke.load_modules(path)


if __name__ == "__main__":
    unittest.main()
