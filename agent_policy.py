"""Version anchors shared by future agent decision stages."""
from __future__ import annotations


# Decision behavior version. Any change to decision rules, candidate actions, or stop
# conditions must bump this value. Decision-influenced cache fingerprints must include it.
AGENT_POLICY_VERSION = "agent-policy-v0"
