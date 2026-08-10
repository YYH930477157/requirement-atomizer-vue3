"""自包含文档批注 HTML 导出回归。"""
from __future__ import annotations
import html
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import doc_annotation_export as dae
import ai_extract
import claim_artifacts
import claim_catalog
import claim_ledger
import claim_review_actions
from parsers.pdf_parser import extract_pdf
from result_package import (
    commit_analysis_completion,
    initialize_result_package,
    package_artifact_path,
    resolve_analysis_root,
)
from tests.test_claim_artifacts import _catalog, _publish
from tests.test_claim_catalog import _block


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
    @staticmethod
    def _claims_from_html(rendered: str) -> list[dict]:
        match = re.search(r"const CLAIMS = (\[.*?\]);\n", rendered)
        if not match:
            raise AssertionError("claim annotation payload is missing")
        return json.loads(match.group(1))

    def test_claim_status_set_is_identical_in_optimized_and_pdf_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = _catalog()
            text = catalog["catalog"][0]["text"]
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B1", "order": 1, "type": "paragraph", "text": text,
                "section_path": ["4 Functions"], "noise": False,
                "requirement_like": True, "page_number": 1,
            }) + "\n", encoding="utf-8")
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(out, actor_trigger="annotation-v13-test")
            region = {"page_number": 1, "bbox": [50, 100, 550, 130],
                      "page_width": 600, "page_height": 800}
            optimized = dae.render_annotation_html(out, layout_mode="optimized")
            original = dae.render_annotation_html(
                out,
                layout_mode="pdf_original",
                pdf_href=dae.ANNOTATION_SOURCE_PDF,
                pdf_pages=[{"page_number": 1, "href": "page.png", "width": 600, "height": 800}],
                pdf_geometry={"B1": [region]},
            )

        optimized_claims = self._claims_from_html(optimized)
        original_claims = self._claims_from_html(original)
        status_set = lambda rows: {(row["claim_id"], row["resolution"]) for row in rows}
        self.assertEqual(status_set(optimized_claims), status_set(original_claims))
        self.assertIn('<span class="claim-span-zone claim-covered"', optimized)
        self.assertIn('class="claim-zone claim-zone-pdf claim-covered"', original)
        self.assertIn('data-claim-start="0"', original)

    def test_stale_claim_focus_is_audited_without_source_zone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = _catalog()
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(out, actor_trigger="annotation-v13-stale")
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B1", "order": 1, "type": "paragraph",
                "text": "The source changed after catalog publication.",
                "section_path": ["4 Functions"], "noise": False,
            }) + "\n", encoding="utf-8")

            rendered = dae.render_annotation_html(out, layout_mode="optimized")
            original = dae.render_annotation_html(
                out, layout_mode="pdf_original",
                pdf_href=dae.ANNOTATION_SOURCE_PDF,
                pdf_pages=[{"page_number": 1, "href": "page.png",
                            "width": 600, "height": 800}],
                pdf_geometry={"B1": [{"page_number": 1,
                                       "bbox": [50, 100, 550, 130],
                                       "page_width": 600, "page_height": 800}]},
            )

        claims = self._claims_from_html(rendered)
        self.assertFalse(claims[0]["mapped"])
        self.assertIn("no longer matches", claims[0]["mapping_error"])
        self.assertNotIn('<span class="claim-span-zone ', rendered)
        self.assertNotIn('class="claim-zone claim-zone-pdf ', original)

    def test_claim_span_remaps_to_one_exact_match_in_rendered_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = _catalog()
            claim_text = catalog["catalog"][0]["text"]
            claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [{
                "block_id": "B1", "order": 1, "type": "paragraph",
                "text": claim_text, "section_path": ["4 Functions"],
                "noise": False, "requirement_like": True,
            }])
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(
                out, actor_trigger="annotation-v13-remap"
            )

            state = dae._claim_annotation_state(out, [{
                "block_id": "B1", "text": f"Normalized prefix: {claim_text}",
            }])

        record = state["records"][0]
        self.assertTrue(record["mapped"])
        self.assertEqual(record["start"], len("Normalized prefix: "))
        self.assertEqual(record["end"], len("Normalized prefix: ") + len(claim_text))
        self.assertEqual(state["spans_by_block"]["B1"], [record])
        zones = dae._claim_pdf_zones(
            state["records"],
            {"B1": [{"page_number": 1, "bbox": [0, 0, 10, 10],
                     "page_width": 100, "page_height": 100}]},
            {},
        )
        self.assertEqual((zones[0]["start"], zones[0]["end"]), (0, len(claim_text)))

    def test_ambiguous_rendered_claim_text_emits_no_text_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            catalog = _catalog()
            claim_text = catalog["catalog"][0]["text"]
            claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [{
                "block_id": "B1", "order": 1, "type": "paragraph",
                "text": claim_text, "section_path": ["4 Functions"],
                "noise": False, "requirement_like": True,
            }])
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(
                out, actor_trigger="annotation-v13-ambiguous"
            )

            state = dae._claim_annotation_state(out, [{
                "block_id": "B1", "text": f"x {claim_text} / {claim_text}",
            }])

        record = state["records"][0]
        self.assertTrue(record["mapped"])
        self.assertNotIn("start", record)
        self.assertNotIn("B1", state["spans_by_block"])
        self.assertIn("no unique exact match", record["render_mapping_error"])

    def test_claim_span_uses_document_view_normalization(self) -> None:
        raw = 'The  product shall support “status”\nindication…'
        for block_type in ("paragraph", "list_item"):
            with self.subTest(block_type=block_type), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                block = _block("B1", raw, block_type=block_type)
                catalog = claim_catalog.build_claim_catalog([block], [])
                claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [block])
                _publish(out, catalog)
                claim_review_actions.fold_effective_ledger(
                    out, actor_trigger=f"annotation-v13-normalized-{block_type}"
                )

                rendered = dae.render_annotation_html(out, layout_mode="optimized")

                record = self._claims_from_html(rendered)[0]
                expected = dae.normalize_text(record["text"])
                self.assertEqual(record["rendered_text"], expected)
                self.assertEqual((record["start"], record["end"]), (0, len(expected)))
                self.assertIn('<span class="claim-span-zone ', rendered)

    def test_existing_invalid_claim_snapshot_is_not_reported_as_empty(self) -> None:
        scenarios = ("legacy", "recovery_pending", "corrupt")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                catalog = _catalog()
                claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [{
                    "block_id": "B1", "order": 1, "type": "paragraph",
                    "text": catalog["catalog"][0]["text"],
                    "section_path": ["4 Functions"], "noise": False,
                }])
                _publish(out, catalog)
                if scenario != "legacy":
                    claim_review_actions.fold_effective_ledger(
                        out, actor_trigger=f"annotation-v13-{scenario}"
                    )
                if scenario == "recovery_pending":
                    (out / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).write_text(
                        '{"unfinished":true}', encoding="utf-8"
                    )
                elif scenario == "corrupt":
                    with (out / claim_artifacts.CLAIM_CATALOG).open("ab") as handle:
                        handle.write(b"\n")

                with self.assertRaisesRegex(
                    dae.ClaimAnnotationUnavailable,
                    "claim annotation snapshot unavailable",
                ):
                    dae._claim_annotation_state(out, [])

    def test_overlapping_pdf_claim_zones_get_distinct_marker_lanes(self) -> None:
        region = {"page_number": 1, "bbox": [50, 100, 550, 130],
                  "page_width": 600, "page_height": 800}
        records = [
            {"claim_id": claim_id, "claim_hash": f"sha256:{claim_id}",
             "block_id": "B1", "resolution": "uncertain", "mapped": True,
             "focus": {"kind": "text_span", "start": index * 5,
                       "end": index * 5 + 4}}
            for index, claim_id in enumerate(("CLM-A", "CLM-B"))
        ]

        zones = dae._claim_pdf_zones(records, {"B1": [region]}, {})

        self.assertEqual(len(zones), 2)
        self.assertNotEqual(zones[0]["rect"], zones[1]["rect"])
        self.assertEqual({zone["marker_lanes"] for zone in zones}, {2})
        first, second = sorted(zones, key=lambda zone: zone["marker_lane"])
        self.assertLessEqual(
            first["rect"]["left"] + first["rect"]["width"],
            second["rect"]["left"],
        )

    @staticmethod
    def _current_table(matrix: list[list[str]]) -> tuple[dict, list[dict], list[dict]]:
        """当前版本（table-structure-v2+）表格块——迁移门只认此结构。"""
        from atomize import build_table_artifacts
        from requirement_kb import KnowledgeRepository

        return build_table_artifacts(
            matrix,
            table_id="TBL-000001",
            block_id="TB1",
            order=1,
            table_title="",
            section_path=["4 Functions"],
            knowledge_bases=KnowledgeRepository.from_paths([]),
        )

    def test_table_claim_uses_data_row_card_and_pdf_row_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            table, items, cells = self._current_table([["Name", "Value"], ["A", "10 V"]])
            catalog = claim_catalog.build_claim_catalog(
                [table], items, table_cell_items=cells
            )
            claim_id = catalog["catalog"][0]["claim_id"]
            claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [table])
            claim_artifacts.atomic_write_jsonl(out / "table_items.jsonl", items)
            claim_artifacts.atomic_write_jsonl(out / "table_cell_items.jsonl", cells)
            claim_artifacts.atomic_write_jsonl(out / "ai_requirements.jsonl", [])
            ai_extract.write_ai_requirements_metadata(out, input_fingerprint="annotation-v15")
            shadow = claim_ledger.build_shadow_ledger(catalog, [])
            claim_artifacts.publish_shadow_generation(
                out, catalog, shadow, run_id="annotation-v15-table",
                requirements_sha256=claim_artifacts.file_sha256(out / "ai_requirements.jsonl"),
            )
            claim_review_actions.fold_effective_ledger(out, actor_trigger="annotation-v15-table")
            optimized = dae.render_annotation_html(out, layout_mode="optimized")
            region = {"page_number": 2, "bbox": [60, 200, 540, 230],
                      "page_width": 600, "page_height": 800}
            original = dae.render_annotation_html(
                out, layout_mode="pdf_original", pdf_href=dae.ANNOTATION_SOURCE_PDF,
                pdf_pages=[{"page_number": 2, "href": "page.png", "width": 600, "height": 800}],
                pdf_geometry={}, pdf_row_geometry={"TB1": {1: [region]}},
            )

        self.assertIn(f'data-claim-id="{claim_id}"', optimized)
        self.assertIn('class="claim-table-row"', optimized)
        self.assertIn(f'data-claim-id="{claim_id}"', original)
        self.assertIn('data-row-index="1"', original)

    def test_table_row_claims_map_rows_in_both_layouts(self) -> None:
        # 当前结构表的逐行 claim 行映射（optimized + pdf_original 双布局）。
        # 旧 table_fallback claim 只存在于 legacy 结构表——F6 迁移门拒折旧结构 base,
        # 该路径不再可达，本用例以逐行 claim 守住双布局行映射契约
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            table, items, cells = self._current_table(
                [["Name", "Value"], ["A", "10 V"], ["B", "20 V"]]
            )
            catalog = claim_catalog.build_claim_catalog(
                [table], items, table_cell_items=cells
            )
            claim_ids = [row["claim_id"] for row in catalog["catalog"]]
            self.assertEqual(len(claim_ids), 2)
            claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [table])
            claim_artifacts.atomic_write_jsonl(out / "table_items.jsonl", items)
            claim_artifacts.atomic_write_jsonl(out / "table_cell_items.jsonl", cells)
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(
                out, actor_trigger="annotation-v15-table-rows"
            )
            optimized = dae.render_annotation_html(out, layout_mode="optimized")
            regions = {
                1: [{"page_number": 2, "bbox": [60, 200, 540, 230],
                     "page_width": 600, "page_height": 800}],
                2: [{"page_number": 2, "bbox": [60, 230, 540, 260],
                     "page_width": 600, "page_height": 800}],
            }
            original = dae.render_annotation_html(
                out, layout_mode="pdf_original", pdf_href=dae.ANNOTATION_SOURCE_PDF,
                pdf_pages=[{"page_number": 2, "href": "page.png",
                            "width": 600, "height": 800}],
                pdf_geometry={}, pdf_row_geometry={"TB1": regions},
            )

        records = self._claims_from_html(optimized)
        self.assertEqual(
            sorted(tuple(record["data_row_indexes"]) for record in records),
            [(1,), (2,)],
        )
        for claim_id in claim_ids:
            self.assertIn(f'data-claim-id="{claim_id}"', optimized)
            self.assertIn(f'data-claim-id="{claim_id}"', original)
        self.assertIn('data-row-index="1"', original)
        self.assertIn('data-row-index="2"', original)

    def test_table_cell_claims_reach_records_payload_and_cells_index(self) -> None:
        """P0-2 真实链路：catalog→publish→fold→annotation 全程 table_cell claim 不得丢失。

        修复前 `_claim_annotation_state` 的 cell 分支 `continue` 跳过公共
        records.append——catalog_cell_claims=2 而 claim_records/claim_zones 全为 0，
        前端只能消费手工 mock 的数据。本测试用真实 catalog/publish/fold 驱动，
        断言三个消费面（state records、应用内 payload、导出 HTML claims_json）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            table, items, cells = self._current_table([
                ["Feature", "Behavior", "Note"],
                ["Encryption",
                 "The meter shall authenticate all clients. "
                 "The meter shall log authentication failures.",
                 "see below"],
                ["Signing", "The meter shall sign responses.", "free text"],
            ])
            catalog = claim_catalog.build_claim_catalog(
                [table], items, table_cell_items=cells
            )
            cell_claims = [
                row for row in catalog["catalog"] if row["source_kind"] == "table_cell"
            ]
            # 夹具守门：结构变化使 cell claim 归零时必须先修夹具，不许空断言放行
            formal_cell_claims = [
                row for row in cell_claims if row["eligibility"] == "claim"
            ]
            excluded_candidates = [
                row for row in cell_claims if row["eligibility"] == "excluded"
            ]
            self.assertEqual(len(formal_cell_claims), 2)
            self.assertEqual(len(excluded_candidates), 1)
            self.assertEqual(
                excluded_candidates[0]["exclusion"]["reason"],
                "unsignaled_table_cell",
            )
            claim_artifacts.atomic_write_jsonl(out / "blocks.jsonl", [table])
            claim_artifacts.atomic_write_jsonl(out / "table_items.jsonl", items)
            claim_artifacts.atomic_write_jsonl(out / "table_cell_items.jsonl", cells)
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(
                out, actor_trigger="annotation-v16-cell-records"
            )

            state = dae._claim_annotation_state(out, [table])
            state_cell_records = [
                row for row in state["records"] if row["source_kind"] == "table_cell"
            ]
            self.assertEqual(
                sorted(row["claim_id"] for row in state_cell_records),
                sorted(row["claim_id"] for row in cell_claims),
            )
            for record in state_cell_records:
                self.assertTrue(record["mapped"])
                self.assertIn("table_cell_id", record)
                self.assertIn("header_path", record)
            self.assertEqual(
                sorted(row["claim_id"] for row in state["cells_by_block"].get("TB1", [])),
                sorted(row["claim_id"] for row in cell_claims),
            )

            payload = dae.build_pdf_annotation_payload(out)
            payload_cell_records = [
                row for row in payload["claim_records"]
                if row["source_kind"] == "table_cell"
            ]
            self.assertEqual(
                sorted(row["claim_id"] for row in payload_cell_records),
                sorted(row["claim_id"] for row in cell_claims),
            )

            rendered = dae.render_annotation_html(out, layout_mode="optimized")
            html_cell_records = [
                row for row in self._claims_from_html(rendered)
                if row["source_kind"] == "table_cell"
            ]
            self.assertEqual(
                sorted(row["claim_id"] for row in html_cell_records),
                sorted(row["claim_id"] for row in cell_claims),
            )

            # P1-3：静态审核 HTML 按物理 R×C 在 <td> 内渲染 cell claim 入口——
            # 两条 cell claim 同属 Encryption 行的 Behavior 格（locator R2-C2，数据行 1）
            formal_cell_ids = {
                row["locator"]["table_cell_id"] for row in formal_cell_claims
            }
            candidate_cell_ids = {
                row["locator"]["table_cell_id"] for row in excluded_candidates
            }
            self.assertEqual(len(formal_cell_ids), 1)
            self.assertEqual(len(candidate_cell_ids), 1)
            cell_id = next(iter(formal_cell_ids))
            candidate_cell_id = next(iter(candidate_cell_ids))
            self.assertNotEqual(cell_id, candidate_cell_id)
            chip_cells = re.findall(
                r'class="claim-cell-chip [^"]*"[^>]*data-table-cell-id="([^"]+)"',
                rendered,
            )
            self.assertEqual(
                sorted(chip_cells),
                sorted([cell_id, cell_id, candidate_cell_id]),
            )
            for row in cell_claims:
                self.assertIn(f'data-claim-id="{row["claim_id"]}"', rendered)
            # 落在正确 <td>：Encryption 数据行（第 2 个 <tr>）的 Behavior 格内
            body_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", rendered, re.DOTALL)
            encryption_row = next(
                row_html for row_html in body_rows if "Encryption" in row_html
            )
            tds = re.findall(r"<td>(.*?)</td>", encryption_row, re.DOTALL)
            self.assertIn("claim-cell-chip", tds[1])
            self.assertIn("claim-cell-chip", tds[2])
            self.assertNotIn("claim-cell-chip", tds[0])

    def test_full_html_uses_committed_claim_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            _publish(out, _catalog())
            claim_review_actions.fold_effective_ledger(
                out,
                actor_trigger="annotation-integration-test",
            )

            rendered = dae.render_annotation_html(out)

        self.assertIn('class="claim-distribution"', rendered)
        self.assertIn('class="claim-covered">1</i>', rendered)
        self.assertIn('class="claim-excluded">0</i>', rendered)
        self.assertIn('class="claim-uncertain">0</i>', rendered)

    def test_block_claim_distribution_badge_is_count_only(self) -> None:
        rendered = dae._render_one_block(
            "B1",
            "Auxiliary outputs",
            [],
            "body",
            True,
            False,
            False,
            [],
            claim_counts={"covered": 2, "excluded": 1, "uncertain": 3},
        )

        self.assertIn('class="claim-distribution"', rendered)
        self.assertIn('class="claim-covered">2</i>', rendered)
        self.assertIn('class="claim-excluded">1</i>', rendered)
        self.assertIn('class="claim-uncertain">3</i>', rendered)
        self.assertNotIn("claim_id", rendered)

    def test_reflow_echo_tag_lists_all_linked_requirements(self) -> None:
        rendered = dae._render_one_block(
            "B-ECHO", "Repeated source paragraph.", [], "body",
            False, False, False, [], {"AIR-1": 1, "AIR-2": 2},
            block={"block_id": "B-ECHO", "type": "paragraph"},
            echo_reqs=[{"ai_req_id": "AIR-1"}, {"ai_req_id": "AIR-2"}],
        )

        self.assertIn("重复·见01/02", rendered)
        self.assertIn('data-echo-reqs="AIR-1 AIR-2"', rendered)

    def test_pdf_original_layout_renders_pages_with_clickable_annotation_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            source_pdf = Path(__file__).parent / "fixtures" / "sample_text_tables.pdf"
            blocks, _, _ = extract_pdf(source_pdf, knowledge_bases=[], document_profile=None)
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
            self.assertIn('cursor: pointer; pointer-events: auto; border-radius: 3px;', rendered)
            self.assertIn('white-space: nowrap; pointer-events: auto;', rendered)
            self.assertIn('cursor: pointer; opacity: 0;', rendered)
            self.assertIn('const page = Number(zone.getAttribute("data-page") || 0);', rendered)
            self.assertIn('selectPdfContextRecord(zoneKey, info, page)', rendered)
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
            self.assertIn('const PDF_HREF = "document_facsimile.pdf";', rendered)
            self.assertIn('"source_page": 2', rendered)
            self.assertIn('"annotation_number": 1', rendered)
            self.assertIn('item.onclick = () => select(r.ai_req_id);', rendered)
            self.assertIn('if (PDF_MODE) showPdfPage(r.source_page);', rendered)
            self.assertIn('"#page=" + pageNumber + "&view=FitH"', rendered)
            self.assertNotIn('class="doc-block', rendered)

    def test_result_package_html_uses_hidden_page_assets_and_published_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "result"
            source_pdf = Path(tmp) / "source.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\noriginal-pdf-bytes\n%%EOF")
            started = initialize_result_package(
                root,
                input_path=source_pdf,
                requested_stages=["export-annotation-html"],
            )
            out = resolve_analysis_root(root)
            _seed(out)
            (out / "manifest.json").write_text(
                json.dumps({"input": str(source_pdf), "input_format": "pdf"}),
                encoding="utf-8",
            )
            pages = [{
                "page_number": 1,
                "file": "page-0001.png",
                "href": "document_pages/page-0001.png",
                "width": 595,
                "height": 842,
            }]

            with (
                patch.object(dae, "_resolve_pdf_geometry", return_value={}),
                patch.object(
                    dae,
                    "_ensure_pdf_page_images",
                    return_value=(pages, [str(out / "document_pages" / "page-0001.png")]),
                ),
            ):
                dae.export_annotation_bundle(out, layout_mode="pdf_original")
            # R1（2026-08-03 复审）后活动 attempt 期间直接发布被拒——
            # 走真实完成提交流程（run_manifest 阶段台账 + commit 一次性发布）
            run_id = started["active_attempt"]["run_id"]
            package_artifact_path(root, "run_manifest", for_write=True).write_text(
                json.dumps({
                    "stages": {
                        "export-annotation-html": {
                            "status": "ok",
                            "attempt_run_id": run_id,
                        }
                    }
                }),
                encoding="utf-8",
            )
            commit_analysis_completion(
                root, run_id=run_id, completed_stages=["export-annotation-html"],
            )

            rendered = (root / dae.ANNOTATION_HTML).read_text(encoding="utf-8")
            self.assertIn(
                '.ratomizer/pipeline/document_pages/page-0001.png', rendered
            )
            self.assertIn('const PDF_HREF = "document_facsimile.pdf";', rendered)
            self.assertEqual(
                (root / "document_facsimile.pdf").read_bytes(), source_pdf.read_bytes()
            )

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

            with patch.object(
                dae,
                "_facsimile_source_pdf",
                return_value=(None, "unavailable:test-fixture"),
            ):
                target, summary = dae.export_annotation_bundle(
                    out, layout_mode="pdf_original"
                )
            rendered = target.read_text(encoding="utf-8")

            self.assertEqual(summary["layout_mode_requested"], "pdf_original")
            self.assertEqual(summary["layout_mode"], "optimized")
            self.assertIsNone(summary["source_pdf"])
            self.assertIn('class="reader-shell"', rendered)
            self.assertIn('const PDF_MODE = false;', rendered)
            self.assertIn('class="doc-block', rendered)

    def test_non_pdf_fallback_still_generates_translation_sidecar(self) -> None:
        quote = "The manufacturer shall mark its trademark on the equipment."
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            _seed_marker_block(out, quote)
            source_docx = root / "source.docx"
            source_docx.write_bytes(b"not-a-pdf")
            (out / "manifest.json").write_text(
                json.dumps({"input": str(source_docx), "input_format": "docx"}),
                encoding="utf-8",
            )

            def chat(_system: str, _user: str) -> dict:
                return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

            with patch.object(
                dae,
                "_facsimile_source_pdf",
                return_value=(None, "unavailable:test-fixture"),
            ), patch("functional_synthesis._resolve_catalog_chat",
                     return_value=(chat, "llm:test-model")):
                target, summary = dae.export_annotation_bundle(
                    out, route="openai_compatible")

            rendered = target.read_text(encoding="utf-8")
            sidecar_exists = (out / dae.ANNOTATION_TRANSLATIONS).exists()

        self.assertEqual(summary["layout_mode_requested"], "pdf_original")
        self.assertEqual(summary["layout_mode"], "optimized")
        self.assertEqual(summary["route"], "openai_compatible")
        self.assertTrue(sidecar_exists)
        self.assertIn("制造商应在设备上标注其商标。", rendered)

    def test_default_export_prefers_original_pdf_layout(self) -> None:
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

            _target, summary = dae.export_annotation_bundle(out)

            self.assertEqual(summary["layout_mode_requested"], "pdf_original")
            self.assertEqual(summary["layout_mode"], "pdf_original")

    def test_pdf_original_collects_translation_candidates_without_geometry(self) -> None:
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
            pages = [{"page_number": 1, "href": "annotation_pages/page-0001.png", "width": 595, "height": 842}]

            def chat(_system: str, _user: str) -> dict:
                return {"items": [{"id": index, "translation": "中文译文"}
                                  for index in range(1, 9)]}

            with (patch.object(dae, "_resolve_pdf_geometry", return_value={}),
                  patch.object(dae, "_ensure_pdf_page_images",
                               return_value=(pages, [str(out / "annotation_pages" / "page-0001.png")])),
                  patch("functional_synthesis._resolve_catalog_chat",
                        return_value=(chat, "llm:test-model"))):
                target, summary = dae.export_annotation_bundle(
                    out, route="openai_compatible", layout_mode="pdf_original")

            rendered = target.read_text(encoding="utf-8")
            sidecar = json.loads(
                (out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

            self.assertIn(
                ("omission", "An uncovered requirement shall hold."),
                dae._collected_marker_texts.values(),
            )
            self.assertIn(
                ("covered", "The meter shall measure volume < 5 & log it."),
                dae._collected_marker_texts.values(),
            )
            self.assertEqual(summary["translated"], 2)
            self.assertEqual(len(sidecar["items"]), 2)
            self.assertIn('const PDF_CONTEXT = {"B2":', rendered)
            self.assertIn('"translation": "中文译文"', rendered)

    def test_pdf_context_can_embed_anchor_translation_for_hardware_fallback(self) -> None:
        blocks = [{"block_id": "B1", "text": "The enclosure shall be sealed."}]
        semantics = [{"block_id": "B1", "text": blocks[0]["text"],
                      "kind": "req", "req_id": "AIR-1"}]
        key = dae._translation_key(blocks[0]["text"])
        with patch.object(dae, "_active_translations", {key: "外壳应密封。"}):
            records = dae._pdf_context_records(
                blocks, [], include_requirements=True, semantics=semantics)

        self.assertEqual(records["B1"]["translation"], "外壳应密封。")
        self.assertEqual(records["B1"]["page"], 0)

    def test_pdf_semantics_marks_non_anchor_source_blocks_as_covered(self) -> None:
        blocks = [
            {"block_id": "A1", "text": "Primary anchor one.", "type": "paragraph", "noise": False},
            {"block_id": "C1", "text": "Shared covered constraint.", "type": "paragraph", "noise": False},
            {"block_id": "A2", "text": "Primary anchor two.", "type": "paragraph", "noise": False},
            {"block_id": "E1", "text": "Repeated source text.", "type": "paragraph", "noise": False},
        ]
        requirements = [
            {"ai_req_id": "REQ-1", "anchor_block_id": "A1",
             "source_block_ids": ["A1", "C1", "E1"], "echo_block_ids": ["E1"]},
            {"ai_req_id": "REQ-2", "anchor_block_id": "A2",
             "source_block_ids": ["A2", "C1"]},
            {"ai_req_id": "REQ-3", "anchor_block_id": "A1",
             "source_block_ids": ["A1"]},
        ]

        semantics = dae._pdf_block_semantics(
            blocks, requirements, {"A1", "A2", "C1", "E1"})
        by_block = {item["block_id"]: item for item in semantics}

        self.assertEqual(by_block["A1"]["kind"], "req")
        self.assertEqual(by_block["A1"]["req_ids"], ["REQ-1", "REQ-3"])
        self.assertEqual(by_block["E1"]["kind"], "echo")
        self.assertEqual(by_block["E1"]["req_ids"], ["REQ-1"])
        self.assertEqual(by_block["C1"]["kind"], "covered")
        self.assertEqual(by_block["C1"]["req_ids"], ["REQ-1", "REQ-2"])

    def test_pdf_covered_zone_renders_linked_analysis_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            shared = "The shared constraint shall apply to both requirements."
            blocks = [
                {"block_id": "A1", "order": 1, "type": "paragraph",
                 "text": "The first function shall run.", "section_path": ["4"],
                 "page_number": 1, "requirement_like": True, "noise": False},
                {"block_id": "C1", "order": 2, "type": "paragraph", "text": shared,
                 "section_path": ["4"], "page_number": 2,
                 "requirement_like": True, "noise": False},
                {"block_id": "A2", "order": 3, "type": "paragraph",
                 "text": "The second function shall run.", "section_path": ["4"],
                 "page_number": 2, "requirement_like": True, "noise": False},
            ]
            (out / "blocks.jsonl").write_text(
                "".join(json.dumps(block, ensure_ascii=False) + "\n" for block in blocks),
                encoding="utf-8")
            requirements = [
                {"ai_req_id": "REQ-1", "title": "需求一", "description": "解析一", "module": "其它",
                 "anchor_block_id": "A1", "source_block_ids": ["A1", "C1"],
                 "source_quote": "The first function shall run."},
                {"ai_req_id": "REQ-2", "title": "需求二", "description": "解析二", "module": "其它",
                 "anchor_block_id": "A2", "source_block_ids": ["A2", "C1"],
                 "source_quote": "The second function shall run."},
                {"ai_req_id": "REQ-3", "title": "需求三", "description": "解析三", "module": "其它",
                 "anchor_block_id": "A1", "source_block_ids": ["A1"],
                 "source_quote": "The first function shall run."},
            ]
            (out / "ai_requirements.jsonl").write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in requirements),
                encoding="utf-8")
            key = dae._translation_key(shared)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {"owner": "covered", "translation": "共享约束适用于两项需求。",
                                "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
            }, ensure_ascii=False), encoding="utf-8")
            pages = [
                {"page_number": 1, "href": "document_pages/page-0001.png",
                 "width": 595, "height": 842},
                {"page_number": 2, "href": "document_pages/page-0002.png",
                 "width": 595, "height": 842},
            ]
            geometry = {
                "A1": [{"page_number": 1, "bbox": [50, 60, 400, 85],
                        "page_width": 595, "page_height": 842}],
                "C1": [{"page_number": 2, "bbox": [50, 100, 400, 125],
                        "page_width": 595, "page_height": 842}],
                "A2": [{"page_number": 2, "bbox": [50, 140, 400, 165],
                        "page_width": 595, "page_height": 842}],
            }

            rendered = dae.render_annotation_html(
                out, layout_mode="pdf_original", pdf_href=dae.ANNOTATION_SOURCE_PDF,
                pdf_pages=pages, pdf_geometry=geometry)

        self.assertIn('class="pdf-block-zone zone-covered"', rendered)
        self.assertIn('data-covered-reqs="REQ-1 REQ-2"', rendered)
        self.assertIn('data-reqs="REQ-1 REQ-3"', rendered)
        self.assertIn('"kind": "covered"', rendered)
        self.assertIn('"covered_req_ids": ["REQ-1", "REQ-2"]', rendered)
        self.assertIn('"translation": "共享约束适用于两项需求。"', rendered)
        self.assertIn("该段已纳入需求解析", rendered)
        self.assertIn("selectPdfCoveredRecord(zoneKey, info, page)", rendered)
        self.assertIn("selectPdfRequirementGroup(zoneKey, info, reqIds, page)", rendered)
        self.assertIn("covered.includes(id)", rendered)
        self.assertIn("const sourcePage = Number(clickedPage || info.page || 0);", rendered)

    def test_pdf_original_translation_rerender_keeps_page_geometry(self) -> None:
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
            pages = [{
                "page_number": 1,
                "href": "document_pages/page-0001.png",
                "width": 595,
                "height": 842,
            }]
            geometry = {
                "B2": [{"page_number": 1, "bbox": [50, 60, 400, 85],
                        "page_width": 595, "page_height": 842}],
                "B3": [{"page_number": 1, "bbox": [50, 100, 400, 125],
                        "page_width": 595, "page_height": 842}],
            }

            def chat(_system: str, _user: str) -> dict:
                return {"items": [{"id": index, "translation": "中文译文"}
                                  for index in range(1, 9)]}

            with (patch.object(dae, "_resolve_pdf_geometry", return_value=geometry),
                  patch.object(dae, "_ensure_pdf_page_images",
                               return_value=(pages, [str(out / "document_pages" / "page-0001.png")])),
                  patch("functional_synthesis._resolve_catalog_chat",
                        return_value=(chat, "llm:test-model"))):
                target, summary = dae.export_annotation_bundle(
                    out, route="openai_compatible", layout_mode="pdf_original")

            rendered = target.read_text(encoding="utf-8")
            sidecar = json.loads(
                (out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(summary["route"], "openai_compatible")
        self.assertEqual(summary["translated"], 2)
        self.assertTrue(summary["annotation_overlay"])
        self.assertEqual(len(sidecar["items"]), 2)
        self.assertIn('class="pdf-page"', rendered)
        self.assertIn('class="pdf-block-zone zone-req"', rendered)
        self.assertIn('"translation": "中文译文"', rendered)
        self.assertNotIn('id="pdf-frame"', rendered)

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

    def test_renders_text_repair_and_failed_section_audit_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            path = out / "blocks.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            rows[1].update({
                "raw_text": "i sobliged",
                "text": "is obliged",
                "text_repaired": True,
                "text_repair_version": "pdf-text-repair-v2",
                "text_repairs": [{
                    "rule": "wordlist_fragment_repair",
                    "before": "i sobliged",
                    "after": "is obliged",
                }],
            })
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 1,
                "failed_section_ids": ["4"],
                "failed_section_block_ids": [rows[1]["block_id"]],
            }), encoding="utf-8")

            rendered = dae.render_annotation_html(out)

        self.assertIn('class="repair-tag"', rendered)
        self.assertIn('class="failed-extraction-tag"', rendered)
        self.assertIn("const REPAIR_AUDIT =", rendered)
        self.assertIn("function selectFailedExtraction(blockId)", rendered)
        self.assertIn('e.target.closest("[data-failed-block]")', rendered)
        self.assertIn("i sobliged", rendered)
        self.assertIn("wordlist_fragment_repair", rendered)

    def test_narrow_layout_keeps_parse_results_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

        self.assertIn("grid-template-rows: minmax(0, 56fr) minmax(0, 44fr)", rendered)
        self.assertNotIn("grid-template-rows: minmax(56vh, 1fr) minmax(320px, 44vh)", rendered)
        self.assertNotIn(".detail { display: none; }", rendered)

    def test_detail_empty_states_and_missing_summary_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

        self.assertEqual(rendered.count("点击原文段落或页边编号查看解析结果"), 2)
        self.assertNotIn("点击批注标记查看详情", rendered)
        self.assertIn("未生成需求摘要", rendered)

    def test_pdf_zoom_floor_tracks_the_current_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            rendered = dae.render_annotation_html(out)

        self.assertIn("function pdfZoomMinimum()", rendered)
        self.assertIn("containerWidth - pageChrome - PDF_ZOOM_STEP", rendered)
        self.assertIn("const minimum = Math.min(pdfPageWidth, pdfZoomMinimum());", rendered)
        self.assertNotIn("Math.max(520, Math.min(1500", rendered)

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
            quote = "Data that the MGW must collect, record locally and transmit remotely."
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
                     'of MGWs in "modalità walk by" o "drive by"')
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
            quote = "Event or report in the MGW, which can affect its functioning or alter its data in its contents."
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
            req_a = "The MGW shall record measurement data."
            hardware = "The manufacturer shall place its trademark on the device."
            req_b = "The MGW shall transmit data remotely."
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
            self.assertRegex(
                rendered,
                r'"ai_req_id": "AI-B".*?"annotation_number": 3',
            )

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
                "version": 2, "items": {key: {"owner": "hardware", "translation": "制造商应在设备上标注其商标。",
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
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
                                              "rejected": True, "reason": "翻译含无据编码/数字",
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
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

    def test_batch_guard_rejection_retries_single_item_successfully(self) -> None:
        calls: list[str] = []
        timed_quote = "The meter shall respond within 30 seconds."

        def chat(_system: str, user: str) -> dict:
            calls.append(user)
            if "原文条目 JSON" in user:
                # 30 属于第 1 条，却被批次响应串进第 2 条；只应重试第 2 条。
                return {"items": [
                    {"id": 1, "translation": "电表应在 30 秒内响应。"},
                    {"id": 2, "translation": "制造商应在 30 秒内标注设备。"},
                ]}
            self.assertIn("单条整段重试", user)
            self.assertIn("30", user)   # 护栏反馈明确告诉模型禁止复现的 token
            self.assertIn("不得借用此前批次或其他条目", user)
            self.assertIn(self.QUOTE, user)
            self.assertNotIn(timed_quote, user)
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat,
                texts={
                    dae._translation_key(timed_quote): ("context", timed_quote),
                    dae._translation_key(self.QUOTE): ("hardware", self.QUOTE),
                })
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(self.QUOTE)]

        self.assertEqual(len(calls), 2)
        self.assertEqual(summary["translated"], 2)
        self.assertEqual(summary["rejected"], 0)
        self.assertEqual(summary["single_retries"], 1)
        self.assertEqual(summary["retry_calls"], 1)
        self.assertEqual(summary["strategy_version"], dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION)
        self.assertEqual(sidecar["strategy_version"], dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION)
        self.assertEqual(entry["strategy"], "single")
        self.assertEqual(entry["status"], "accepted")
        self.assertEqual(entry["retry_count"], 1)
        self.assertEqual(sidecar["items"][dae._translation_key(timed_quote)]["strategy"], "batch")

    def test_batch_call_failure_retries_single_item_successfully(self) -> None:
        calls: list[str] = []

        def chat(_system: str, user: str) -> dict:
            calls.append(user)
            if "原文条目 JSON" in user:
                raise RuntimeError("temporary batch failure")
            self.assertIn("单条整段重试", user)
            self.assertIn("batch_call_failed", user)
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(self.QUOTE)]

        self.assertEqual(len(calls), 2)
        self.assertEqual(summary["failed_calls"], 1)
        self.assertEqual(summary["translated"], 1)
        self.assertEqual(summary["unresolved"], 0)
        self.assertEqual(entry["strategy"], "single")

    def test_batch_and_single_call_failures_fall_back_to_all_sentence_segments(self) -> None:
        quote = "The meter shall log events. The display shall show alarms."
        calls: list[str] = []

        def chat(_system: str, user: str) -> dict:
            calls.append(user)
            if "原文条目 JSON" in user:
                raise RuntimeError("batch unavailable")
            if "单条整段重试" in user:
                raise RuntimeError("single unavailable")
            if "第 1/2 句段" in user:
                return {"items": [{"id": 1, "translation": "电表应记录事件。"}]}
            if "第 2/2 句段" in user:
                return {"items": [{"id": 1, "translation": "显示器应显示告警。"}]}
            self.fail(f"unexpected prompt: {user}")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, quote)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(quote)]

        self.assertEqual(len(calls), 4)
        self.assertEqual(summary["failed_calls"], 2)
        self.assertEqual(summary["retry_calls"], 3)
        self.assertEqual(summary["translated"], 1)
        self.assertEqual(summary["unresolved"], 0)
        self.assertEqual(entry["strategy"], "sentence")
        self.assertEqual(entry["translation"], "电表应记录事件。显示器应显示告警。")

    def test_batch_missing_item_retries_only_that_item(self) -> None:
        calls: list[str] = []

        def chat(_system: str, user: str) -> dict:
            calls.append(user)
            if "原文条目 JSON" in user:
                return {"items": []}
            self.assertIn("batch_missing_item", user)
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)

        self.assertEqual(len(calls), 2)
        self.assertEqual(summary["batch_calls"], 1)
        self.assertEqual(summary["single_retries"], 1)
        self.assertEqual(summary["translated"], 1)
        self.assertEqual(summary["unresolved"], 0)

    def test_single_guard_rejection_falls_back_to_sentence_segments(self) -> None:
        quote = "The meter shall log events. The display shall show alarms."
        calls: list[str] = []

        def chat(_system: str, user: str) -> dict:
            calls.append(user)
            if "原文条目 JSON" in user:
                return {"items": [{"id": 1, "translation": "电表应在 30 秒内记录事件并显示告警。"}]}
            if "单条整段重试" in user:
                return {"items": [{"id": 1, "translation": "电表应记录 40 个事件并显示告警。"}]}
            if "第 1/2 句段" in user:
                return {"items": [{"id": 1, "translation": "电表应记录事件。"}]}
            if "第 2/2 句段" in user:
                return {"items": [{"id": 1, "translation": "显示器应显示告警。"}]}
            self.fail(f"unexpected prompt: {user}")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, quote)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(quote)]

        self.assertEqual(len(calls), 4)
        self.assertEqual(summary["translated"], 1)
        self.assertEqual(summary["rejected"], 0)
        self.assertEqual(summary["segment_retries"], 1)
        self.assertEqual(summary["segment_calls"], 2)
        self.assertEqual(summary["retry_calls"], 3)
        self.assertEqual(entry["translation"], "电表应记录事件。显示器应显示告警。")
        self.assertEqual(entry["strategy"], "sentence")
        self.assertEqual(entry["attempts"], {"batch": 1, "single": 1, "sentence": 2})
        self.assertEqual(entry["retry_count"], 3)

    def test_sentence_fallback_rejects_whole_item_when_one_segment_fails(self) -> None:
        quote = "The meter shall log events. The display shall show alarms."

        def chat(_system: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                return {"items": [{"id": 1, "translation": "电表应在 30 秒内处理事件。"}]}
            if "单条整段重试" in user:
                return {"items": [{"id": 1, "translation": "电表应记录 40 个事件。"}]}
            if "第 1/2 句段" in user:
                return {"items": [{"id": 1, "translation": "电表应记录事件。"}]}
            if "第 2/2 句段" in user:
                return {"items": [{"id": 1, "translation": "显示器应显示 99 个告警。"}]}
            self.fail(f"unexpected prompt: {user}")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, quote)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(quote)]

        self.assertEqual(summary["translated"], 0)
        self.assertEqual(summary["rejected"], 1)
        self.assertTrue(entry["rejected"])
        self.assertEqual(entry["translation"], "")
        self.assertEqual(entry["strategy"], "sentence")
        self.assertIn("第 2/2 句段", entry["reason"])
        self.assertNotIn("电表应记录事件", entry["translation"])

    def test_sentence_split_preserves_newline_content_and_abbreviations(self) -> None:
        text = "Use alarm types, e.g. tamper alerts.\nThe meter shall log events."
        segments = dae._split_translation_segments(text)

        self.assertEqual(segments, [
            "Use alarm types, e.g. tamper alerts.",
            "The meter shall log events.",
        ])
        self.assertEqual(
            re.sub(r"\s+", "", "".join(segments)),
            re.sub(r"\s+", "", text),
        )

    def test_old_rejected_cache_entry_is_retried_after_strategy_upgrade(self) -> None:
        calls = 0

        def chat(_system: str, _user: str) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {"owner": "hardware", "translation": "", "rejected": True,
                                "reason": "翻译含无据编码/数字"}},
            }, ensure_ascii=False), encoding="utf-8")

            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(calls, 1)
        self.assertEqual(summary["cached"], 0)
        self.assertEqual(summary["translated"], 1)
        self.assertFalse(sidecar["items"][key]["rejected"])
        self.assertEqual(sidecar["items"][key]["strategy_version"],
                         dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION)

    def test_old_accepted_cache_entry_is_reused_without_llm_call(self) -> None:
        def chat(_system: str, _user: str) -> dict:
            self.fail("accepted cache entry must not call the LLM")

        guard_calls: list[tuple[str, str]] = []
        real_guard = dae._fabricated_translation_tokens

        def guarded(source: str, translated: str) -> list[str]:
            guard_calls.append((source, translated))
            return real_guard(source, translated)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {"owner": "hardware",
                                "translation": "制造商应在设备上标注其商标。",
                                "guards_version": "annotation-translation-guards-v0"}},
            }, ensure_ascii=False), encoding="utf-8")

            with patch.object(dae, "_fabricated_translation_tokens", side_effect=guarded):
                summary = dae.generate_annotation_translations(
                    out, route="openai_compatible", chat=chat)
            sidecar = json.loads(
                (out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(len(guard_calls), 1)
        self.assertEqual(summary["cached"], 1)
        self.assertEqual(summary["cached_accepted"], 1)
        self.assertEqual(summary["translated"], 0)
        self.assertEqual(summary["retry_calls"], 0)
        self.assertEqual(
            sidecar["items"][key]["guards_version"],
            dae.ANNOTATION_TRANSLATION_GUARDS_VERSION,
        )

    def test_old_accepted_cache_is_hidden_until_current_guard_revalidates_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {
                    "owner": "hardware",
                    "translation": "制造商应在 30 秒内标注其商标。",
                    "guards_version": "annotation-translation-guards-v0",
                }},
            }, ensure_ascii=False), encoding="utf-8")

            translations, notes = dae._load_annotation_translations(out)
            html = dae.render_annotation_html(out)

        self.assertEqual(translations, {})
        self.assertEqual(notes, {})
        self.assertNotIn("制造商应在 30 秒内标注其商标。", html)

    def test_export_rerenders_after_zero_call_guard_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            translated = "制造商应在设备上标注其商标。"
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {
                    "owner": "hardware",
                    "translation": translated,
                    "guards_version": "annotation-translation-guards-v0",
                }},
            }, ensure_ascii=False), encoding="utf-8")

            path, summary = dae.export_annotation_bundle(
                out,
                route="openai_compatible",
                layout_mode=dae.LAYOUT_OPTIMIZED,
            )
            rendered = path.read_text(encoding="utf-8")

        self.assertEqual(summary["cache_migrated"], 1)
        self.assertEqual(summary["translated"], 0)
        self.assertIn(translated, rendered)

    def test_stub_export_still_runs_zero_call_guard_migration(self) -> None:
        """回归：stub（无 LLM）路由曾跳过迁移，旧护栏译文从视图/导出永久消失。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            translated = "电表应在设备上标注商标。"
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {
                    "owner": "hardware",
                    "translation": translated,
                    "guards_version": "annotation-translation-guards-v0",
                }},
            }, ensure_ascii=False), encoding="utf-8")

            path, summary = dae.export_annotation_bundle(
                out,
                route="stub",
                layout_mode=dae.LAYOUT_OPTIMIZED,
            )
            rendered = path.read_text(encoding="utf-8")
            sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(summary["cache_migrated"], 1)
        self.assertEqual(summary["translated"], 0)
        self.assertIn(translated, rendered)
        self.assertEqual(sidecar["items"][key]["guards_version"],
                         dae.ANNOTATION_TRANSLATION_GUARDS_VERSION)

    def test_old_accepted_cache_failing_current_guard_is_replaced(self) -> None:
        calls = 0

        def chat(_system: str, _user: str) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {
                    "owner": "hardware",
                    "translation": "制造商应在 30 秒内标注其商标。",
                    "guards_version": "annotation-translation-guards-v0",
                }},
            }, ensure_ascii=False), encoding="utf-8")

            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            sidecar = json.loads(
                (out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(calls, 1)
        self.assertEqual(summary["cached"], 0)
        self.assertEqual(summary["translated"], 1)
        self.assertEqual(
            sidecar["items"][key]["translation"],
            "制造商应在设备上标注其商标。",
        )
        self.assertEqual(
            sidecar["items"][key]["guards_version"],
            dae.ANNOTATION_TRANSLATION_GUARDS_VERSION,
        )

    def test_invalidated_accepted_cache_stays_pending_when_llm_is_unavailable(self) -> None:
        calls = 0

        def chat(_system: str, _user: str) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 1,
                "items": {key: {
                    "owner": "hardware",
                    "translation": "制造商应在 30 秒内标注其商标。",
                    "guards_version": "annotation-translation-guards-v0",
                }},
            }, ensure_ascii=False), encoding="utf-8")

            first = dae.generate_annotation_translations(out, route="stub")
            invalidated = json.loads(
                (out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            second = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)
            recovered = json.loads(
                (out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(first["cache_invalidated"], 1)
        self.assertEqual(first["unresolved"], 1)
        self.assertEqual(invalidated["items"][key]["translation"], "")
        self.assertEqual(invalidated["items"][key]["status"], "unresolved")
        self.assertFalse(invalidated["items"][key]["rejected"])
        self.assertEqual(calls, 1)
        self.assertEqual(second["translated"], 1)
        self.assertEqual(
            recovered["items"][key]["translation"],
            "制造商应在设备上标注其商标。",
        )

    def test_current_strategy_rejected_cache_entry_is_reused_without_llm_call(self) -> None:
        def chat(_system: str, _user: str) -> dict:
            self.fail("current-strategy rejection must not call the LLM again")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            key = dae._translation_key(self.QUOTE)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 2,
                "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                "items": {key: {
                    "owner": "hardware", "translation": "", "rejected": True,
                    "status": "rejected", "reason": "翻译含无据编码/数字",
                    "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                    "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION,
                }},
            }, ensure_ascii=False), encoding="utf-8")

            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=chat)

        self.assertEqual(summary["cached"], 1)
        self.assertEqual(summary["cached_rejected"], 1)
        self.assertEqual(summary["translated"], 0)
        self.assertEqual(summary["retry_calls"], 0)

    def test_translation_sidecar_replace_retries_windows_reader_lock(self) -> None:
        real_replace = dae.os.replace
        attempts = 0

        def flaky_replace(source: str | Path, target: str | Path) -> None:
            nonlocal attempts
            self.assertTrue((out / "annotation_translations.lock").exists())
            attempts += 1
            if attempts == 1:
                raise PermissionError("target is being read")
            real_replace(source, target)

        def chat(_system: str, _user: str) -> dict:
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, self.QUOTE)
            with patch.object(dae.os, "replace", side_effect=flaky_replace), \
                    patch.object(dae.time, "sleep") as sleep:
                summary = dae.generate_annotation_translations(
                    out, route="openai_compatible", chat=chat)

            self.assertEqual(summary["translated"], 1)
            self.assertTrue((out / dae.ANNOTATION_TRANSLATIONS).exists())
            self.assertEqual(attempts, 2)
            sleep.assert_called_once_with(dae._TRANSLATION_REPLACE_RETRY_S)

    def test_translation_sidecar_locked_merge_preserves_concurrent_acceptance(self) -> None:
        first_key = dae._translation_key(self.QUOTE)
        second_text = "The meter shall log events."
        second_key = dae._translation_key(second_text)
        accepted = {"owner": "hardware", "translation": "制造商应标注商标。",
                    "rejected": False, "status": "accepted"}
        second = {"owner": "software", "translation": "电表应记录事件。",
                  "rejected": False, "status": "accepted"}
        stale_rejection = {"owner": "hardware", "translation": "", "rejected": True,
                           "status": "rejected", "reason": "无据数字"}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            first_view = {first_key: accepted}
            dae._write_translation_sidecar(out, first_view, "test", {first_key})

            stale_second_view = {second_key: second}
            dae._write_translation_sidecar(out, stale_second_view, "test", {second_key})
            self.assertEqual(set(stale_second_view), {first_key, second_key})

            conflicting_view = {first_key: stale_rejection}
            dae._write_translation_sidecar(out, conflicting_view, "test", {first_key})
            saved = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))

        self.assertEqual(saved["items"][first_key]["translation"], "制造商应标注商标。")
        self.assertEqual(saved["items"][second_key]["translation"], "电表应记录事件。")
        self.assertFalse(saved["items"][first_key]["rejected"])

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
                                              "translation": "一条未被覆盖的需求应当成立。",
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
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
                    key: {"owner": "omission", "translation": "一条未被覆盖的需求应当成立。",
                          "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION},
                    dae._translation_key("其它"): {"owner": "omission", "translation": "",
                                                   "rejected": True, "reason": "含无据数字",
                                                   "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION},
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
                                              "translation": "本文件系依据 M/441 号授权起草的背景说明。",
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
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

    def test_export_stage_producer_includes_translation_strategy_version(self) -> None:
        import desktop_tasks

        producer = desktop_tasks.stage_producer("export-annotation-html")
        # v16 阶段戳（P0-2/P1-3：cell claim 进入 records/zones + 静态 HTML 按
        # 物理 R×C 渲染 claim 入口）——随 P0-2 修复从 v15 升位，两处钉串同源
        self.assertIn("doc_annotation_export/v16-cell-claim-projection", producer)
        self.assertIn(dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION, producer)
        self.assertIn(dae.ANNOTATION_TRANSLATION_GUARDS_VERSION, producer)


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
                                                      "translation": "电池寿命累计器",
                                                      "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
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
                                                               "translation": "电表应记录事件。",
                                                               "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
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
                payload = desktop_tasks.export_annotation_html_task(out, layout_mode="optimized")
            self.assertNotIn("对外分享", str(payload.get("note") or ""))


class PdfAnnotationPayloadTests(unittest.TestCase):
    def test_missing_native_pdf_uses_packaged_copy_only_when_sha_chain_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-native-source")
            initialize_result_package(root, input_path=source, requested_stages=["atomize"])
            out = resolve_analysis_root(root)
            packaged = package_artifact_path(root, "document_facsimile", for_write=True)
            packaged.write_bytes(source.read_bytes())
            source_sha = dae._file_sha256(source)
            (out / "manifest.json").write_text(json.dumps({
                "input": str(source), "input_format": "pdf",
            }), encoding="utf-8")
            pages = out / "document_pages"
            pages.mkdir()
            (pages / "manifest.json").write_text(json.dumps({
                "version": 1, "source_sha256": source_sha,
            }), encoding="utf-8")
            source.unlink()

            self.assertEqual(dae._source_pdf_path(out), packaged)

            (pages / "manifest.json").write_text(json.dumps({
                "version": 1, "source_sha256": "0" * 64,
            }), encoding="utf-8")
            self.assertIsNone(dae._source_pdf_path(out))

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
                "version": 1, "source_sha256": dae._file_sha256(out / "doc.pdf"),
                "dpi": dae.PDF_PAGE_RENDER_DPI,
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

    def test_payload_can_project_partial_requirements_instead_of_old_final_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            partial = [{
                "ai_req_id": "AIR-PARTIAL",
                "title": "增量需求",
                "description": "d",
                "module": "事件",
                "source_quote": "An uncovered requirement shall hold.",
                "source_block_ids": ["B2"],
                "anchor_block_id": "B2",
            }]

            payload = dae.build_pdf_annotation_payload(out, requirements=partial)

            self.assertEqual(
                [marker["req_id"] for marker in payload["requirement_markers"]],
                ["AIR-PARTIAL"],
            )
            self.assertEqual(
                [marker["block_id"] for marker in payload["omission_markers"]],
                ["B1"],
            )

    def test_payload_unavailable_without_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out, with_pages=False)
            payload = dae.build_pdf_annotation_payload(out)
            self.assertFalse(payload["available"])
            self.assertIn("重新导出批注 HTML", payload["reason"])
            self.assertNotIn("原版影印模式", payload["reason"])

    def test_unavailable_pdf_payload_still_carries_text_claim_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out, with_pages=False)
            blocks = [json.loads(line) for line in
                      (out / "blocks.jsonl").read_text(encoding="utf-8").splitlines()]
            catalog = claim_catalog.build_claim_catalog(blocks, [])
            _publish(out, catalog)
            claim_review_actions.fold_effective_ledger(
                out, actor_trigger="annotation-v13-no-pages"
            )

            payload = dae.build_pdf_annotation_payload(out)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["claim_annotation_version"], dae.CLAIM_ANNOTATION_VERSION)
        self.assertEqual(
            {row["claim_id"] for row in payload["claim_records"]},
            {row["claim_id"] for row in catalog["catalog"]},
        )
        self.assertEqual(payload["claim_zones"], [])

    def test_payload_rejects_stale_or_incompatible_page_manifest(self) -> None:
        mutations = ({"version": 0}, {"source_sha256": "stale"}, {"dpi": 72})
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                self._seed(out)
                path = out / dae.ANNOTATION_PAGES_DIR / dae.ANNOTATION_PAGES_MANIFEST
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest.update(mutation)
                path.write_text(json.dumps(manifest), encoding="utf-8")

                payload = dae.build_pdf_annotation_payload(out)

                self.assertFalse(payload["available"])
                self.assertIn("影印页缓存", payload["reason"])
                self.assertNotIn("原版影印模式", payload["reason"])


