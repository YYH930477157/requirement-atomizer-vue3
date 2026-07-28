"""WP-A 转换层（doc_facsimile）：COM / soffice / 双缺三路径 + 指纹缓存（全部 mock，无真实 Office）。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import doc_facsimile
from doc_facsimile import (
    DOC_FACSIMILE_VERSION,
    FACSIMILE_PDF,
    _convert_via_com,
    _convert_via_soffice,
    convert_to_pdf,
    find_soffice,
    read_facsimile_status,
)


def _make_com_modules(app: mock.Mock) -> dict[str, types.ModuleType]:
    """构造假的 pythoncom / win32com 模块树，Dispatch 返回给定 app mock。"""
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = mock.Mock()
    pythoncom.CoUninitialize = mock.Mock()
    client = types.ModuleType("win32com.client")
    client.Dispatch = mock.Mock(return_value=app)
    win32com = types.ModuleType("win32com")
    win32com.client = client
    return {"pythoncom": pythoncom, "win32com": win32com, "win32com.client": client}


def _word_app(target_writer) -> mock.Mock:
    app = mock.Mock()
    document = mock.Mock()
    document.SaveAs2.side_effect = target_writer
    app.Documents.Open.return_value = document
    return app


class ComConversionTests(unittest.TestCase):
    def test_word_com_parameters_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.docx"
            source.write_bytes(b"docx-bytes")
            target = root / "out.pdf"

            def save_as2(path: str, FileFormat: int | None = None) -> None:
                Path(path).write_bytes(b"%PDF-1.4 fake")

            app = _word_app(save_as2)
            modules = _make_com_modules(app)
            with mock.patch.dict(sys.modules, modules):
                ok = _convert_via_com(source, target)

            self.assertTrue(ok)
            modules["win32com.client"].Dispatch.assert_called_once_with("Word.Application")
            self.assertFalse(app.Visible)
            self.assertEqual(app.DisplayAlerts, 0)
            app.Documents.Open.assert_called_once_with(str(source.resolve()), ReadOnly=True)
            document = app.Documents.Open.return_value
            document.SaveAs2.assert_called_once_with(str(target), FileFormat=17)
            document.Close.assert_called_once()
            app.Quit.assert_called_once()
            modules["pythoncom"].CoUninitialize.assert_called_once()

    def test_excel_com_export_as_fixed_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            source.write_bytes(b"xlsx-bytes")
            target = root / "out.pdf"

            app = mock.Mock()
            workbook = mock.Mock()
            workbook.ExportAsFixedFormat.side_effect = lambda fmt, path: Path(path).write_bytes(b"%PDF")
            app.Workbooks.Open.return_value = workbook
            modules = _make_com_modules(app)
            with mock.patch.dict(sys.modules, modules):
                ok = _convert_via_com(source, target)

            self.assertTrue(ok)
            modules["win32com.client"].Dispatch.assert_called_once_with("Excel.Application")
            workbook.ExportAsFixedFormat.assert_called_once_with(0, str(target))
            workbook.Close.assert_called_once()
            app.Quit.assert_called_once()
            modules["pythoncom"].CoUninitialize.assert_called_once()

    def test_com_dispatch_failure_cleans_up_and_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.docx"
            source.write_bytes(b"docx-bytes")
            app = mock.Mock()
            modules = _make_com_modules(app)
            modules["win32com.client"].Dispatch.side_effect = RuntimeError("no office")
            with mock.patch.dict(sys.modules, modules):
                ok = _convert_via_com(source, root / "out.pdf")

            self.assertFalse(ok)
            app.Quit.assert_not_called()   # app 从未创建
            modules["pythoncom"].CoUninitialize.assert_called_once()   # 反初始化仍必须执行

    def test_com_pywin32_missing_degrades_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.docx"
            source.write_bytes(b"docx-bytes")
            # sys.modules 里显式 None → import 抛 ImportError（非 win 环境同形态）
            with mock.patch.dict(sys.modules, {"pythoncom": None, "win32com": None,
                                               "win32com.client": None}):
                ok = _convert_via_com(source, root / "out.pdf")
            self.assertFalse(ok)


class SofficeConversionTests(unittest.TestCase):
    def test_find_soffice_path_first(self) -> None:
        with mock.patch.object(doc_facsimile.shutil, "which", return_value="/usr/bin/soffice"):
            self.assertEqual(find_soffice(), "/usr/bin/soffice")

    def test_find_soffice_fallback_install_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "soffice.exe"
            fake.write_bytes(b"exe")
            with mock.patch.object(doc_facsimile.shutil, "which", return_value=None), \
                    mock.patch.object(doc_facsimile, "_SOFFICE_FALLBACK", str(fake)):
                self.assertEqual(find_soffice(), str(fake))

    def test_find_soffice_missing_everywhere(self) -> None:
        with mock.patch.object(doc_facsimile.shutil, "which", return_value=None), \
                mock.patch.object(doc_facsimile, "_SOFFICE_FALLBACK", "D:/nonexistent/soffice.exe"):
            self.assertIsNone(find_soffice())

    def test_soffice_timeout_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.docx"
            source.write_bytes(b"docx-bytes")
            with mock.patch.object(doc_facsimile, "find_soffice", return_value="/fake/soffice"), \
                    mock.patch.object(doc_facsimile.subprocess, "run",
                                      side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=1)):
                ok = _convert_via_soffice(source, root, root / "out.pdf")
            self.assertFalse(ok)
            self.assertFalse((root / "out.pdf").exists())


class ConvertToPdfTests(unittest.TestCase):
    def _seed(self, root: Path) -> Path:
        source = root / "source.docx"
        source.write_bytes(b"docx-bytes-v1")
        return source

    def test_com_success_writes_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._seed(root)

            def fake_com(input_path: Path, target: Path, **_kw) -> bool:
                target.write_bytes(b"%PDF")
                return True

            with mock.patch.object(doc_facsimile, "_convert_via_com", side_effect=fake_com) as com, \
                    mock.patch.object(doc_facsimile, "_convert_via_soffice") as soffice:
                result = convert_to_pdf(source, root)

            self.assertEqual(result, (root / FACSIMILE_PDF).resolve())
            com.assert_called_once()
            soffice.assert_not_called()   # COM 成功不走兜底
            self.assertEqual(read_facsimile_status(root), "com")

    def test_com_unavailable_falls_back_to_soffice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._seed(root)

            def fake_soffice(input_path: Path, out_dir: Path, target: Path, **_kw) -> bool:
                target.write_bytes(b"%PDF")
                return True

            with mock.patch.object(doc_facsimile, "_convert_via_com", return_value=False), \
                    mock.patch.object(doc_facsimile, "_convert_via_soffice", side_effect=fake_soffice):
                result = convert_to_pdf(source, root)

            self.assertIsNotNone(result)
            self.assertEqual(read_facsimile_status(root), "libreoffice")

    def test_both_unavailable_returns_none_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._seed(root)
            with mock.patch.object(doc_facsimile, "_convert_via_com", return_value=False), \
                    mock.patch.object(doc_facsimile, "_convert_via_soffice", return_value=False):
                result = convert_to_pdf(source, root)

            self.assertIsNone(result)
            status = read_facsimile_status(root)
            self.assertIsNotNone(status)
            self.assertTrue(status.startswith("unavailable:"))
            self.assertFalse((root / FACSIMILE_PDF).exists())   # 不伪造页图来源

    def test_cache_fingerprint_hit_skips_reconversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._seed(root)
            target = root / FACSIMILE_PDF
            target.write_bytes(b"%PDF cached")
            doc_facsimile._write_facsimile_meta(root, input_path=source.resolve(), facsimile="com")

            def forbidden(*_a, **_kw) -> bool:
                raise AssertionError("指纹命中不应重转")

            with mock.patch.object(doc_facsimile, "_convert_via_com", side_effect=forbidden), \
                    mock.patch.object(doc_facsimile, "_convert_via_soffice", side_effect=forbidden):
                result = convert_to_pdf(source, root)

            self.assertEqual(result, target.resolve())
            self.assertEqual(target.read_bytes(), b"%PDF cached")   # 缓存原样保留

    def test_version_mismatch_reconverts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._seed(root)
            target = root / FACSIMILE_PDF
            target.write_bytes(b"%PDF stale")
            doc_facsimile._write_facsimile_meta(root, input_path=source.resolve(), facsimile="com")
            meta = json.loads((root / doc_facsimile.FACSIMILE_PDF_META).read_text(encoding="utf-8"))
            meta["version"] = "doc-facsimile-v0-stale"
            (root / doc_facsimile.FACSIMILE_PDF_META).write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8")

            def fake_com(input_path: Path, out_target: Path, **_kw) -> bool:
                out_target.write_bytes(b"%PDF fresh")
                return True

            with mock.patch.object(doc_facsimile, "_convert_via_com", side_effect=fake_com) as com:
                result = convert_to_pdf(source, root)

            com.assert_called_once()   # 版本未 bump 的旧缓存不得复用
            self.assertIsNotNone(result)
            self.assertEqual(target.read_bytes(), b"%PDF fresh")
            self.assertEqual(DOC_FACSIMILE_VERSION, "doc-facsimile-v1")

    def test_input_content_change_reconverts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._seed(root)
            target = root / FACSIMILE_PDF
            target.write_bytes(b"%PDF stale")
            doc_facsimile._write_facsimile_meta(root, input_path=source.resolve(), facsimile="com")
            source.write_bytes(b"docx-bytes-v2-changed")

            with mock.patch.object(doc_facsimile, "_convert_via_com", return_value=False), \
                    mock.patch.object(doc_facsimile, "_convert_via_soffice", return_value=False):
                result = convert_to_pdf(source, root)

            self.assertIsNone(result)   # 指纹不符 → 重转；双缺 → 如实 unavailable
            self.assertTrue(read_facsimile_status(root).startswith("unavailable:"))

    def test_non_office_input_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.4")
            self.assertIsNone(convert_to_pdf(source, root))

    def test_missing_input_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(convert_to_pdf(root / "missing.docx", root))


if __name__ == "__main__":
    unittest.main()
