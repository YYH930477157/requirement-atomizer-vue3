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
from requirement_kb.obsidian import compile_vault_to_json, export_json_to_vault
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

    def test_duplicate_entry_id_across_kbs_is_exposed_not_shadowed(self) -> None:
        # 回归护栏：同一 entry_id 跨多个 KB 文件时（实测默认 4 库有 86 处冲突），
        # 旧实现悄悄保留「最后加载」的那份、遮蔽权威条目。现在首个加载优先且暴露歧义。
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "kb_a.json").write_text(json.dumps({
                "kb_id": "kb_a",
                "entries": [{"id": "KB-DUP", "name": "Authoritative", "definition": "from A"}],
            }), encoding="utf-8")
            (d / "kb_b.json").write_text(json.dumps({
                "kb_id": "kb_b",
                "entries": [{"id": "KB-DUP", "name": "Shadow", "definition": "from B"}],
            }), encoding="utf-8")
            repo = KnowledgeRepository.from_paths([d / "kb_a.json", d / "kb_b.json"])

        self.assertEqual(repo.id_collisions(), {"KB-DUP": ["kb_a", "kb_b"]})
        row = repo.get("KB-DUP")
        self.assertEqual(row["kb_id"], "kb_a")  # 首个/权威优先，不被 B 遮蔽
        self.assertEqual(row["kb_id_collisions"], ["kb_a", "kb_b"])
        explicit = repo.get("KB-DUP", kb_id="kb_b")
        self.assertEqual(explicit["definition"], "from B")
        self.assertNotIn("kb_id_collisions", explicit)

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

    def test_obsidian_export_groups_cosem_classes_by_class_id_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_path = Path(tmp) / "classes.json"
            kb_path.write_text(
                json.dumps(
                    {
                        "kb_id": "test_kb",
                        "name": "Test KB",
                        "version": "0.1.0",
                        "entries": [
                            {
                                "id": "KB-L3-IC-3-REGISTER",
                                "type": "cosem_interface_class",
                                "layer": "cosem_class",
                                "name": "Register",
                                "aliases": ["class 3"],
                                "keywords": ["register"],
                                "domain_tags": ["cosem_class"],
                                "definition": "Register class.",
                                "relations": [],
                                "class_id": 3,
                                "version": 0,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            vault = Path(tmp) / "vault"

            written = export_json_to_vault([kb_path], vault)

        self.assertIn(vault / "03_cosem_classes" / "003-Register" / "Register.md", written)
        self.assertFalse((vault / "03_cosem_classes" / "Register.md").exists())

    def test_obsidian_export_groups_object_instances_by_class_id_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_path = Path(tmp) / "objects.json"
            kb_path.write_text(
                json.dumps(
                    {
                        "kb_id": "test_kb",
                        "name": "Test KB",
                        "version": "0.1.0",
                        "entries": [
                            {
                                "id": "KB-L3-IC-3-REGISTER",
                                "type": "cosem_interface_class",
                                "layer": "cosem_class",
                                "name": "Register",
                                "aliases": [],
                                "keywords": ["register"],
                                "domain_tags": ["cosem_class"],
                                "definition": "Register class.",
                                "relations": [],
                                "class_id": 3,
                                "version": 0,
                            },
                            {
                                "id": "KB-OBIS-1-0-1-8-0-255-ACTIVE-ENERGY-IMPORT",
                                "type": "cosem_object_instance",
                                "layer": "cosem_object_instance",
                                "name": "Active energy import total",
                                "aliases": [],
                                "keywords": ["1-0:1.8.0.255"],
                                "domain_tags": ["cosem_object"],
                                "definition": "Active energy import object.",
                                "relations": [],
                                "likely_interface_class_id": 3,
                                "likely_interface_class_name": "register",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            vault = Path(tmp) / "vault"

            written = export_json_to_vault([kb_path], vault)

        self.assertIn(
            vault / "04_object_instances" / "003-Register" / "Active energy import total.md",
            written,
        )
        self.assertFalse((vault / "04_object_instances" / "Active energy import total.md").exists())

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

    def test_requirement_kb_cli_coverage_prints_utf8_when_console_encoding_is_gbk(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "requirement_kb.cli",
                "coverage",
                str(ROOT / "knowledge_bases" / "compiled_from_obsidian.json"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env={"PYTHONIOENCODING": "gbk"},
            encoding="utf-8",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("KB Coverage Report", completed.stdout)
        self.assertIn("Catalogue/structure tables not expected to have row-level instances", completed.stdout)
        self.assertNotIn("Tables with catalogue but NO row-level instances", completed.stdout)

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
