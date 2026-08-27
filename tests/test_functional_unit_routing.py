"""§17 unit 级路由接线（2026-08-17，NEXT-SESSION-PLAN 第 1 项）。

clause_family 策略下，表格主导条款（全部声明块都是表格块，且这些块上的单元无
b_track/mixed 路由）离开 B 轨输入与守恒基线；清单/计数/版本身份全部写入产物
meta（``unit_routing`` 块），绝不静默。legacy 策略零变化：不加载单元、不过滤、
产物不带该块、指纹不含路由维度。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import functional_extract as fe
import functional_reextract
from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
from unit_router import UNIT_ROUTER_VERSION

B1_TEXT = "The meter shall log quality events with a timestamp."
B2_TABLE_TEXT = "[TBL-000001] Table 1 - Limits\nVoltage | Limit\n230 | 240"
B2_MODAL_CELL = "The meter shall record the voltage in all phases."


def _blocks_jsonl(extra_paragraph: bool = False) -> list[dict]:
    rows = [
        {"block_id": "B1", "type": "paragraph", "section_path": ["4.1"],
         "text": B1_TEXT, "order": 1},
        {"block_id": "B2", "type": "table", "section_path": ["4.2"],
         "text": B2_TABLE_TEXT, "order": 2},
    ]
    if extra_paragraph:
        rows.append({
            "block_id": "B3", "type": "paragraph", "section_path": ["4.2"],
            "text": "The display shall show the voltage.", "order": 3,
        })
    return rows


def _chunks_jsonl(extra_paragraph: bool = False) -> list[dict]:
    rows = [
        {"section_path": ["4.1"], "heading": "4.1", "text": B1_TEXT,
         "block_ids": ["B1"]},
        {"section_path": ["4.2"], "heading": "4.2", "text": B2_TABLE_TEXT,
         "block_ids": ["B2"] + (["B3"] if extra_paragraph else [])},
    ]
    return rows


def _cell_unit(unit_id: str, text: str, roles: list[str]) -> dict:
    return {
        "schema": "extraction-unit/v1", "unit_id": unit_id,
        "unit_kind": "table_cell", "source_text": text,
        "source_text_hash": "sha256:" + __import__("hashlib").sha256(
            text.encode("utf-8")).hexdigest(),
        "clause_path": ["4.2"], "source_block_ids": ["B2"], "roles": roles,
        "context_refs": [], "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": {"source_type": "table_cell", "source_id": unit_id},
        "table_context": {"table_id": "TBL-000001", "cell_id": unit_id,
                          "disposition": roles[0]},
    }


def _prose_unit() -> dict:
    return {
        "schema": "extraction-unit/v1", "unit_id": "UNIT-B1-S000",
        "unit_kind": "clause_segment", "source_text": B1_TEXT,
        "source_text_hash": "sha256:" + __import__("hashlib").sha256(
            B1_TEXT.encode("utf-8")).hexdigest(),
        "clause_path": ["4.1"], "source_block_ids": ["B1"],
        "roles": ["requirement_candidate"], "context_refs": [],
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": {"source_type": "block_sentence", "source_id": "B1#0"},
    }


def _decision(unit_id: str, route: str) -> dict:
    return {"schema": "unit-routing-decision/v1", "unit_id": unit_id,
            "route": route, "router_version": UNIT_ROUTER_VERSION}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")


def _seed_out(out: Path, *, cell_roles: list[str] | None = None,
              cell_routes: list[str] | None = None,
              extra_paragraph: bool = False,
              with_artifacts: bool = True) -> None:
    _write_jsonl(out / "blocks.jsonl", _blocks_jsonl(extra_paragraph))
    _write_jsonl(out / "chunks.jsonl", _chunks_jsonl(extra_paragraph))
    if not with_artifacts:
        return
    # 表格解析在场性护栏：table_items 存在即视为表格内容可核验
    _write_jsonl(out / "table_items.jsonl", [{
        "item_id": "TBLI-1", "table_id": "TBL-000001", "table_block_id": "B2",
        "leaf_role": "row", "row_index": 1, "text": "230 | 240",
        "section_path": ["4.2"], "fields": {"Voltage": "230", "Limit": "240"},
    }])
    roles = cell_roles or ["context", "context"]
    routes = cell_routes or ["context", "context"]
    units = [_prose_unit()] + [
        _cell_unit(f"UNIT-C{index + 1}", text, [role])
        for index, (text, role) in enumerate(
            zip(["230", "240"], roles))
    ]
    decisions = [_decision("UNIT-B1-S000", "b_track")] + [
        _decision(f"UNIT-C{index + 1}", route)
        for index, route in enumerate(routes)
    ]
    _write_jsonl(out / "extraction_units.jsonl", units)
    _write_jsonl(out / "unit_routing_decisions.jsonl", decisions)


def _chat_prose(system: str, user: str) -> dict:
    return {"items": [{
        "objective": B1_TEXT, "behaviors": ["log quality events"],
        "source_quote": B1_TEXT, "source_block_ids": ["B1"],
    }]}


class ApplyUnitRoutingTests(unittest.TestCase):
    def test_pure_table_context_cells_routed_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            sections = fe.load_clauses(out)
            kept, meta = fe.apply_unit_routing(
                sections, blocks=_blocks_jsonl(), out_dir=out)
            self.assertEqual([s["section_id"] for s in kept], ["4.1"])
            self.assertEqual(meta["status"], "ok")
            self.assertEqual(meta["table_dominated_routed_out"], 1)
            self.assertEqual(meta["routed_out_section_ids"], ["4.2"])
            self.assertEqual(meta["routed_out_block_ids"], ["B2"])
            self.assertEqual(meta["mixed_table_sections_kept"], 0)
            self.assertEqual(meta.get("tender_span_routed_out", 0), 0)

    def test_b_track_cell_keeps_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, cell_roles=["requirement_candidate"] * 2,
                      cell_routes=["b_track", "context"])
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks_jsonl(), out_dir=out)
            self.assertEqual(len(kept), 2)
            self.assertEqual(meta["table_dominated_routed_out"], 0)

    def test_mixed_route_keeps_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, cell_routes=["mixed", "context"])
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks_jsonl(), out_dir=out)
            self.assertEqual(len(kept), 2)
            self.assertEqual(meta["table_dominated_routed_out"], 0)

    def test_review_cells_routed_out_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, cell_roles=["review_candidate"] * 2,
                      cell_routes=["review", "review"])
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks_jsonl(), out_dir=out)
            self.assertEqual([s["section_id"] for s in kept], ["4.1"])
            self.assertEqual(meta["table_dominated_routed_out"], 1)
            self.assertEqual(meta["routed_out_review_units"], 2)

    def test_table_plus_prose_section_kept_as_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, extra_paragraph=True)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out),
                blocks=_blocks_jsonl(extra_paragraph=True), out_dir=out)
            self.assertEqual(len(kept), 2)
            self.assertEqual(meta["table_dominated_routed_out"], 0)
            self.assertEqual(meta["mixed_table_sections_kept"], 1)

    def test_missing_units_keeps_all_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, with_artifacts=False)
            # blocks 里存在表格块但表格解析产物缺席 → 内容不可核验 → 如实 unavailable。
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks_jsonl(), out_dir=out)
            self.assertEqual(len(kept), 2)
            self.assertEqual(meta["status"], "unavailable")
            self.assertEqual(meta["reason"], "table_parse_inputs_missing")

    def test_no_table_blocks_needs_no_table_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "blocks.jsonl", [
                {"block_id": "B1", "type": "paragraph",
                 "section_path": ["4.1"], "text": B1_TEXT, "order": 1}])
            _write_jsonl(out / "chunks.jsonl", [
                {"section_path": ["4.1"], "heading": "4.1", "text": B1_TEXT,
                 "block_ids": ["B1"]}])
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=[
                    {"block_id": "B1", "type": "paragraph",
                     "section_path": ["4.1"], "text": B1_TEXT}], out_dir=out)
            # 无表格块：无需表格解析产物；单元缺席现场规划（prose 信号句成单元），
            # 无纯表格条款可路由 → ok + 0 routed。
            self.assertEqual(len(kept), 1)
            self.assertEqual(meta["status"], "ok")
            self.assertEqual(meta["table_dominated_routed_out"], 0)

    def test_front_matter_sections_routed_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            sections = fe.load_clauses(out) + [{
                "section_id": "Scope", "section_path": ["Scope"],
                "heading": "Scope", "text": "This Standard applies to smart meters.",
                "block_ids": ["B9"]}]
            kept, meta = fe.apply_unit_routing(
                sections, blocks=_blocks_jsonl(), out_dir=out)
            self.assertNotIn("Scope", [s["section_id"] for s in kept])
            self.assertEqual(meta["front_matter_routed_out"], 1)
            self.assertEqual(meta["front_matter_section_ids"], ["Scope"])

    def test_tender_instruction_sections_routed_out_meter_kept(self) -> None:
        """招标程序性条款（开标/税清/保函）出 B 轨；电表技术条款留下。

        WS-B（docs/architecture-convergence-plan-2026-08-27.md）：节级词表不再单独
        决定整节。本测试改为给程序性标题块进块流作跨度锚点（词表降级为辅助证据），
        聚合走 span 回退；EVENT LOG 无程序跨度且无 procedural_subject → 保留。
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            extra_blocks = [
                {"block_id": "H-BID", "type": "heading",
                 "text": "1.10 Bid Opening", "order": 10},
                {"block_id": "B-BID", "type": "paragraph",
                 "text": "Bids shall be opened in public.", "order": 11},
                {"block_id": "H-TAX", "type": "heading",
                 "text": "11 Valid Tax Clearance Certificate", "order": 12},
                {"block_id": "B-TAX", "type": "paragraph",
                 "text": "Bidders shall attach a tax clearance certificate.",
                 "order": 13},
                {"block_id": "H-BG", "type": "heading",
                 "text": "Bank Guarantee letterhead", "order": 14},
                {"block_id": "B-BG", "type": "paragraph",
                 "text": "The guarantee shall be an original document.",
                 "order": 15},
                {"block_id": "H-EVT", "type": "heading",
                 "text": "8 METER TECHNICAL SPECIFICATION", "order": 16},
                {"block_id": "B-EVT", "type": "paragraph",
                 "text": "The meter shall store events in memory.", "order": 17},
            ]
            sections = fe.load_clauses(out) + [
                {
                    "section_id": "1.10 Bid Opening",
                    "section_path": ["1.10 Bid Opening"],
                    "heading": "1.10 Bid Opening",
                    "text": "Bids shall be opened in public.",
                    "block_ids": ["H-BID", "B-BID"],
                },
                {
                    "section_id": "11 Valid Tax Clearance Certificate",
                    "section_path": ["11 Valid Tax Clearance Certificate"],
                    "heading": "11 Valid Tax Clearance Certificate",
                    "text": "Bidders shall attach a tax clearance certificate.",
                    "block_ids": ["H-TAX", "B-TAX"],
                },
                {
                    "section_id": "Bank Guarantee letterhead",
                    "section_path": [
                        "Letterhead of registered commercial bank "
                        "(i.e. the Supplier of the Bank Guarantee)"
                    ],
                    "heading": "Bank Guarantee",
                    "text": "The guarantee shall be an original document.",
                    "block_ids": ["H-BG", "B-BG"],
                },
                {
                    "section_id": "8.7 EVENT LOG",
                    "section_path": ["8 METER FUNCTIONS", "8.7 EVENT LOG"],
                    "heading": "8.7 EVENT LOG",
                    "text": "The meter shall store events in memory.",
                    "block_ids": ["H-EVT", "B-EVT"],
                },
            ]
            kept, meta = fe.apply_unit_routing(
                sections, blocks=_blocks_jsonl() + extra_blocks, out_dir=out)
            kept_ids = {s["section_id"] for s in kept}
            self.assertIn("4.1", kept_ids)
            self.assertIn("8.7 EVENT LOG", kept_ids)
            self.assertNotIn("1.10 Bid Opening", kept_ids)
            self.assertNotIn("11 Valid Tax Clearance Certificate", kept_ids)
            self.assertNotIn("Bank Guarantee letterhead", kept_ids)
            routed = set(meta.get("tender_span_section_ids") or []) | set(
                meta.get("tender_procedural_section_ids") or [])
            self.assertEqual(len(routed & {
                "1.10 Bid Opening",
                "11 Valid Tax Clearance Certificate",
                "Bank Guarantee letterhead",
            }), 3)

    def test_mid_document_introduction_not_routed_as_tender(self) -> None:
        """正文条款标题含 Introduction 不得当招标前言踢出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            sections = fe.load_clauses(out) + [{
                "section_id": "5.1 Introduction to event records",
                "section_path": ["5 Meter functions", "5.1 Introduction to event records"],
                "heading": "5.1 Introduction to event records",
                "text": "The meter shall record events.",
                "block_ids": ["B-INTRO"],
            }]
            kept, meta = fe.apply_unit_routing(
                sections, blocks=_blocks_jsonl(), out_dir=out)
            self.assertIn(
                "5.1 Introduction to event records",
                {s["section_id"] for s in kept},
            )
            self.assertEqual(meta.get("tender_procedural_routed_out", 0), 0)
            self.assertEqual(meta.get("tender_span_routed_out", 0), 0)

    def _tender_span_blocks(self) -> list[dict]:
        return [
            {"block_id": "H-ITB", "type": "heading",
             "text": "Instructions to Bidders", "order": 1},
            {"block_id": "S-COI", "type": "heading",
             "text": "3 Any conflict of interest on the part of the Bidder must be declared.",
             "order": 2},
            {"block_id": "P-COI", "type": "paragraph",
             "text": "The Bidder shall declare any conflict.", "order": 3},
            {"block_id": "S-TECH-IN-SPAN", "type": "heading",
             "text": "1 METER TECHNICAL SPECIFICATION", "order": 4},
            {"block_id": "P-TECH-IN-SPAN", "type": "paragraph",
             "text": "The meter shall record voltage.", "order": 5},
            {"block_id": "H-TECH", "type": "heading",
             "text": "1 METER TECHNICAL SPECIFICATION", "order": 6},
            {"block_id": "P-TECH", "type": "paragraph",
             "text": "The meter shall log events.", "order": 7},
            {"block_id": "H-PRICE", "type": "heading",
             "text": "Commercial Schedule", "order": 8},
            {"block_id": "P-PRICE", "type": "paragraph",
             "text": "Unit prices shall be quoted in USD.", "order": 9},
            {"block_id": "H-INTRO", "type": "heading",
             "text": "Introduction", "order": 10},
            {"block_id": "P-INTRO", "type": "paragraph",
             "text": "This document describes the procurement.", "order": 11},
            {"block_id": "B-CROSS-A", "type": "paragraph",
             "text": "Conflict clause body.", "order": 12},
            {"block_id": "B-CROSS-B", "type": "paragraph",
             "text": "The meter shall keep a log.", "order": 13},
        ]

    def test_tender_span_inherits_sentence_headings_until_technical_reset(self) -> None:
        """instructions 锚点后的句子型 heading 继承区域；technical 锚点重置为保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            blocks = _blocks_jsonl() + self._tender_span_blocks()
            sections = fe.load_clauses(out) + [
                {
                    "section_id": "3 Any conflict of interest on the part of the Bidder must be declared.",
                    "section_path": [
                        "3 Any conflict of interest on the part of the Bidder must be declared."
                    ],
                    "heading": "3 Any conflict of interest on the part of the Bidder must be declared.",
                    "text": "The Bidder shall declare any conflict.",
                    "block_ids": ["S-COI", "P-COI"],
                },
                {
                    "section_id": "1 METER TECHNICAL SPECIFICATION",
                    "section_path": ["1 METER TECHNICAL SPECIFICATION"],
                    "heading": "1 METER TECHNICAL SPECIFICATION",
                    "text": "The meter shall log events.",
                    "block_ids": ["H-TECH", "P-TECH"],
                },
                {
                    "section_id": "quoted prices",
                    "section_path": ["quoted prices"],
                    "heading": "quoted prices",
                    "text": "Unit prices shall be quoted in USD.",
                    "block_ids": ["P-PRICE"],
                },
                {
                    "section_id": "Introduction body",
                    "section_path": ["Introduction body"],
                    "heading": "This document",
                    "text": "This document describes the procurement.",
                    "block_ids": ["P-INTRO"],
                },
            ]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            kept_ids = {s["section_id"] for s in kept}
            self.assertNotIn(
                "3 Any conflict of interest on the part of the Bidder must be declared.",
                kept_ids)
            self.assertIn("1 METER TECHNICAL SPECIFICATION", kept_ids)
            self.assertNotIn("quoted prices", kept_ids)
            self.assertIn("Introduction body", kept_ids)
            self.assertGreaterEqual(meta["tender_span_routed_out"], 1)
            # WS-B（docs/architecture-convergence-plan-2026-08-27.md）：节级词表
            # 独立分支退役；无义务单元时只走跨度回退。COI 句子 heading 是跨度锚点，
            # 计入 tender_span 而非旧 tender_procedural 词表桶。
            conflict_id = (
                "3 Any conflict of interest on the part of the Bidder must be declared."
            )
            self.assertIn(conflict_id, meta["tender_span_section_ids"])
            self.assertIn(conflict_id, meta["routed_out_section_ids"])
            self.assertIn("quoted prices", meta["tender_span_section_ids"])
            self.assertNotIn(
                "1 METER TECHNICAL SPECIFICATION", meta["tender_span_section_ids"])
            self.assertNotIn("Introduction body", meta["tender_span_section_ids"])

    def test_technical_title_inside_instructions_span_is_kept(self) -> None:
        """条款自带 technical 标题但物理位置在 instructions 跨度内 → 保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            blocks = _blocks_jsonl() + self._tender_span_blocks()
            sections = fe.load_clauses(out) + [{
                "section_id": "1 METER TECHNICAL SPECIFICATION (in span)",
                "section_path": ["1 METER TECHNICAL SPECIFICATION"],
                "heading": "1 METER TECHNICAL SPECIFICATION",
                "text": "The meter shall record voltage.",
                "block_ids": ["S-TECH-IN-SPAN", "P-TECH-IN-SPAN"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn(
                "1 METER TECHNICAL SPECIFICATION (in span)",
                {s["section_id"] for s in kept})
            self.assertNotIn(
                "1 METER TECHNICAL SPECIFICATION (in span)",
                meta.get("tender_span_section_ids", []))

    def test_technical_title_under_procedural_ancestor_path_is_kept(self) -> None:
        """P3（2026-08-27）：程序性命中来自祖先路径元素、条款自身是技术章 → 保留。

        ITB 下挂技术小节是招标文档常见形态：section_path[0]="Instructions to Bidders"
        命中程序性词表，而自身 heading="6 TECHNICAL DATA OF THE METER" 是技术内容——
        旧逐标题分支 any() 命中即整节路由出（内容静默出守恒基线）。修复后与块内/
        跨度分支对称：自身标题（含块内 heading）出现 tender_technical → 保守保留。
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-ITB", "type": "heading",
                 "text": "Instructions to Bidders", "order": 1},
                {"block_id": "S-TECH-NEST", "type": "heading",
                 "text": "6 TECHNICAL DATA OF THE METER", "order": 2},
                {"block_id": "P-TECH-NEST", "type": "paragraph",
                 "text": "The meter shall log load profile data.", "order": 3},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "6 TECHNICAL DATA OF THE METER",
                "section_path": ["Instructions to Bidders", "6 TECHNICAL DATA OF THE METER"],
                "heading": "6 TECHNICAL DATA OF THE METER",
                "text": "The meter shall log load profile data.",
                "block_ids": ["S-TECH-NEST", "P-TECH-NEST"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            kept_ids = {s["section_id"] for s in kept}
            self.assertIn("6 TECHNICAL DATA OF THE METER", kept_ids)
            self.assertNotIn(
                "6 TECHNICAL DATA OF THE METER",
                meta.get("tender_procedural_section_ids", []))

    def test_pure_procedural_own_title_still_routes_out(self) -> None:
        """P3 反例：自身标题程序性且无任何 technical 信号 → 仍逐标题路由出（v4 语义不变）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-ITB2", "type": "heading",
                 "text": "Instructions to Bidders", "order": 1},
                {"block_id": "P-BID", "type": "paragraph",
                 "text": "The Bidder shall submit the bid security.", "order": 2},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "Instructions to Bidders",
                "section_path": ["Instructions to Bidders"],
                "heading": "Instructions to Bidders",
                "text": "The Bidder shall submit the bid security.",
                "block_ids": ["H-ITB2", "P-BID"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertNotIn("Instructions to Bidders", {s["section_id"] for s in kept})
            # WS-B：本夹具未给该节规划义务单元，聚合走跨度回退（ITB heading 是
            # instructions 锚点），不再由节级词表独立分支记入 tender_procedural。
            self.assertIn(
                "Instructions to Bidders",
                meta.get("tender_span_section_ids", []))

    def test_clause_crossing_span_boundary_is_kept(self) -> None:
        """条款块跨越跨度边界（部分在外）→ 保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            blocks = _blocks_jsonl() + self._tender_span_blocks()
            sections = fe.load_clauses(out) + [{
                "section_id": "cross-boundary",
                "section_path": ["cross-boundary"],
                "heading": "cross-boundary",
                "text": "Conflict clause body. The meter shall keep a log.",
                "block_ids": ["P-COI", "P-TECH"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn("cross-boundary", {s["section_id"] for s in kept})
            self.assertNotIn("cross-boundary", meta.get("tender_span_section_ids", []))

    def test_sentence_procedural_headings_routed_by_title_anchor(self) -> None:
        """句子形程序性 heading 自身成为锚点 → 逐标题路由出（不依赖跨度继承）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-TECH-BRO", "type": "heading",
                 "text": "16 Technical Brochures and Technical Data Sheets", "order": 1},
                {"block_id": "S-OEM", "type": "heading",
                 "text": (
                     "26 There shall be no change of Original Equipment Manufacturer "
                     "(OEM) for this tender."
                 ),
                 "order": 2},
                {"block_id": "P-OEM", "type": "paragraph",
                 "text": "Change of OEM is prohibited.", "order": 3},
                {"block_id": "H-METER", "type": "heading",
                 "text": "1 METER TECHNICAL SPECIFICATION", "order": 4},
                {"block_id": "P-METER", "type": "paragraph",
                 "text": "The meter shall log events.", "order": 5},
                {"block_id": "H-CHUNK", "type": "heading",
                 "text": "1.1 Preparation of Bids", "order": 6},
                {"block_id": "P-CHUNK", "type": "paragraph",
                 "text": "Complete the bid submission sheet.", "order": 7},
            ]
            sections = fe.load_clauses(out) + [
                {
                    "section_id": (
                        "26 There shall be no change of Original Equipment Manufacturer "
                        "(OEM) for this tender."
                    ),
                    "section_path": [
                        "26 There shall be no change of Original Equipment Manufacturer "
                        "(OEM) for this tender."
                    ],
                    "heading": (
                        "26 There shall be no change of Original Equipment Manufacturer "
                        "(OEM) for this tender."
                    ),
                    "text": "Change of OEM is prohibited.",
                    "block_ids": ["S-OEM", "P-OEM"],
                },
                {
                    "section_id": "1 METER TECHNICAL SPECIFICATION",
                    "section_path": ["1 METER TECHNICAL SPECIFICATION"],
                    "heading": "1 METER TECHNICAL SPECIFICATION",
                    "text": "The meter shall log events.",
                    "block_ids": ["H-METER", "P-METER"],
                },
                {
                    "section_id": "CH-000004",
                    "section_path": [],
                    "heading": "",
                    "text": "Complete the bid submission sheet.",
                    "block_ids": ["H-CHUNK", "P-CHUNK"],
                },
            ]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            kept_ids = {s["section_id"] for s in kept}
            self.assertNotIn(
                "26 There shall be no change of Original Equipment Manufacturer "
                "(OEM) for this tender.",
                kept_ids,
            )
            self.assertIn("1 METER TECHNICAL SPECIFICATION", kept_ids)
            self.assertNotIn("CH-000004", kept_ids)
            # WS-B：句子锚点仍供给 tender_region_spans；整节路由出改记跨度桶
            # （节级词表独立判定退役）。v4 锚点来源保留。
            oem_id = (
                "26 There shall be no change of Original Equipment Manufacturer "
                "(OEM) for this tender."
            )
            self.assertIn(oem_id, meta["tender_span_section_ids"])
            self.assertIn("CH-000004", meta["tender_span_section_ids"])

    def test_block_only_procedural_heading_kept_when_section_title_technical(self) -> None:
        """块内程序性句 heading 不得把自身 technical 标题的条款一级误路由出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            tech_section_id = "6 TECHNICAL DATA REQUIREMENTS TABLE"
            blocks = _blocks_jsonl() + [
                {"block_id": "H-TECH", "type": "heading",
                 "text": tech_section_id, "order": 1},
                {"block_id": "S-DELIVERY", "type": "heading",
                 "text": (
                     "13 Delivery period is two (2) months or better from receipt "
                     "of order and contract and must be clearly stated;"
                 ),
                 "order": 2},
                {"block_id": "P-TECH", "type": "paragraph",
                 "text": "The meter shall measure voltage.", "order": 3},
            ]
            sections = fe.load_clauses(out) + [
                {
                    "section_id": tech_section_id,
                    "section_path": [tech_section_id],
                    "heading": tech_section_id,
                    "text": "The meter shall measure voltage.",
                    "block_ids": ["H-TECH", "S-DELIVERY", "P-TECH"],
                },
                {
                    "section_id": "CH-000004",
                    "section_path": [],
                    "heading": "",
                    "text": "Complete the bid submission sheet.",
                    "block_ids": ["H-CHUNK", "P-CHUNK"],
                },
            ]
            chunk_blocks = [
                {"block_id": "H-CHUNK", "type": "heading",
                 "text": "1.1 Preparation of Bids", "order": 4},
                {"block_id": "P-CHUNK", "type": "paragraph",
                 "text": "Complete the bid submission sheet.", "order": 5},
            ]
            kept, meta = fe.apply_unit_routing(
                sections, blocks=blocks + chunk_blocks, out_dir=out)
            kept_ids = {s["section_id"] for s in kept}
            self.assertIn(tech_section_id, kept_ids)
            self.assertNotIn(tech_section_id, meta["tender_procedural_section_ids"])
            self.assertNotIn(tech_section_id, meta.get("tender_span_section_ids", []))
            self.assertNotIn("CH-000004", kept_ids)
            # WS-B：CH-000004 无自身标题、块内 Preparation of Bids 是跨度锚点 → span。
            self.assertIn("CH-000004", meta["tender_span_section_ids"])

    def test_front_matter_numbered_definitions_routed_control_kept(self) -> None:
        """编号前缀剥离：'2 DEFINITIONS' 命中；'2 20 Control of' 不命中 definitions。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            sections = fe.load_clauses(out) + [
                {
                    "section_id": "2 DEFINITIONS",
                    "section_path": ["2 DEFINITIONS"],
                    "heading": "2 DEFINITIONS",
                    "text": "For the purpose of this document.",
                    "block_ids": ["B-DEF"],
                },
                {
                    "section_id": "2 20 Control of",
                    "section_path": ["2 20 Control of"],
                    "heading": "2 20 Control of",
                    "text": "The meter shall control disconnection.",
                    "block_ids": ["B-CTL"],
                },
            ]
            kept, meta = fe.apply_unit_routing(
                sections, blocks=_blocks_jsonl(), out_dir=out)
            kept_ids = {s["section_id"] for s in kept}
            self.assertNotIn("2 DEFINITIONS", kept_ids)
            self.assertIn("2 20 Control of", kept_ids)
            self.assertIn("2 DEFINITIONS", meta["front_matter_section_ids"])

    def test_stale_decisions_recomputed_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            rows = [json.loads(line) for line in
                    (out / "unit_routing_decisions.jsonl").read_text(
                        encoding="utf-8").splitlines() if line.strip()]
            rows[0].pop("unit_id")  # 破坏决策与单元集的对应 → 现场重算
            _write_jsonl(out / "unit_routing_decisions.jsonl", rows)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks_jsonl(), out_dir=out)
            self.assertTrue(meta["decisions_recomputed"])
            self.assertEqual([s["section_id"] for s in kept], ["4.1"])

    def test_all_procedural_subject_units_route_section_out(self) -> None:
        """WS-B 聚合正例：全部义务承载单元 procedural_subject → 路由出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            bid_text = "The Bidder shall submit the bid security before opening."
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-BID-S000",
                "unit_kind": "clause_segment",
                "source_text": bid_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    bid_text.encode("utf-8")).hexdigest(),
                "clause_path": ["ITB"],
                "source_block_ids": ["P-BID-AGG"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence", "source_id": "P-BID-AGG#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            units.append(extra_unit)
            _write_jsonl(out / "extraction_units.jsonl", units)
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "P-BID-AGG", "type": "paragraph",
                 "text": bid_text, "order": 20},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "ITB security",
                "section_path": ["ITB security"],
                "heading": "ITB security",
                "text": bid_text,
                "block_ids": ["P-BID-AGG"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertNotIn("ITB security", {s["section_id"] for s in kept})
            self.assertIn("ITB security", meta["tender_procedural_section_ids"])

    def test_mixed_product_obligation_keeps_section(self) -> None:
        """WS-B 聚合反例：同节混入产品义务单元 → 整节保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            bid_text = "The Bidder shall submit the bid security."
            meter_text = "The meter shall log events."
            extra = []
            for uid, text, bid in (
                ("UNIT-MIX-BID", bid_text, "P-MIX-BID"),
                ("UNIT-MIX-METER", meter_text, "P-MIX-METER"),
            ):
                extra.append({
                    "schema": "extraction-unit/v1",
                    "unit_id": uid,
                    "unit_kind": "clause_segment",
                    "source_text": text,
                    "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                        text.encode("utf-8")).hexdigest(),
                    "clause_path": ["mixed"],
                    "source_block_ids": [bid],
                    "roles": ["requirement_candidate"],
                    "context_refs": [],
                    "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                    "locator": {"source_type": "block_sentence", "source_id": f"{bid}#0"},
                })
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + extra)
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "P-MIX-BID", "type": "paragraph",
                 "text": bid_text, "order": 21},
                {"block_id": "P-MIX-METER", "type": "paragraph",
                 "text": meter_text, "order": 22},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "15 GUARANTEED LIFE SPAN",
                "section_path": ["15 GUARANTEED LIFE SPAN"],
                "heading": "15 GUARANTEED LIFE SPAN",
                "text": f"{bid_text} {meter_text}",
                "block_ids": ["P-MIX-BID", "P-MIX-METER"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn("15 GUARANTEED LIFE SPAN", {s["section_id"] for s in kept})
            self.assertNotIn(
                "15 GUARANTEED LIFE SPAN",
                meta.get("tender_procedural_section_ids", []))
            self.assertNotIn(
                "15 GUARANTEED LIFE SPAN",
                meta.get("tender_span_section_ids", []))

    def test_technical_title_still_protects_aggregation(self) -> None:
        """WS-B：technical 硬信号保护在聚合路径仍生效。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            bid_text = "The Bidder shall submit the bid security."
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-TECH-BID",
                "unit_kind": "clause_segment",
                "source_text": bid_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    bid_text.encode("utf-8")).hexdigest(),
                "clause_path": ["tech"],
                "source_block_ids": ["P-TECH-BID"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence",
                            "source_id": "P-TECH-BID#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + [extra_unit])
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-TECH-KEEP", "type": "heading",
                 "text": "6 TECHNICAL DATA OF THE METER", "order": 30},
                {"block_id": "P-TECH-BID", "type": "paragraph",
                 "text": bid_text, "order": 31},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "6 TECHNICAL DATA OF THE METER",
                "section_path": ["6 TECHNICAL DATA OF THE METER"],
                "heading": "6 TECHNICAL DATA OF THE METER",
                "text": bid_text,
                "block_ids": ["H-TECH-KEEP", "P-TECH-BID"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn(
                "6 TECHNICAL DATA OF THE METER", {s["section_id"] for s in kept})
            self.assertNotIn(
                "6 TECHNICAL DATA OF THE METER",
                meta.get("tender_procedural_section_ids", []))

    def test_product_obligation_in_procedural_span_is_kept(self) -> None:
        """产品义务句落在程序性跨度内仍保留（跨度不得吞产品主体）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            meter_text = (
                "The meter shall have a guaranteed life span of 15 years "
                "and a failure rate not exceeding 3%."
            )
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-LIFE-METER",
                "unit_kind": "clause_segment",
                "source_text": meter_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    meter_text.encode("utf-8")).hexdigest(),
                "clause_path": ["life"],
                "source_block_ids": ["P-LIFE"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence",
                            "source_id": "P-LIFE#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + [extra_unit])
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-ITB-LIFE", "type": "heading",
                 "text": "Instructions to Bidders", "order": 40},
                {"block_id": "H-LIFE", "type": "heading",
                 "text": "15 GUARANTEED LIFE SPAN", "order": 41},
                {"block_id": "P-LIFE", "type": "paragraph",
                 "text": meter_text, "order": 42},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "15 GUARANTEED LIFE SPAN",
                "section_path": ["15 GUARANTEED LIFE SPAN"],
                "heading": "15 GUARANTEED LIFE SPAN",
                "text": meter_text,
                "block_ids": ["H-LIFE", "P-LIFE"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn("15 GUARANTEED LIFE SPAN", {s["section_id"] for s in kept})
            self.assertNotIn(
                "15 GUARANTEED LIFE SPAN",
                meta.get("tender_span_section_ids", []))

    def test_title_prior_routes_certificate_subject_out(self) -> None:
        """R2：标题词表程序性 + 非产品主语（certificate shall）→ 路由出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            cert_text = "The tax clearance certificate shall be valid for the bid."
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-TAX-CERT",
                "unit_kind": "clause_segment",
                "source_text": cert_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    cert_text.encode("utf-8")).hexdigest(),
                "clause_path": ["tax"],
                "source_block_ids": ["P-TAX-CERT"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence",
                            "source_id": "P-TAX-CERT#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + [extra_unit])
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-TAX-CERT", "type": "heading",
                 "text": "11 Valid Tax Clearance Certificate", "order": 50},
                {"block_id": "P-TAX-CERT", "type": "paragraph",
                 "text": cert_text, "order": 51},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "11 Valid Tax Clearance Certificate",
                "section_path": ["11 Valid Tax Clearance Certificate"],
                "heading": "11 Valid Tax Clearance Certificate",
                "text": cert_text,
                "block_ids": ["H-TAX-CERT", "P-TAX-CERT"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertNotIn(
                "11 Valid Tax Clearance Certificate", {s["section_id"] for s in kept})
            self.assertIn(
                "11 Valid Tax Clearance Certificate",
                meta.get("tender_procedural_section_ids", []))

    def test_title_prior_product_subject_keeps_section(self) -> None:
        """R2 反例：程序性标题下的产品主语句不得路由出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            meter_text = "The meter shall attach a tax clearance certificate."
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-TAX-METER",
                "unit_kind": "clause_segment",
                "source_text": meter_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    meter_text.encode("utf-8")).hexdigest(),
                "clause_path": ["tax"],
                "source_block_ids": ["P-TAX-METER"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence",
                            "source_id": "P-TAX-METER#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + [extra_unit])
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-TAX-METER", "type": "heading",
                 "text": "11 Valid Tax Clearance Certificate", "order": 52},
                {"block_id": "P-TAX-METER", "type": "paragraph",
                 "text": meter_text, "order": 53},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "11 Valid Tax Clearance Certificate",
                "section_path": ["11 Valid Tax Clearance Certificate"],
                "heading": "11 Valid Tax Clearance Certificate",
                "text": meter_text,
                "block_ids": ["H-TAX-METER", "P-TAX-METER"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn(
                "11 Valid Tax Clearance Certificate", {s["section_id"] for s in kept})
            self.assertNotIn(
                "11 Valid Tax Clearance Certificate",
                meta.get("tender_procedural_section_ids", []))

    def test_swallowed_technical_heading_does_not_block_own_procedural_title(self) -> None:
        """块流吞进的 technical heading 不得否决自身程序性标题（供货历史残骸）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            hist_text = (
                "The manufacturer shall submit supply history for the past five years."
            )
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-HIST",
                "unit_kind": "clause_segment",
                "source_text": hist_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    hist_text.encode("utf-8")).hexdigest(),
                "clause_path": ["hist"],
                "source_block_ids": ["P-HIST"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence",
                            "source_id": "P-HIST#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + [extra_unit])
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-HIST", "type": "heading",
                 "text": "22 Manufacturer's supply history for the past five years",
                 "order": 60},
                {"block_id": "P-HIST", "type": "paragraph",
                 "text": hist_text, "order": 61},
                {"block_id": "H-SWALLOW", "type": "heading",
                 "text": "23 Compliance statement to the technical specification",
                 "order": 62},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "22 Manufacturer's supply history for the past five years",
                "section_path": [
                    "22 Manufacturer's supply history for the past five years"
                ],
                "heading": "22 Manufacturer's supply history for the past five years",
                "text": hist_text,
                "block_ids": ["H-HIST", "P-HIST", "H-SWALLOW"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertNotIn(
                "22 Manufacturer's supply history for the past five years",
                {s["section_id"] for s in kept})
            routed = set(meta.get("tender_procedural_section_ids") or []) | set(
                meta.get("tender_span_section_ids") or [])
            self.assertIn(
                "22 Manufacturer's supply history for the past five years", routed)

    def test_life_span_title_is_not_procedural_prior(self) -> None:
        """15 GUARANTEED LIFE SPAN 标题不在程序性词表，产品句保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            meter_text = (
                "The meter shall have a guaranteed life span of 15 years "
                "and a failure rate not exceeding 3%."
            )
            extra_unit = {
                "schema": "extraction-unit/v1",
                "unit_id": "UNIT-LIFE-PRIOR",
                "unit_kind": "clause_segment",
                "source_text": meter_text,
                "source_text_hash": "sha256:" + __import__("hashlib").sha256(
                    meter_text.encode("utf-8")).hexdigest(),
                "clause_path": ["life"],
                "source_block_ids": ["P-LIFE-PRIOR"],
                "roles": ["requirement_candidate"],
                "context_refs": [],
                "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                "locator": {"source_type": "block_sentence",
                            "source_id": "P-LIFE-PRIOR#0"},
            }
            units = [json.loads(line) for line in
                     (out / "extraction_units.jsonl").read_text(
                         encoding="utf-8").splitlines() if line.strip()]
            _write_jsonl(out / "extraction_units.jsonl", units + [extra_unit])
            (out / "unit_routing_decisions.jsonl").unlink(missing_ok=True)
            blocks = _blocks_jsonl() + [
                {"block_id": "H-LIFE-PRIOR", "type": "heading",
                 "text": "15 GUARANTEED LIFE SPAN", "order": 54},
                {"block_id": "P-LIFE-PRIOR", "type": "paragraph",
                 "text": meter_text, "order": 55},
            ]
            sections = fe.load_clauses(out) + [{
                "section_id": "15 GUARANTEED LIFE SPAN",
                "section_path": ["15 GUARANTEED LIFE SPAN"],
                "heading": "15 GUARANTEED LIFE SPAN",
                "text": meter_text,
                "block_ids": ["H-LIFE-PRIOR", "P-LIFE-PRIOR"],
            }]
            kept, meta = fe.apply_unit_routing(sections, blocks=blocks, out_dir=out)
            self.assertIn("15 GUARANTEED LIFE SPAN", {s["section_id"] for s in kept})
            self.assertNotIn(
                "15 GUARANTEED LIFE SPAN",
                meta.get("tender_procedural_section_ids", []))


class RunIntegrationTests(unittest.TestCase):
    def test_legacy_strategy_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            result = fe.run_functional_extract(out, route="stub", strategy="legacy")
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["clause_count"], 2)
            self.assertNotIn("unit_routing", payload)
            self.assertNotIn("unit_routing", result)
            self.assertEqual(result["execution_status"], "ok")

    def test_unset_strategy_routes_like_clause_family_when_extract_on(self) -> None:
        """直抽默认开且未指定策略 → 生效 clause_family，表格条款被路由出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RATOMIZER_CONTEXT_PACK_STRATEGY", None)
                os.environ.pop("RATOMIZER_FUNCTIONAL_EXTRACT", None)
                result = fe.run_functional_extract(out, route="stub")
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            routing = payload["unit_routing"]
            self.assertEqual(result["unit_routing"]["status"], "ok")
            self.assertEqual(routing["status"], "ok")
            self.assertEqual(routing["table_dominated_routed_out"], 1)
            self.assertEqual(routing["routed_out_section_ids"], ["4.2"])

    def test_clause_family_routes_out_table_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            result = fe.run_functional_extract(
                out, route="stub", strategy="clause_family")
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["clause_count"], 1)
            routing = payload["unit_routing"]
            self.assertEqual(routing["status"], "ok")
            self.assertEqual(routing["table_dominated_routed_out"], 1)
            self.assertEqual(routing["routed_out_section_ids"], ["4.2"])
            self.assertEqual(routing["sections_total"], 2)
            self.assertEqual(routing["sections_extracted"], 1)
            self.assertEqual(
                routing["routing_version"], fe.FUNCTIONAL_UNIT_ROUTING_VERSION)
            self.assertTrue(payload["conservation"].get("ok"))
            self.assertEqual(result["unit_routing"]["table_dominated_routed_out"], 1)
            # 条目只来自保留条款——表格条款的 stub 项不再产生
            self.assertTrue(all(
                "B2" not in (item.get("source_block_ids") or [])
                for item in payload["items"]))

    def test_clause_family_caches_routing_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            fe.run_functional_extract(out, route="stub", strategy="clause_family")
            (out / "functional_requirements.json").unlink()
            replay = fe.run_functional_extract(out, route="stub",
                                               strategy="clause_family")
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            # 缓存命中补写也携带路由审计块（指纹含路由维度，重放即同语义）
            self.assertIn("unit_routing", payload)
            self.assertEqual(replay["clause_count"], 1)


class FingerprintScopingTests(unittest.TestCase):
    SECTIONS = [{"section_id": "4.1", "section_path": ["4.1"],
                 "heading": "4.1", "text": B1_TEXT, "block_ids": ["B1"]}]

    def test_legacy_fingerprint_ignores_routing_version(self) -> None:
        before = fe.extraction_fingerprint(self.SECTIONS, route_key="stub")
        with mock.patch.object(fe, "FUNCTIONAL_UNIT_ROUTING_VERSION",
                               "functional-unit-routing-v9"):
            after = fe.extraction_fingerprint(self.SECTIONS, route_key="stub")
            clause_family = fe.extraction_fingerprint(
                self.SECTIONS, route_key="stub", context_strategy="clause_family")
        self.assertEqual(before, after)
        self.assertNotEqual(before, clause_family)

    def test_clause_family_fingerprint_tracks_routing_version(self) -> None:
        first = fe.extraction_fingerprint(
            self.SECTIONS, route_key="stub", context_strategy="clause_family")
        with mock.patch.object(fe, "FUNCTIONAL_UNIT_ROUTING_VERSION",
                               "functional-unit-routing-v9"):
            second = fe.extraction_fingerprint(
                self.SECTIONS, route_key="stub", context_strategy="clause_family")
        self.assertNotEqual(first, second)

    def test_routing_key_pins_all_three_versions(self) -> None:
        key = fe._unit_routing_key()
        self.assertIn(fe.FUNCTIONAL_UNIT_ROUTING_VERSION, key)
        self.assertIn(EXTRACTION_UNIT_PLANNER_VERSION, key)
        self.assertIn(UNIT_ROUTER_VERSION, key)
        # P2（2026-08-27）：路由判定消费 tender_regions 词表（逐标题/跨度/句子锚点）
        # ——词表版本必须进键，否则改词表只有人工 bump 接线版本才失效。
        from tender_regions import TENDER_REGION_FILTER_VERSION
        self.assertIn(TENDER_REGION_FILTER_VERSION, key)
        # P1：血统版本单源供 stage producer 与缓存键共用，两侧不漂移
        self.assertEqual("|".join(fe.routing_lineage_versions().values()), key)


class ReextractParityTests(unittest.TestCase):
    def test_reextract_baseline_scoped_to_routed_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out)
            fe.run_functional_extract(
                out, chat=_chat_prose, route="openai_compatible",
                strategy="clause_family")
            mutation = functional_reextract.functional_targeted_reextract(
                out, affected_block_ids=["B1"],
                expected_product_fingerprint="", route="openai_compatible",
                chat=_chat_prose)
            self.assertTrue(mutation["conservation_ok"])
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            # 重抽产物保留策略身份 + 刷新路由审计块（后续重抽同口径）
            self.assertEqual(payload["context_pack_strategy"], "clause_family")
            self.assertEqual(payload["unit_routing"]["table_dominated_routed_out"], 1)


if __name__ == "__main__":
    unittest.main()
