from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quality_gates import (
    GATE_NEEDS_REVIEW,
    GATE_NEEDS_WORK,
    GATE_PASS,
    GATE_RETRY_LOCAL,
    evaluate_document_gates,
)
from routed_execution import (
    ROUTED_MERGE_VERSION,
    dedupe_authoritative,
    implementation_constraints,
    obligation_identity,
    shape_mixed_requirement,
)
from routing_gaps import (
    ROUTING_GAPS_FILENAME,
    build_gap,
    gaps_from_routing_decisions,
    load_routing_gaps,
    merge_gaps,
    summarize_gaps,
    write_routing_gaps,
)
from unit_router import route_unit


def _unit(unit_id: str, text: str, *, kind: str = "clause_segment",
          roles: list[str] | None = None) -> dict:
    import hashlib

    return {
        "schema": "extraction-unit/v1", "unit_id": unit_id, "unit_kind": kind,
        "source_text": text,
        "source_text_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "clause_path": ["6", "6.12"], "source_block_ids": ["BLK-000081"],
        "roles": roles or ["requirement_candidate"], "context_refs": [],
        "planner_version": "extraction-unit-planner-v1",
        "locator": {"source_type": "block_sentence", "source_id": unit_id},
    }


MIXED_TEXT = ("The meter shall expose event records through interface class 7, "
              "attribute 2, with read-only access.")


class MixedMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.unit = _unit("UNIT-BLK-000081-S000", MIXED_TEXT)
        self.decision = route_unit(self.unit)
        self.assertEqual(self.decision["route"], "mixed")

    def test_mixed_merge_yields_single_authoritative_with_constraints(self) -> None:
        requirement = shape_mixed_requirement(self.unit, self.decision)
        self.assertEqual(requirement["schema"], "authoritative-requirement/v1")
        self.assertEqual(requirement["route_provenance"]["behavior"], "b_track")
        self.assertEqual(requirement["route_provenance"]["structured_fields"],
                         "deterministic_a_join")
        constraints = requirement["implementation_constraints"]
        self.assertEqual(constraints["class_id"], 7)
        self.assertEqual(constraints["class_name"], "Profile Generic")
        self.assertEqual(constraints["attribute_id"], 2)
        self.assertEqual(constraints["access"], "read_only")
        self.assertEqual(requirement["source_unit_id"], self.unit["unit_id"])

    def test_narrative_placeholder_is_never_disguised_as_llm_output(self) -> None:
        shadow = shape_mixed_requirement(self.unit, self.decision)
        self.assertEqual(shadow["route_provenance"]["narrative_source"], "unit_text")
        processed = shape_mixed_requirement(
            self.unit, self.decision, narrative="电表应提供事件记录读取功能。")
        self.assertEqual(processed["route_provenance"]["narrative_source"],
                         "b_track_processor")
        self.assertEqual(processed["software_requirement_text"], "电表应提供事件记录读取功能。")

    def test_constraints_reject_unverified_class_and_bad_obis(self) -> None:
        unit = _unit("U-bad", "The link shall use interface class 999 with code 9-9.")
        constraints = implementation_constraints(unit, None)
        self.assertNotIn("class_id", constraints)
        self.assertNotIn("obis", constraints)

    def test_obligation_identity_stable_and_discriminative(self) -> None:
        first = obligation_identity(self.unit)
        # 同文本同单元 → 同 identity；空白差异归一
        same = obligation_identity(_unit(self.unit["unit_id"], MIXED_TEXT + "  "))
        self.assertEqual(first, same)
        other = obligation_identity(_unit("UNIT-BLK-000082-S000", MIXED_TEXT))
        self.assertNotEqual(first, other)

    def test_dedupe_keeps_one_authoritative_per_obligation(self) -> None:
        b_side = shape_mixed_requirement(self.unit, self.decision,
                                         narrative="电表应提供事件记录读取功能。")
        duplicate = shape_mixed_requirement(self.unit, self.decision)
        authoritative, duplicates = dedupe_authoritative([b_side, duplicate])
        self.assertEqual(len(authoritative), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(authoritative[0]["obligation_id"],
                         b_side["obligation_id"])
        self.assertEqual(authoritative[0]["route_provenance"]["merge_version"],
                         ROUTED_MERGE_VERSION)


class RoutingGapTests(unittest.TestCase):
    def test_review_decisions_materialize_as_gaps(self) -> None:
        decisions = [
            route_unit(_unit("U-ok", "The meter shall log events.")),
            route_unit(_unit("U-weak", "Value: 42", kind="table_cell")),
            route_unit(_unit("U-nosig", "Voltage 230 V.")),
        ]
        gaps = gaps_from_routing_decisions(decisions)
        self.assertEqual(len(gaps), 2)
        self.assertTrue(all(gap["gate"] == "routing_review_pending" for gap in gaps))
        self.assertTrue(all(not gap["blocking"] for gap in gaps))
        self.assertTrue(all(gap["recommended_action"] == "expert_review" for gap in gaps))
        summary = summarize_gaps(gaps)
        self.assertEqual(summary["gap_count"], 2)

    def test_gap_id_stable_and_merge_dedupes(self) -> None:
        first = build_gap(unit_id="U1", gate="g", reason="r")
        again = build_gap(unit_id="U1", gate="g", reason="r")
        self.assertEqual(first["gap_id"], again["gap_id"])
        merged = merge_gaps([first, again])
        self.assertEqual(len(merged), 1)
        other = build_gap(unit_id="U1", gate="g", reason="different")
        self.assertNotEqual(first["gap_id"], other["gap_id"])

    def test_unknown_action_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_gap(unit_id="U1", gate="g", reason="r",
                      recommended_action="silent_drop")

    def test_write_and_load_governed_gaps(self) -> None:
        gaps = gaps_from_routing_decisions(
            [route_unit(_unit("U-weak", "Value: 42", kind="table_cell"))])
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            summary = write_routing_gaps(out_dir, gaps)
            self.assertTrue((out_dir / ROUTING_GAPS_FILENAME).is_file())
            loaded = load_routing_gaps(out_dir)
            self.assertEqual(loaded, merge_gaps(gaps))
            self.assertEqual(summary["gap_count"], 1)


class QualityGateTests(unittest.TestCase):
    def test_missing_products_are_needs_work_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate_document_gates(Path(tmp))
            self.assertEqual(report["overall"], GATE_NEEDS_WORK)
            self.assertEqual(report["gates"]["execution_status"]["status"], GATE_NEEDS_WORK)
            self.assertEqual(report["gates"]["obligation_conservation"]["status"],
                             GATE_NEEDS_WORK)
            # legacy 布局无 marker：结果包 gate 不阻塞
            self.assertEqual(report["gates"]["result_package_completion"]["status"],
                             GATE_PASS)
            # 未跑路由：不阻塞 legacy 执行
            self.assertEqual(report["gates"]["routing_review_pending"]["status"],
                             GATE_PASS)
            # 无表格产物：closure 不适用（不伪造失败）
            self.assertEqual(report["gates"]["table_cell_closure"]["status"], GATE_PASS)

    def test_tables_without_dispositions_are_needs_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "table_cell_items.jsonl").write_text(
                json.dumps({"cell_id": "T1"}) + "\n", encoding="utf-8")
            report = evaluate_document_gates(out_dir)
            self.assertEqual(report["gates"]["table_cell_closure"]["status"],
                             GATE_NEEDS_WORK)

    def test_ok_product_with_ready_dispositions_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "functional_requirements.json").write_text(json.dumps({
                "execution_status": "ok",
                "conservation": {"ok": True, "checks": {"obligation_coverage": {"ok": True}}},
                "items": [{"id": "FREQ-1"}],
            }, ensure_ascii=False), encoding="utf-8")
            (out_dir / "table_cell_dispositions.jsonl").write_text(
                json.dumps({"cell_id": "T1", "structure_review_status": "ready"},
                           ensure_ascii=False) + "\n", encoding="utf-8")
            report = evaluate_document_gates(out_dir)
            self.assertEqual(report["overall"], GATE_PASS)
            self.assertEqual(report["gates"]["obligation_conservation"]["status"], GATE_PASS)

    def test_partial_execution_is_needs_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "functional_requirements.json").write_text(json.dumps({
                "execution_status": "partial",
                "conservation": {"ok": False,
                                 "checks": {"obligation_coverage": {"ok": False}}},
            }, ensure_ascii=False), encoding="utf-8")
            report = evaluate_document_gates(out_dir)
            self.assertEqual(report["gates"]["execution_status"]["status"], GATE_NEEDS_WORK)
            self.assertEqual(report["gates"]["obligation_conservation"]["status"],
                             GATE_NEEDS_WORK)
            self.assertIn("obligation_coverage",
                          report["gates"]["obligation_conservation"]["failed_checks"])

    def test_pending_dispositions_are_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "table_cell_dispositions.jsonl").write_text("\n".join(json.dumps(row)
                for row in ({"cell_id": "T1", "structure_review_status": "ready"},
                            {"cell_id": "T2", "structure_review_status": "pending"})) + "\n",
                encoding="utf-8")
            report = evaluate_document_gates(out_dir)
            self.assertEqual(report["gates"]["table_cell_closure"]["status"],
                             GATE_NEEDS_REVIEW)
            self.assertEqual(report["gates"]["table_cell_closure"]["pending_count"], 1)

    def test_review_routing_decisions_are_retry_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "unit_routing_decisions.jsonl").write_text(json.dumps({
                "unit_id": "U1", "route": "review"}) + "\n", encoding="utf-8")
            report = evaluate_document_gates(out_dir)
            self.assertEqual(report["gates"]["routing_review_pending"]["status"],
                             GATE_RETRY_LOCAL)
            self.assertEqual(report["gates"]["routing_review_pending"]["review_count"], 1)


if __name__ == "__main__":
    unittest.main()
