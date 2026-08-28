"""并行测试运行器的合成目录契约：聚合计数、崩溃保留、退出码、serial 对照。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_tests_parallel as rtp  # noqa: E402


_OK_SRC = """\
import unittest

class OkTests(unittest.TestCase):
    def test_a(self) -> None:
        self.assertTrue(True)

    def test_b(self) -> None:
        self.assertEqual(1, 1)
"""

_FAIL_SRC = """\
import unittest

class FailTests(unittest.TestCase):
    def test_fail(self) -> None:
        self.assertEqual(1, 2)

    def test_ok(self) -> None:
        self.assertTrue(True)
"""

_SKIP_SRC = """\
import unittest

class SkipTests(unittest.TestCase):
    @unittest.skip("synthetic skip")
    def test_skip(self) -> None:
        self.fail("should be skipped")

    def test_ok(self) -> None:
        self.assertTrue(True)
"""

_IMPORT_ERR_SRC = """\
raise RuntimeError("synthetic import boom")
"""


def _write_synth(root: Path) -> Path:
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_ok.py").write_text(_OK_SRC, encoding="utf-8")
    (tests_dir / "test_fail.py").write_text(_FAIL_SRC, encoding="utf-8")
    (tests_dir / "test_skip.py").write_text(_SKIP_SRC, encoding="utf-8")
    (tests_dir / "test_import_error.py").write_text(_IMPORT_ERR_SRC, encoding="utf-8")
    return tests_dir


class DiscoverModulesTests(unittest.TestCase):
    def test_discovers_test_star_sorted_by_size_desc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_small.py").write_text("x\n", encoding="utf-8")
            (tests_dir / "test_large.py").write_text("y\n" * 80, encoding="utf-8")
            (tests_dir / "helper.py").write_text("not a test module\n", encoding="utf-8")
            modules = rtp.discover_modules(tests_dir)
            self.assertEqual(modules, ["tests.test_large", "tests.test_small"])

    def test_pattern_filters_module_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_alpha.py").write_text("a\n", encoding="utf-8")
            (tests_dir / "test_beta.py").write_text("b\n", encoding="utf-8")
            modules = rtp.discover_modules(tests_dir, pattern="*alpha*")
            self.assertEqual(modules, ["tests.test_alpha"])


class ParseUnittestOutputTests(unittest.TestCase):
    def test_parses_ok_with_skipped(self) -> None:
        text = "Ran 3 tests in 0.012s\n\nOK (skipped=1)\n"
        parsed = rtp.parse_unittest_output(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tests, 3)
        self.assertEqual(parsed.failures, 0)
        self.assertEqual(parsed.errors, 0)
        self.assertEqual(parsed.skipped, 1)
        self.assertTrue(parsed.ok)

    def test_parses_failed_counts(self) -> None:
        text = "Ran 1 test in 0.001s\n\nFAILED (failures=1, errors=2, skipped=3)\n"
        parsed = rtp.parse_unittest_output(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tests, 1)
        self.assertEqual(parsed.failures, 1)
        self.assertEqual(parsed.errors, 2)
        self.assertEqual(parsed.skipped, 3)
        self.assertFalse(parsed.ok)

    def test_missing_ran_line_returns_none(self) -> None:
        self.assertIsNone(rtp.parse_unittest_output("Traceback (most recent call last):\nboom\n"))

    def test_parser_uses_last_ran_and_status_after_it(self) -> None:
        text = (
            "Ran 99 tests in 0.001s\n\nOK\n"
            "test_fail (mod.T.test_fail) ... FAIL\n"
            "Ran 1 test in 0.002s\n\nFAILED (failures=1)\n"
        )
        parsed = rtp.parse_unittest_output(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tests, 1)
        self.assertEqual(parsed.failures, 1)
        self.assertFalse(parsed.ok)


class ParallelRunnerContractTests(unittest.TestCase):
    def _run_synth(self, *, serial: bool) -> rtp.SuiteResult:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = _write_synth(root)
            modules = rtp.discover_modules(tests_dir)
            return rtp.run_suite(
                modules,
                cwd=root,
                python=[sys.executable],
                workers=3,
                serial=serial,
                timeout=60.0,
            )

    def test_aggregation_counts_and_import_crash_preserved(self) -> None:
        result = self._run_synth(serial=False)
        # 可解析模块：ok=2 + fail=2 + skip=2。import 崩溃走
        # ``python -m unittest tests.test_xxx`` 直接加载，不会包成
        # _FailedTest，因此没有 ``Ran N tests``——计模块失败，不虚构用例数。
        self.assertEqual(result.tests, 6)
        self.assertEqual(result.failures, 1)
        self.assertEqual(result.errors, 0)
        self.assertEqual(result.skipped, 1)
        crash = next(r for r in result.results if r.module.endswith("test_import_error"))
        self.assertFalse(crash.parsed)
        self.assertTrue(crash.failed)
        combined = crash.stdout + crash.stderr
        self.assertIn("synthetic import boom", combined)
        self.assertEqual(rtp.suite_exit_code(result), 1)

    def test_all_green_suite_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "__init__.py").write_text("", encoding="utf-8")
            (tests_dir / "test_ok.py").write_text(_OK_SRC, encoding="utf-8")
            result = rtp.run_suite(
                rtp.discover_modules(tests_dir),
                cwd=root,
                python=[sys.executable],
                workers=2,
                timeout=60.0,
            )
            self.assertEqual(result.tests, 2)
            self.assertEqual(result.failures, 0)
            self.assertEqual(result.errors, 0)
            self.assertEqual(result.skipped, 0)
            self.assertEqual(rtp.suite_exit_code(result), 0)

    def test_unparsed_module_counts_as_failure_and_keeps_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub = root / "stub_python.py"
            stub.write_text(
                "import sys\n"
                "sys.stdout.write('no ran-line here\\n')\n"
                "sys.stderr.write('stub stderr\\n')\n"
                "sys.exit(2)\n",
                encoding="utf-8",
            )
            result = rtp.run_suite(
                ["tests.test_missing"],
                cwd=root,
                python=[sys.executable, str(stub)],
                workers=1,
                timeout=30.0,
            )
            self.assertEqual(len(result.results), 1)
            row = result.results[0]
            self.assertFalse(row.parsed)
            self.assertTrue(row.failed)
            self.assertIn("no ran-line here", row.stdout)
            self.assertIn("stub stderr", row.stderr)
            self.assertEqual(rtp.suite_exit_code(result), 1)

    def test_fake_summary_on_stdout_does_not_mask_real_failure(self) -> None:
        fake_then_fail = (
            "import sys\n"
            "import unittest\n"
            "\n"
            'print("Ran 99 tests in 0.001s")\n'
            "print()\n"
            'print("OK")\n'
            "\n"
            "class FailAfterFakeSummaryTests(unittest.TestCase):\n"
            "    def test_fail(self) -> None:\n"
            "        self.assertEqual(1, 2)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "__init__.py").write_text("", encoding="utf-8")
            (tests_dir / "test_fake_ok.py").write_text(fake_then_fail, encoding="utf-8")
            result = rtp.run_suite(
                rtp.discover_modules(tests_dir),
                cwd=root,
                python=[sys.executable],
                workers=1,
                timeout=60.0,
            )
            self.assertEqual(len(result.results), 1)
            row = result.results[0]
            self.assertTrue(row.failed)
            self.assertEqual(row.tests, 1)
            self.assertNotEqual(row.tests, 99)
            self.assertEqual(row.failures, 1)
            self.assertEqual(rtp.suite_exit_code(result), 1)

    def test_nonzero_exit_with_ok_summary_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub = root / "stub_python.py"
            stub.write_text(
                "import sys\n"
                "sys.stdout.write('Ran 1 test in 0.001s\\n\\nOK\\n')\n"
                "sys.exit(3)\n",
                encoding="utf-8",
            )
            result = rtp.run_suite(
                ["tests.test_ok_but_exit"],
                cwd=root,
                python=[sys.executable, str(stub)],
                workers=1,
                timeout=30.0,
            )
            self.assertEqual(len(result.results), 1)
            row = result.results[0]
            self.assertTrue(row.parsed)
            self.assertTrue(row.ok)
            self.assertEqual(row.returncode, 3)
            self.assertTrue(row.failed)
            self.assertEqual(rtp.suite_exit_code(result), 1)

    def test_serial_and_parallel_agree_on_counts(self) -> None:
        parallel = self._run_synth(serial=False)
        serial = self._run_synth(serial=True)
        self.assertEqual(parallel.tests, serial.tests)
        self.assertEqual(parallel.failures, serial.failures)
        self.assertEqual(parallel.errors, serial.errors)
        self.assertEqual(parallel.skipped, serial.skipped)
        self.assertEqual(
            {r.module for r in parallel.results},
            {r.module for r in serial.results},
        )


if __name__ == "__main__":
    unittest.main()
