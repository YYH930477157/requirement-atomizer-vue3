"""T2-1 编排环缺口读取层夹具测试（确定性、只读、零副作用）。

四类缺口 + verification 反哺候选各自用真实 sidecar 夹具验证读取正确；并断言 read_gaps
调用前后盘上产物字节不变（只读纪律）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestration_gaps import (
    ACTION_HUMAN_REVIEW,
    ACTION_SPOT_EXTRACT,
    ACTION_TARGETED_REEXTRACT,
    ORCHESTRATION_GAP_VERSION,
    ROUTE_EXTRACT,
    ROUTE_HUMAN,
    OrchestrationGapInputError,
    read_gaps,
)


def _block(block_id: str, text: str, *, order: int = 1, requirement_like: bool = True) -> dict:
    return {
        "block_id": block_id,
        "order": order,
        "text": text,
        "requirement_like": requirement_like,
        "noise": False,
        "doc_region": "body",
        "type": "paragraph",
    }


def _seed_minimal(out: Path) -> None:
    """blocks.jsonl + ai_requirements.jsonl（编排环最小必需产物）。"""
    (out / "blocks.jsonl").write_text(
        json.dumps(_block("B1", "The meter shall log events.", order=1)) + "\n"
        + json.dumps(_block("B2", "The meter shall report voltage.", order=2)) + "\n",
        encoding="utf-8",
    )
    (out / "ai_requirements.jsonl").write_text(
        json.dumps({
            "ai_req_id": "AIR-001",
            "title": "Log events",
            "description": "The meter shall log events.",
            "type": "functional",
            "source_section": "4.1",
            "source_quote": "The meter shall log events.",
            "source_block_ids": ["B1"],
            "suspicion_reasons": [],   # 默认无 suspicion，避免污染各专用夹具
        }) + "\n",
        encoding="utf-8",
    )


def _write_json(out: Path, name: str, payload: dict) -> None:
    (out / name).write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


class OrchestrationGapReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        _seed_minimal(self.out)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- ① clarification_blocking ---

    def test_clarification_blocking_gap_routed_to_human(self) -> None:
        # 编码漂移 → suspicion:code_drift → BLOCKER_BLOCKING（必答未答）
        req = json.loads((self.out / "ai_requirements.jsonl").read_text(encoding="utf-8").splitlines()[0])
        req["suspicion_reasons"] = ["编码漂移"]
        (self.out / "ai_requirements.jsonl").write_text(json.dumps(req) + "\n", encoding="utf-8")

        report = read_gaps(self.out)
        blocking = [g for g in report.gaps if g.kind == "clarification_blocking"]
        self.assertEqual(len(blocking), 1)
        gap = blocking[0]
        self.assertEqual(gap.route, ROUTE_HUMAN)
        self.assertEqual(gap.action, ACTION_HUMAN_REVIEW)
        self.assertEqual(gap.severity, "high")
        self.assertTrue(gap.target_id.startswith("CLR-"))
        self.assertEqual(report.counts_by_kind["clarification_blocking"], 1)

    # --- ② conservation_open ---

    def test_conservation_missing_is_extract_extra_is_human(self) -> None:
        _write_json(self.out, "functional_requirements.json", {
            "schema_version": 1,
            "producer": "functional-extract-v1",
            "conservation": {
                "ok": False,
                "missing_block_ids": ["B2"],
                "extra_block_ids": ["BX"],
                "duplicate_assignments": [],
                "evidence_mismatches": [],
            },
            "items": [],
        })
        report = read_gaps(self.out)
        cons = [g for g in report.gaps if g.kind == "conservation_open"]
        kinds = {(g.evidence["reason"], g.route) for g in cons}
        self.assertIn(("missing", ROUTE_EXTRACT), kinds)
        self.assertIn(("extra", ROUTE_HUMAN), kinds)
        missing = next(g for g in cons if g.evidence["reason"] == "missing")
        self.assertEqual(missing.action, ACTION_TARGETED_REEXTRACT)
        self.assertEqual(missing.block_id, "B2")
        self.assertEqual(missing.severity, "high")
        # ok=True 时不产缺口（下一断言）
        self.assertTrue(report.sources_available["functional_requirements"])

    def test_conservation_ok_yields_no_gap(self) -> None:
        _write_json(self.out, "functional_requirements.json", {
            "conservation": {"ok": True, "missing_block_ids": []}, "items": [],
        })
        report = read_gaps(self.out)
        self.assertEqual(report.counts_by_kind["conservation_open"], 0)

    def test_conservation_absent_is_available_false_not_an_error(self) -> None:
        report = read_gaps(self.out)
        self.assertFalse(report.sources_available["functional_requirements"])
        self.assertEqual(report.counts_by_kind["conservation_open"], 0)

    # --- ③ sampling_escalate ---

    def test_sampling_escalate_maps_deferred_claims_to_blocks(self) -> None:
        _write_json(self.out, "claim_sampling_summary.json", {
            "schema": "claim-sampling-summary/v1",
            "mode": "sampling",
            "escalate": True,
            "deferred_claim_ids": ["CLM-aaa", "CLM-bbb"],
            "deferred_count": 2,
            "selected_ratio": 0.1,
        })
        (self.out / "claim_catalog.jsonl").write_text(
            json.dumps({"claim_id": "CLM-aaa", "block_id": "B2",
                        "locator": {"block_id": "B2"}}) + "\n"
            + json.dumps({"claim_id": "CLM-bbb", "block_id": "",
                          "locator": {"block_id": ""}}) + "\n",
            encoding="utf-8",
        )
        report = read_gaps(self.out)
        samp = sorted(report.gaps, key=lambda g: g.target_id)
        samp = [g for g in samp if g.kind == "sampling_escalate"]
        self.assertEqual(len(samp), 2)
        mapped = next(g for g in samp if g.target_id == "CLM-aaa")
        self.assertEqual(mapped.route, ROUTE_EXTRACT)
        self.assertEqual(mapped.action, ACTION_SPOT_EXTRACT)
        self.assertEqual(mapped.block_id, "B2")
        unmapped = next(g for g in samp if g.target_id == "CLM-bbb")
        self.assertEqual(unmapped.route, ROUTE_HUMAN)

    def test_sampling_no_escalate_yields_no_gap(self) -> None:
        _write_json(self.out, "claim_sampling_summary.json", {"escalate": False})
        report = read_gaps(self.out)
        self.assertEqual(report.counts_by_kind["sampling_escalate"], 0)

    # --- ④ weakness ---

    def test_weakness_gap_routed_to_human(self) -> None:
        # 弱词扫描：functional_requirements.json 里的条目含弱词 → weakness:vague_word
        _write_json(self.out, "functional_requirements.json", {
            "items": [{
                "functional_requirement_id": "FR-1",
                "title": "Behave appropriately",
                "objective": "The meter shall respond as appropriate.",
                "behaviors": [],
                "source_section": "4.2",
                "source_quote": "as appropriate",
            }],
        })
        report = read_gaps(self.out)
        weak = [g for g in report.gaps if g.kind == "weakness"]
        self.assertGreaterEqual(len(weak), 1)
        self.assertTrue(all(g.route == ROUTE_HUMAN for g in weak))
        self.assertTrue(all(g.action == ACTION_HUMAN_REVIEW for g in weak))

    # --- T2-3 verification 反哺候选 ---

    def test_verification_candidate_for_untested_requirement(self) -> None:
        (self.out / "verification_states.jsonl").write_text(
            json.dumps({"requirement_id": "AIR-001",
                        "verification": {"test_completed": False, "implemented": "partial"},
                        "lifecycle_state": "draft"}) + "\n",
            encoding="utf-8",
        )
        report = read_gaps(self.out)
        self.assertEqual(len(report.verification_candidates), 1)
        cand = report.verification_candidates[0]
        self.assertEqual(cand.requirement_id, "AIR-001")
        self.assertIn("test_not_completed", cand.reason)
        self.assertIn("implementation_deviation", cand.reason)

    def test_verified_requirement_yields_no_candidate(self) -> None:
        (self.out / "verification_states.jsonl").write_text(
            json.dumps({"requirement_id": "AIR-001",
                        "verification": {"test_completed": True, "implemented": "yes"}}) + "\n",
            encoding="utf-8",
        )
        report = read_gaps(self.out)
        self.assertEqual(report.verification_candidates, ())

    # --- 只读纪律 + 最小产物 ---

    def test_read_gaps_is_read_only(self) -> None:
        (self.out / "functional_requirements.json").write_text(
            json.dumps({"conservation": {"ok": False, "missing_block_ids": ["B2"]}, "items": []}),
            encoding="utf-8",
        )

        def business_files() -> dict[str, bytes]:
            # 排除 *.lock——read_gaps 复用的 clarification/ai_review 读路径会留下 OS 锁哨兵
            # （process_file_lock，与 agent_state 同源），那是串行化副产物，不是业务状态。
            return {
                p.name: p.read_bytes()
                for p in self.out.iterdir()
                if p.is_file() and not p.name.endswith(".lock")
            }

        before = business_files()
        read_gaps(self.out)
        read_gaps(self.out)
        after = business_files()
        # 不新增业务文件、不改既有业务文件
        self.assertEqual(set(before), set(after))
        for name, payload in before.items():
            self.assertEqual(after[name], payload, f"{name} 被读取层修改")

    def test_missing_minimal_artifacts_raises(self) -> None:
        empty = Path(tempfile.mkdtemp())
        with self.assertRaises(OrchestrationGapInputError):
            read_gaps(empty)
        empty.rmdir()

    def test_report_version_and_schema(self) -> None:
        report = read_gaps(self.out)
        self.assertEqual(report.version, ORCHESTRATION_GAP_VERSION)
        as_dict = report.to_dict()
        self.assertEqual(as_dict["schema"], "orchestration-gap-report/v1")
        self.assertEqual(
            sorted(as_dict["counts_by_kind"]),
            ["clarification_blocking", "conservation_open", "sampling_escalate", "weakness"],
        )


if __name__ == "__main__":
    unittest.main()
