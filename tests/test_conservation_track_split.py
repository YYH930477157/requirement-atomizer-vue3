"""WS-A（2026-08-27）：守恒基线按单元类型分轨。

方案：docs/architecture-convergence-plan-2026-08-27.md §WS-A。
a_track/context 表格单元的数字不进 narrative preservation，改记
delegated_to_cell_conservation；dispositions 缺席时该表格块退回全量基线。
无 out_dir 的直调（legacy 路径）与分轨前语义一致。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import functional_extract as fe
from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
from unit_router import UNIT_ROUTER_VERSION


PROSE = "The meter shall log quality events with a timestamp."
TABLE_FLAT = (
    "[TBL-000001] TECHNICAL DATA\n"
    "Voltage | 230\n"
    "Current | 5"
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prose_unit() -> dict:
    return {
        "schema": "extraction-unit/v1",
        "unit_id": "UNIT-P1-S000",
        "unit_kind": "clause_segment",
        "source_text": PROSE,
        "source_text_hash": "sha256:" + __import__("hashlib").sha256(
            PROSE.encode("utf-8")).hexdigest(),
        "clause_path": ["6"],
        "source_block_ids": ["P1"],
        "roles": ["requirement_candidate"],
        "context_refs": [],
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": {"source_type": "block_sentence", "source_id": "P1#0"},
    }


def _cell_unit(uid: str, text: str, block_id: str = "T1") -> dict:
    return {
        "schema": "extraction-unit/v1",
        "unit_id": uid,
        "unit_kind": "table_cell",
        "source_text": text,
        "source_text_hash": "sha256:" + __import__("hashlib").sha256(
            text.encode("utf-8")).hexdigest(),
        "clause_path": ["6"],
        "source_block_ids": [block_id],
        "roles": ["context"],
        "context_refs": [],
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": {"source_type": "table_cell", "source_id": uid},
        "table_context": {
            "table_id": "TBL-000001", "cell_id": uid, "disposition": "context",
        },
    }


def _decision(unit_id: str, route: str) -> dict:
    return {
        "schema": "unit-routing-decision/v1",
        "unit_id": unit_id,
        "route": route,
        "router_version": UNIT_ROUTER_VERSION,
    }


def _mixed_section() -> dict:
    return {
        "section_id": "6 TECHNICAL DATA",
        "section_path": ["6 TECHNICAL DATA"],
        "heading": "6 TECHNICAL DATA",
        "text": f"{PROSE}\n{TABLE_FLAT}",
        "block_ids": ["P1", "T1"],
    }


def _blocks() -> list[dict]:
    return [
        {"block_id": "P1", "type": "paragraph", "section_path": ["6"],
         "text": PROSE, "order": 1},
        {"block_id": "T1", "type": "table", "section_path": ["6"],
         "text": TABLE_FLAT, "order": 2},
    ]


def _item() -> dict:
    return {
        "functional_requirement_id": "F1",
        "source_block_ids": ["P1", "T1"],
        "source_quote": PROSE,
        "objective": PROSE,
        "behaviors": [],
    }


def _seed(out: Path, *, dispositions: bool, cell_route: str = "a_track") -> None:
    _write_jsonl(out / "blocks.jsonl", _blocks())
    _write_jsonl(out / "table_items.jsonl", [{
        "item_id": "TBLI-1", "table_id": "TBL-000001", "table_block_id": "T1",
        "leaf_role": "row", "row_index": 1, "text": "230 | 5",
        "section_path": ["6"],
    }])
    units = [
        _prose_unit(),
        _cell_unit("UNIT-C230", "230"),
        _cell_unit("UNIT-C5", "5"),
    ]
    decisions = [
        _decision("UNIT-P1-S000", "b_track"),
        _decision("UNIT-C230", cell_route),
        _decision("UNIT-C5", cell_route),
    ]
    _write_jsonl(out / "extraction_units.jsonl", units)
    _write_jsonl(out / "unit_routing_decisions.jsonl", decisions)
    if dispositions:
        _write_jsonl(out / "table_cell_dispositions.jsonl", [
            {"schema": "table-cell-disposition/v2", "cell_id": "C230",
             "table_id": "TBL-000001", "table_block_id": "T1",
             "text": "230", "role": "context", "disposition": "context"},
            {"schema": "table-cell-disposition/v2", "cell_id": "C5",
             "table_id": "TBL-000001", "table_block_id": "T1",
             "text": "5", "role": "context", "disposition": "context"},
        ])


class ConservationTrackSplitTests(unittest.TestCase):
    def test_mixed_section_delegates_a_track_table_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, dispositions=True)
            report = fe.conservation_report(
                [_mixed_section()], [_item()],
                blocks=_blocks(), out_dir=out)
            delegated = report["checks"]["preservation"]["delegated_to_cell_conservation"]
            self.assertEqual(len(delegated), 1)
            self.assertEqual(delegated[0]["block_id"], "T1")
            self.assertEqual(
                delegated[0]["reason"],
                "table_block_fully_delegated_to_cell_conservation",
            )
            self.assertGreaterEqual(len(delegated[0]["units"]), 2)
            self.assertTrue(all(
                row["unit_id"] and row["route"] in ("a_track", "context")
                for row in delegated[0]["units"]
            ))
            blocking = report["checks"]["preservation"]["blocking_losses"]
            number_tokens = {
                str(row.get("token")) for row in blocking
                if row.get("kind") == "number"
            }
            self.assertNotIn("230", number_tokens)
            self.assertNotIn("5", number_tokens)
            uncovered = report["checks"]["obligation_coverage"]["uncovered_obligations"]
            self.assertTrue(
                all("230" not in (row.get("sentence") or "") for row in uncovered),
                uncovered,
            )

    def test_delegated_audit_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, dispositions=True, cell_route="context")
            report = fe.conservation_report(
                [_mixed_section()], [_item()],
                blocks=_blocks(), out_dir=out)
            row = report["checks"]["preservation"]["delegated_to_cell_conservation"][0]
            self.assertEqual(
                set(row),
                {"block_id", "block_ids", "units", "reason"},
            )
            self.assertEqual(row["block_id"], "T1")
            self.assertEqual(row["block_ids"], ["T1"])
            self.assertTrue(row["units"])
            self.assertEqual(row["units"][0]["unit_kind"], "table_cell")
            self.assertIn(row["units"][0]["route"], ("a_track", "context"))

    def test_missing_dispositions_keeps_table_in_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, dispositions=False)
            report = fe.conservation_report(
                [_mixed_section()], [_item()],
                blocks=_blocks(), out_dir=out)
            self.assertEqual(
                report["checks"]["preservation"]["delegated_to_cell_conservation"],
                [],
            )
            blocking = report["checks"]["preservation"]["blocking_losses"]
            number_tokens = {
                str(row.get("token")) for row in blocking
                if row.get("kind") == "number"
            }
            self.assertTrue({"230", "5"} & number_tokens, blocking)

    def test_legacy_direct_call_without_out_dir_unchanged(self) -> None:
        section = _mixed_section()
        item = _item()
        report = fe.conservation_report([section], [item])
        # 无 out_dir：不得委托，表格数字仍在 preservation 基线。
        self.assertEqual(
            report["checks"]["preservation"]["delegated_to_cell_conservation"],
            [])
        blocking = report["checks"]["preservation"]["blocking_losses"]
        number_tokens = {
            str(row.get("token")) for row in blocking
            if row.get("kind") == "number"
        }
        self.assertTrue({"230", "5"} & number_tokens, blocking)

    def test_b_track_table_unit_stays_in_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, dispositions=True, cell_route="b_track")
            report = fe.conservation_report(
                [_mixed_section()], [_item()],
                blocks=_blocks(), out_dir=out)
            self.assertEqual(
                report["checks"]["preservation"]["delegated_to_cell_conservation"],
                [],
            )

    def test_block_granularity_when_unit_text_not_in_section(self) -> None:
        """行渲染 source_text 对不上条款扁平 text 时，仍按块 text 剔除数字。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed(out, dispositions=True)
            units = [
                json.loads(line) for line in
                (out / "extraction_units.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()
            ]
            for unit in units:
                if unit.get("unit_kind") == "table_cell":
                    unit["source_text"] = (
                        f"column_1=6.1 | Specification={unit['source_text']}"
                    )
            _write_jsonl(out / "extraction_units.jsonl", units)
            report = fe.conservation_report(
                [_mixed_section()], [_item()],
                blocks=_blocks(), out_dir=out)
            delegated = report["checks"]["preservation"]["delegated_to_cell_conservation"]
            self.assertEqual(len(delegated), 1)
            self.assertEqual(delegated[0]["block_id"], "T1")
            blocking = report["checks"]["preservation"]["blocking_losses"]
            number_tokens = {
                str(row.get("token")) for row in blocking
                if row.get("kind") == "number"
            }
            self.assertNotIn("230", number_tokens)
            self.assertNotIn("5", number_tokens)

    def test_partial_table_block_stays_in_baseline(self) -> None:
        """同块混有 b_track 表格单元 → 整块保留（宁多记账）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "blocks.jsonl", _blocks())
            _write_jsonl(out / "table_items.jsonl", [{
                "item_id": "TBLI-1", "table_id": "TBL-000001",
                "table_block_id": "T1", "leaf_role": "row", "row_index": 1,
                "text": "230 | 5", "section_path": ["6"],
            }])
            units = [
                _prose_unit(),
                _cell_unit("UNIT-C230", "230"),
                _cell_unit("UNIT-C5", "5"),
            ]
            decisions = [
                _decision("UNIT-P1-S000", "b_track"),
                _decision("UNIT-C230", "a_track"),
                _decision("UNIT-C5", "b_track"),
            ]
            _write_jsonl(out / "extraction_units.jsonl", units)
            _write_jsonl(out / "unit_routing_decisions.jsonl", decisions)
            _write_jsonl(out / "table_cell_dispositions.jsonl", [
                {"schema": "table-cell-disposition/v2", "cell_id": "C230",
                 "table_id": "TBL-000001", "table_block_id": "T1",
                 "text": "230", "role": "context", "disposition": "context"},
                {"schema": "table-cell-disposition/v2", "cell_id": "C5",
                 "table_id": "TBL-000001", "table_block_id": "T1",
                 "text": "5", "role": "context", "disposition": "context"},
            ])
            report = fe.conservation_report(
                [_mixed_section()], [_item()],
                blocks=_blocks(), out_dir=out)
            self.assertEqual(
                report["checks"]["preservation"]["delegated_to_cell_conservation"],
                [],
            )
            blocking = report["checks"]["preservation"]["blocking_losses"]
            number_tokens = {
                str(row.get("token")) for row in blocking
                if row.get("kind") == "number"
            }
            self.assertTrue({"230", "5"} & number_tokens, blocking)


if __name__ == "__main__":
    unittest.main()
