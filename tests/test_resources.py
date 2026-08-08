from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resources import package_root


class ResourcePathTests(unittest.TestCase):
    def test_package_root_uses_source_module_directory_when_not_frozen(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(package_root(), Path(__file__).resolve().parents[1])

    def test_package_root_uses_executable_directory_when_frozen(self) -> None:
        exe_path = Path("D:/dist/RequirementAtomizer/ratomizer.exe")

        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(exe_path)):
            self.assertEqual(package_root(), exe_path.parent)

    def test_onefile_prefers_meipass_over_electron_resources_layout(self) -> None:
        """electron portable：onefile backend exe 在 <resources>/backend/，
        <resources>/llm_agents 由 extraResources 复制（无 schemas/）。
        package_root 必须返回 _MEIPASS（onefile datas 权威位置），不能被
        llm_agents 启发式误指到 <resources>/——否则 schema 加载报 No such file。"""
        with tempfile.TemporaryDirectory() as td:
            resources = Path(td) / "resources"
            backend = resources / "backend"
            meipass = Path(td) / "_meipass"
            (backend).mkdir(parents=True)
            (resources / "llm_agents").mkdir()
            # onefile datas（含 schemas）解压到 _MEIPASS，而非 resources/
            (meipass / "schemas").mkdir(parents=True)
            (meipass / "llm_agents").mkdir()
            exe = backend / "ratomizer-desktop.exe"

            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", str(exe)), \
                 patch.object(sys, "_MEIPASS", str(meipass), create=True):
                self.assertEqual(package_root(), meipass)

    def test_onedir_backend_uses_parent_when_llm_agents_present(self) -> None:
        """onedir（ratomizer.spec COLLECT）：exe 在 backend/，datas 与父目录同级。
        _MEIPASS 指向 exe 自身目录（onedir 语义），故走 backend 启发式返回父目录。"""
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "RequirementAtomizer"
            backend = pkg / "backend"
            (backend).mkdir(parents=True)
            (pkg / "llm_agents").mkdir()
            exe = backend / "ratomizer.exe"

            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", str(exe)), \
                 patch.object(sys, "_MEIPASS", str(backend), create=True):
                self.assertEqual(package_root(), pkg)


if __name__ == "__main__":
    unittest.main()
