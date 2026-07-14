"""自包含文档批注 HTML 导出回归。"""
from __future__ import annotations

import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import doc_annotation_export as dae
from parsers.pdf_parser import extract_pdf


def _seed(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        json.dumps({"block_id": "B1", "order": 1, "type": "heading", "text": "4 Requirements",
                    "section_path": ["4 Requirements"], "page_number": 1,
                    "requirement_like": False, "noise": False}) + "\n" +
        json.dumps({"block_id": "B2", "order": 2, "type": "paragraph",
                    "text": "The meter shall measure volume < 5 & log it.",
                    "section_path": ["4 Requirements"], "page_number": 2,
                    "requirement_like": True, "noise": False}) + "\n" +
        json.dumps({"block_id": "B3", "order": 3, "type": "paragraph",
                    "text": "An uncovered requirement shall hold.",
                    "section_path": ["4 Requirements"], "page_number": 3,
                    "requirement_like": True, "noise": False}) + "\n",
        encoding="utf-8")
    doc = {"requirements": [
        {"id": "REQ-001", "title": "体积计量", "description": "应计量体积", "module": "计量",
         "source_section": "4", "source_quote": "The meter shall measure volume < 5 & log it.",
         "source_block_ids": ["B2"], "acceptance_criteria": ["按 4.2 测试"], "labels": ["计量"]},
    ]}
    (out / "merged_spec_requirements.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class DocAnnotationExportTests(unittest.TestCase):
    def test_pdf_original_layout_renders_pages_with_clickable_annotation_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            source_pdf = Path(__file__).parent / "fixtures" / "sample_text_tables.pdf"
            blocks, _ = extract_pdf(source_pdf, knowledge_bases=[], document_profile=None)
            for block in blocks:
                block.pop("pdf_regions", None)  # 模拟升级前已经生成的旧输出
            (out / "blocks.jsonl").write_text(
                "".join(json.dumps(block, ensure_ascii=False) + "\n" for block in blocks),
                encoding="utf-8",
            )
            anchor = next(block for block in blocks if block.get("requirement_like") and not block.get("noise"))
            (out / "merged_spec_requirements.json").write_text(json.dumps({"requirements": [{
                "id": "REQ-PDF-1",
                "title": "PDF 坐标批注",
                "description": "应按原文执行。",
                "module": "其它",
                "source_section": "5.1",
                "source_quote": anchor["text"],
                "source_block_ids": [anchor["block_id"]],
                "labels": ["其它"],
            }]}, ensure_ascii=False), encoding="utf-8")
            (out / "manifest.json").write_text(
                json.dumps({"input": str(source_pdf), "input_format": "pdf"}),
                encoding="utf-8",
            )

            target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")
            rendered = target.read_text(encoding="utf-8")

            self.assertTrue(summary["annotation_overlay"])
            self.assertTrue((out / dae.ANNOTATION_PDF_GEOMETRY).is_file())
            self.assertGreater(len(summary["page_files"]), 0)
            self.assertTrue(all(Path(path).is_file() for path in summary["page_files"]))
            self.assertIn('class="pdf-page"', rendered)
            self.assertIn('class="pdf-marker marker-requirement', rendered)
            self.assertIn('class="pdf-marker omission-tag marker-omission"', rendered)
            self.assertIn('data-req="', rendered)
            self.assertIn('data-omission-text="', rendered)
            self.assertIn('function setPdfZoom', rendered)
            self.assertIn('IntersectionObserver', rendered)
            self.assertIn('className = "pdf-index-tabs"', rendered)
            self.assertIn('if (pdfMarker) { select(pdfMarker.getAttribute("data-req")); return; }', rendered)
            self.assertIn('function renderOmissionDetails', rendered)
            self.assertNotIn('id="pdf-frame"', rendered)

    def test_pdf_original_layout_copies_source_pdf_and_embeds_it_without_reflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            _seed(out)
            source_pdf = root / "source.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\noriginal-pdf-bytes\n%%EOF")
            (out / "manifest.json").write_text(
                json.dumps({"input": str(source_pdf), "input_format": "pdf"}),
                encoding="utf-8",
            )

            target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")
            rendered = target.read_text(encoding="utf-8")

            copied_pdf = out / dae.ANNOTATION_SOURCE_PDF
            self.assertEqual(copied_pdf.read_bytes(), source_pdf.read_bytes())
            self.assertEqual(summary["layout_mode_requested"], "pdf_original")
            self.assertEqual(summary["layout_mode"], "pdf_original")
            self.assertEqual(summary["source_pdf"], str(copied_pdf))
            self.assertIn('class="reader-shell pdf-original"', rendered)
            self.assertIn('id="pdf-frame"', rendered)
            self.assertIn('const PDF_MODE = true;', rendered)
            self.assertIn('const PDF_HREF = "document_source.pdf";', rendered)
            self.assertIn('"source_page": 2', rendered)
            self.assertIn('"annotation_number": 1', rendered)
            self.assertIn('item.onclick = () => select(r.ai_req_id);', rendered)
            self.assertIn('if (PDF_MODE) showPdfPage(r.source_page);', rendered)
            self.assertIn('"#page=" + pageNumber + "&view=FitH"', rendered)
            self.assertNotIn('class="doc-block', rendered)

    def test_pdf_original_layout_falls_back_for_non_pdf_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            _seed(out)
            source_docx = root / "source.docx"
            source_docx.write_bytes(b"not-a-pdf")
            (out / "manifest.json").write_text(
                json.dumps({"input": str(source_docx), "input_format": "docx"}),
                encoding="utf-8",
            )

            target, summary = dae.export_annotation_bundle(out, layout_mode="pdf_original")
            rendered = target.read_text(encoding="utf-8")

            self.assertEqual(summary["layout_mode_requested"], "pdf_original")
            self.assertEqual(summary["layout_mode"], "optimized")
            self.assertIsNone(summary["source_pdf"])
            self.assertIn('class="reader-shell"', rendered)
            self.assertIn('const PDF_MODE = false;', rendered)
            self.assertIn('class="doc-block', rendered)

    def test_renders_self_contained_html_with_data_and_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            html = dae.render_annotation_html(out)
            # 自包含：无外部 link/script src
            self.assertNotIn("<link", html)
            self.assertNotIn("<script src", html)
            # 数据嵌入 + 文档块渲染 + 批注 chip
            self.assertIn("const REQUIREMENTS =", html)
            self.assertEqual(html.count('class="doc-block'), 3)
            self.assertIn('data-req=', html)              # 批注 chip
            self.assertIn("疑似遗漏", html)
            # 无残留 format 占位符
            import re
            self.assertEqual(re.findall(r"\{[a-z_]+\}", html), [])

    def test_reader_style_is_quiet_and_premium(self) -> None:
        """高级阅读器风格：弱化工具按钮和 emoji，批注以细线/编号锚点呈现。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            html = dae.render_annotation_html(out)
            self.assertIn('class="reader-shell"', html)
            self.assertIn("annotation-rail", html)
            self.assertIn("reader-topbar", html)
            self.assertIn("annotation-card", html)
            self.assertIn("annotation-index", html)
            self.assertNotIn("💬", html)
            self.assertNotIn("📋", html)

    def test_uncovered_paragraph_uses_quiet_inline_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)

            rendered = dae.render_annotation_html(out)

            self.assertIn(
                'An uncovered requirement shall hold.<button class="omission-tag"',
                rendered,
            )
            self.assertIn('>未覆盖</button>', rendered)
            self.assertNotIn('<div class="omission-flag">', rendered)
            self.assertNotIn('⚠ 未覆盖', rendered)
            self.assertIn('.doc-block { margin-bottom: 0; }', rendered)
            self.assertIn('font-family: var(--sans); font-size: 16px; line-height: 1.65;', rendered)

    def test_reader_preserves_paragraph_list_and_note_rhythm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            blocks = [
                {"block_id": "B1", "order": 1, "type": "paragraph",
                 "text": "NOTE This paragraph provides context.", "section_path": ["1 Scope"],
                 "requirement_like": False, "noise": False},
                {"block_id": "B2", "order": 2, "type": "paragraph",
                 "text": "The following locations apply:", "section_path": ["1 Scope"],
                 "requirement_like": False, "noise": False},
                {"block_id": "B3", "order": 3, "type": "paragraph",
                 "text": "\uf8e7 closed locations", "section_path": ["1 Scope"],
                 "requirement_like": False, "noise": False},
                {"block_id": "B4", "order": 4, "type": "paragraph",
                 "text": "- open locations", "section_path": ["1 Scope"],
                 "requirement_like": False, "noise": False},
                {"block_id": "B5", "order": 5, "type": "paragraph",
                 "text": "and in locations with electromagnetic disturbances.",
                 "section_path": ["1 Scope"], "requirement_like": False, "noise": False},
            ]
            (out / "blocks.jsonl").write_text(
                "".join(json.dumps(block) + "\n" for block in blocks), encoding="utf-8")
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")

            rendered = dae.render_annotation_html(out)

            self.assertIn('class="doc-block note short"', rendered)
            self.assertEqual(rendered.count('class="doc-block list-item short"'), 2)
            self.assertIn('.doc-block.list-item + .doc-block:not(.list-item):not(.heading)', rendered)
            self.assertIn('.doc-block.note .text', rendered)
            self.assertIn('.doc-content { width: 100%; max-width: none;', rendered)

    def test_html_escapes_block_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            html = dae.render_annotation_html(out)
            # 块正文里的 < & 必须转义，不破坏标记
            self.assertIn("volume &lt; 5 &amp; log", html)
            self.assertNotIn("volume < 5 & log it.</p>", html)

    def test_annotation_number_is_inline_after_quoted_paragraph_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

            self.assertIn(
                'The meter shall measure volume &lt; 5 &amp; log it.'
                '<button class="chip annotation-index"',
                rendered,
            )
            self.assertIn('data-inline-marker="1"', rendered)
            self.assertNotIn('right: calc(100% + 12px)', rendered)
            self.assertIn('font-size: 12px', rendered)
            self.assertIn('font-weight: 750', rendered)
            self.assertIn('<span class="annotation-owner">软件</span>', rendered)

    def test_annotation_number_is_inline_inside_table_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            quote = "Data that the GdM must collect, record locally and transmit remotely."
            (out / "blocks.jsonl").write_text(
                json.dumps({
                    "block_id": "T1",
                    "order": 1,
                    "type": "table",
                    "text": quote,
                    "section_path": ["4 Requirements"],
                    "requirement_like": True,
                    "noise": False,
                    "doc_region": "body",
                    "table_title": "Table 4",
                    "header_rows": [["Function", "Requirement"]],
                    "data_rows": [["Data collection", quote]],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out / "ai_requirements.jsonl").write_text(
                json.dumps({
                    "ai_req_id": "AI-TABLE",
                    "title": "Data collection",
                    "description": "Collect, store and transmit data.",
                    "module": "Data",
                    "source_section": "4",
                    "source_quote": quote,
                    "source_block_ids": ["T1"],
                    "labels": ["Data"],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            rendered = dae.render_annotation_html(out)

            self.assertIn(
                quote + '<button class="chip annotation-index" data-req="AI-TABLE" data-inline-marker="1"',
                rendered,
            )
            self.assertNotIn(f'<td>{quote}</td>', rendered)

    def test_unanalyzed_hardware_table_text_gets_classification_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            quote = ("a natural or legal person who manufactures a device or has a device designed "
                     "or manufactured, and places it on the market by placing its name or trademark "
                     "on it or puts it into service for the own purposes;")
            (out / "blocks.jsonl").write_text(
                json.dumps({
                    "block_id": "T1",
                    "order": 1,
                    "type": "table",
                    "text": "3.13 | manufacturer\n | " + quote,
                    "section_path": ["3 TERMS AND DEFINITIONS"],
                    "requirement_like": True,
                    "noise": False,
                    "doc_region": "body",
                    "table_title": "Terms",
                    "header_rows": [["3.13", "manufacturer"]],
                    "data_rows": [["", quote]],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")

            rendered = dae.render_annotation_html(out)

            self.assertIn(quote + '<button class="source-classification source-classification-hardware"', rendered)
            self.assertIn('data-source-classification="hardware"', rendered)
            self.assertIn('data-source-text=', rendered)
            self.assertIn('<span class="annotation-number">01</span>', rendered)
            self.assertIn('<span class="annotation-owner">硬件</span>', rendered)
            self.assertIn("function selectSourceClassification", rendered)
            self.assertIn("为什么没有生成研发需求", rendered)

    def test_unanalyzed_hardware_software_definition_gets_co_design_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            quote = ("Set of central hardware and software components intended for the management "
                     "of the functions of remote reading and remote management of measurement groups.")
            (out / "blocks.jsonl").write_text(
                json.dumps({
                    "block_id": "B1",
                    "order": 1,
                    "type": "paragraph",
                    "text": quote,
                    "section_path": ["3 TERMS AND DEFINITIONS", "3.4 (Remote Management) Center"],
                    "requirement_like": False,
                    "noise": False,
                    "doc_region": "body",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")

            rendered = dae.render_annotation_html(out)

            self.assertIn(quote + '<button class="source-classification source-classification-co_design"', rendered)
            self.assertIn('data-source-classification="co_design"', rendered)
            self.assertIn('<span class="annotation-number">01</span>', rendered)
            self.assertIn('<span class="annotation-owner">协同</span>', rendered)

    def test_unanalyzed_mobile_concentrator_definition_gets_hardware_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            title = "Dispositivo walk by"
            quote = ('Device with mobile data concentrator function. It allows the management '
                     'of GdMs in "modalità walk by" o "drive by"')
            (out / "blocks.jsonl").write_text(
                json.dumps({
                    "block_id": "T1",
                    "order": 1,
                    "type": "table",
                    "text": f"3.10 | {title}\n | {quote}",
                    "section_path": ["3 TERMS AND DEFINITIONS"],
                    "requirement_like": True,
                    "noise": False,
                    "doc_region": "body",
                    "table_title": "Terms",
                    "header_rows": [["3.10", title]],
                    "data_rows": [["", quote]],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")

            rendered = dae.render_annotation_html(out)

            self.assertIn(
                html.escape(quote) + '<button class="source-classification source-classification-hardware"',
                rendered,
            )
            self.assertIn('<span class="annotation-owner">硬件</span>', rendered)

    def test_unanalyzed_significant_event_definition_gets_software_term_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            title = "significant event"
            quote = "Event or report in the GdM, which can affect its functioning or alter its data in its contents."
            (out / "blocks.jsonl").write_text(
                json.dumps({
                    "block_id": "T1",
                    "order": 1,
                    "type": "table",
                    "text": f"3.15 | {title}\n | {quote}",
                    "section_path": ["3 TERMS AND DEFINITIONS"],
                    "requirement_like": True,
                    "noise": False,
                    "doc_region": "body",
                    "table_title": "Terms",
                    "header_rows": [["3.15", title]],
                    "data_rows": [["", quote]],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")

            rendered = dae.render_annotation_html(out)

            self.assertIn(
                quote + '<button class="source-classification source-classification-software_term"',
                rendered,
            )
            self.assertIn('data-source-classification="software_term"', rendered)
            self.assertIn('<span class="annotation-owner">术语</span>', rendered)
            self.assertIn("软件概念或事件/状态术语", rendered)

    def test_inline_markers_number_requirements_and_classifications_in_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            req_a = "The GdM shall record measurement data."
            hardware = "The manufacturer shall place its trademark on the device."
            req_b = "The GdM shall transmit data remotely."
            (out / "blocks.jsonl").write_text(
                json.dumps({
                    "block_id": "T1",
                    "order": 1,
                    "type": "table",
                    "text": "\n".join([req_a, hardware, req_b]),
                    "section_path": ["4 Requirements"],
                    "requirement_like": True,
                    "noise": False,
                    "doc_region": "body",
                    "table_title": "Mixed",
                    "header_rows": [["Item", "Text"]],
                    "data_rows": [["A", req_a], ["B", hardware], ["C", req_b]],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out / "ai_requirements.jsonl").write_text(
                json.dumps({
                    "ai_req_id": "AI-A",
                    "title": "Record data",
                    "description": "Record measurement data.",
                    "module": "Data",
                    "source_section": "4",
                    "source_quote": req_a,
                    "source_block_ids": ["T1"],
                }, ensure_ascii=False) + "\n" +
                json.dumps({
                    "ai_req_id": "AI-B",
                    "title": "Transmit data",
                    "description": "Transmit data remotely.",
                    "module": "Communication",
                    "source_section": "4",
                    "source_quote": req_b,
                    "source_block_ids": ["T1"],
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            rendered = dae.render_annotation_html(out)

            positions = [
                rendered.index('<span class="annotation-number">01</span><span class="annotation-owner">软件</span>'),
                rendered.index('<span class="annotation-number">02</span><span class="annotation-owner">硬件</span>'),
                rendered.index('<span class="annotation-number">03</span><span class="annotation-owner">软件</span>'),
            ]
            self.assertEqual(positions, sorted(positions))

    def test_exact_source_anchor_places_marker_on_quoted_block_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            blocks = [
                {"block_id": "B1", "order": 1, "type": "heading", "text": "3.24 billing period",
                 "section_path": ["3.24 billing period"], "requirement_like": False, "noise": False},
                {"block_id": "B2", "order": 2, "type": "paragraph", "text": "Unrelated definition.",
                 "section_path": ["3.24 billing period"], "requirement_like": False, "noise": False},
                {"block_id": "B3", "order": 3, "type": "paragraph",
                 "text": "The billing period can be valid for 1, 2, 3, 4, 6, 12 months.",
                 "section_path": ["3.24 billing period"], "requirement_like": True, "noise": False},
            ]
            (out / "blocks.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in blocks), encoding="utf-8")
            (out / "ai_requirements.jsonl").write_text(json.dumps({
                "ai_req_id": "AI-BILLING", "title": "结算周期", "description": "周期可配置。",
                "source_quote": blocks[2]["text"], "source_section": "3.24",
                "source_block_ids": ["B3"], "anchor_block_id": "B3", "module": "结算",
            }, ensure_ascii=False) + "\n", encoding="utf-8")

            rendered = dae.render_annotation_html(out)

        b2_start = rendered.index('data-block-id="B2"')
        b3_start = rendered.index('data-block-id="B3"')
        b3_end = rendered.find('</div></div>', b3_start)
        self.assertNotIn('data-req="AI-BILLING"', rendered[b2_start:b3_start])
        self.assertIn('data-req="AI-BILLING"', rendered[b3_start:b3_end if b3_end >= 0 else None])

    def test_omission_flag_for_uncovered_requirement_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            html = dae.render_annotation_html(out)
            # B3 是 requirement_like 且未覆盖 → 含「未覆盖」；B2 被覆盖、B1 是标题
            self.assertIn("未覆盖", html)

    def test_export_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            path = dae.export_annotation_html(out)
            self.assertEqual(path.name, "document_annotation.html")
            self.assertTrue(path.exists())
            self.assertIn("const REQUIREMENTS =", path.read_text(encoding="utf-8"))

    def test_leader_dots_cleaned_in_toc(self) -> None:
        """目录点连线 + 页码在渲染层清洁：Foreword .... 3 → Foreword。"""
        cleaned = dae._clean_block_text("Foreword .................................. 3")
        self.assertEqual(cleaned, "Foreword")
        # 非目录正文不受影响
        self.assertIn("measure", dae._clean_block_text("The meter shall measure volume."))

    def test_symbol_only_lines_filtered(self) -> None:
        """纯框线乱码行（PDF 表格边框误读）在渲染时跳过。"""
        self.assertTrue(dae._is_symbol_only("--`,``,```,`,,```,,,-`-`,,`,,`,`,,`---"))
        self.assertTrue(dae._is_symbol_only(".........."))
        self.assertFalse(dae._is_symbol_only("The meter shall measure volume."))
        self.assertFalse(dae._is_symbol_only("Gas meter 7-0:1.8.0.255"))

    def test_non_body_regions_collapsed(self) -> None:
        """前言/目录区的 blocks 折叠进 <details>，正文不折叠。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "F1", "order": 1, "type": "paragraph", "text": "Foreword text here.",
                            "section_path": [], "requirement_like": False, "noise": False,
                            "doc_region": "front_matter"}) + "\n" +
                json.dumps({"block_id": "F2", "order": 2, "type": "paragraph", "text": "TOC line .... 5",
                            "section_path": [], "requirement_like": False, "noise": False,
                            "doc_region": "table_of_contents"}) + "\n" +
                json.dumps({"block_id": "B1", "order": 3, "type": "heading", "text": "4 Requirements",
                            "section_path": ["4 Requirements"], "requirement_like": False, "noise": False,
                            "doc_region": "body"}) + "\n" +
                json.dumps({"block_id": "B2", "order": 4, "type": "paragraph", "text": "Body content.",
                            "section_path": ["4 Requirements"], "requirement_like": False, "noise": False,
                            "doc_region": "body"}) + "\n",
                encoding="utf-8")
            (out / "merged_spec_requirements.json").write_text(
                json.dumps({"requirements": []}), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            # 前言/目录折叠
            self.assertIn("region-collapse", rendered)
            self.assertIn("前言", rendered)
            # leader-dots 清洁
            self.assertIn("TOC line", rendered)
            self.assertNotIn(".... 5", rendered)
            # 正文不折叠、正常渲染
            self.assertIn("Body content.", rendered)

    def test_noise_blocks_hidden(self) -> None:
        """noise 块（页眉/页脚/水印）不渲染——排版保真（2026-07-07 UNI 12007：292 条
        页眉页脚穿插正文）。数据仍保留在 blocks.jsonl，仅视图不显示。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "N1", "order": 1, "type": "paragraph", "text": "EN 16314:2013 (E)",
                            "section_path": [], "requirement_like": False, "noise": True,
                            "doc_region": "body"}) + "\n" +
                json.dumps({"block_id": "B1", "order": 2, "type": "paragraph", "text": "Real content.",
                            "section_path": [], "requirement_like": False, "noise": False,
                            "doc_region": "body"}) + "\n",
                encoding="utf-8")
            (out / "merged_spec_requirements.json").write_text(
                json.dumps({"requirements": []}), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            self.assertNotIn("EN 16314:2013 (E)", rendered)   # 噪声不渲染
            self.assertIn("Real content.", rendered)           # 正文照常

    def test_heading_levels_rendered(self) -> None:
        """heading 按 section_path 深度渲染 h1/h2/h3 class。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "H1", "order": 1, "type": "heading", "text": "4 Scope",
                            "section_path": ["4 Scope"], "requirement_like": False, "noise": False,
                            "doc_region": "body"}) + "\n" +
                json.dumps({"block_id": "H2", "order": 2, "type": "heading", "text": "4.1 General",
                            "section_path": ["4 Scope", "4.1 General"], "requirement_like": False, "noise": False,
                            "doc_region": "body"}) + "\n",
                encoding="utf-8")
            (out / "merged_spec_requirements.json").write_text(
                json.dumps({"requirements": []}), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            self.assertIn("doc-block heading h1", rendered)
            self.assertIn("doc-block heading h2", rendered)

    def test_annotation_html_includes_ownership_review_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

            self.assertIn("function ownershipOf", rendered)
            self.assertIn('id="own-sel"', rendered)
            self.assertIn("ownership_override", rendered)

    def test_annotation_html_ownership_override_has_auto_no_override_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

            self.assertIn('["", "自动/不覆盖"]', rendered)
            self.assertIn("function baseOwnership", rendered)
            self.assertIn("function currentOwnershipOverride", rendered)
            self.assertIn("function ownershipOverrideForSave", rendered)
            self.assertNotIn('|| "software"', rendered)
            self.assertNotIn("|| 'software'", rendered)
            self.assertIn('if (!selected) return "";', rendered)
            self.assertIn("if (current && selected === current) return current;", rendered)
            self.assertIn('return selected !== base ? selected : "";', rendered)
            self.assertIn("const ownershipOverride = ownershipOverrideForSave(id);", rendered)
            self.assertIn("ownership_override: ownershipOverride", rendered)

    def test_hardware_detail_hides_full_guidance_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

            self.assertIn("function isHardwareRequirement", rendered)
            self.assertIn("const isHardware = isHardwareRequirement(r);", rendered)
            self.assertIn("const dev = isHardware ? \"\" :", rendered)
            self.assertIn("const acc = isHardware ? \"\" :", rendered)
            self.assertIn("hardwareTranslationHtml(r)", rendered)
            self.assertIn("ownershipReasonHtml(r)", rendered)



class FunctionalSynthesisAnnotationTests(unittest.TestCase):
    def test_detail_panel_renders_function_membership_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            source_id = dae.build_ai_requirements(out)[0]["ai_req_id"]
            (out / "functional_requirements.json").write_text(json.dumps({"items": [{
                "functional_requirement_id": "FREQ-1",
                "title": "体积计量管理",
                "objective": "实现体积计量管理。",
                "behaviors": ["应计量体积"],
                "variants": [{"name": "常规", "behavior": "按正常周期计量"}],
                "conflict_flags": ["参数待确认"],
                "source_ai_requirement_ids": [source_id],
            }]}, ensure_ascii=False), encoding="utf-8")

            rendered = dae.render_annotation_html(out)

        self.assertIn("所属研发功能", rendered)
        self.assertIn("functional_title", rendered)
        self.assertIn("functional_objective", rendered)
        self.assertIn("functional_variants", rendered)
        self.assertIn("functional_conflict_flags", rendered)
if __name__ == "__main__":
    unittest.main()


class OutlineMapTests(unittest.TestCase):
    """左栏=文件目录（2026-07-10 真实反馈）：印刷目录为权威源,回链正文;无目录回退标题。"""

    def test_printed_toc_preferred_and_backlinked(self) -> None:
        blocks = [
            {"block_id": "T1", "type": "paragraph", "text": "1 Scope .......... 5", "noise": False},
            {"block_id": "T2", "type": "paragraph", "text": "2 References .......... 6", "noise": False},
            {"block_id": "T3", "type": "paragraph", "text": "2.1 Normative .......... 6", "noise": False},
            {"block_id": "T4", "type": "paragraph", "text": "3 Terms .......... 7", "noise": False},
            {"block_id": "T5", "type": "paragraph", "text": "4 System .......... 9", "noise": False},
            {"block_id": "H1", "type": "heading", "text": "1 Scope", "noise": False},
            {"block_id": "H2", "type": "heading", "text": "2 References", "noise": False},
            {"block_id": "H21", "type": "heading", "text": "2.1 Normative", "noise": False},
            # 事件表行(编号递增的假章)不得进目录
            {"block_id": "E1", "type": "heading", "text": "3 Battery emergency 5.12", "noise": False},
        ]
        omap = dae._build_outline_map(blocks)
        self.assertEqual(omap.get("H1"), 1)
        self.assertEqual(omap.get("H2"), 1)
        self.assertEqual(omap.get("H21"), 2)
        self.assertNotIn("E1", omap)     # 表行与目录条目 "3 Terms" 前缀不符
        self.assertNotIn("T1", omap)     # 目录条目本身不做导航目标

    def test_fallback_headings_when_no_printed_toc(self) -> None:
        blocks = [
            {"block_id": "H1", "type": "heading", "text": "1 Scope", "noise": False,
             "section_path": ["1 Scope"]},
            {"block_id": "H2", "type": "heading", "text": "2 References", "noise": False,
             "section_path": ["2 References"]},
        ]
        omap = dae._build_outline_map(blocks)
        self.assertEqual(set(omap), {"H1", "H2"})


def _seed_marker_block(out: Path, quote: str) -> None:
    (out / "blocks.jsonl").write_text(
        json.dumps({"block_id": "B1", "order": 1, "type": "paragraph", "text": quote,
                    "section_path": ["3 TERMS"], "requirement_like": False, "noise": False,
                    "doc_region": "body"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")


class MarkerTranslationTests(unittest.TestCase):
    """块级"说明"标记三段式（归类原因/原文翻译/原文引用）与翻译通路护栏。"""

    QUOTE = "The manufacturer shall place its trademark on the device."

    def test_detail_card_has_three_sections_with_translation_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            rendered = dae.render_annotation_html(out)
            # 卡片脚本包含三段：原因标题 / 原文翻译 / 原文引用（无译文时给可读空态）
            self.assertIn("为什么没有生成研发需求", rendered)
            self.assertIn("原文翻译", rendered)
            self.assertIn("原文引用", rendered)
            self.assertIn("未生成翻译", rendered)
            self.assertIn('data-source-translation=""', rendered)

    def test_marker_embeds_translation_from_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {key: {"owner": "hardware", "translation": "制造商应在设备上标注其商标。"}},
            }, ensure_ascii=False), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            self.assertIn('data-source-translation="制造商应在设备上标注其商标。"', rendered)

    def test_rejected_sidecar_entry_is_not_embedded_but_note_shows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {key: {"owner": "hardware", "translation": "",
                                              "rejected": True, "reason": "翻译含无据编码/数字"}},
            }, ensure_ascii=False), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            # 拒绝要如实呈现：译文不嵌入,但拒绝原因随标记进卡片（检查单 #3 标记随行）
            self.assertIn('data-source-translation=""', rendered)
            self.assertIn('data-source-translation-note="翻译含无据编码/数字"', rendered)
            self.assertIn("翻译未通过防幻觉校验", rendered)

    def test_quote_fragment_yellow_highlight_machinery_present(self) -> None:
        """选中批注：引用片段精确黄标（sc-quote,只盖 source_quote 本体）、上下文整块保持蓝底。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            rendered = dae.render_annotation_html(out)
            self.assertIn("mark.sc-quote", rendered)              # 黄标样式（p 与 td 通用）
            self.assertIn("function clearSourceQuoteMarks", rendered)
            self.assertIn("function markQuoteTextNodes", rendered)   # 需求角标选中→引用片段黄标
            self.assertIn("markQuoteTextNodes(marker.parentElement, r.source_quote)", rendered)
            self.assertIn('classList.add("in-span", "evidence")', rendered)   # 蓝底保留

    def test_digit_grouping_in_source_is_not_fabrication(self) -> None:
        """欧标千位分隔："4 000 cycles" 忠实翻译写 "4000" 是格式归一,不得拒绝（test16 实测误伤）。"""

        def chat(system: str, user: str) -> dict:
            return {"items": [{"id": 1, "translation": "阀门应运行 4000 次循环。"}]}

        quote = "The valve shall operate for 4 000 cycles."
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, quote)
            summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
            self.assertEqual(summary["translated"], 1)
            self.assertEqual(summary["rejected"], 0)

    def test_generate_translations_writes_cache_and_reuses(self) -> None:
        calls: list[str] = []

        def chat(system: str, user: str) -> dict:
            calls.append(user)
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
            self.assertEqual(summary["translated"], 1)
            self.assertEqual(summary["route"], "openai_compatible")
            self.assertEqual(len(calls), 1)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            key = dae._translation_key(self.QUOTE)
            self.assertEqual(sidecar["items"][key]["translation"], "制造商应在设备上标注其商标。")
            # 第二次：全部命中缓存，零调用
            summary2 = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
            self.assertEqual(summary2["cached"], 1)
            self.assertEqual(summary2["translated"], 0)
            self.assertEqual(len(calls), 1)
            # 导出嵌入译文
            path, _ = dae.export_annotation_bundle(out, route=None)
            self.assertIn('data-source-translation="制造商应在设备上标注其商标。"',
                          path.read_text(encoding="utf-8"))

    def test_generate_translations_rejects_fabricated_code_and_int(self) -> None:
        """编向：忠实翻译不会引入源文没有的编码/数字——出现即拒绝并留账不嵌入。"""

        def chat(system: str, user: str) -> dict:
            return {"items": [{"id": 1, "translation": "制造商应在 30 秒内标注对象 0-0:96.1.0.255。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
            self.assertEqual(summary["rejected"], 1)
            self.assertEqual(summary["translated"], 0)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(self.QUOTE)]
            self.assertTrue(entry["rejected"])
            self.assertIn("无据编码/数字", entry["reason"])
            rendered = dae.render_annotation_html(out)
            self.assertIn('data-source-translation=""', rendered)

    def test_first_export_embeds_all_rejected_notes(self) -> None:
        def chat(_system: str, _user: str) -> dict:
            return {
                "items": [{
                    "id": 1,
                    "translation": "制造商应在 30 秒内标注对象 0-0:96.1.0.255。",
                }]
            }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            with patch(
                "functional_synthesis._resolve_catalog_chat",
                return_value=(chat, "llm:test-model"),
            ):
                path, summary = dae.export_annotation_bundle(out, route="openai_compatible")

            rendered = path.read_text(encoding="utf-8")

        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(summary["translated"], 0)
        self.assertIn('data-source-translation-note="翻译含无据编码/数字', rendered)

    def test_generate_translations_missing_item_stays_pending(self) -> None:
        """漏向：LLM 漏答的条目不落账，下次导出自动重试。"""

        def chat(system: str, user: str) -> dict:
            return {"items": []}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
            self.assertEqual(summary["unresolved"], 1)
            self.assertFalse((out / dae.ANNOTATION_TRANSLATIONS).exists())

    def test_generate_translations_degrades_honestly_without_llm(self) -> None:
        import os as _os
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            saved = _os.environ.pop("RATOMIZER_LLM_API_KEY", None)
            try:
                summary = dae.generate_annotation_translations(out, route="openai_compatible")
            finally:
                if saved is not None:
                    _os.environ["RATOMIZER_LLM_API_KEY"] = saved
            self.assertEqual(summary["route"], "stub")
            self.assertEqual(summary["unresolved"], 1)
            self.assertFalse((out / dae.ANNOTATION_TRANSLATIONS).exists())

    def test_omission_tag_is_clickable_three_part_card(self) -> None:
        """未覆盖段与说明标记同待遇：可点击按钮 + 三段式卡片（原因/翻译/引用）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)   # B3 requirement_like 且未覆盖
            quote = "An uncovered requirement shall hold."
            key = dae._translation_key(quote)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {key: {"owner": "omission",
                                              "translation": "一条未被覆盖的需求应当成立。"}},
            }, ensure_ascii=False), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            self.assertIn('<button class="omission-tag"', rendered)
            self.assertIn(f'data-omission-text="{quote}"', rendered)
            self.assertIn('data-omission-translation="一条未被覆盖的需求应当成立。"', rendered)
            self.assertIn("为什么标为未覆盖", rendered)
            self.assertIn("没有任何已抽取需求的来源范围覆盖它", rendered)
            self.assertIn("function selectOmission", rendered)

    def test_omission_text_enters_translation_collection(self) -> None:
        """未覆盖段文本进翻译收集（owner=omission），LLM 导出时自动补齐。"""

        def chat(system: str, user: str) -> dict:
            payload = json.loads(user.split("原文条目 JSON:")[-1])
            names = "甲乙丙丁戊己庚辛"
            return {"items": [{"id": e["id"], "translation": f"中文译文{names[e['id'] - 1]}"} for e in payload]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
            self.assertGreaterEqual(summary["translated"], 1)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            key = dae._translation_key("An uncovered requirement shall hold.")
            self.assertEqual(sidecar["items"][key]["owner"], "omission")
            # 有批注的块(B2)也进收集——硬件卡块级翻译回退的料(test18)
            covered_key = dae._translation_key("The meter shall measure volume < 5 & log it.")
            self.assertEqual(sidecar["items"][covered_key]["owner"], "covered")

    def test_api_blocks_carry_translation(self) -> None:
        """应用内视图同语义：build_document_blocks 按内容哈希附带块级译文。"""
        from api_server import build_document_blocks
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            quote = "An uncovered requirement shall hold."
            key = dae._translation_key(quote)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {
                    key: {"owner": "omission", "translation": "一条未被覆盖的需求应当成立。"},
                    dae._translation_key("其它"): {"owner": "omission", "translation": "",
                                                   "rejected": True, "reason": "含无据数字"},
                }}, ensure_ascii=False), encoding="utf-8")
            doc = build_document_blocks(out)
            by_id = {b["block_id"]: b for b in doc["blocks"]}
            self.assertEqual(by_id["B3"].get("translation"), "一条未被覆盖的需求应当成立。")
            self.assertNotIn("translation", by_id["B2"])   # 无译文的块不带字段

    def test_context_paragraph_collected_and_card_present(self) -> None:
        """全文每段都有分析结果：背景段进翻译收集（owner=context）、可点击出说明卡。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            plain = "This document was drafted under Mandate M/441 as background."
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B1", "order": 1, "type": "paragraph", "text": plain,
                            "section_path": ["Introduction"], "requirement_like": False,
                            "noise": False, "doc_region": "introduction"}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")
            key = dae._translation_key(plain)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {key: {"owner": "context",
                                              "translation": "本文件系依据 M/441 号授权起草的背景说明。"}},
            }, ensure_ascii=False), encoding="utf-8")
            rendered = dae.render_annotation_html(out)
            self.assertIn('data-translation="本文件系依据 M/441 号授权起草的背景说明。"', rendered)
            self.assertIn("function selectContextBlock", rendered)
            self.assertIn("被判定为背景/说明性内容", rendered)
            self.assertIn(("context", plain), dae._collected_marker_texts.values())

    def test_front_matter_context_not_collected(self) -> None:
        """封面/目录区背景段不进翻译收集（折叠区,翻译无消费场景纯烧调用）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            cover = "EUROPEAN STANDARD EN 16314 July 2013 English Version"
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B1", "order": 1, "type": "paragraph", "text": cover,
                            "section_path": [], "requirement_like": False,
                            "noise": False, "doc_region": "front_matter"}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")
            dae.render_annotation_html(out)
            self.assertNotIn(("context", cover), dae._collected_marker_texts.values())

    def test_export_task_reports_translation_route(self) -> None:
        import desktop_tasks
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            payload = desktop_tasks.export_annotation_html_task(out)
            self.assertEqual(payload["route"], "stub")
            self.assertIn("translations", payload)
            self.assertTrue(Path(payload["path"]).exists())


