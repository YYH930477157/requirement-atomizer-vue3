from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class CliReviewForwardingTests(unittest.TestCase):
    """审计 R2-H3：--kb/--domain-pack 贯通到审查阶段——cli run/review 此前只喂 atomize，
    审查恒落默认 KB/默认捆绑包。"""

    def _run_args(self, root: Path, **overrides) -> argparse.Namespace:
        args = argparse.Namespace(
            input=root / "input.docx",
            out=root / "out",
            chunk_chars=3500,
            kb=[],
            domain_pack=None,
            skip_review=False,
            export="",
            llm_route=None,
            review_scope=None,
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_command_run_forwards_kb_and_domain_pack_to_review(self) -> None:
        import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb.json"
            pack = root / "domain_packs" / "dlms_cosem"
            args = self._run_args(root, kb=[kb], domain_pack=pack)

            with (
                patch("cli.run_atomizer_pipeline") as atomize,
                patch("cli.run_review_pipeline") as review,
                patch("cli.quality_summary_for", return_value={}),
            ):
                atomize.return_value = {"counts": {"atomic_requirements": 0}}
                review.return_value = {"reviews": 0}
                cli.command_run(args, 0.0, {})

        # run 的 --domain-pack 是目录（atomize 语义），审查侧转发目录下的 pack.yaml
        review.assert_called_once_with(
            args.out, route=None, scope=None,
            kb_paths=[kb], domain_pack_path=pack / "pack.yaml")

    def test_command_run_without_explicit_pack_keeps_review_default(self) -> None:
        import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._run_args(root)

            with (
                patch("cli.run_atomizer_pipeline") as atomize,
                patch("cli.run_review_pipeline") as review,
                patch("cli.quality_summary_for", return_value={}),
            ):
                atomize.return_value = {"counts": {"atomic_requirements": 0}}
                review.return_value = {"reviews": 0}
                cli.command_run(args, 0.0, {})

        # 未传 --kb/--domain-pack 时不得显式传 None/空列表——显式 None 会关掉
        # run_review_pipeline 默认捆绑包的 review_policy 合并
        review.assert_called_once_with(args.out, route=None, scope=None)

    def test_command_review_forwards_kb(self) -> None:
        import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "kb.json"
            args = argparse.Namespace(
                out=root / "out",
                review_pipeline=None,
                domain_pack=None,
                limit=0,
                llm_route=None,
                review_scope=None,
                kb=[kb],
            )

            with (
                patch("cli.run_review_pipeline") as review,
                patch("cli.quality_summary_for", return_value={}),
            ):
                review.return_value = {"reviews": 0}
                cli.command_review(args, 0.0, {})

        review.assert_called_once_with(args.out, limit=0, route=None, scope=None, kb_paths=[kb])

    def test_command_review_without_kb_omits_kwarg(self) -> None:
        import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(
                out=root / "out",
                review_pipeline=None,
                domain_pack=None,
                limit=0,
                llm_route=None,
                review_scope=None,
                kb=[],
            )

            with (
                patch("cli.run_review_pipeline") as review,
                patch("cli.quality_summary_for", return_value={}),
            ):
                review.return_value = {"reviews": 0}
                cli.command_review(args, 0.0, {})

        # 空 --kb 列表不得覆盖 run_review_pipeline 的默认 KB 解析
        review.assert_called_once_with(args.out, limit=0, route=None, scope=None)

    def test_review_subcommand_parses_repeatable_kb(self) -> None:
        import cli

        args = cli.parse_args(["review", "--out", "out", "--kb", "a.json", "--kb", "b.json"])

        self.assertEqual(args.kb, [Path("a.json"), Path("b.json")])


if __name__ == "__main__":
    unittest.main()
