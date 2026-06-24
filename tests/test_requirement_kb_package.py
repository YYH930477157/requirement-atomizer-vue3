from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from requirement_kb import KnowledgeRepository, clean_text, compile_term_pattern, find_matched_terms
from requirement_kb.cli import default_kb_paths
from requirement_kb.obsidian import compile_vault_to_json
from requirement_kb.schema import validate_kb_file
from requirement_kb.server import KBRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]


class RequirementKBPackageTests(unittest.TestCase):
    def test_public_api_loads_and_matches_runtime_kb(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "energy_metering_cosem_classes.json"])

        matches = repo.match_text("The register object shall expose readable attributes.", limit=5)

        self.assertTrue(matches)
        first = matches[0]
        self.assertEqual(first["kb_id"], "energy_metering_cosem_classes")
        self.assertIn("entry_id", first)
        self.assertIn("name", first)
        self.assertIn("definition", first)
        self.assertIn("matched_terms", first)
        self.assertIn("score", first)

    def test_matching_helpers_are_exported_from_package(self) -> None:
        pattern = compile_term_pattern(["register"])

        self.assertEqual(clean_text("Register\u3000object"), "Register object")
        self.assertEqual(find_matched_terms(pattern, "Registers shall be readable"), ["register"])

    def test_obsidian_compile_and_schema_validation_are_package_apis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            note = vault / "01_terms" / "Register.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                """---
id: KB-REGISTER
kb_id: test_kb
type: term
layer: term
name: Register
aliases: []
keywords:
- register
domain_tags:
- cosem
relations: []
---

# Register

## Definition

A COSEM interface class for scalar measured values.
""",
                encoding="utf-8",
            )
            out_path = Path(tmp) / "compiled.json"

            payload = compile_vault_to_json(vault, out_path, kb_id="auto")
            issues = validate_kb_file(out_path)

        self.assertEqual(payload["kb_id"], "obsidian_compiled_kb")
        self.assertEqual(payload["entries"][0]["id"], "KB-REGISTER")
        self.assertEqual([issue for issue in issues if issue.severity == "error"], [])

    def test_requirement_kb_cli_info_prints_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "requirement_kb.cli",
                "--kb",
                str(ROOT / "knowledge_bases" / "energy_metering.json"),
                "info",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload[0]["kb_id"], "energy_metering")

    def test_default_kb_paths_can_be_overridden_for_external_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"REQUIREMENT_KB_HOME": tmp}, clear=False):
                paths = default_kb_paths()

        self.assertEqual(paths[0], Path(tmp).resolve() / "energy_metering.json")
        self.assertEqual(paths[1], Path(tmp).resolve() / "energy_metering_protocol_layer.json")
        self.assertEqual(paths[2], Path(tmp).resolve() / "energy_metering_cosem_classes.json")
        self.assertEqual(paths[3], Path(tmp).resolve() / "compiled_from_obsidian.json")

    def test_http_handler_exposes_package_repository_to_other_tools(self) -> None:
        class TestHandler(KBRequestHandler):
            pass

        TestHandler.repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "energy_metering.json"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/info", timeout=5) as response:
                info = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/search?q=DLMS&limit=1",
                timeout=5,
            ) as response:
                matches = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(info[0]["kb_id"], "energy_metering")
        self.assertEqual(matches[0]["name"], "DLMS")


if __name__ == "__main__":
    unittest.main()
