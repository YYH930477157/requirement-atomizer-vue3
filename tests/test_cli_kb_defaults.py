from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
