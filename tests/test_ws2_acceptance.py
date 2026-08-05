"""WS2 §4.1.2 claim_acceptance 两级产出校验门测试。

验收面：evaluate_functional_conservation 在 records 无 functional_output 块时
not_applicable pass（行为不动）；有块且守恒 → pass；有块且未闭合 → fail。
"""
from __future__ import annotations

import unittest

from claim_acceptance import evaluate_functional_conservation


def _record(artifact_status: str = "valid", functional_output: dict | None = None) -> dict:
    record = {
        "run_id": "R1",
        "sequence": 1,
        "artifact_status": artifact_status,
        "document_id": "D1",
    }
    if functional_output is not None:
        record["functional_output"] = functional_output
    return record


class FunctionalConservationGateTests(unittest.TestCase):
    def test_no_functional_output_passes_not_applicable(self) -> None:
        gate = evaluate_functional_conservation([_record()])
        self.assertEqual(gate["status"], "pass")
        self.assertEqual(gate["reason"], "functional_evidence_not_applicable")

    def test_conserved_functional_output_passes(self) -> None:
        gate = evaluate_functional_conservation(
            [_record(functional_output={"ok": True, "block_export": False})]
        )
        self.assertEqual(gate["status"], "pass")
        self.assertEqual(gate["reason"], "functional_conservation_closed")

    def test_unclosed_functional_output_fails(self) -> None:
        gate = evaluate_functional_conservation(
            [_record(functional_output={
                "ok": False,
                "missing_block_ids": ["B9"],
                "block_export": True,
            })]
        )
        self.assertEqual(gate["status"], "fail")
        self.assertEqual(gate["reason"], "functional_conservation_not_closed")

    def test_duplicate_assignments_fail(self) -> None:
        gate = evaluate_functional_conservation(
            [_record(functional_output={
                "ok": False, "duplicate_assignments": ["B1"],
            })]
        )
        self.assertEqual(gate["status"], "fail")

    def test_only_invalid_records_pass_not_applicable(self) -> None:
        # invalid run 的 functional_output 不计入（artifact_status != valid）
        gate = evaluate_functional_conservation(
            [_record(artifact_status="invalid", functional_output={"ok": False})]
        )
        self.assertEqual(gate["status"], "pass")
        self.assertEqual(gate["reason"], "functional_evidence_not_applicable")

    def test_any_valid_run_unclosed_fails(self) -> None:
        records = [
            _record(functional_output={"ok": True}),
            _record(functional_output={"ok": False, "missing_block_ids": ["B1"]}),
        ]
        # 第二条 run_id 应不同，但即使同 run_id 也按 valid 计数
        records[1] = dict(records[1], run_id="R2", sequence=2)
        gate = evaluate_functional_conservation(records)
        self.assertEqual(gate["status"], "fail")


class Phase0ReportUnchangedTests(unittest.TestCase):
    """evaluate_phase0_evidence 不自动并入 functional_conservation（schema 冻结枚举）。"""

    def test_report_gates_do_not_include_functional_conservation(self) -> None:
        from claim_acceptance import evaluate_phase0_evidence
        # 最小 records（缺很多必填字段 → 仍能返回，functional 不在 gates 枚举里）
        records = [{
            "run_id": "R1", "sequence": 1, "artifact_status": "invalid",
            "document_id": "D1",
            "functional_output": {"ok": False, "missing_block_ids": ["B1"]},
        }]
        report = evaluate_phase0_evidence(
            "ds-test", records, {},
            {"evidence_status": "invalid", "artifact_status": "invalid"},
        )
        # functional_conservation 未并入 gates（冻结 schema）
        self.assertNotIn("functional_conservation", report["gates"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
