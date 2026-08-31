"""routing v8：heading-only 条款出抽取池（2026-08-31）。

SBD result3 实证：TGS 章 24 个「只有标题没有正文」的条款进了 B 轨抽取池——LLM
失败退化 stub（objective 模板回显 heading），成功也只能回显标题（零义务内容）。
本测试钉住新判据的三条（无实质正文/零义务单元/无表格块）与宁漏勿错反例：
非 heading 实质文本在场（含 v6 碎片过滤会剔掉义务的碎片正文）一律保留。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import functional_extract as fe
import functional_reextract
from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
from unit_router import UNIT_ROUTER_VERSION

TGS_HEADING = "22.6.5. LOAD PROFILES OF METERED VALUES - TGS"
OBLIGATION_TEXT = "The meter shall log quality events with a timestamp."


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")


def _seed(out: Path, blocks: list[dict], chunks: list[dict]) -> None:
    _write_jsonl(out / "blocks.jsonl", blocks)
    _write_jsonl(out / "chunks.jsonl", chunks)


def _basic_blocks() -> list[dict]:
    """一个 heading-only 条款（TGS）+ 一个正常义务条款（4.1）。"""
    return [
        {"block_id": "H-TGS", "type": "heading",
         "section_path": [TGS_HEADING], "text": TGS_HEADING, "order": 1},
        {"block_id": "B1", "type": "paragraph", "section_path": ["4.1"],
         "text": OBLIGATION_TEXT, "order": 2},
    ]


def _basic_chunks() -> list[dict]:
    return [
        {"section_path": [TGS_HEADING], "heading": TGS_HEADING,
         "text": TGS_HEADING, "block_ids": ["H-TGS"]},
        {"section_path": ["4.1"], "heading": "4.1", "text": OBLIGATION_TEXT,
         "block_ids": ["B1"]},
    ]


class HeadingOnlyRoutingTests(unittest.TestCase):
    def test_heading_only_section_routed_out(self) -> None:
        """正例：单 heading 块、无正文 → heading_only 路由出 + meta 审计完整。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, _basic_blocks(), _basic_chunks())
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_basic_blocks(), out_dir=out)
            self.assertEqual(meta["status"], "ok")
            self.assertEqual([s["section_id"] for s in kept], ["4.1"])
            self.assertEqual(meta["heading_only_sections_routed_out"], 1)
            self.assertEqual(meta["heading_only_section_ids"], [TGS_HEADING])
            self.assertIn(TGS_HEADING, meta["routed_out_section_ids"])
            self.assertIn("H-TGS", meta["routed_out_block_ids"])

    def test_heading_plus_obligation_body_is_kept(self) -> None:
        """反例：heading + 一句义务正文（shall）→ 保留。"""
        blocks = [
            {"block_id": "H-TGS", "type": "heading",
             "section_path": [TGS_HEADING], "text": TGS_HEADING, "order": 1},
            {"block_id": "P1", "type": "paragraph",
             "section_path": [TGS_HEADING],
             "text": "The meter shall store load profiles of metered values.",
             "order": 2},
        ]
        chunks = [{
            "section_path": [TGS_HEADING], "heading": TGS_HEADING,
            "text": TGS_HEADING
                    + "\nThe meter shall store load profiles of metered values.",
            "block_ids": ["H-TGS", "P1"],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, blocks, chunks)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=blocks, out_dir=out)
            self.assertEqual([s["section_id"] for s in kept], [TGS_HEADING])
            self.assertEqual(meta["heading_only_sections_routed_out"], 0)
            self.assertEqual(meta["heading_only_section_ids"], [])

    def test_fragment_body_is_kept(self) -> None:
        """关键宁漏勿错钉：正文是碎片（内容词<2，v6 碎片过滤后义务单元数 0）。

        这种条款的义务单元数确实为 0，但正文非空——判据一（非 heading 实质文本
        在场）必须挡住它不误杀。
        """
        fragment = "will be issued and"
        section = {
            "section_id": TGS_HEADING, "section_path": [TGS_HEADING],
            "heading": TGS_HEADING,
            "text": TGS_HEADING + "\n" + fragment,
            "block_ids": ["H-TGS", "P1"],
        }
        # 前提自证：该条款经 v6 碎片过滤后义务单元数确实为 0（碎片被剔）。
        rows, fragments = fe._obligation_index_with_fragment_audit(section)
        self.assertEqual(rows, [])
        self.assertEqual(fragments, 1)
        blocks = [
            {"block_id": "H-TGS", "type": "heading",
             "section_path": [TGS_HEADING], "text": TGS_HEADING, "order": 1},
            {"block_id": "P1", "type": "paragraph",
             "section_path": [TGS_HEADING], "text": fragment, "order": 2},
        ]
        chunks = [{
            "section_path": [TGS_HEADING], "heading": TGS_HEADING,
            "text": TGS_HEADING + "\n" + fragment,
            "block_ids": ["H-TGS", "P1"],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, blocks, chunks)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=blocks, out_dir=out)
            self.assertEqual([s["section_id"] for s in kept], [TGS_HEADING])
            self.assertEqual(meta["heading_only_sections_routed_out"], 0)

    def test_heading_plus_table_block_not_heading_only(self) -> None:
        """反例：heading + 表格块 → 不走 heading_only 通道；表格路由通道行为不变。"""
        table_text = "[TBL-000001] Table 1 - Limits\nVoltage | Limit\n230 | 240"
        blocks = [
            {"block_id": "H-TGS", "type": "heading",
             "section_path": [TGS_HEADING], "text": TGS_HEADING, "order": 1},
            {"block_id": "T1", "type": "table",
             "section_path": [TGS_HEADING], "text": table_text, "order": 2},
            {"block_id": "T2", "type": "table", "section_path": ["4.2"],
             "text": table_text, "order": 3},
        ]
        chunks = [
            {"section_path": [TGS_HEADING], "heading": TGS_HEADING,
             "text": TGS_HEADING + "\n" + table_text,
             "block_ids": ["H-TGS", "T1"]},
            {"section_path": ["4.2"], "heading": "4.2", "text": table_text,
             "block_ids": ["T2"]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, blocks, chunks)
            # 表格解析在场性护栏 + 表格单元 context 路由（复用既有 fixture 形态）。
            _write_jsonl(out / "table_items.jsonl", [{
                "item_id": "TBLI-1", "table_id": "TBL-000001",
                "table_block_id": "T1", "leaf_role": "row", "row_index": 1,
                "text": "230 | 240", "section_path": [TGS_HEADING],
                "fields": {"Voltage": "230", "Limit": "240"},
            }])
            units = []
            decisions = []
            for index, bid in enumerate(["T1", "T2"]):
                unit_id = f"UNIT-C{index + 1}"
                units.append({
                    "schema": "extraction-unit/v1", "unit_id": unit_id,
                    "unit_kind": "table_cell", "source_text": "230",
                    "source_text_hash": "sha256:"
                        + __import__("hashlib").sha256(b"230").hexdigest(),
                    "clause_path": [TGS_HEADING if bid == "T1" else "4.2"],
                    "source_block_ids": [bid], "roles": ["context"],
                    "context_refs": [],
                    "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
                    "locator": {"source_type": "table_cell",
                                "source_id": unit_id},
                    "table_context": {"table_id": "TBL-000001",
                                      "cell_id": unit_id,
                                      "disposition": "context"},
                })
                decisions.append({
                    "schema": "unit-routing-decision/v1", "unit_id": unit_id,
                    "route": "context",
                    "router_version": UNIT_ROUTER_VERSION,
                })
            _write_jsonl(out / "extraction_units.jsonl", units)
            _write_jsonl(out / "unit_routing_decisions.jsonl", decisions)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=blocks, out_dir=out)
            # heading+表格混合条款走既有 mixed 保留；纯表格条款走既有表格通道路由出。
            self.assertEqual(meta["heading_only_sections_routed_out"], 0)
            self.assertEqual([s["section_id"] for s in kept], [TGS_HEADING])
            self.assertEqual(meta["mixed_table_sections_kept"], 1)
            self.assertEqual(meta["table_dominated_routed_out"], 1)
            self.assertEqual(meta["routed_out_section_ids"], ["4.2"])

    def test_v8_in_routing_lineage_versions(self) -> None:
        """版本断言：v8 经 routing_lineage_versions 自动进缓存键与 stage producer。"""
        self.assertEqual(
            fe.FUNCTIONAL_UNIT_ROUTING_VERSION, "functional-unit-routing-v8")
        self.assertEqual(
            fe.routing_lineage_versions()["functional_unit_routing"],
            "functional-unit-routing-v8")

    def test_routed_heading_only_absent_from_conservation_baseline(self) -> None:
        """守恒基线：路由出的 heading-only 条款不出现在 conservation_report 里。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, _basic_blocks(), _basic_chunks())
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_basic_blocks(), out_dir=out)
            self.assertEqual(meta["heading_only_sections_routed_out"], 1)
            report = fe.conservation_report(
                kept, [], blocks=_basic_blocks(), out_dir=out)
            dumped = json.dumps(report, ensure_ascii=False)
            self.assertNotIn(TGS_HEADING, dumped)
            self.assertNotIn("H-TGS", dumped)
            # 保留条款仍在基线里（items 为空 → 4.1 如实未覆盖）。
            self.assertIn("4.1", dumped)

    def test_reextract_reuses_apply_unit_routing_authority(self) -> None:
        """functional_reextract 复用同一 apply_unit_routing 权威（不复制判定）。

        clause_family 产物的重抽条款池用当前代码确定性重算路由——patch 路由
        权威使其路由出全部条款，重抽必须因"无功能范围"响亮失败且权威被调用。
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, _basic_blocks(), _basic_chunks())
            (out / "functional_requirements.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "producer": "functional-extract-v1",
                    "context_pack_strategy": "clause_family",
                    "items": [],
                }, ensure_ascii=False),
                encoding="utf-8")
            with mock.patch.object(
                fe, "apply_unit_routing",
                return_value=([], {"status": "ok"}),
            ) as routing:
                with self.assertRaises(
                    functional_reextract.FunctionalReextractError,
                ) as ctx:
                    functional_reextract.functional_targeted_reextract(
                        out, affected_block_ids=["B1"],
                        expected_product_fingerprint="", route="stub")
                self.assertTrue(routing.called)
                self.assertIn("routed out", str(ctx.exception))


