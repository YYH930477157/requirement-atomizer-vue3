"""自包含文档批注 HTML 导出回归。"""
from __future__ import annotations

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

    def test_noise_blocks_greyed(self) -> None:
        """noise 块渲染时带 noise class（灰显），不删除。"""
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
            self.assertIn("doc-block noise", rendered)

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


if __name__ == "__main__":
    unittest.main()
