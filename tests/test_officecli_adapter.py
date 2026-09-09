from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

import officecli_adapter as adapter
from officecli_adapter import enrich_docx_blocks


class OfficeCliAdapterTests(unittest.TestCase):
    def setUp(self):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {adapter.OFFICECLI_ENV, adapter.OFFICECLI_PATH_ENV}}
        self.environment_patch = mock.patch.dict(os.environ, environment, clear=True)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def test_default_uses_bundled_runtime_on_mac_and_windows(self):
        for platform, filename in (("darwin", "officecli"), ("win32", "officecli.exe")):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                binary = root / filename
                binary.write_bytes(b"bundled")
                with mock.patch.object(adapter.sys, "platform", platform), \
                     mock.patch.object(adapter, "_BUNDLED_ROOT", root), \
                     mock.patch.object(adapter.shutil, "which") as which:
                    self.assertEqual(adapter.officecli_path(), str(binary))
                    which.assert_not_called()

    def test_path_discovery_requires_explicit_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            external = root / "external"
            external.write_bytes(b"external")
            with mock.patch.object(adapter, "_BUNDLED_ROOT", root / "missing"), \
                 mock.patch.object(adapter.shutil, "which", return_value=str(external)) as which:
                self.assertIsNone(adapter.officecli_path())
                self.assertEqual(adapter.officecli_unavailable_reason(), "officecli_not_found")
                which.assert_not_called()
                os.environ[adapter.OFFICECLI_ENV] = "auto"
                self.assertEqual(adapter.officecli_path(), str(external))

    def test_explicit_off_overrides_path_without_running_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "officecli"
            binary.write_bytes(b"runtime")
            os.environ[adapter.OFFICECLI_PATH_ENV] = str(binary)
            for mode in ("off", "0", "false", "disabled"):
                with self.subTest(mode=mode), mock.patch.object(adapter.subprocess, "run") as run:
                    os.environ[adapter.OFFICECLI_ENV] = mode
                    self.assertIsNone(adapter.officecli_path())
                    result = enrich_docx_blocks([], Path("source.docx"))
                    self.assertEqual(result["reason"], "officecli_disabled")
                    run.assert_not_called()

    def test_invalid_mode_and_invalid_explicit_path_are_honest(self):
        os.environ[adapter.OFFICECLI_ENV] = "typo"
        self.assertIsNone(adapter.officecli_path())
        self.assertEqual(adapter.officecli_unavailable_reason(), "officecli_invalid_mode")
        os.environ[adapter.OFFICECLI_ENV] = "bundled"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[adapter.OFFICECLI_PATH_ENV] = str(Path(tmp) / "absent")
            self.assertIsNone(adapter.officecli_path())
            self.assertEqual(adapter.officecli_unavailable_reason(), "officecli_path_not_a_file")

    def test_atomize_cache_tracks_runtime_selection_and_content(self):
        from desktop_tasks import stage_input_fingerprint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            binary = root / "runtime"
            binary.write_bytes(b"version-one")
            os.environ[adapter.OFFICECLI_PATH_ENV] = str(binary)
            enabled = stage_input_fingerprint(root, "atomize")
            os.environ[adapter.OFFICECLI_ENV] = "off"
            disabled = stage_input_fingerprint(root, "atomize")
            self.assertNotEqual(enabled, disabled)
            os.environ[adapter.OFFICECLI_ENV] = "bundled"
            self.assertEqual(enabled, stage_input_fingerprint(root, "atomize"))
            binary.write_bytes(b"version-two-updated")
            self.assertNotEqual(enabled, stage_input_fingerprint(root, "atomize"))

    def test_xlsx_adds_stable_cell_paths_without_rewriting_values(self):
        cells = [{"sheet_name": "Requirements", "a1_address": "B2", "text": "original"}]
        rows = [{"sheet_name": "Requirements", "row_index": 2}]
        fake = '{"success":true,"data":{"sheets":[{"name":"Requirements","rows":[{"row":2,"cells":{"B2":"Office value"}}]}]}}'
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as source, tempfile.NamedTemporaryFile() as binary, \
             mock.patch.dict(os.environ, {"RATOMIZER_OFFICECLI_PATH": binary.name}, clear=False), \
             mock.patch("officecli_adapter.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=fake)
            result = __import__("officecli_adapter").enrich_xlsx_artifacts([], rows, cells, Path(source.name))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(cells[0]["text"], "original")
        self.assertEqual(cells[0]["officecli_path"], "/Requirements/B2")

    def test_unavailable_is_honest_and_does_not_mutate(self):
        blocks = [{"block_id": "B1", "type": "heading", "text": "9.1.1 The meter shall..."}]
        with mock.patch.dict(os.environ, {"RATOMIZER_OFFICECLI": "off"}, clear=False):
            result = enrich_docx_blocks(blocks, Path("/tmp/missing.docx"))
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("officecli_style", blocks[0])

    def test_style_hints_correct_numbered_body_and_lists(self):
        blocks = [
            {"block_id": "B1", "type": "heading", "text": "9 Communication", "section_path": ["9 Communication"]},
            {"block_id": "B2", "type": "heading", "text": "9.1.1 The meter shall provide a modular interface.", "section_path": ["9.1.1 The meter shall provide a modular interface."]},
            {"block_id": "B3", "type": "paragraph", "text": "Upon receipt of the request, the system shall:"},
            {"block_id": "B4", "type": "paragraph", "text": "Validate Meter B eligibility."},
        ]
        fake = '{"success":true,"data":{"content":"' \
               '[/body/p[1]] 「9 Communication」 ← Title | 26pt\\n' \
               '[/body/p[2]] 「9.1.1 The meter shall provide a modular interface.」 ← Normal | 11pt\\n' \
               '[/body/p[3]] 「Upon receipt of the request, the system shall:」 ← Normal | 11pt\\n' \
               '[/body/p[4]] • 「Validate Meter B eligibility.」 ← List Bullet | 11pt"}}'
        with tempfile.NamedTemporaryFile(suffix=".docx") as source, tempfile.NamedTemporaryFile() as binary, \
             mock.patch.dict(os.environ, {"RATOMIZER_OFFICECLI_PATH": binary.name}, clear=False), \
             mock.patch("officecli_adapter.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=fake)
            result = enrich_docx_blocks(blocks, Path(source.name))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(blocks[1]["type"], "paragraph")
        self.assertEqual(blocks[1]["section_path"], ["9 Communication"])
        self.assertTrue(blocks[3]["is_list_item"])