class TranslationKeyParityTests(unittest.TestCase):
    """0714 评审跟进:API 读键与导出写键同源(写侧=渲染清洗后文本的哈希)。"""

    def test_api_finds_translation_keyed_on_cleaned_text(self) -> None:
        from api_server import build_document_blocks, translation_key
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            raw = "Battery lifetime totaliser ................................ 24"
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B1", "order": 1, "type": "paragraph", "text": raw,
                "section_path": [], "requirement_like": False, "noise": False,
                "doc_region": "body"}, ensure_ascii=False) + "\n", encoding="utf-8")
            cleaned_key = translation_key(dae._clean_block_text(raw))
            self.assertNotEqual(cleaned_key, translation_key(raw))   # 前提:两键确实不同
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {cleaned_key: {"owner": "context",
                                                      "translation": "电池寿命累计器"}},
            }, ensure_ascii=False), encoding="utf-8")
            doc = build_document_blocks(out)
            self.assertEqual(doc["blocks"][0].get("translation"), "电池寿命累计器")

    def test_api_raw_key_still_wins_for_legacy_sidecar(self) -> None:
        from api_server import build_document_blocks, translation_key
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            raw = "The meter shall log events."
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B1", "order": 1, "type": "paragraph", "text": raw,
                "section_path": [], "requirement_like": False, "noise": False,
                "doc_region": "body"}, ensure_ascii=False) + "\n", encoding="utf-8")
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1, "items": {translation_key(raw): {"owner": "context",
                                                               "translation": "电表应记录事件。"}},
            }, ensure_ascii=False), encoding="utf-8")
            doc = build_document_blocks(out)
            self.assertEqual(doc["blocks"][0].get("translation"), "电表应记录事件。")


