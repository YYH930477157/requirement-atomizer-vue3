"""ai_review_actions 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_review_actions import (
    ai_req_id,
    apply_ai_review_action,
    read_ai_review_states,
    source_ai_requirement_id,
)


class OwnershipOverrideTests(unittest.TestCase):
    def test_persists_ownership_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            state = apply_ai_review_action(
                tmp_path,
                "AI-1",
                "accepted",
                module_override="时钟需求",
                ownership_override="co_design",
                reason="硬件 RTC 依赖需要确认",
                actor="tester",
            )

            assert state["ownership_override"] == "co_design"
            states = read_ai_review_states(tmp_path)
            assert states["AI-1"]["ownership_override"] == "co_design"

    def test_rejects_invalid_ownership_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as ctx:
                apply_ai_review_action(Path(td), "AI-1", "accepted", ownership_override="firmware")
            assert "unknown ownership" in str(ctx.exception)


class SourceAiRequirementIdTests(unittest.TestCase):
    """三处（api_server/ai_extract/requirements_analysis）共用的唯一主键实现。"""

    def test_explicit_id_wins_over_content_hash(self) -> None:
        req = {"ai_req_id": "AIR-explicit", "source_quote": "q", "title": "t"}
        assert source_ai_requirement_id(req) == "AIR-explicit"

    def test_falls_back_to_content_hash(self) -> None:
        req = {"source_section": "4", "source_quote": "q", "title": "t"}
        assert source_ai_requirement_id(req) == ai_req_id(req)


if __name__ == "__main__":
    unittest.main()
