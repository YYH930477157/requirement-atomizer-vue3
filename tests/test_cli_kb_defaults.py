from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from requirement_kb.cli import package_root


class CliKnowledgeBaseDefaultTests(unittest.TestCase):
    def test_command_run_uses_default_kbs_when_not_supplied(self) -> None:
        import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            default_paths = [root / "energy.json", root / "compiled_from_obsidian.json"]
            args = argparse.Namespace(
                input=input_path,
                out=out_dir,
                chunk_chars=3500,
                kb=[],
                domain_pack=None,
                skip_review=True,
                export="",
                llm_route=None,
                review_scope=None,
            )

            with (
                patch("cli.default_kb_paths", return_value=default_paths),
                patch("cli.run_atomizer_pipeline") as atomize,
                patch("cli.quality_summary_for", return_value={}),
            ):
                atomize.return_value = {"counts": {"atomic_requirements": 0}}
                cli.command_run(args, 0.0, {})

        atomize.assert_called_once()
        self.assertEqual(atomize.call_args.kwargs["kb_paths"], default_paths)

    def test_command_run_preserves_explicit_kbs(self) -> None:
        import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "custom.json"
            args = argparse.Namespace(
                input=root / "input.docx",
                out=root / "out",
                chunk_chars=3500,
                kb=[explicit],
                domain_pack=None,
                skip_review=True,
                export="",
                llm_route=None,
                review_scope=None,
            )

            with (
                patch("cli.default_kb_paths") as default_kb_paths,
                patch("cli.run_atomizer_pipeline") as atomize,
                patch("cli.quality_summary_for", return_value={}),
            ):
                atomize.return_value = {"counts": {"atomic_requirements": 0}}
                cli.command_run(args, 0.0, {})

        default_kb_paths.assert_not_called()
        self.assertEqual(atomize.call_args.kwargs["kb_paths"], [explicit])


class RequirementKbPackageRootTests(unittest.TestCase):
    """锁定 requirement_kb.cli.package_root 的 frozen 解析，防再次与 resources.py 分叉。

    历史 bug：旧版只取 sys.executable 父目录，在 Electron 打包（exe 在 resources/backend/，
    数据在上一级 resources/）下找不到 knowledge_bases/，导致 'No such file: …/backend/
    knowledge_bases/energy_metering.json'。
    """

    def test_not_frozen_returns_repo_root(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(package_root(), Path(__file__).resolve().parents[1])

    def test_electron_backend_layout_returns_resources_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resources = Path(tmp) / "resources"
            (resources / "backend").mkdir(parents=True)
            (resources / "llm_agents").mkdir()
            exe = resources / "backend" / "ratomizer-desktop.exe"
            exe.write_text("")
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(exe)),
            ):
                self.assertEqual(package_root(), resources.resolve())

    def test_onefile_uses_meipass_when_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "_MEI012345"
            meipass.mkdir()
            exe = Path("D:/onefile/ratomizer-desktop.exe")
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "_MEIPASS", str(meipass), create=True),
            ):
                self.assertEqual(package_root(), meipass.resolve())

    def test_frozen_falls_back_to_executable_dir(self) -> None:
        exe = Path("D:/dist/RequirementAtomizer/ratomizer.exe")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(exe)),
            patch.object(sys, "_MEIPASS", "", create=True),
        ):
            self.assertEqual(package_root(), exe.parent)


if __name__ == "__main__":
    unittest.main()
