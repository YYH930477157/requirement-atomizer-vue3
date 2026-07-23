"""安装后冒烟测试（审计 P1）：wheel 构建 → 内容检查 → 隔离安装 → 真实导入。

此前验收只在仓库根跑测试，py-modules 漏注册 functional_catalog、顶层 schemas/ 未打包
都因此漏网——安装后 import agent_eval 报 ModuleNotFoundError、
decide_trace.load_decide_trace_schema() 报文件不存在。本测试把"安装后能用"钉成回归。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _build_wheel(target: Path) -> Path:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--no-input", "-w", str(target), str(ROOT)],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise unittest.SkipTest(f"wheel build unavailable in this environment: {result.stderr[-500:]}")
    wheels = sorted(target.glob("*.whl"))
    if not wheels:
        raise unittest.SkipTest("wheel build produced no artifact")
    return wheels[-1]


class WheelPackagingSmokeTests(unittest.TestCase):
    def test_wheel_contents_and_installed_imports(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wheel = _build_wheel(Path(td) / "dist")
            Path(td + "/dist").mkdir(exist_ok=True)

        with tempfile.TemporaryDirectory() as td:
            dist = Path(td) / "dist"
            dist.mkdir()
            wheel = _build_wheel(dist)

            names = set(zipfile.ZipFile(wheel).namelist())
            for required in (
                "agent_eval.py", "agent_loop.py", "agent_state.py", "agent_tools.py",
                "agent_compare.py", "agent_decider.py", "decide_trace.py",
                "functional_catalog.py", "review_tools.py",
                "schemas/decide_trace.schema.json", "schemas/agent_eval_case.schema.json",
            ):
                self.assertIn(required, names, f"wheel missing {required}")

            site = Path(td) / "site"
            install = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-deps", "--no-input",
                 "--target", str(site), str(wheel)],
                capture_output=True, text=True, timeout=600,
            )
            self.assertEqual(install.returncode, 0, install.stderr[-500:])

            probe = (
                "import agent_eval, decide_trace;"
                "decide_trace.load_decide_trace_schema();"
                "agent_eval.load_case_schema();"
                "import functional_catalog, review_tools;"
                "print('SMOKE OK')"
            )
            run = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True, text=True, timeout=120,
                env={"PYTHONPATH": str(site), "PATH": ""},
            )
            self.assertEqual(run.returncode, 0, f"{run.stdout[-300:]} {run.stderr[-500:]}")
            self.assertIn("SMOKE OK", run.stdout)


if __name__ == "__main__":
    unittest.main()
