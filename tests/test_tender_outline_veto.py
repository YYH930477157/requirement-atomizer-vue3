"""tender 路由连坐的窄门修（routing v7）：聚合路由出之前，条款内 confirmed 的
被吞并 heading 先切开再分别路由——程序性残骸照旧路由出，被连坐的技术内容
得到独立判定的机会（result3 实证：2.3 STATEMENT OF REQUIREMENTS 整章被
利益冲突条款连坐路由出，根本不进抽取）。

纯切分语义：只在 confirmed 吞并 heading 处切开、块零位移（不做 toc 剔除/
demoted 并入——那是 outline authority flag 的语义，不进路由层）；无吞并或
仅 suspect/toc 吞并时行为与 v6 逐字节一致。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import functional_extract as fe
from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
from unit_router import UNIT_ROUTER_VERSION

H0_TEXT = "3 Any conflict of interest on the part of the Bidder must be declared."
H2_TEXT = "2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)"
B1_TEXT = "The Bidder shall declare any conflict of interest in writing."
B2_TEXT = "The equipment shall be designed for prepaid metering operations."


def _blocks(with_tail: str | None = None) -> list[dict]:
    rows = [
        {"block_id": "H0", "type": "heading", "text": H0_TEXT, "order": 1,
         "section_path": [H0_TEXT]},
        {"block_id": "B1", "type": "paragraph", "text": B1_TEXT, "order": 2,
         "section_path": [H0_TEXT]},
    ]
    if with_tail is not None:
        rows.append({"block_id": "HT", "type": "heading", "text": with_tail,
                     "order": 3, "section_path": [H0_TEXT]})
        rows.append({"block_id": "B2", "type": "paragraph", "text": B2_TEXT,
                     "order": 4, "section_path": [H0_TEXT]})
    return rows


def _chunk(with_tail: str | None = None) -> dict:
    ids = ["H0", "B1"] + (["HT", "B2"] if with_tail is not None else [])
    return {"section_path": [H0_TEXT], "heading": H0_TEXT,
            "block_ids": ids,
            "text": "\n\n".join(
                {"H0": H0_TEXT, "B1": B1_TEXT, "HT": with_tail or "",
                 "B2": B2_TEXT}[bid] for bid in ids)}


def _unit(unit_id: str, block_id: str, text: str) -> dict:
    import hashlib

    return {
        "schema": "extraction-unit/v1", "unit_id": unit_id,
        "unit_kind": "clause_segment", "source_text": text,
        "source_text_hash": "sha256:" + hashlib.sha256(
            text.encode("utf-8")).hexdigest(),
        "clause_path": [H0_TEXT], "source_block_ids": [block_id],
        "roles": ["requirement_candidate"], "context_refs": [],
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": {"source_type": "block_sentence", "source_id": f"{block_id}#0"},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")


def _seed(out: Path, with_tail: str | None = None) -> None:
    _write_jsonl(out / "blocks.jsonl", _blocks(with_tail))
    _write_jsonl(out / "chunks.jsonl", [_chunk(with_tail)])
    units = [_unit("UNIT-B1", "B1", B1_TEXT)]
    if with_tail is not None:
        units.append(_unit("UNIT-B2", "B2", B2_TEXT))
    decisions = [
        {"schema": "unit-routing-decision/v1", "unit_id": unit["unit_id"],
         "route": "b_track", "procedural_subject": True,
         "router_version": UNIT_ROUTER_VERSION}
        for unit in units
    ]
    _write_jsonl(out / "extraction_units.jsonl", units)
    _write_jsonl(out / "unit_routing_decisions.jsonl", decisions)


def _union_block_ids(sections: list[dict]) -> set[str]:
    seen: set[str] = set()
    for section in sections:
        seen.update(str(b) for b in (section.get("block_ids") or []))
    return seen


class TenderOutlineVetoTests(unittest.TestCase):
    def test_confirmed_swallowed_heading_splits_before_tender_route_out(self) -> None:
        """2.3 形态：confirmed 吞并 heading 切开——技术片保留，程序片照旧路由出。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, with_tail=H2_TEXT)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks(H2_TEXT), out_dir=out)

        self.assertEqual(
            [str(s.get("section_id")) for s in kept], [H2_TEXT],
            "被吞并的 technical heading 条款应获得独立路由判定并被保留",
        )
        self.assertEqual(meta.get("outline_veto_split_sections"), 1)
        self.assertEqual(meta.get("outline_veto_split_block_ids"), ["HT"])
        # 块守恒：kept + routed_out 恰好等于输入块集（纯切分零位移）
        routed_ids = set(meta.get("routed_out_block_ids") or [])
        self.assertEqual(
            _union_block_ids(kept) | routed_ids, {"H0", "B1", "HT", "B2"})
        # 技术片带上 heading 派生身份（不继承利益冲突父链）
        self.assertEqual(kept[0].get("section_path"), [H2_TEXT])
        self.assertIn("prepaid metering", str(kept[0].get("text") or ""))

    def test_no_swallowed_heading_routes_out_whole_as_v6(self) -> None:
        """无吞并 heading：行为与 v6 一致——整条款路由出，无切分。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks(), out_dir=out)

        self.assertEqual(kept, [])
        self.assertEqual(meta.get("tender_procedural_routed_out"), 1)
        self.assertEqual(meta.get("outline_veto_split_sections"), 0)

    def test_toc_swallowed_heading_does_not_split(self) -> None:
        """toc_entry 吞并不是切分点（宁漏勿错：只有 confirmed 才切）。"""
        toc_tail = "2.3 List of requirements .......... 15"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, with_tail=toc_tail)
            kept, meta = fe.apply_unit_routing(
                fe.load_clauses(out), blocks=_blocks(toc_tail), out_dir=out)

        self.assertEqual(kept, [])
        self.assertEqual(meta.get("outline_veto_split_sections"), 0)


if __name__ == "__main__":
    unittest.main()
