"""按测试模块分片的并行 unittest 运行器。

发现 ``tests/test_*.py``，按文件大小降序入队，用 N 个并发子进程跑
``python -m unittest tests.test_xxx -v``。不引入 pytest，不改现有测试语义。
"""
from __future__ import annotations

import argparse
import fnmatch
import locale
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

# 经验上会跨进程冲突的模块逃生口。空集起步；只在验证阶段实证到并行不稳定
# （固定端口、固定路径、共享文件锁等）后才加入，并在条目旁注明原因。
SERIAL_MODULES: set[str] = set()

DEFAULT_TIMEOUT_S = 20 * 60
DEFAULT_WORKER_CAP = 8

_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_STATUS_RE = re.compile(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", re.MULTILINE)
_COUNT_RE = re.compile(r"(failures|errors|skipped)=(\d+)")


@dataclass(frozen=True)
class ParsedCounts:
    tests: int
    failures: int
    errors: int
    skipped: int
    ok: bool


@dataclass
class ModuleResult:
    module: str
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    parsed: bool = False
    ok: bool = False
    duration_s: float = 0.0
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def failed(self) -> bool:
        if self.timed_out or not self.parsed:
            return True
        # unittest 全绿退出码恒为 0；解析出 OK 但子进程非零退出不能算过。
        if self.returncode != 0:
            return True
        return (not self.ok) or self.failures > 0 or self.errors > 0


@dataclass
class SuiteResult:
    results: list[ModuleResult] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def tests(self) -> int:
        return sum(row.tests for row in self.results)

    @property
    def failures(self) -> int:
        return sum(row.failures for row in self.results)

    @property
    def errors(self) -> int:
        return sum(row.errors for row in self.results)

    @property
    def skipped(self) -> int:
        return sum(row.skipped for row in self.results)

    @property
    def failed_modules(self) -> list[ModuleResult]:
        return [row for row in self.results if row.failed]


def default_workers() -> int:
    return min(os.cpu_count() or 4, DEFAULT_WORKER_CAP)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    encoding = sys.stdout.encoding or locale.getpreferredencoding(False) or "utf-8"
    return data.decode(encoding, errors="replace")


def _normalize_output(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_unittest_output(text: str) -> ParsedCounts | None:
    """解析真实模块汇总：取最后一个 ``Ran N tests``，状态行只看其后文本。

    输入是 stdout+stderr 拼接，stdout 在前。测试正文可能打印伪 ``Ran``/``OK``
    行；unittest 真实汇总永远在输出末尾。取首个匹配会把伪汇总当成模块结果。
    """
    normalized = _normalize_output(text)
    ran_matches = list(_RAN_RE.finditer(normalized))
    if not ran_matches:
        return None
    ran = ran_matches[-1]
    tests = int(ran.group(1))
    tail = normalized[ran.end():]
    status_matches = list(_STATUS_RE.finditer(tail))
    failures = 0
    errors = 0
    skipped = 0
    ok = False
    if status_matches:
        status = status_matches[-1]
        ok = status.group(1) == "OK"
        detail = status.group(2) or ""
        for key, value in _COUNT_RE.findall(detail):
            count = int(value)
            if key == "failures":
                failures = count
            elif key == "errors":
                errors = count
            elif key == "skipped":
                skipped = count
    return ParsedCounts(
        tests=tests,
        failures=failures,
        errors=errors,
        skipped=skipped,
        ok=ok,
    )


def discover_modules(
    tests_dir: Path,
    *,
    pattern: str | None = None,
    module_prefix: str = "tests",
) -> list[str]:
    """枚举 ``test_*.py``，按文件大小降序返回 ``tests.test_xxx`` 模块名。"""
    files = [
        path
        for path in tests_dir.glob("test_*.py")
        if path.is_file()
    ]
    files.sort(key=lambda path: (-path.stat().st_size, path.name.lower()))
    modules: list[str] = []
    for path in files:
        name = f"{module_prefix}.{path.stem}"
        if pattern and not _pattern_matches(pattern, path, name):
            continue
        modules.append(name)
    return modules


def _pattern_matches(pattern: str, path: Path, module: str) -> bool:
    return any(
        fnmatch.fnmatch(candidate, pattern)
        for candidate in (path.name, path.stem, module)
    )


def run_module(
    module: str,
    *,
    cwd: Path,
    python: Sequence[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    env: dict[str, str] | None = None,
) -> ModuleResult:
    command = list(python or [sys.executable]) + ["-m", "unittest", module, "-v"]
    started = time.perf_counter()
    timed_out = False
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env if env is not None else os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        stdout_b, stderr_b = proc.communicate()
    duration_s = time.perf_counter() - started
    stdout = _decode(stdout_b)
    stderr = _decode(stderr_b)
    row = ModuleResult(
        module=module,
        duration_s=duration_s,
        returncode=-1 if proc.returncode is None else proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )
    parsed = None if timed_out else parse_unittest_output(stdout + "\n" + stderr)
    if parsed is not None:
        row.parsed = True
        row.tests = parsed.tests
        row.failures = parsed.failures
        row.errors = parsed.errors
        row.skipped = parsed.skipped
        row.ok = parsed.ok
    return row


def run_suite(
    modules: Sequence[str],
    *,
    cwd: Path,
    python: Sequence[str] | None = None,
    workers: int | None = None,
    serial: bool = False,
    serial_modules: Iterable[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    env: dict[str, str] | None = None,
    on_module_done: Callable[[ModuleResult, int, int], None] | None = None,
) -> SuiteResult:
    """跑给定模块列表。核心入口，测试可注入 python/cwd/模块列表。"""
    serial_set = set(SERIAL_MODULES if serial_modules is None else serial_modules)
    if serial:
        parallel_mods: list[str] = []
        serial_mods = list(modules)
    else:
        parallel_mods = [name for name in modules if name not in serial_set]
        serial_mods = [name for name in modules if name in serial_set]

    n_workers = default_workers() if workers is None else max(1, int(workers))
    started = time.perf_counter()
    completed: list[ModuleResult] = []
    total = len(modules)

    def _record(row: ModuleResult) -> None:
        completed.append(row)
        if on_module_done is not None:
            on_module_done(row, len(completed), total)

    if parallel_mods:
        pool_size = min(n_workers, len(parallel_mods))
        if pool_size == 1:
            for name in parallel_mods:
                _record(
                    run_module(
                        name,
                        cwd=cwd,
                        python=python,
                        timeout=timeout,
                        env=env,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=pool_size) as pool:
                futures = [
                    pool.submit(
                        run_module,
                        name,
                        cwd=cwd,
                        python=python,
                        timeout=timeout,
                        env=env,
                    )
                    for name in parallel_mods
                ]
                for future in as_completed(futures):
                    _record(future.result())

    for name in serial_mods:
        _record(
            run_module(
                name,
                cwd=cwd,
                python=python,
                timeout=timeout,
                env=env,
            )
        )

    by_module = {row.module: row for row in completed}
    ordered = [by_module[name] for name in modules if name in by_module]
    return SuiteResult(results=ordered, elapsed_s=time.perf_counter() - started)


def suite_exit_code(result: SuiteResult) -> int:
    return 1 if any(row.failed for row in result.results) else 0


def format_summary_line(result: SuiteResult) -> str:
    return (
        f"total={result.tests} failures={result.failures} errors={result.errors} "
        f"skipped={result.skipped} elapsed={result.elapsed_s:.1f}s "
        f"modules={len(result.results)} failed_modules={len(result.failed_modules)}"
    )


def print_report(result: SuiteResult, stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    failed = result.failed_modules
    if failed:
        print("======== FAILED MODULES ========", file=stream)
        for row in failed:
            print(f"----- {row.module} -----", file=stream)
            if row.timed_out:
                print(f"(timed out after {row.duration_s:.1f}s)", file=stream)
            if not row.parsed and not row.timed_out:
                print("(unparsed: no 'Ran N tests' line)", file=stream)
            if row.stdout:
                print(row.stdout, file=stream, end="" if row.stdout.endswith("\n") else "\n")
            if row.stderr:
                print(row.stderr, file=stream, end="" if row.stderr.endswith("\n") else "\n")
        print("", file=stream)
    print("======== SUMMARY ========", file=stream)
    print(format_summary_line(result), file=stream)
    print("slowest 10:", file=stream)
    for row in sorted(result.results, key=lambda item: item.duration_s, reverse=True)[:10]:
        status = "FAIL" if row.failed else "OK"
        print(f"  {row.duration_s:7.1f}s  {status:4}  {row.module}", file=stream)


def _progress_line(row: ModuleResult, done: int, total: int) -> str:
    if row.timed_out:
        status = "TIMEOUT"
    elif not row.parsed:
        status = "UNPARSED"
    elif row.failed:
        status = "FAIL"
    else:
        status = "OK"
    return (
        f"[{done}/{total}] {status} {row.module} "
        f"({row.duration_s:.1f}s, tests={row.tests} fail={row.failures} "
        f"err={row.errors} skip={row.skipped})"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run tests/test_*.py in parallel module shards (stdlib unittest)."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers(),
        help=f"concurrent module subprocesses (default min(cpu_count, {DEFAULT_WORKER_CAP}))",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="per-module timeout in seconds (default 1200)",
    )
    parser.add_argument(
        "--pattern",
        default=None,
        help="optional fnmatch filter on filename / module name",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="run every module sequentially (old-behavior fallback)",
    )
    parser.add_argument(
        "--tests-dir",
        default=None,
        help="override tests directory (default: <repo>/tests)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = default_repo_root()
    tests_dir = Path(args.tests_dir) if args.tests_dir else root / "tests"
    modules = discover_modules(tests_dir, pattern=args.pattern)
    if not modules:
        print("No test modules found.", file=sys.stderr)
        return 1
    workers = max(1, int(args.workers))
    print(
        f"Running {len(modules)} modules; workers={workers}; "
        f"serial={bool(args.serial)}; timeout={args.timeout:.0f}s; "
        f"serial_modules={len(SERIAL_MODULES)}",
        flush=True,
    )
    result = run_suite(
        modules,
        cwd=root,
        python=[sys.executable],
        workers=workers,
        serial=bool(args.serial),
        timeout=float(args.timeout),
        on_module_done=lambda row, done, total: print(
            _progress_line(row, done, total),
            flush=True,
        ),
    )
    print_report(result)
    return suite_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