class HeadingOnlyPredicateTests(unittest.TestCase):
    """判据单元级钉子（保守分支逐条钉住）。"""

    def _blocks_by_id(self, blocks: list[dict]) -> dict[str, dict]:
        return {str(b["block_id"]): b for b in blocks}

    def test_missing_block_keeps_section(self) -> None:
        section = {"section_id": TGS_HEADING, "section_path": [TGS_HEADING],
                   "heading": TGS_HEADING, "text": TGS_HEADING,
                   "block_ids": ["H-MISSING"]}
        self.assertFalse(
            fe._section_is_heading_only(section, {}, set()))

    def test_empty_block_ids_keeps_section(self) -> None:
        section = {"section_id": TGS_HEADING, "section_path": [TGS_HEADING],
                   "heading": TGS_HEADING, "text": TGS_HEADING,
                   "block_ids": []}
        self.assertFalse(fe._section_is_heading_only(section, {}, set()))

    def test_heading_echo_paragraph_still_heading_only(self) -> None:
        """正文块只是 heading 的逐字回显（解析器双写）→ 仍是 heading-only。"""
        blocks = [
            {"block_id": "H1", "type": "heading", "text": TGS_HEADING},
            {"block_id": "P1", "type": "paragraph",
             "text": "LOAD PROFILES OF METERED VALUES - TGS"},
        ]
        section = {"section_id": TGS_HEADING, "section_path": [TGS_HEADING],
                   "heading": TGS_HEADING,
                   "text": TGS_HEADING
                           + "\nLOAD PROFILES OF METERED VALUES - TGS",
                   "block_ids": ["H1", "P1"]}
        self.assertTrue(fe._section_is_heading_only(
            section, self._blocks_by_id(blocks), set()))

    def test_bare_number_body_keeps_section(self) -> None:
        """正文块只剩一个数字（"42."）→ 数字是内容，保守保留。"""
        blocks = [
            {"block_id": "H1", "type": "heading", "text": TGS_HEADING},
            {"block_id": "P1", "type": "paragraph", "text": "42."},
        ]
        section = {"section_id": TGS_HEADING, "section_path": [TGS_HEADING],
                   "heading": TGS_HEADING, "text": TGS_HEADING + "\n42.",
                   "block_ids": ["H1", "P1"]}
        self.assertFalse(fe._section_is_heading_only(
            section, self._blocks_by_id(blocks), set()))

    def test_table_block_never_heading_only(self) -> None:
        blocks = [
            {"block_id": "H1", "type": "heading", "text": TGS_HEADING},
            {"block_id": "T1", "type": "table", "text": "a | b"},
        ]
        section = {"section_id": TGS_HEADING, "section_path": [TGS_HEADING],
                   "heading": TGS_HEADING, "text": TGS_HEADING,
                   "block_ids": ["H1", "T1"]}
        self.assertFalse(fe._section_is_heading_only(
            section, self._blocks_by_id(blocks), {"T1"}))

    def test_no_heading_identity_keeps_section(self) -> None:
        """无任何 heading 身份（heading/section_path/heading 块全空）→ 保留。"""
        blocks = [{"block_id": "P1", "type": "paragraph", "text": "…—…"}]
        section = {"section_id": "", "section_path": [], "heading": "",
                   "text": "…—…", "block_ids": ["P1"]}
        self.assertFalse(fe._section_is_heading_only(
            section, self._blocks_by_id(blocks), set()))


if __name__ == "__main__":
    unittest.main()
