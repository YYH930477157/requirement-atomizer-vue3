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

    def test_subprocess_reads_utf8_regardless_of_windows_locale(self):
        """zh-CN Windows 默认 GBK；officecli 输出 UTF-8（含 「」）——必须显式 utf-8 解码。

        否则 reader 线程 UnicodeDecodeError 被 ValueError 分支吞掉，内置 OfficeCLI
        在中文 Windows 上永远静默降级 unavailable（2026-09-09 打包冒烟实测）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "officecli.exe"
            binary.write_bytes(b"runtime")
            with mock.patch.dict(os.environ, {adapter.OFFICECLI_PATH_ENV: str(binary)}, clear=False), \
                 mock.patch("officecli_adapter.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=1, stdout="{}")
                enrich_docx_blocks([], Path("source.docx"))
                kwargs = run.call_args.kwargs
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")

    def test_invocation_uses_stable_input_copy_never_the_source(self):
        """officecli daemon 永不释放被查看文件的句柄——subprocess 只准看到稳定副本。

        直接喂源文件会把用户文档永久锁死（不能移动/删除），测试临时目录也因此
        清理失败（WinError 32，2026-09-09 实测复归）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "spec.docx"
            source.write_bytes(b"PK-source-document")
            with mock.patch.dict(os.environ, {adapter.OFFICECLI_PATH_ENV: str(tmp_path / "officecli.exe")}, clear=False), \
                 mock.patch.object(adapter.tempfile, "gettempdir", return_value=str(tmp_path / "cache")), \
                 mock.patch("officecli_adapter.subprocess.run") as run:
                (tmp_path / "officecli.exe").write_bytes(b"runtime")
                run.return_value = mock.Mock(returncode=1, stdout="{}")
                enrich_docx_blocks([], source)
                first_argv = run.call_args.args[0]
                # 同一源文件再次解析 → 复用同一副本（同一文档版本只复制一次）。
                enrich_docx_blocks([], source)
                second_argv = run.call_args.args[0]
            copies = list((tmp_path / "cache" / "ratomizer-officecli-inputs").glob("doc-*.docx"))
            self.assertEqual(len(copies), 1, "同一文档版本只复制一份")
            self.assertEqual(copies[0].read_bytes(), b"PK-source-document")
            self.assertNotEqual(first_argv[2], str(source), "officecli 不得直视源文件")
            self.assertEqual(first_argv[2], second_argv[2], "副本跨解析复用")

    def test_frozen_invocation_stages_to_stable_cache(self):
        """onefile 冻结下不直接执行 _MEI* 里的副本（daemon 会锁住它 → 解包目录泄漏）。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "officecli.exe"
            source.write_bytes(b"bundled-runtime")
            with mock.patch.object(adapter.sys, "frozen", True, create=True), \
                 mock.patch.object(adapter.tempfile, "gettempdir", return_value=str(tmp_path)), \
                 mock.patch.dict(os.environ, {adapter.OFFICECLI_PATH_ENV: str(source)}, clear=False), \
                 mock.patch("officecli_adapter.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=1, stdout="{}")
                result = enrich_docx_blocks([], Path("source.docx"))
                argv = run.call_args.args[0]
            staged = list((tmp_path / "ratomizer-officecli").glob("officecli-*.exe"))
            self.assertEqual(len(staged), 1, "同一内容二进制只复制一份")
            self.assertEqual(staged[0].read_bytes(), b"bundled-runtime")
            self.assertEqual(argv[0], str(staged[0]))
            self.assertNotEqual(argv[0], str(source), "执行的必须是缓存副本而非 _MEI 原路径")
        self.assertEqual(result["reason"], "officecli_nonzero_exit")

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