class PdfOriginalShareNoteTests(unittest.TestCase):
    """0714 评审跟进:原版影印 bundle 含完整客户 PDF——任务提示随载荷可见。"""

    def test_pdf_original_result_carries_share_warning(self) -> None:
        import desktop_tasks
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake = {"route": "stub", "layout_mode_requested": "pdf_original",
                    "layout_mode": "pdf_original", "source_pdf": str(out / "document_source.pdf"),
                    "annotation_overlay": True, "page_files": []}
            with mock.patch("doc_annotation_export.export_annotation_bundle",
                            return_value=(out / "document_annotation.html", fake)):
                payload = desktop_tasks.export_annotation_html_task(out, layout_mode="pdf_original")
            self.assertIn("对外分享前请确认", str(payload.get("note")))

    def test_optimized_result_has_no_share_warning(self) -> None:
        import desktop_tasks
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake = {"route": "stub", "layout_mode_requested": "optimized",
                    "layout_mode": "optimized", "page_files": []}
            with mock.patch("doc_annotation_export.export_annotation_bundle",
                            return_value=(out / "document_annotation.html", fake)):
                payload = desktop_tasks.export_annotation_html_task(out)
            self.assertNotIn("对外分享", str(payload.get("note") or ""))


class PdfAnnotationPayloadTests(unittest.TestCase):
    """0714:应用内原版影印数据与分享 HTML 同源(几何/换算共用实现)。"""

    def _seed(self, out: Path, *, with_pages: bool = True) -> None:
        import shutil
        fixture = Path(__file__).parent / "fixtures" / "sample_text_tables.pdf"
        shutil.copy2(fixture, out / "doc.pdf")
        (out / "manifest.json").write_text(json.dumps({"input": "doc.pdf"}), encoding="utf-8")
        region = {"page_number": 1, "bbox": [50.0, 100.0, 400.0, 130.0],
                  "page_width": 595.0, "page_height": 842.0}
        blocks = [
            {"block_id": "B1", "order": 1, "type": "paragraph",
             "text": "The meter shall measure volume.", "section_path": ["4"],
             "requirement_like": True, "noise": False, "page_number": 1, "pdf_regions": [region]},
            {"block_id": "B2", "order": 2, "type": "paragraph",
             "text": "An uncovered requirement shall hold.", "section_path": ["4"],
             "requirement_like": True, "noise": False, "page_number": 1,
             "pdf_regions": [{**region, "bbox": [50.0, 200.0, 400.0, 230.0]}]},
        ]
        (out / "blocks.jsonl").write_text(
            "\n".join(json.dumps(b, ensure_ascii=False) for b in blocks) + "\n", encoding="utf-8")
        (out / "ai_requirements.jsonl").write_text(json.dumps({
            "ai_req_id": "AIR-1", "title": "计量", "description": "d", "module": "计量",
            "source_quote": "The meter shall measure volume.",
            "source_block_ids": ["B1"], "anchor_block_id": "B1"}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        if with_pages:
            pages_dir = out / dae.ANNOTATION_PAGES_DIR
            pages_dir.mkdir()
            (pages_dir / "page-0001.png").write_bytes(b"\x89PNG-fake")
            (pages_dir / dae.ANNOTATION_PAGES_MANIFEST).write_text(json.dumps({
                "version": 1, "source_sha256": "x", "dpi": 144,
                "pages": [{"page_number": 1, "file": "page-0001.png",
                           "width": 595.0, "height": 842.0}]}), encoding="utf-8")

    def test_payload_available_with_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            payload = dae.build_pdf_annotation_payload(out)
            self.assertTrue(payload["available"])
            self.assertEqual(payload["pages"][0]["file"], "page-0001.png")
            req_marker = payload["requirement_markers"][0]
            self.assertEqual(req_marker["req_id"], "AIR-1")
            self.assertEqual(req_marker["page"], 1)
            for key in ("left", "top", "width", "height"):
                self.assertIn(key, req_marker["rect"])
            self.assertEqual(payload["omission_markers"][0]["block_id"], "B2")

    def test_payload_unavailable_without_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out, with_pages=False)
            payload = dae.build_pdf_annotation_payload(out)
            self.assertFalse(payload["available"])
            self.assertIn("导出批注HTML", payload["reason"])
