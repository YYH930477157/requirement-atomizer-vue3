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
