from __future__ import annotations

import json
import unittest
from pathlib import Path

import desktop_tasks
from agent_policy import AGENT_POLICY_VERSION


ROOT = Path(__file__).resolve().parents[1]


class AgentPolicyVersionTests(unittest.TestCase):
    def test_policy_version_is_frozen_in_trace_schema(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "decide_trace.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(AGENT_POLICY_VERSION, "agent-policy-v1")
        self.assertEqual(schema["properties"]["policy_version"]["const"], AGENT_POLICY_VERSION)

    def test_reserved_agent_stage_producer_includes_policy_version(self) -> None:
        self.assertEqual(
            desktop_tasks.stage_producer("agent-triage"),
            f"agent-triage+{AGENT_POLICY_VERSION}",
        )


if __name__ == "__main__":
    unittest.main()
