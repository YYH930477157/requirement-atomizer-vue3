"""WP-A 影印接入（doc_annotation_export × doc_facsimile）：docx/xlsx 影印渲染与原生 PDF 同构，
无转换器如实降级，不伪造页图。"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import doc_annotation_export as dae
import doc_facsimile
from parsers.pdf_parser import extract_pdf

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample_text_tables.pdf"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_blocks(out: Path) -> list[dict]:
    """用夹具 PDF 的真实解析块——facsimile PDF=同一夹具时几何锚定与原生 PDF 完全同路径。"""
    blocks, _ = extract_pdf(FIXTURE_PDF, knowledge_bases=[], document_profile=None)
    (out / "blocks.jsonl").write_text(
        "".join(json.dumps(block, ensure_ascii=False) + "\n" for block in blocks),
        encoding="utf-8",
    )
    anchor = next(block for block in blocks if block.get("requirement_like") and not block.get("noise"))
    (out / "merged_spec_requirements.json").write_text(json.dumps({"requirements": [{
        "id": "REQ-1", "title": "锚定需求", "description": "应按原文执行。", "module": "其它",
        "source_section": "1", "source_quote": anchor["text"],
        "source_block_ids": [anchor["block_id"]], "labels": ["其它"],
    }]}, ensure_ascii=False), encoding="utf-8")
    return blocks


def _seed_docx_out(root: Path) -> tuple[Path, Path]:
    out = root / "out"
    out.mkdir()
    source_docx = root / "source.docx"
    source_docx.write_bytes(b"fake-docx-bytes")
    _seed_blocks(out)
    (out / "manifest.json").write_text(
        json.dumps({"input": str(source_docx), "input_format": "docx"}),
        encoding="utf-8",
    )
    return out, source_docx


def _plant_facsimile(out: Path, source_docx: Path, engine: str = "com") -> Path:
    """模拟导出阶段已完成转换：影印 PDF = 夹具 PDF + 指纹 sidecar。"""
    target = out / doc_facsimile.FACSIMILE_PDF
    shutil.copyfile(FIXTURE_PDF, target)
    doc_facsimile._write_facsimile_meta(out, input_path=source_docx.resolve(), facsimile=engine)
    return target


class FacsimileExportTests(unittest.TestCase):
    def test_docx_with_facsimile_pdf_matches_native_pdf_rendering(self) -> None:
        """有 facsimile PDF 时几何/页图产出与原生 PDF 同构（渲染代码零分叉）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, source_docx = _seed_docx_out(root)
            facsimile = _plant_facsimile(out, source_docx)

            target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")
            rendered = target.read_text(encoding="utf-8")

            self.assertEqual(summary["facsimile"], "com")
            self.assertEqual(summary["layout_mode"], "pdf_original")
            self.assertTrue(summary["annotation_overlay"])
            self.assertGreater(len(summary["page_files"]), 0)
            self.assertIn('class="pdf-page"', rendered)
            # 几何缓存锚在影印 PDF 的内容指纹上（不是 docx）
            geometry = json.loads((out / dae.ANNOTATION_PDF_GEOMETRY).read_text(encoding="utf-8"))
            self.assertEqual(geometry["source_sha256"], _sha256(facsimile))
            pages_manifest = json.loads(
                (out / dae.ANNOTATION_PAGES_DIR / dae.ANNOTATION_PAGES_MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(pages_manifest["source_sha256"], _sha256(facsimile))

            # 原生 PDF 对照组：同块 + 同夹具，页数与几何必须逐键相同
            native_out = root / "out_native"
            native_out.mkdir()
            _seed_blocks(native_out)
            (native_out / "manifest.json").write_text(
                json.dumps({"input": str(FIXTURE_PDF), "input_format": "pdf"}), encoding="utf-8")
            _native_target, native_summary = dae.export_annotation_bundle(
                native_out, layout_mode="pdf_original")

            self.assertIsNone(native_summary["facsimile"])   # 原生 PDF 无影印血统
            self.assertEqual(len(summary["page_files"]), len(native_summary["page_files"]))
            facsimile_geometry = json.loads((out / dae.ANNOTATION_PDF_GEOMETRY).read_text(encoding="utf-8"))["geometry"]
            native_geometry = json.loads((native_out / dae.ANNOTATION_PDF_GEOMETRY).read_text(encoding="utf-8"))["geometry"]
            self.assertEqual(facsimile_geometry, native_geometry)

    def test_lazy_conversion_runs_when_facsimile_missing(self) -> None:
        """导出阶段懒转换：无影印时调用 convert_to_pdf（指纹命中跳过）再走同一渲染。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, source_docx = _seed_docx_out(root)
            calls: list[tuple[Path, Path]] = []

            def fake_convert(input_path: Path, work_dir: Path) -> Path:
                calls.append((input_path, work_dir))
                target = work_dir / doc_facsimile.FACSIMILE_PDF
                shutil.copyfile(FIXTURE_PDF, target)
                doc_facsimile._write_facsimile_meta(
                    work_dir, input_path=input_path, facsimile="libreoffice")
                return target

            with mock.patch.object(doc_facsimile, "convert_to_pdf", side_effect=fake_convert):
                target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], source_docx.resolve())
            self.assertEqual(summary["facsimile"], "libreoffice")
            self.assertTrue(summary["annotation_overlay"])
            self.assertIn('class="pdf-page"', target.read_text(encoding="utf-8"))

    def test_unavailable_converter_degrades_honestly_without_fake_pages(self) -> None:
        """无转换器：维持文本批注，summary 如实 unavailable，零页图产物。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, source_docx = _seed_docx_out(root)

            def fake_convert(input_path: Path, work_dir: Path) -> None:
                doc_facsimile._write_facsimile_meta(
                    work_dir, input_path=input_path,
                    facsimile="unavailable:无可用转换器（Office COM 与 LibreOffice 均不可用）")
                return None

            with mock.patch.object(doc_facsimile, "convert_to_pdf", side_effect=fake_convert):
                target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")

            self.assertTrue(summary["facsimile"].startswith("unavailable:"))
            self.assertEqual(summary["layout_mode"], "optimized")   # 如实退回文本批注
            self.assertFalse(summary["annotation_overlay"])
            self.assertFalse((out / dae.ANNOTATION_PAGES_DIR).exists())   # 无伪造页图
            self.assertIsNone(summary["source_pdf"])
            degraded = target.read_text(encoding="utf-8")
            self.assertIn("doc-block", degraded)   # 文本批注视图照常渲染
            self.assertNotIn('class="pdf-page"', degraded)


class FacsimilePayloadTests(unittest.TestCase):
    def test_payload_uses_facsimile_readonly(self) -> None:
        """应用内页图数据：docx 输出目录同等开放（只读复用导出阶段产物，不现场转换）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, source_docx = _seed_docx_out(root)
            _plant_facsimile(out, source_docx)
            dae.export_annotation_bundle(out, layout_mode="pdf_original")

            def forbidden(*_a, **_kw):
                raise AssertionError("应用内只读路径不得现场转换")

            with mock.patch.object(doc_facsimile, "convert_to_pdf", side_effect=forbidden):
                payload = dae.build_pdf_annotation_payload(out)

            self.assertTrue(payload["available"])
            self.assertEqual(payload["facsimile"], "com")
            self.assertGreater(len(payload["pages"]), 0)
            self.assertGreater(len(payload["block_zones"]), 0)

    def test_payload_reports_unavailable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, source_docx = _seed_docx_out(root)
            doc_facsimile._write_facsimile_meta(
                out, input_path=source_docx.resolve(),
                facsimile="unavailable:无可用转换器（Office COM 与 LibreOffice 均不可用）")

            payload = dae.build_pdf_annotation_payload(out)

            self.assertFalse(payload["available"])
            self.assertIn("影印转换不可用", payload["reason"])
            self.assertTrue(payload["facsimile"].startswith("unavailable:"))

    def test_payload_reports_pending_generation_when_never_converted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, _source_docx = _seed_docx_out(root)

            payload = dae.build_pdf_annotation_payload(out)

            self.assertFalse(payload["available"])
            self.assertIn("影印页尚未生成", payload["reason"])

    def test_native_pdf_payload_has_no_facsimile_provenance(self) -> None:
        """原生 PDF 路径不受影印支路影响（明确不做：不动 PDF 原生影印路径）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            _seed_blocks(out)
            (out / "manifest.json").write_text(
                json.dumps({"input": str(FIXTURE_PDF), "input_format": "pdf"}), encoding="utf-8")
            dae.export_annotation_bundle(out, layout_mode="pdf_original")

            payload = dae.build_pdf_annotation_payload(out)

            self.assertTrue(payload["available"])
            self.assertIsNone(payload["facsimile"])

    def test_xlsx_input_uses_same_facsimile_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            source_xlsx = root / "source.xlsx"
            source_xlsx.write_bytes(b"fake-xlsx-bytes")
            _seed_blocks(out)
            (out / "manifest.json").write_text(
                json.dumps({"input": str(source_xlsx), "input_format": "xlsx"}), encoding="utf-8")
            _plant_facsimile(out, source_xlsx, engine="com")

            _target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")

            self.assertEqual(summary["facsimile"], "com")
            self.assertTrue(summary["annotation_overlay"])


if __name__ == "__main__":
    unittest.main()
