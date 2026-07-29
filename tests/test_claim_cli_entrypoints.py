from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import cli
import desktop_tasks


class ClaimCliEntrypointTests(unittest.TestCase):
    def test_claim_ledger_fold_accepts_spec_flag_and_compat_alias(self) -> None:
        for parser in (cli.parse_args, desktop_tasks.parse_args):
            for flag in ("--out-dir", "--out"):
                with self.subTest(parser=parser.__module__, flag=flag):
                    args = parser(["claim-ledger-fold", flag, "ledger-out"])
                    self.assertEqual(args.out, Path("ledger-out"))

    def test_ratomizer_forwards_phase0_commands(self) -> None:
        cases = (
            (
                "claim_acceptance.main",
                ["claim-shadow-acceptance", "--input", "input.json", "--output", "report.json"],
                ["--input", "input.json", "--output", "report.json"],
            ),
            (
                "claim_review_packet.main",
                ["claim-shadow-review-packet", "--input", "input.json", "--output-dir", "packet"],
                ["--input", "input.json", "--output-dir", "packet"],
            ),
            (
                "claim_review_import.main",
                [
                    "claim-shadow-review-import",
                    "--input", "input.json",
                    "--decisions", "decisions.json",
                    "--output", "reviewed.json",
                    "--golden-manifest", "manifest.json",
                ],
                [
                    "--input", "input.json",
                    "--decisions", "decisions.json",
                    "--output", "reviewed.json",
                    "--golden-manifest", "manifest.json",
                ],
            ),
        )
        for target, argv, forwarded in cases:
            with self.subTest(command=argv[0]), patch(target, return_value=7) as tool:
                self.assertEqual(cli.main(argv), 7)
                tool.assert_called_once_with(forwarded)

    def test_desktop_backend_tasks_forward_phase0_commands(self) -> None:
        cases = (
            (
                "claim_acceptance.main",
                ["claim-shadow-acceptance", "--input", "input.json"],
                ["--input", "input.json"],
            ),
            (
                "claim_review_packet.main",
                ["claim-shadow-review-packet", "--input", "input.json", "--output-dir", "packet"],
                ["--input", "input.json", "--output-dir", "packet"],
            ),
            (
                "claim_review_import.main",
                [
                    "claim-shadow-review-import",
                    "--input", "input.json",
                    "--decisions", "decisions.json",
                    "--output", "reviewed.json",
                    "--golden-manifest", "manifest.json",
                ],
                [
                    "--input", "input.json",
                    "--decisions", "decisions.json",
                    "--output", "reviewed.json",
                    "--golden-manifest", "manifest.json",
                ],
            ),
        )
        for target, argv, forwarded in cases:
            with self.subTest(command=argv[0]), patch(target, return_value=7) as tool:
                self.assertEqual(desktop_tasks.main(argv), 7)
                tool.assert_called_once_with(forwarded)


if __name__ == "__main__":
    unittest.main()
