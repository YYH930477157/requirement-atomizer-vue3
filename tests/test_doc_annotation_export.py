"""自包含文档批注 HTML 导出回归。"""
from __future__ import annotations

import html
import json
import tempfile
import unittest
from pathlib import Path

import doc_annotation_export as dae


def _seed(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        json.dumps({"block_id": "B1", "order": 1, "type": "heading", "text": "4 Requirements",
                    "section_path": ["4 Requirements"], "requirement_like": False, "noise": False}) + "\n" +
        json.dumps({"block_id": "B2", "order": 2, "type": "paragraph",
                    "text": "The meter shall measure volume < 5 & log it.",
                    "section_path": ["4 Requirements"], "requirement_like": True, "noise": False}) + "\n" +
        json.dumps({"block_id": "B3", "order": 3, "type": "paragraph",
                    "text": "An uncovered requirement shall hold.",
                    "section_path": ["4 Requirements"], "requirement_like": True, "noise": False}) + "\n",
        encoding="utf-8")
    doc = {"requirements": [
        {"id": "REQ-001", "title": "体积计量", "description": "应计量体积", "module": "计量",
         "source_section": "4", "source_quote": "The meter shall measure volume < 5 & log it.",
         "source_block_ids": ["B2"], "acceptance_criteria": ["按 4.2 测试"], "labels": ["计量"]},
    ]}
    (out / "merged_spec_requirements.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class DocAnnotationExportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