def _extract_numbered(user: str) -> list[dict]:
    """从批次 prompt 抽出模型可见的原文条目 JSON（id/text），供 mock 按本批内容回填。"""
    match = re.search(r"原文条目 JSON:\s*(\[.*\])", user, re.S)
    return json.loads(match.group(1)) if match else []


class TranslationBatchOptimizationTests(unittest.TestCase):
    """翻译优化批处理（RATOMIZER_TRANSLATE_BATCH>0）：双上限贪心装包 + 拆半降级 + 逐条护栏。

    默认 OFF 时策略/缓存指纹保持 v2 不变；批次响应解析的越界/重复 id 卫生处理对 OFF 路径
    同样生效（对正常响应无影响）。本类只测 opt-in 新行为与 fail-closed 边界。任何异常条目
    （缺/重/越界 id）不得覆盖或污染合法条目；漂移译文绝不放行；缓存仍是单条粒度，重跑只补
    未命中/未解决条。
    """

    def _on_env(self, count: str = "10", max_chars: str = "8000"):
        return patch.dict(os.environ, {
            "RATOMIZER_TRANSLATE_BATCH": count,
            "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": max_chars,
        })

    def _off_env(self):
        return patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "0"})

    # --- Req 6：提示词版本真实进策略/producer/缓存指纹（不只是登记摆设）---
    def test_prompt_version_constant_registered_and_derived_into_strategy(self) -> None:
        from prompt_registry import is_registered
        self.assertEqual(dae.TRANSLATION_BATCH_PROMPT_VERSION, "translation-prompt-v3")
        self.assertTrue(is_registered(dae.TRANSLATION_BATCH_PROMPT_VERSION))
        # 策略版本由提示词版本派生 → 改提示词版本即改缓存/阶段指纹
        self.assertTrue(dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED.startswith(
            dae.TRANSLATION_BATCH_PROMPT_VERSION))

    def test_strategy_version_switches_with_mode(self) -> None:
        with self._off_env():
            self.assertEqual(dae._active_translation_strategy_version(),
                             dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION)
        with self._on_env():
            active = dae._active_translation_strategy_version()
            # 策略版本含提示词版本前缀 + 有效配置指纹（条数/字符），配置变化→指纹变
            self.assertTrue(active.startswith(dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED))
            self.assertIn(dae.TRANSLATION_BATCH_PROMPT_VERSION, active)
            self.assertIn("-b10-c8000", active)

    def test_prompt_version_enters_producer_stamp_only_when_on(self) -> None:
        import desktop_tasks
        with self._on_env():
            stamp_on = desktop_tasks.stage_producer("export-annotation-html")
            self.assertIn(dae.TRANSLATION_BATCH_PROMPT_VERSION, stamp_on)
            self.assertIn(dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED, stamp_on)
        with self._off_env():
            stamp_off = desktop_tasks.stage_producer("export-annotation-html")
            self.assertIn(dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION, stamp_off)
            self.assertNotIn(dae.TRANSLATION_BATCH_PROMPT_VERSION, stamp_off)

    # --- Req 7：默认 OFF 路径行为与 v2 缓存复用不变 ---
    def test_off_default_uses_v2_strategy_and_legacy_batch8_slice(self) -> None:
        items = [(f"k{i}", "context", f"text number {i}") for i in range(20)]
        with self._off_env():
            self.assertEqual(dae._translate_batch_count(), 0)
            batches = dae._pack_translation_batches(items, count_limit=dae._translate_batch_count(),
                                                    max_chars=dae._translate_batch_max_chars())
            self.assertEqual([len(b) for b in batches], [8, 8, 4])   # 旧 _TRANSLATION_BATCH=8 切片
            self.assertEqual(dae._active_translation_strategy_version(),
                             dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION)

    def test_off_reuses_v2_accepted_cache_without_retranslate(self) -> None:
        calls = 0

        def chat(_s: str, _u: str) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [{"id": 1, "translation": "电表应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, "The manufacturer shall place its trademark on the device.")
            key = dae._translation_key("The manufacturer shall place its trademark on the device.")
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 2,
                "items": {key: {"owner": "hardware",
                                "translation": "制造商应在设备上标注其商标。",
                                "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
            }, ensure_ascii=False), encoding="utf-8")
            with self._off_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
        self.assertEqual(calls, 0)   # v2 已接受译文零调用复用
        self.assertEqual(summary["cached"], 1)
        self.assertEqual(summary["translated"], 0)

    def test_off_duplicate_id_is_dropped_and_retried_singly(self) -> None:
        # Fix-B2：OFF 路径同样做 fail-closed 重复 id 卫生处理（注释已如实化），
        # 重复 id 全部丢弃 → 单条重试取回干净译文。
        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                return {"items": [{"id": 1, "translation": "合法译文"},
                                  {"id": 1, "translation": "污染 9999"},   # 重复 id
                                  {"id": 2, "translation": "乙"}]}
            self.assertIn("单条整段重试", user)
            return {"items": [{"id": 1, "translation": "重试干净译文"}]}

        texts = {dae._translation_key("alpha"): ("context", "alpha"),
                 dae._translation_key("beta"): ("context", "beta")}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._off_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        self.assertEqual(sidecar["items"][dae._translation_key("alpha")]["translation"], "重试干净译文")
        self.assertEqual(sidecar["items"][dae._translation_key("alpha")]["strategy"], "single")
        self.assertEqual(sidecar["items"][dae._translation_key("beta")]["translation"], "乙")
        self.assertEqual(sidecar["items"][dae._translation_key("beta")]["strategy"], "batch")
        self.assertEqual(summary["translated"], 2)
        self.assertEqual(summary["single_retries"], 1)

    # --- Req 2：装包边界（直接单测 _pack_translation_batches）---
    def test_pack_11th_item_closes_batch_on_count_limit(self) -> None:
        items = [(f"k{i}", "context", f"text item {i}") for i in range(11)]
        batches = dae._pack_translation_batches(items, count_limit=10, max_chars=8000)
        self.assertEqual([len(b) for b in batches], [10, 1])

    def test_pack_char_limit_closes_batch(self) -> None:
        items = [(f"k{i}", "context", "x" * 30) for i in range(4)]   # 每条 30 字符
        batches = dae._pack_translation_batches(items, count_limit=100, max_chars=100)
        self.assertEqual([len(b) for b in batches], [3, 1])          # 90≤100，第 4 条 120>100 封包

    def test_pack_single_over_limit_goes_solo_untruncated(self) -> None:
        big = "y" * 200
        items = [("short1", "context", "small"), ("big", "context", big), ("short2", "context", "tiny")]
        batches = dae._pack_translation_batches(items, count_limit=10, max_chars=100)
        self.assertEqual([len(b) for b in batches], [1, 1, 1])       # 超限条独立成包，宁超勿截
        self.assertEqual(batches[1][0][0], "big")
        self.assertEqual(len(dae._cleaned_marker_text(batches[1][0][2])), 200)   # 未截断

    # --- Req 1：fail-closed 异常 id（缺/重/越界/乱序）---
    def test_out_of_bounds_id_ignored_without_polluting_legit_items(self) -> None:
        # 越界 id 99 与负数/0：忽略，不落表、不崩溃，合法条目照常回填
        result, parseable = dae._translate_marker_batch(
            lambda _s, _u: {"items": [
                {"id": 1, "translation": "甲"},
                {"id": 99, "translation": "污染"},
                {"id": 0, "translation": "零"},
                {"id": -1, "translation": "负"},
                {"id": 2, "translation": "乙"},
            ]},
            [("k1", "context", "alpha"), ("k2", "context", "beta")], optimized=True)
        self.assertTrue(parseable)
        self.assertEqual(result, {1: "甲", 2: "乙"})   # 越界全部丢弃，合法位不染

    def test_duplicate_id_dropped_retries_singly_without_overwriting(self) -> None:
        # id 1 出现两次（第二次含漂移 9999）：歧义 → 该 id 全部丢弃 → 单条重试取回干净译文
        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                return {"items": [{"id": 1, "translation": "合法译文"},
                                  {"id": 1, "translation": "污染 9999"},   # 重复 id
                                  {"id": 2, "translation": "乙"}]}
            # 单条整段重试（id 1 被丢弃后触发）
            self.assertIn("单条整段重试", user)
            return {"items": [{"id": 1, "translation": "重试干净译文"}]}

        texts = {dae._translation_key("alpha"): ("context", "alpha"),
                 dae._translation_key("beta"): ("context", "beta")}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        # id 1 的两条 batch 回填都被丢（含漂移的那条没覆盖合法位）；id 2 不受影响
        self.assertEqual(sidecar["items"][dae._translation_key("alpha")]["translation"], "重试干净译文")
        self.assertEqual(sidecar["items"][dae._translation_key("alpha")]["strategy"], "single")
        self.assertEqual(sidecar["items"][dae._translation_key("beta")]["translation"], "乙")
        self.assertEqual(sidecar["items"][dae._translation_key("beta")]["strategy"], "batch")
        self.assertEqual(summary["translated"], 2)
        self.assertEqual(summary["single_retries"], 1)

    def test_missing_id_retries_only_that_item(self) -> None:
        # 批次漏回 id 2：只重试 id 2，id 1 批次接受
        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                return {"items": [{"id": 1, "translation": "甲"}]}   # 缺 id 2
            self.assertIn("单条整段重试", user)
            return {"items": [{"id": 1, "translation": "乙"}]}

        texts = {dae._translation_key("alpha"): ("context", "alpha"),
                 dae._translation_key("beta"): ("context", "beta")}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        self.assertEqual(sidecar["items"][dae._translation_key("alpha")]["strategy"], "batch")
        self.assertEqual(sidecar["items"][dae._translation_key("beta")]["strategy"], "single")
        self.assertEqual(summary["translated"], 2)
        self.assertEqual(summary["single_retries"], 1)

    def test_out_of_order_id_maps_by_value(self) -> None:
        # 乱序回填：按 id 值映射到位，不按数组顺序
        result, _ = dae._translate_marker_batch(
            lambda _s, _u: {"items": [
                {"id": 3, "translation": "丙"},
                {"id": 1, "translation": "甲"},
                {"id": 2, "translation": "乙"},
            ]},
            [("k1", "context", "alpha"), ("k2", "context", "beta"), ("k3", "context", "gamma")],
            optimized=True)
        self.assertEqual(result, {1: "甲", 2: "乙", 3: "丙"})

    # --- Req 4：每条漂移独立拦截，成功同批条目仍落盘 ---
    def test_drift_in_one_item_does_not_block_others(self) -> None:
        a = "The meter shall log events."
        b = "The valve shall open fully."

        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                items = []
                for e in _extract_numbered(user):
                    if e["text"].startswith("The meter shall log"):
                        items.append({"id": e["id"], "translation": "电表应记录 42 事件。"})  # 42 无据→漂移
                    else:
                        items.append({"id": e["id"], "translation": "阀门应完全开启。"})
                return {"items": items}
            self.assertIn("单条整段重试", user)
            return {"items": [{"id": 1, "translation": "电表应记录事件。"}]}   # 干净重试

        texts = {dae._translation_key(a): ("context", a), dae._translation_key(b): ("context", b)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        # A 漂移被拦→单条重试接受；B 批次直接接受并落盘（不被 A 拖累）
        self.assertEqual(sidecar["items"][dae._translation_key(a)]["strategy"], "single")
        self.assertEqual(sidecar["items"][dae._translation_key(a)]["translation"], "电表应记录事件。")
        self.assertEqual(sidecar["items"][dae._translation_key(b)]["strategy"], "batch")
        self.assertEqual(sidecar["items"][dae._translation_key(b)]["translation"], "阀门应完全开启。")
        self.assertEqual(summary["translated"], 2)
        self.assertEqual(summary["rejected"], 0)

    def test_drift_translation_never_released(self) -> None:
        # 单条重试仍漂移、句段也救不回 → 该条不放行漂移译文（rejected/unresolved，translation 空）
        a = "The meter shall log events."

        def chat(_s: str, user: str) -> dict:
            # 所有回合一律塞入无据 9999
            return {"items": [{"id": 1, "translation": "电表应记录 9999 事件。"}]}

        texts = {dae._translation_key(a): ("context", a)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        entry = sidecar["items"][dae._translation_key(a)]
        self.assertNotEqual(entry["translation"], "电表应记录 9999 事件。")   # 漂移译文绝不出现在产物
        self.assertEqual(entry["translation"], "")
        self.assertIn(entry["status"], {"rejected", "unresolved"})
        self.assertEqual(summary["translated"], 0)

    # --- Req 3：整批非法→拆半（≤2 层）→逐条；部分缺条只补该条 ---
    def test_whole_batch_malformed_splits_halves_then_succeeds(self) -> None:
        texts = {dae._translation_key(t): ("context", t) for t in
                 ["Alpha alpha.", "Bravo bravo.", "Charlie charlie.", "Delta delta."]}

        def chat(_s: str, user: str) -> dict:
            numbered = _extract_numbered(user)
            if len(numbered) >= 4:
                return {"items": "truncated"}   # 整批结构非法（items 非列表）→ 拆半
            return {"items": [{"id": e["id"], "translation": f"<{e['text'][:5]}>"} for e in numbered]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env(count="10"):
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        # 整批(1) + 左右半批(2) = 3 次调用，failed=1（整批），全部经拆半救回、逐条不触发
        self.assertEqual(summary["batch_calls"], 3)
        self.assertEqual(summary["failed_calls"], 1)
        self.assertEqual(summary["single_retries"], 0)
        self.assertEqual(summary["translated"], 4)
        # id 偏移正确：右半 local id → 全局位（Charlie/Delta 落对）
        self.assertEqual(sidecar["items"][dae._translation_key("Charlie charlie.")]["translation"], "<Charl>")
        self.assertEqual(sidecar["items"][dae._translation_key("Delta delta.")]["translation"], "<Delta>")

    def test_split_exhausts_then_per_item_retry(self) -> None:
        # 整批与所有拆半都非法 → 拆到单条后回退逐条级联
        texts = {dae._translation_key(t): ("context", t) for t in ["Alpha alpha.", "Bravo bravo."]}

        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:        # 任何批次（整批/半批/单条批）一律非法
                return {"items": "broken"}
            self.assertIn("单条整段重试", user)  # 逐条级联
            return {"items": [{"id": 1, "translation": "干净译文"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env(count="10"):
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
        # 整批(1) + 两个单条半(2) = 3 次批次调用全 failed；2 条各走一次单条重试
        self.assertEqual(summary["batch_calls"], 3)
        self.assertEqual(summary["failed_calls"], 3)
        self.assertEqual(summary["single_retries"], 2)
        self.assertEqual(summary["translated"], 2)

    def test_partial_missing_only_refills_that_item(self) -> None:
        # items 列表存在（结构合法）但缺 id 2：只补 id 2，不算整批非法、不拆半
        texts = {dae._translation_key(t): ("context", t) for t in ["Alpha.", "Bravo.", "Charlie."]}

        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                return {"items": [{"id": 1, "translation": "甲"}, {"id": 3, "translation": "丙"}]}  # 缺 2
            self.assertIn("单条整段重试", user)
            return {"items": [{"id": 1, "translation": "乙"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env(count="10"):
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        self.assertEqual(summary["batch_calls"], 1)          # 不拆半
        self.assertEqual(summary["failed_calls"], 0)
        self.assertEqual(summary["single_retries"], 1)       # 只补 id 2
        self.assertEqual(sidecar["items"][dae._translation_key("Bravo.")]["strategy"], "single")
        self.assertEqual(sidecar["items"][dae._translation_key("Alpha.")]["strategy"], "batch")

    # --- Req 5：单条粒度缓存，重跑只补未命中/未解决条 ---
    def test_rerun_only_translates_uncached_items(self) -> None:
        calls = 0
        a, b, c = "The meter shall log events.", "The valve shall open.", "The alarm shall ring."

        def chat(_s: str, _u: str) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [{"id": 1, "translation": "新译文"}]}

        texts = {dae._translation_key(a): ("context", a),
                 dae._translation_key(b): ("context", b),
                 dae._translation_key(c): ("context", c)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            seed = {dae._translation_key(a): {"owner": "context", "translation": "甲缓存",
                                              "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION},
                    dae._translation_key(b): {"owner": "context", "translation": "乙缓存",
                                              "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}}
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps(
                {"version": 2, "items": seed}, ensure_ascii=False), encoding="utf-8")
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        self.assertEqual(calls, 1)                          # 只补未缓存的 c（1 批 1 条）
        self.assertEqual(summary["cached"], 2)
        self.assertEqual(summary["translated"], 1)
        self.assertEqual(sidecar["items"][dae._translation_key(a)]["translation"], "甲缓存")  # 复用
        self.assertEqual(sidecar["items"][dae._translation_key(c)]["translation"], "新译文")  # 新抽

    def test_rerun_retries_unresolved_entry(self) -> None:
        calls = 0
        a, b = "The meter shall log events.", "The valve shall open."

        def chat(_s: str, _u: str) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [{"id": 1, "translation": "救回译文"}]}

        texts = {dae._translation_key(a): ("context", a), dae._translation_key(b): ("context", b)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            seed = {dae._translation_key(a): {"owner": "context", "translation": "甲缓存",
                                              "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION},
                    # b 为 unresolved（空译文、未拒绝）→ 不复用、需重抽
                    dae._translation_key(b): {"owner": "context", "translation": "", "rejected": False,
                                              "status": "unresolved",
                                              "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED,
                                              "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}}
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps(
                {"version": 2, "items": seed}, ensure_ascii=False), encoding="utf-8")
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
        self.assertEqual(calls, 1)                          # 只重抽未解决的 b
        self.assertEqual(summary["cached"], 1)
        self.assertEqual(summary["translated"], 1)

    # --- Req 6 落地：ON 运行写出的缓存条目策略版本含提示词版本 ---
    def test_on_run_entry_strategy_version_carries_prompt_version(self) -> None:
        quote = "The manufacturer shall place its trademark on the device."

        def chat(_s: str, _u: str) -> dict:
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, quote)
            with self._on_env():
                dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
            entry = sidecar["items"][dae._translation_key(quote)]
        self.assertIn(dae.TRANSLATION_BATCH_PROMPT_VERSION, entry["strategy_version"])
        self.assertTrue(entry["strategy_version"].startswith(
            dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED))
        self.assertIn("-b10-c8000", entry["strategy_version"])   # 有效配置进逐条缓存指纹

    # --- Issue 1：count 硬上限 ≤10 + 非整数 fail-safe ---
    def test_count_clamped_to_10(self) -> None:
        for raw, expected in [("100", 10), ("15", 10), ("11", 10), ("10", 10), ("5", 5), ("1", 1)]:
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": raw}):
                self.assertEqual(dae._translate_batch_count(), expected, f"raw={raw!r}")

    def test_non_integer_count_fails_safe_off(self) -> None:
        for raw in ["3.5", "0.5", "abc", "", "0", "-3"]:   # 非整数/非数字/≤0 → fail-safe OFF
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": raw}):
                self.assertEqual(dae._translate_batch_count(), 0, f"raw={raw!r}")
        # clamp 后 100 仍启用优化模式（=10），不会因超限关掉
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "100"}):
            self.assertGreater(dae._translate_batch_count(), 0)

    def test_max_chars_non_integer_fails_safe_to_default(self) -> None:
        # Fix-B3：max_chars 与 count 解析一致——非整数不得静默截断，应 fail-safe 回默认值。
        for raw in ["3.5", "0.5", "abc"]:
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": raw}):
                self.assertEqual(dae._translate_batch_max_chars(),
                                 dae._TRANSLATION_BATCH_MAX_CHARS_DEFAULT,
                                 f"raw={raw!r}")

    def test_max_chars_zero_or_negative_fails_safe_to_default(self) -> None:
        # Fix-B3：0/负数同样回默认值（无意义配置不静默生效）。
        for raw in ["0", "-100", "-1"]:
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": raw}):
                self.assertEqual(dae._translate_batch_max_chars(),
                                 dae._TRANSLATION_BATCH_MAX_CHARS_DEFAULT,
                                 f"raw={raw!r}")

    def test_max_chars_valid_integer_used(self) -> None:
        for raw, expected in [("8000", 8000), ("4000", 4000), ("1", 1)]:
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": raw}):
                self.assertEqual(dae._translate_batch_max_chars(), expected, f"raw={raw!r}")

    def test_clamped_count_drives_packing(self) -> None:
        # RATOMIZER_TRANSLATE_BATCH=100 → clamp 10 → 实际每包 ≤10
        items = [(f"k{i}", "context", f"item {i}") for i in range(25)]
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "100"}):
            count = dae._translate_batch_count()
            batches = dae._pack_translation_batches(items, count_limit=count, max_chars=8000)
        self.assertEqual(count, 10)
        self.assertTrue(all(len(b) <= 10 for b in batches))
        self.assertEqual([len(b) for b in batches], [10, 10, 5])

    # --- Issue 2：有效配置进阶段指纹 + 拒绝缓存随配置失效 ---
    def test_config_values_enter_strategy_and_producer_stamp(self) -> None:
        import desktop_tasks
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "10",
                                     "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": "8000"}):
            strat_a = dae._active_translation_strategy_version()
            stamp_a = desktop_tasks.stage_producer("export-annotation-html")
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "5",
                                     "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": "4000"}):
            strat_b = dae._active_translation_strategy_version()
            stamp_b = desktop_tasks.stage_producer("export-annotation-html")
        # 10/8000 与 5/4000 不是同一行为配置：策略版本与阶段戳都不同
        self.assertNotEqual(strat_a, strat_b)
        self.assertIn("-b10-c8000", strat_a)
        self.assertIn("-b5-c4000", strat_b)
        self.assertNotEqual(stamp_a, stamp_b)

    def test_rejected_cache_invalidates_on_config_change(self) -> None:
        # b10-c8000 下被拒的条目，切到 b5-c4000 后 strategy_version 不匹配 → 不复用拒绝 → 重试
        quote = "The valve shall open fully."

        def chat(_s: str, _u: str) -> dict:
            return {"items": [{"id": 1, "translation": "阀门应完全开启。"}]}

        key = dae._translation_key(quote)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, quote)
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "10",
                                         "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": "8000"}):
                strat_old = dae._active_translation_strategy_version()
            # 写一条绑定旧配置的拒绝项
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 2,
                "items": {key: {"owner": "context", "translation": "", "rejected": True,
                                "reason": "翻译含无据编码/数字",
                                "strategy_version": strat_old,
                                "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
            }, ensure_ascii=False), encoding="utf-8")
            # 切配置后重跑：旧拒绝不共键 → 重抽成功
            with patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "5",
                                         "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS": "4000"}):
                summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        self.assertEqual(summary["cached"], 0)          # 旧拒绝在新配置下不复用
        self.assertEqual(summary["translated"], 1)
        self.assertFalse(sidecar["items"][key]["rejected"])

    # --- Issue 3：严格双向护栏——原文 token 缺失逐条拦截 ---
    def test_strict_guard_catches_missing_that_v2_misses(self) -> None:
        src = "The meter shall support OBIS 0-0:96.1.0.255 at 230 V."
        lossy = "电表应支持该对象。"   # 丢失 OBIS/230/V，但没有新增 → v2 漏判
        self.assertEqual(dae._fabricated_translation_tokens(src, lossy), [])   # v2 不拦
        drift, _fab = dae._translation_drift(src, lossy, strict=True)
        self.assertTrue(drift)                            # v3 严格拦下
        self.assertTrue(any("0-0:96.1.0.255" in t for t in drift))
        self.assertTrue(any("230" in t for t in drift))
        self.assertTrue(any(t.endswith("V") for t in drift))

    def test_strict_guard_allows_thousand_separator_in_translation(self) -> None:
        # Fix-B1 钉死：千分位原文与忠实译文均含 "3,200"，缺失方向不得误报 3200。
        src = "The test shall run 3,200 cycles."
        faithful = "测试应运行 3,200 次循环。"
        self.assertEqual(dae._fabricated_translation_tokens(src, faithful), [])
        drift, _fab = dae._translation_drift(src, faithful, strict=True)
        self.assertFalse(drift, f"expected no drift, got {drift}")

    def test_strict_guard_allows_preserved_enum_numbers_in_translation(self) -> None:
        # Fix-B1 钉死：数字枚举在译文中保留编号，缺失方向不得误报 1/2。
        src = "1. First action. 2. Second action."
        faithful = "1. 第一个动作。2. 第二个动作。"
        self.assertEqual(dae._fabricated_translation_tokens(src, faithful), [])
        drift, _fab = dae._translation_drift(src, faithful, strict=True)
        self.assertFalse(drift, f"expected no drift, got {drift}")

    def test_missing_obis_int_unit_intercepted_same_batch_other_succeeds(self) -> None:
        a = "The meter shall support OBIS 0-0:96.1.0.255 at 230 V."
        b = "The valve shall open fully."

        def chat(_s: str, user: str) -> dict:
            if "原文条目 JSON" in user:
                items = []
                for e in _extract_numbered(user):
                    if e["text"].startswith("The meter shall support"):
                        # 丢失 OBIS/230/V → v3 严格漂移
                        items.append({"id": e["id"], "translation": "电表应支持该对象。"})
                    else:
                        items.append({"id": e["id"], "translation": "阀门应完全开启。"})
                return {"items": items}
            # A 的单条重试：干净保留全部受保护 token
            self.assertIn("单条整段重试", user)
            return {"items": [{"id": 1, "translation": "电表应支持 OBIS 0-0:96.1.0.255，230 V。"}]}

        texts = {dae._translation_key(a): ("context", a), dae._translation_key(b): ("context", b)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        # A 漂移被逐条拦→单条重试取回干净译文；B 同批不受影响、批次直接接受
        entry_a = sidecar["items"][dae._translation_key(a)]
        entry_b = sidecar["items"][dae._translation_key(b)]
        self.assertEqual(entry_a["strategy"], "single")
        self.assertIn("0-0:96.1.0.255", entry_a["translation"])
        self.assertIn("230 V", entry_a["translation"])
        self.assertEqual(entry_b["strategy"], "batch")
        self.assertEqual(entry_b["translation"], "阀门应完全开启。")
        self.assertEqual(summary["translated"], 2)
        self.assertEqual(summary["single_retries"], 1)

    def test_missing_token_translation_never_released(self) -> None:
        # 单条重试仍丢失 token → 不放行缺失译文（rejected，translation 空）
        a = "The meter shall support OBIS 0-0:96.1.0.255 at 230 V."

        def chat(_s: str, _u: str) -> dict:
            return {"items": [{"id": 1, "translation": "电表应支持该对象。"}]}   # 始终丢失

        texts = {dae._translation_key(a): ("context", a)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible",
                                                               chat=chat, texts=texts)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        entry = sidecar["items"][dae._translation_key(a)]
        self.assertEqual(entry["translation"], "")        # 缺失译文绝不放行
        drift_tokens = [token for rejection in entry["rejections"]
                        for token in rejection.get("drift_tokens", [])]
        self.assertIn("缺失:0-0:96.1.0.255", drift_tokens)  # 审计保留被拦截证据
        self.assertIn("受保护编码/数值/单位漂移", entry["reason"])
        self.assertEqual(summary["translated"], 0)

    def test_v2_accepted_missing_token_not_reused_under_v3(self) -> None:
        # v2 接受的旧译文丢失 token（v2 新增护栏漏判）→ v3 严格复验不过 → 不直接复用、重新翻译
        a = "The meter shall support OBIS 0-0:96.1.0.255 at 230 V."
        lossy = "电表应支持该对象。"
        self.assertEqual(dae._fabricated_translation_tokens(a, lossy), [])   # 确属 v2 漏判
        key = dae._translation_key(a)

        def chat(_s: str, _u: str) -> dict:
            return {"items": [{"id": 1, "translation": "电表应支持 OBIS 0-0:96.1.0.255，230 V。"}]}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, a)
            (out / dae.ANNOTATION_TRANSLATIONS).write_text(json.dumps({
                "version": 2,
                "items": {key: {"owner": "context", "translation": lossy,
                                "strategy_version": dae.ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                "guards_version": dae.ANNOTATION_TRANSLATION_GUARDS_VERSION}},
            }, ensure_ascii=False), encoding="utf-8")
            with self._on_env():
                summary = dae.generate_annotation_translations(out, route="openai_compatible", chat=chat)
                sidecar = json.loads((out / dae.ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
        entry = sidecar["items"][key]
        self.assertEqual(summary["translated"], 1)        # 重新翻译（未被零调用复用）
        self.assertIn("0-0:96.1.0.255", entry["translation"])   # 旧缺失译文被替换
        self.assertNotEqual(entry["translation"], lossy)

    def test_invalidation_cas_does_not_overwrite_concurrent_safe_translation(self) -> None:
        old = "旧的不完整译文"
        incoming = {
            "translation": "",
            "rejected": False,
            "status": "unresolved",
            "invalidated_translation_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
        }
        concurrent = {"translation": "并发写入的安全译文", "rejected": False,
                      "status": "accepted"}
        self.assertEqual(
            dae._merge_translation_update(concurrent, incoming)["translation"],
            "并发写入的安全译文",
        )
