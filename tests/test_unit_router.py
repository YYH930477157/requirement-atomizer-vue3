from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
from unit_router import (
    UNIT_ROUTER_VERSION,
    UNIT_ROUTING_DECISIONS_FILENAME,
    load_routing_decisions,
    route_document,
    route_unit,
    route_units,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = Draft202012Validator(json.loads(
    (REPO_ROOT / "schemas" / "unit_routing_decision.schema.json").read_text(encoding="utf-8")))


def _unit(unit_id: str, text: str, *, kind: str = "clause_segment",
          roles: list[str] | None = None, headers: list[str] | None = None,
          disposition: str | None = None) -> dict:
    import hashlib

    return {
        "schema": "extraction-unit/v1",
        "unit_id": unit_id,
        "unit_kind": kind,
        "source_text": text,
        "source_text_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "clause_path": ["6", "6.12"],
        "source_block_ids": ["BLK-000081"],
        "roles": roles or ["requirement_candidate"],
        "context_refs": [],
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": {"source_type": "block_sentence", "source_id": f"{unit_id}#0"},
        **({"table_context": {
            "table_id": "TBL-000001", "row_index": 4, "column_index": 3,
            "headers": headers or [], "disposition": disposition}}
           if kind in ("table_row", "table_cell") else {}),
    }


class UnitRouterRuleTests(unittest.TestCase):
    def test_mixed_sentence_routes_mixed_with_b_primary(self) -> None:
        decision = route_unit(_unit("U1", (
            "The meter shall expose event records through interface class 7, "
            "attribute 2, with read-only access.")))
        self.assertEqual(decision["route"], "mixed")
        self.assertEqual(decision["primary_route"], "b_track")
        self.assertEqual(decision["a_score"], 1.0)
        self.assertEqual(decision["b_score"], 1.0)
        kinds = {item["kind"] for item in decision["evidence"]}
        self.assertIn("modal", kinds)
        self.assertIn("class_id", kinds)

    def test_pure_shall_sentence_routes_b_track(self) -> None:
        decision = route_unit(_unit("U2", "The meter shall log events."))
        self.assertEqual(decision["route"], "b_track")
        self.assertEqual(decision["primary_route"], "b_track")
        self.assertEqual(decision["a_score"], 0.0)
        self.assertTrue(any(item["kind"] == "modal" for item in decision["evidence"]))

    def test_chinese_obligation_routes_b_track(self) -> None:
        decision = route_unit(_unit("U3", "电表必须支持事件记录读取。"))
        self.assertEqual(decision["route"], "b_track")

    def test_read_only_word_alone_does_not_make_mixed(self) -> None:
        decision = route_unit(_unit(
            "U4", "The operator shall have read-only access to configuration data."))
        self.assertEqual(decision["route"], "b_track")
        self.assertEqual(decision["a_score"], 0.0)

    def test_cosem_table_row_routes_a_track(self) -> None:
        decision = route_unit(_unit(
            "U5", "Event log | 1-1:0.99.98.255 | Profile Generic | Capture period",
            kind="table_row", roles=["requirement_candidate", "cosem_structured"],
            headers=["Object/attribute name", "CL", "Value"]))
        self.assertEqual(decision["route"], "a_track")
        self.assertEqual(decision["primary_route"], "a_track")
        kinds = {item["kind"] for item in decision["evidence"]}
        self.assertIn("obis", kinds)
        self.assertIn("cosem_context", kinds)

    def test_cosem_table_with_modal_routes_a_priority_v2(self) -> None:
        # v2 标定：COSEM 结构表单元带义务模态（参数叙述列）→ a_track，不再 mixed
        decision = route_unit(_unit(
            "U5m", "Event log | 1-1:0.99.98.255 | all events must be registered",
            kind="table_cell",
            roles=["requirement_candidate", "cosem_structured"],
            headers=["Object/attribute name", "CL", "Value"]))
        self.assertEqual(decision["route"], "a_track")
        self.assertEqual(decision["rule"], "cosem_table_a_priority")
        self.assertEqual(decision["router_version"], "unit-router-v3")

    def test_cosem_table_b_modal_only_also_a_priority_v2(self) -> None:
        # v2：COSEM 表内只有模态（参数叙述列）无 A 信号的格同样归 A 轨
        decision = route_unit(_unit(
            "U5b", "all events must be registered in the buffer",
            kind="table_cell",
            roles=["requirement_candidate", "cosem_structured"],
            headers=["Object/attribute name", "CL", "Value"]))
        self.assertEqual(decision["route"], "a_track")
        self.assertEqual(decision["rule"], "cosem_table_a_priority")

    def test_composite_disposition_table_routes_a_authority_v3(self) -> None:
        # v3：处置=composite 的表格内容（如矩阵勾号行）归 claim 组合权威，词法 marker 不认领
        decision = route_unit(_unit(
            "U10c", "X", kind="table_cell", roles=["requirement_candidate"],
            headers=["xDLMS Service"], disposition="composite"))
        self.assertEqual(decision["route"], "a_track")
        self.assertEqual(decision["rule"], "table_composition_a_authority")

    def test_context_disposition_table_modal_not_b_v3(self) -> None:
        # v3：处置=context 的位定义说明（"must be set to 0"）不被词法模态越权改判
        decision = route_unit(_unit(
            "U10x", "Not used, must be set to \"0\"", kind="table_row",
            roles=["requirement_candidate"], headers=["bit", "Security States"],
            disposition="context"))
        self.assertEqual(decision["route"], "context")
        self.assertEqual(decision["rule"], "context_by_disposition")

    def test_target_disposition_table_modal_stays_b_v3(self) -> None:
        # v3：处置=target（guards-v16 需求形单行）不受影响
        decision = route_unit(_unit(
            "U10t", "The meter shall register all events.", kind="table_cell",
            roles=["requirement_candidate"], headers=["Service", "Description"],
            disposition="target"))
        self.assertEqual(decision["route"], "b_track")
        self.assertEqual(decision["rule"], "hard_b_only")

    def test_non_cosem_table_b_modal_stays_b_track_v2(self) -> None:
        # 非 COSEM 结构表（如术语/安全状态表）的义务格不越权改判
        decision = route_unit(_unit(
            "U5n", "The meter shall register all events.",
            kind="table_cell", roles=["requirement_candidate"],
            headers=["Service", "Description"]))
        self.assertEqual(decision["route"], "b_track")

    def test_prose_mixed_unchanged_in_v2(self) -> None:
        decision = route_unit(_unit(
            "U5p", "The meter shall expose event records through "
            "interface class 7, attribute 2, with read-only access."))
        self.assertEqual(decision["route"], "mixed")
        self.assertEqual(decision["primary_route"], "b_track")
        self.assertEqual(decision["rule"], "hard_ab_mixed")

    def test_class_number_without_whitelist_entry_is_not_hard_a(self) -> None:
        # class 999 不在 COSEM 白名单——不得构成硬 A 信号
        decision = route_unit(_unit("U6", "The link shall use interface class 999."))
        self.assertEqual(decision["route"], "b_track")
        self.assertEqual(decision["a_score"], 0.0)

    def test_definition_reference_heading_narrative_route_context(self) -> None:
        for kind, text in (("definition", "event record: A record of a metering event."),
                           ("reference", "4.2: The device shall operate..."),
                           ("heading", "6.12 Event logs"),
                           ("narrative", "This document describes the architecture.")):
            decision = route_unit(_unit(f"U-{kind}", text, kind=kind, roles=["context"]))
            self.assertEqual(decision["route"], "context", kind)
            self.assertIsNone(decision["primary_route"])
            self.assertEqual(decision["decision_basis"], "deterministic")

    def test_excluded_disposition_routes_context(self) -> None:
        decision = route_unit(_unit(
            "U7", "N/A", kind="table_cell", roles=["excluded"], disposition="excluded"))
        self.assertEqual(decision["route"], "context")

    def test_weak_signal_routes_review_not_dropped(self) -> None:
        # 弱信号（colon_spec）+ 无硬信号 → review（物化待审，不静默丢弃）
        decision = route_unit(_unit(
            "U8", "Value: 42", kind="table_cell", roles=["requirement_candidate"]))
        self.assertEqual(decision["route"], "review")
        self.assertEqual(decision["b_score"], 0.4)

    def test_review_candidate_role_routes_review(self) -> None:
        decision = route_unit(_unit(
            "U9", "Maybe applicable.", kind="table_cell",
            roles=["review_candidate"], disposition="review"))
        self.assertEqual(decision["route"], "review")

    def test_candidate_without_any_signal_routes_review(self) -> None:
        decision = route_unit(_unit("U10", "Voltage 230 V."))
        self.assertEqual(decision["route"], "review")
        self.assertEqual(decision["rule"], "review_no_signal")

    def test_decision_carries_unit_hash_and_versions(self) -> None:
        unit = _unit("U11", "The meter shall log events.")
        decision = route_unit(unit)
        self.assertEqual(decision["source_text_hash"], unit["source_text_hash"])
        self.assertEqual(decision["router_version"], UNIT_ROUTER_VERSION)
        self.assertEqual(decision["planner_version"], EXTRACTION_UNIT_PLANNER_VERSION)


class UnitRouterDocumentTests(unittest.TestCase):
    def test_route_units_summary_and_schema(self) -> None:
        units = [
            _unit("U1", "The meter shall log events."),
            _unit("U2", "The register shall map OBIS 1-0:1.8.0 to class 3."),
            _unit("U3", "Architecture overview text.", kind="narrative", roles=["context"]),
            _unit("U4", "Value: 42", kind="table_cell"),
        ]
        decisions, summary = route_units(units)
        errors = [f"{d['unit_id']}: {e.message}" for d in decisions
                  for e in VALIDATOR.iter_errors(d)]
        self.assertEqual(errors, [])
        self.assertEqual(summary["router_version"], UNIT_ROUTER_VERSION)
        self.assertTrue(summary["shadow_mode"])
        self.assertEqual(summary["unit_count"], 4)
        # U2（shall + OBIS + class 3）是合法 Mixed；纯 shall 是 b_track
        self.assertEqual(summary["counts_by_route"]["b_track"], 1)
        self.assertEqual(summary["counts_by_route"]["mixed"], 1)
        self.assertEqual(summary["counts_by_route"]["context"], 1)
        self.assertEqual(summary["counts_by_route"]["review"], 1)

    def test_route_document_writes_governed_artifact(self) -> None:
        from extraction_units import plan_extraction_units

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            import sys
            sys.path.insert(0, str(REPO_ROOT / "tests"))
            from test_extraction_units import _corpus

            blocks, table_items, cell_items, dispositions = _corpus()
            for name, rows in (("blocks.jsonl", blocks),
                               ("table_items.jsonl", table_items),
                               ("table_cell_items.jsonl", cell_items),
                               ("table_cell_dispositions.jsonl", dispositions)):
                (out_dir / name).write_text(
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")
            plan_extraction_units(out_dir)
            summary = route_document(out_dir, plan_if_missing=False)
            self.assertTrue((out_dir / UNIT_ROUTING_DECISIONS_FILENAME).is_file())
            decisions = load_routing_decisions(out_dir)
            self.assertEqual(len(decisions), summary["unit_count_planned"])
            # 决策 unit 集合与单元产物一一对应
            from extraction_units import load_extraction_units

            self.assertEqual({d["unit_id"] for d in decisions},
                             {u["unit_id"] for u in load_extraction_units(out_dir)})
            # corpus 的 shall 句必须进 b_track/mixed，不进 context
            shall = next(d for d in decisions if d["unit_id"] == "UNIT-BLK-000002-S000")
            self.assertIn(shall["route"], ("b_track", "mixed"))


if __name__ == "__main__":
    unittest.main()
