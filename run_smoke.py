"""Run the repository's fast, deterministic unittest smoke layer."""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


DEFAULT_MANIFEST = Path(__file__).resolve().parent / "tests" / "smoke.txt"


def load_modules(path: Path) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = raw.partition("#")[0].strip()
        if not entry:
            continue
        if not entry.startswith("tests.test_"):
            raise ValueError(f"{path}:{line_number}: expected tests.test_* module, got {entry!r}")
        if entry in seen:
            raise ValueError(f"{path}:{line_number}: duplicate module {entry}")
        seen.add(entry)
        modules.append(entry)
    if not modules:
        raise ValueError(f"{path}: smoke manifest is empty")
    return modules


def build_suite(modules: list[str]) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(modules)
    if loader.errors:
        raise RuntimeError("\n".join(loader.errors))
    return suite


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--list", action="store_true", help="print modules and test count without running")
    parser.add_argument("--failfast", action="store_true")
    parser.add_argument("-v", "--verbosity", action="count", default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        modules = load_modules(args.manifest.resolve())
        suite = build_suite(modules)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"smoke manifest error: {exc}", file=sys.stderr)
        return 2

    count = suite.countTestCases()
    print(f"smoke: {len(modules)} modules / {count} tests", flush=True)
    if args.list:
        print("\n".join(modules))
        return 0
    result = unittest.TextTestRunner(
        verbosity=max(0, args.verbosity),
        failfast=args.failfast,
    ).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
