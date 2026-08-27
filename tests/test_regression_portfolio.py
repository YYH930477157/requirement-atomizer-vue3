"""多文档回归组合钉（架构收敛路线图 WS-C，2026-08-27）。

扩展 test_synthetic_doc_corpus 的合成中性语料模式：四个文档类型 fixture
走当前真实确定性入口（extraction_units 规划、unit_router 路由、
functional_extract.apply_unit_routing、conservation_report），零 LLM。

钉子记录的是**当前行为**（含已知缺陷）。Phase 1 的 WS-A/B 改动应使带
「已知缺陷」注释的断言显式变化；无该注释的值是应保持的结构/审计面。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from atomize import build_table_artifacts
from extraction_units import plan_extraction_units
from functional_extract import apply_unit_routing, conservation_report, load_clauses
from io_utils import read_jsonl
from requirement_kb import KnowledgeRepository
from table_dispositions import build_table_cell_dispositions
from unit_router import route_document

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "portfolio"
KB = KnowledgeRepository.from_paths([])

_STUB_NARRATIVE = "The product shall satisfy the declared behaviour."


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _load_spec(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_expected(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _seed_blocks_chunks(out: Path, spec: dict) -> list[dict]:
    blocks = list(spec["blocks"])
    _write_jsonl(out / "blocks.jsonl", blocks)
    _write_jsonl(out / "chunks.jsonl", list(spec["chunks"]))
    return blocks


def _seed_mixed_table(out: Path, spec: dict) -> list[dict]:
    table = spec["table"]
    table_block, table_items, cell_items = build_table_artifacts(
        list(table["matrix"]),
        table_id=str(table["table_id"]),
        block_id=str(table["block_id"]),
        order=int(table["order"]),
        table_title=str(table["table_title"]),
        section_path=list(spec["section_path"]),
        knowledge_bases=KB,
    )
    heading = dict(spec["heading_block"])
    prose = dict(spec["prose_block"])
    blocks = [heading, table_block, prose]
    dispositions = build_table_cell_dispositions([table_block], cell_items)
    _write_jsonl(out / "blocks.jsonl", blocks)
    _write_jsonl(out / "table_items.jsonl", list(table_items))
    _write_jsonl(out / "table_cell_items.jsonl", list(cell_items))
    _write_jsonl(out / "table_cell_dispositions.jsonl", list(dispositions))
    chunk_text = " ".join(
        str(block.get("text") or "")
        for block in (heading, table_block, prose)
        if str(block.get("text") or "").strip()
    )
    _write_jsonl(out / "chunks.jsonl", [{
        "chunk_id": "CH-MT-1",
        "section_path": list(spec["section_path"]),
        "heading": str(spec["heading"]),
        "text": chunk_text,
        "block_ids": [heading["block_id"], table_block["block_id"], prose["block_id"]],
    }])
    return blocks


def _obligation_count(report: dict) -> int:
    return len(report["checks"]["obligation_coverage"]["uncovered_obligations"])


def _preservation_tokens(report: dict) -> list[dict[str, str]]:
    checks = report["checks"]["preservation"]
    rows: list[dict[str, str]] = []
    for finding in list(checks.get("blocking_losses") or []) + list(
            checks.get("warning_losses") or []):
        rows.append({
            "section_id": str(finding.get("section_id") or ""),
            "kind": str(finding.get("kind") or ""),
            "token": str(finding.get("token") or ""),
            "severity": str(finding.get("severity") or ""),
        })
    return sorted(rows, key=lambda row: (row["section_id"], row["kind"], row["token"]))


def _stub_items(sections: list[dict]) -> list[dict]:
    items = []
    for index, section in enumerate(sections):
        items.append({
            "functional_requirement_id": f"FRE-STUB-{index:03d}",
            "objective": _STUB_NARRATIVE,
            "behaviors": [],
            "source_quote": "",
            "source_block_ids": list(section.get("block_ids") or []),
        })
    return items


def _observe(out: Path, blocks: list[dict]) -> dict:
    plan = plan_extraction_units(out)
    route = route_document(out, plan_if_missing=False)
    sections = load_clauses(out)
    kept, meta = apply_unit_routing(sections, blocks=blocks, out_dir=out)
    empty_all = conservation_report(sections, [], blocks=blocks)
    empty_kept = conservation_report(kept, [], blocks=blocks)
    pres = conservation_report(kept, _stub_items(kept), blocks=blocks)
    section_ids = [str(section.get("section_id") or "") for section in sections]
    kept_ids = [str(section.get("section_id") or "") for section in kept]
    return {
        "plan": {
            "unit_count": plan["unit_count"],
            "counts_by_kind": plan["counts_by_kind"],
            "counts_by_role": plan["counts_by_role"],
        },
        "router": {
            "unit_count": route["unit_count"],
            "counts_by_route": route["counts_by_route"],
            "counts_by_rule": route["counts_by_rule"],
        },
        "apply": {
            "status": meta["status"],
            "sections_total": meta["sections_total"],
            "sections_extracted": meta["sections_extracted"],
            "table_dominated_routed_out": meta["table_dominated_routed_out"],
            "front_matter_routed_out": meta["front_matter_routed_out"],
            "tender_procedural_routed_out": meta["tender_procedural_routed_out"],
            "tender_procedural_section_ids": sorted(
                str(sid) for sid in (meta.get("tender_procedural_section_ids") or [])),
            "tender_span_routed_out": meta["tender_span_routed_out"],
            "tender_span_section_ids": sorted(
                str(sid) for sid in (meta.get("tender_span_section_ids") or [])),
            "routed_out_section_ids": sorted(
                str(sid) for sid in (meta.get("routed_out_section_ids") or [])),
            "mixed_table_sections_kept": meta["mixed_table_sections_kept"],
            "section_ids": section_ids,
            "kept_section_ids": kept_ids,
            "section_id_collision_counts": dict(
                sorted(Counter(section_ids).items())),
        },
        "conservation": {
            "obligation_units_all_sections": _obligation_count(empty_all),
            "obligation_units_kept_baseline": _obligation_count(empty_kept),
            "preservation_tokens": _preservation_tokens(pres),
        },
    }


class TenderPdfPathologyTests(unittest.TestCase):
    """招标 PDF 四类解析病理。出处：CLAUDE.md 2026-08-26 / 2026-08-27。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        spec = _load_spec("tender_pdf_pathology.json")
        cls.blocks = _seed_blocks_chunks(cls.out, spec)
        cls.obs = _observe(cls.out, cls.blocks)
        cls.exp = _load_expected("expected_tender_pdf_pathology.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_unit_plan_and_router_counts(self) -> None:
        # CLAUDE.md 2026-08-26：升格 heading 成 heading/context 单元，不当 clause_segment
        self.assertEqual(self.obs["plan"], self.exp["plan"])
        self.assertEqual(self.obs["router"], self.exp["router"])

    def test_apply_routing_and_pathology_ids(self) -> None:
        apply = self.obs["apply"]
        exp = self.exp["apply"]
        self.assertEqual(apply["status"], exp["status"])
        self.assertEqual(apply["sections_total"], exp["sections_total"])
        self.assertEqual(apply["sections_extracted"], exp["sections_extracted"])
        self.assertEqual(
            apply["tender_procedural_routed_out"],
            exp["tender_procedural_routed_out"],
        )
        self.assertEqual(
            apply["tender_procedural_section_ids"],
            exp["tender_procedural_section_ids"],
        )
        # CLAUDE.md 2026-08-26：正文句升格 heading 仍路由出。
        # WS-A/B 已修复（2026-08-27）：桶重分类——OEM 句从 tender_procedural
        # 移到 tender_span（仍路由出，守恒不变）。
        self.assertIn(
            "26 There shall be no change of original equipment manufacturer for this lot.",
            apply["tender_span_section_ids"],
        )
        # CLAUDE.md 2026-08-26：无自身标题 chunk，块内 Preparation of Bids 锚点路由出
        self.assertIn("CH-000004", apply["tender_procedural_section_ids"])
        # CLAUDE.md 2026-08-27 P3：块流吞下一章 technical heading → 否决路由、保守保留
        # 当前行为（已知缺陷,WS-A/B 将改变此值）
        self.assertIn("2.2 Delivery Schedule", apply["kept_section_ids"])
        self.assertNotIn("2.2 Delivery Schedule", apply["tender_procedural_section_ids"])
        # CLAUDE.md 2026-08-17e / 2026-08-27：两 chunk 共享 section_path 首段，section_id 撞名
        # 当前行为（已知缺陷,WS-A/B 将改变此值）
        self.assertEqual(apply["section_id_collision_counts"]["2 20 Control of"], 2)
        self.assertEqual(apply["section_ids"].count("2 20 Control of"), 2)
        self.assertEqual(apply["kept_section_ids"].count("2 20 Control of"), 2)
        self.assertIn("2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)", apply["kept_section_ids"])
        self.assertEqual(apply["routed_out_section_ids"], exp["routed_out_section_ids"])
        self.assertEqual(apply["tender_span_routed_out"], exp["tender_span_routed_out"])

    def test_conservation_baseline(self) -> None:
        self.assertEqual(self.obs["conservation"], self.exp["conservation"])


class ProseStandardTests(unittest.TestCase):
    """散文标准：名词短语规格 + 义务句。出处：CLAUDE.md 2026-07-20 / 2026-08-19。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        spec = _load_spec("prose_standard.json")
        cls.blocks = _seed_blocks_chunks(cls.out, spec)
        cls.obs = _observe(cls.out, cls.blocks)
        cls.exp = _load_expected("expected_prose_standard.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_noun_phrase_is_narrative_not_clause_segment(self) -> None:
        # CLAUDE.md 2026-07-20：名词短语式规格无情态，规划器整块 narrative
        self.assertEqual(self.obs["plan"], self.exp["plan"])
        self.assertEqual(self.obs["router"], self.exp["router"])
        self.assertGreaterEqual(self.obs["plan"]["counts_by_kind"].get("narrative", 0), 1)
        self.assertGreaterEqual(
            self.obs["plan"]["counts_by_kind"].get("clause_segment", 0), 2)

    def test_no_table_clause_stays_kept(self) -> None:
        apply = self.obs["apply"]
        self.assertEqual(apply["sections_extracted"], 1)
        self.assertEqual(apply["table_dominated_routed_out"], 0)
        self.assertEqual(apply["tender_procedural_routed_out"], 0)
        self.assertEqual(apply["kept_section_ids"], ["5 Functional behaviour"])

    def test_conservation_includes_noun_phrase_numbers(self) -> None:
        # 当前行为（已知缺陷,WS-A/B 将改变此值）：名词短语里的 230/50 进 preservation
        self.assertEqual(self.obs["conservation"], self.exp["conservation"])
        tokens = {row["token"] for row in self.obs["conservation"]["preservation_tokens"]}
        self.assertTrue({"230", "50"} <= tokens)


class MixedTableTests(unittest.TestCase):
    """技术表 + 散文义务同节。出处：CLAUDE.md 2026-08-26 section 6。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        spec = _load_spec("mixed_table.json")
        cls.blocks = _seed_mixed_table(cls.out, spec)
        cls.obs = _observe(cls.out, cls.blocks)
        cls.exp = _load_expected("expected_mixed_table.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_unit_and_router_counts(self) -> None:
        self.assertEqual(self.obs["plan"], self.exp["plan"])
        self.assertEqual(self.obs["router"], self.exp["router"])

    def test_mixed_section_kept_not_table_routed(self) -> None:
        apply = self.obs["apply"]
        self.assertEqual(apply["status"], "ok")
        self.assertEqual(apply["sections_extracted"], 1)
        self.assertEqual(apply["table_dominated_routed_out"], 0)
        self.assertEqual(apply["mixed_table_sections_kept"], 1)
        self.assertEqual(
            apply["kept_section_ids"],
            ["6 TECHNICAL DATA REQUIREMENTS TABLE"],
        )

    def test_table_digits_enter_preservation_baseline(self) -> None:
        # CLAUDE.md 2026-08-26：section 6 表格数字进 B 轨 preservation（49/50 形态）
        # 当前行为（已知缺陷,WS-A/B 将改变此值）
        self.assertEqual(self.obs["conservation"], self.exp["conservation"])
        tokens = {row["token"] for row in self.obs["conservation"]["preservation_tokens"]}
        self.assertTrue({"230", "5", "50"} <= tokens)


class ProceduralTechnicalMixedTests(unittest.TestCase):
    """程序性/产品义务同文档。出处：CLAUDE.md 2026-08-27 诊断 2。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        spec = _load_spec("procedural_technical_mixed.json")
        cls.blocks = _seed_blocks_chunks(cls.out, spec)
        cls.obs = _observe(cls.out, cls.blocks)
        cls.exp = _load_expected("expected_procedural_technical_mixed.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_unit_and_router_counts(self) -> None:
        self.assertEqual(self.obs["plan"], self.exp["plan"])
        self.assertEqual(self.obs["router"], self.exp["router"])
        # 当前 unit_router 不区分 bidder/meter 主体，义务句一律 b_track
        self.assertGreaterEqual(self.obs["router"]["counts_by_route"].get("b_track", 0), 5)

    def test_title_based_routing_not_subject(self) -> None:
        apply = self.obs["apply"]
        self.assertEqual(apply["tender_procedural_section_ids"],
                         self.exp["apply"]["tender_procedural_section_ids"])
        self.assertEqual(apply["tender_span_section_ids"],
                         self.exp["apply"]["tender_span_section_ids"])
        self.assertEqual(apply["kept_section_ids"], self.exp["apply"]["kept_section_ids"])
        # CLAUDE.md 2026-08-20b：开标/税清标题走逐标题程序性路由
        self.assertIn("1.10 Bid Opening", apply["tender_procedural_section_ids"])
        self.assertIn("11 Valid Tax Clearance Certificate", apply["tender_procedural_section_ids"])
        # WS-A/B 已修复（2026-08-27）：产品主语保护——8 Event recording /
        # 9 Retention period 不再被开标锚点跨度整节吞没；tender_span 只剩
        # 12 Spare parts。出处：CLAUDE.md 2026-08-27 诊断 2。
        self.assertEqual(
            apply["tender_span_section_ids"],
            ["12 Spare parts"],
        )
        # WS-A/B 已修复（2026-08-27）：产品主语保护使 8/9 进入 kept；
        # 6 TECHNICAL DATA 仍由 technical 标题否决保留。
        self.assertEqual(apply["kept_section_ids"], [
            "8 Event recording",
            "9 Retention period",
            "6 TECHNICAL DATA REQUIREMENTS TABLE",
        ])

    def test_conservation_baseline(self) -> None:
        # WS-A/B 已修复（2026-08-27）：8/9 产品节回到基线，
        # obligation_units_kept_baseline 1→3；9 Retention period 的 90
        # 恢复为 number blocking。出处：CLAUDE.md 2026-08-27 诊断 2。
        self.assertEqual(self.obs["conservation"], self.exp["conservation"])


if __name__ == "__main__":
    unittest.main()
