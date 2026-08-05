"""WS3 章节级增量重跑测试（条款候选粒度，默认关闭）。

验收门禁#4：单章变化仅重跑变化候选（夹具测试证明）。与全量重跑共用同一 hash_json 幂等键空间。
"""
from __future__ import annotations

import os
import unittest
from typing import Any

from desktop_tasks import (
    clause_candidate_fingerprint,
    diff_clause_candidates,
    incremental_rerun_enabled,
    incremental_rerun_plan,
)


def _chunk(block_ids: list[str], text: str, *, heading: str = "", section_id: str = "") -> dict[str, Any]:
    return {
        "section_id": section_id or block_ids[0],
        "section_path": ["1", section_id or block_ids[0]],
        "heading": heading or (block_ids[0] if block_ids else ""),
        "text": text,
        "block_ids": block_ids,
    }


class IncrementalRerunSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.pop("RATOMIZER_INCREMENTAL_RERUN", None)

    def tearDown(self) -> None:
        if self._prev is not None:
            os.environ["RATOMIZER_INCREMENTAL_RERUN"] = self._prev
        else:
            os.environ.pop("RATOMIZER_INCREMENTAL_RERUN", None)

    def test_disabled_by_default(self) -> None:
        self.assertFalse(incremental_rerun_enabled())

    def test_enabled_via_env(self) -> None:
        self.assertTrue(incremental_rerun_enabled("1"))
        self.assertTrue(incremental_rerun_enabled("true"))
        self.assertFalse(incremental_rerun_enabled("0"))


class ClauseCandidateFingerprintTests(unittest.TestCase):
    def test_content_fingerprint_stable(self) -> None:
        a = _chunk(["B1"], "shall do A")
        b = _chunk(["B1"], "shall do A")
        self.assertEqual(clause_candidate_fingerprint(a), clause_candidate_fingerprint(b))

    def test_fingerprint_changes_with_text(self) -> None:
        a = _chunk(["B1"], "shall do A")
        b = _chunk(["B1"], "shall do B")
        self.assertNotEqual(clause_candidate_fingerprint(a), clause_candidate_fingerprint(b))

    def test_fingerprint_changes_with_block_ids(self) -> None:
        a = _chunk(["B1"], "shall do A")
        b = _chunk(["B1", "B2"], "shall do A")
        self.assertNotEqual(clause_candidate_fingerprint(a), clause_candidate_fingerprint(b))

    def test_fingerprint_in_shared_hash_namespace(self) -> None:
        """与 claim / llm_budget 幂等键共用同一 hash_json 命名空间（sha256: 前缀）。"""
        fp = clause_candidate_fingerprint(_chunk(["B1"], "x"))
        self.assertTrue(str(fp).startswith("sha256:"))


class DiffClauseCandidatesTests(unittest.TestCase):
    def test_single_chapter_change_only_flags_changed(self) -> None:
        """验收门禁#4：单章变化仅返回变化候选，未变候选不进重跑队列。"""
        old = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta"), _chunk(["B3"], "gamma")]
        new = [_chunk(["B1"], "alpha"), _chunk(["B2"], "BETA-CHANGED"), _chunk(["B3"], "gamma")]
        diff = diff_clause_candidates(old, new)
        self.assertEqual([list(k) for k in diff["changed"]], [["B2"]])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["unchanged_count"], 2)

    def test_added_candidate_flagged(self) -> None:
        old = [_chunk(["B1"], "alpha")]
        new = [_chunk(["B1"], "alpha"), _chunk(["B2"], "new")]
        diff = diff_clause_candidates(old, new)
        self.assertEqual([list(k) for k in diff["added"]], [["B2"]])
        self.assertEqual(diff["changed"], [])

    def test_removed_candidate_flagged(self) -> None:
        old = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta")]
        new = [_chunk(["B1"], "alpha")]
        diff = diff_clause_candidates(old, new)
        self.assertEqual([list(k) for k in diff["removed"]], [["B2"]])

    def test_all_unchanged_emits_no_changes(self) -> None:
        old = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta")]
        new = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta")]
        diff = diff_clause_candidates(old, new)
        self.assertEqual(diff["changed"], [])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["unchanged_count"], 2)


class IncrementalRerunPlanTests(unittest.TestCase):
    def test_plan_rerun_queue_is_changed_union_added(self) -> None:
        old = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta"), _chunk(["B3"], "gamma")]
        new = [
            _chunk(["B1"], "alpha"),
            _chunk(["B2"], "BETA-CHANGED"),   # changed
            _chunk(["B4"], "delta"),          # added
        ]
        plan = incremental_rerun_plan(old, new)
        self.assertEqual(sorted(plan["rerun_block_ids"]), ["B2", "B4"])
        self.assertEqual(plan["rerun_block_count"], 2)
        self.assertGreater(plan["rerun_ratio"], 0.0)
        self.assertLess(plan["rerun_ratio"], 1.0)
        self.assertTrue(str(plan["rerun_idempotency_key"]).startswith("sha256:"))

    def test_plan_idempotency_key_stable_for_same_diff(self) -> None:
        old = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta")]
        new1 = [_chunk(["B1"], "alpha"), _chunk(["B2"], "X")]
        new2 = [_chunk(["B1"], "alpha"), _chunk(["B2"], "X")]
        k1 = incremental_rerun_plan(old, new1)["rerun_idempotency_key"]
        k2 = incremental_rerun_plan(old, new2)["rerun_idempotency_key"]
        self.assertEqual(k1, k2)  # 同一变化集合 → 同一幂等键（重试/续跑不二次扣费）

    def test_plan_idempotency_key_differs_for_different_diff(self) -> None:
        old = [_chunk(["B1"], "alpha"), _chunk(["B2"], "beta")]
        new_a = [_chunk(["B1"], "ALPHA"), _chunk(["B2"], "beta")]
        new_b = [_chunk(["B1"], "alpha"), _chunk(["B2"], "BETA")]
        k_a = incremental_rerun_plan(old, new_a)["rerun_idempotency_key"]
        k_b = incremental_rerun_plan(old, new_b)["rerun_idempotency_key"]
        self.assertNotEqual(k_a, k_b)

    def test_no_change_plan_has_empty_rerun_queue(self) -> None:
        old = [_chunk(["B1"], "alpha")]
        new = [_chunk(["B1"], "alpha")]
        plan = incremental_rerun_plan(old, new)
        self.assertEqual(plan["rerun_block_ids"], [])
        self.assertEqual(plan["rerun_block_count"], 0)


if __name__ == "__main__":
    unittest.main()
