"""WS2 §4.3 review_state / ai_review_actions 的 level 字段兼容层测试。

验收面：旧 ai_review_states 文件（无 level）零迁移打开、缺 level 解释为 atomic；
新写 level=functional 被正确持久化与回读。
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import review_state as rs
import ai_review_actions as ara


class ReviewLevelHelperTests(unittest.TestCase):
    def test_missing_level_defaults_atomic(self) -> None:
        self.assertEqual(rs.review_level({}), "atomic")
        self.assertEqual(rs.review_level(None), "atomic")

    def test_functional_level_preserved(self) -> None:
        self.assertEqual(rs.review_level({"level": "functional"}), "functional")

    def test_illegal_level_defaults_atomic(self) -> None:
        self.assertEqual(rs.review_level({"level": "nonsense"}), "atomic")

    def test_normalize(self) -> None:
        self.assertEqual(rs.normalize_review_level("functional"), "functional")
        self.assertEqual(rs.normalize_review_level(None), "atomic")
        self.assertEqual(rs.normalize_review_level("garbage"), "atomic")


class OldAiReviewStatesZeroMigrationTests(unittest.TestCase):
    """旧 ai_review_states.jsonl（无 level 字段）打开正常且解释为 atomic。"""

    def test_old_file_without_level_opens_as_atomic(self) -> None:
        with TemporaryDirectory() as tmp:
            from result_package import governed_artifact_path
            states_path = governed_artifact_path(tmp, ara.AI_REVIEW_STATES, category="state")
            states_path.parent.mkdir(parents=True, exist_ok=True)
            # 手写一条旧格式行（无 level）
            states_path.write_text(
                json.dumps({
                    "ai_req_id": "AIR-old1",
                    "status": "accepted",
                    "module_override": None,
                    "ownership_override": None,
                    "reason": "legacy",
                    "actor": "expert",
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            states = ara.read_ai_review_states(tmp)
            self.assertIn("AIR-old1", states)
            row = states["AIR-old1"]
            # 旧文件读路径不抛、解释为 atomic
            self.assertEqual(rs.review_level(row), "atomic")
            self.assertEqual(row["status"], "accepted")

    def test_new_write_with_functional_level_roundtrips(self) -> None:
        with TemporaryDirectory() as tmp:
            ara.apply_ai_review_action(
                tmp, "AIR-new1", "accepted", actor="expert",
                reason="functional-level review", level="functional",
            )
            states = ara.read_ai_review_states(tmp)
            self.assertEqual(rs.review_level(states["AIR-new1"]), "functional")
            self.assertEqual(states["AIR-new1"]["level"], "functional")

    def test_new_write_without_level_omits_key(self) -> None:
        with TemporaryDirectory() as tmp:
            ara.apply_ai_review_action(
                tmp, "AIR-new2", "accepted", actor="expert", reason="x",
            )
            states = ara.read_ai_review_states(tmp)
            # 不传 level → 行内无 level 键 → 读路径解释为 atomic（零迁移）
            self.assertNotIn("level", states["AIR-new2"])
            self.assertEqual(rs.review_level(states["AIR-new2"]), "atomic")


class ReviewStateLevelRoundtripTests(unittest.TestCase):
    def test_apply_expert_decision_persists_level(self) -> None:
        with TemporaryDirectory() as tmp:
            rs.apply_expert_decision(
                Path(tmp), "REQ-1", "accepted", actor="expert",
                reason="functional", level="functional",
            )
            from result_package import governed_artifact_path
            states_path = governed_artifact_path(tmp, "review_states.jsonl", category="state")
            rows = [json.loads(line) for line in states_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(r.get("level") == "functional" for r in rows))

    def test_apply_expert_decision_default_atomic(self) -> None:
        with TemporaryDirectory() as tmp:
            rs.apply_expert_decision(Path(tmp), "REQ-2", "accepted", actor="expert", reason="x")
            from result_package import governed_artifact_path
            states_path = governed_artifact_path(tmp, "review_states.jsonl", category="state")
            rows = [json.loads(line) for line in states_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            row = next(r for r in rows if r["requirement_id"] == "REQ-2")
            self.assertEqual(row.get("level"), "atomic")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
