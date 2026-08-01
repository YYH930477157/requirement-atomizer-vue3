from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import claim_artifacts
import claim_queue_execution
import claim_reextract_attempts
import llm_client
from tests.test_claim_queue_execution import _hash, _proposal


class ClaimBudgetCheckpointOutboxTests(unittest.TestCase):
    _CHILD = r'''
import json
import os
from pathlib import Path
import sys

import ai_extract
import claim_artifacts
import claim_ledger
import claim_queue_execution
import claim_reextract_attempts
import llm_client
from tests.test_claim_artifacts import _baseline_cost, _catalog, _requirement
from tests.test_claim_queue_execution import _hash, _proposal

root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
network_marker = root / "network_calls.txt"
catalog = _catalog()
requirement = _requirement(catalog)
claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [requirement])
ai_extract.write_ai_requirements_metadata(
    root,
    input_fingerprint="test-input",
    run_id="budget-outbox-requirements",
    no_ledger_baseline_cost=_baseline_cost(),
)
target = claim_ledger.b_track_authority_state([requirement], {})
runtime = claim_ledger.semantic_verifier_runtime(
    route_mode="llm",
    enabled=True,
    rounds=1,
    budget_policy_version=llm_client.LLMRequestBudget.VERSION,
    max_calls=4,
    max_total_tokens=100000,
)
proposal = _proposal()
attempt_id = claim_reextract_attempts.attempt_id(
    proposal["proposal_id"],
    "budget-outbox-request",
)
started = {
    **claim_queue_execution._common_event(
        attempt_id=attempt_id,
        proposal=proposal,
        actor="expert:yyh",
        event_kind="reextract_started",
        detail="budget-outbox-request",
    ),
    "request_idempotency_key": "budget-outbox-request",
    "route": "openai_compatible",
    "model": "fake-model",
    "route_config_revision": _hash("route"),
    "budgets": {
        "max_calls": 4,
        "max_total_tokens": 100000,
        "allow_semantic_verifier": True,
    },
    "preconditions": dict(proposal["execution_preconditions"]),
    "focus": dict(proposal["focus"]),
}
claim_reextract_attempts.append_attempt_events(root, [started])

budget = llm_client.LLMRequestBudget(max_calls=4, max_tokens=100000)
budget.set_checkpoint(claim_queue_execution._ClaimQueueBudgetCheckpoint(
    root,
    attempt_id=attempt_id,
    proposal=proposal,
    actor="expert:yyh",
))
original_update = claim_artifacts._update_verifier_attempt_checkpoint_unlocked
ordinary_failed = False

def crash_at_second_sink(*args, **kwargs):
    global ordinary_failed
    snapshot = dict(kwargs.get("budget_snapshot") or {})
    if (
        mode in {"ordinary", "ordinary_second"}
        and not ordinary_failed
        and int(snapshot.get("attempted_calls") or 0)
        == (2 if mode == "ordinary_second" else 1)
        and int(snapshot.get("reserved_tokens") or 0) > 0
    ):
        ordinary_failed = True
        raise OSError("injected verifier WAL write failure")
    should_exit = (
        int(snapshot.get("attempted_calls") or 0) == 1
        and (
            mode == "pre" and int(snapshot.get("reserved_tokens") or 0) > 0
            or mode == "post"
            and int(snapshot.get("reserved_tokens") or 0) == 0
            and int(snapshot.get("tokens") or 0) == 17
        )
    )
    if should_exit:
        os._exit(91 if mode == "pre" else 92)
    return original_update(*args, **kwargs)

claim_artifacts._update_verifier_attempt_checkpoint_unlocked = crash_at_second_sink

original_replace = claim_artifacts._replace_with_retry

def crash_before_first_sink_replace(source, target):
    if (
        mode == "first"
        and Path(target).name
        == claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS
    ):
        os._exit(93)
    return original_replace(source, target)

if mode == "first":
    claim_artifacts._replace_with_retry = crash_before_first_sink_replace

class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 17},
        }).encode("utf-8")

def fake_urlopen(*_args, **_kwargs):
    count = int(network_marker.read_text(encoding="utf-8")) if network_marker.exists() else 0
    network_marker.write_text(str(count + 1), encoding="utf-8")
    return FakeResponse()

llm_client.urllib.request.urlopen = fake_urlopen
config = llm_client.LLMClientConfig(
    base_url="https://example.invalid/v1",
    model="fake-model",
    max_tokens=32,
    max_retries=0,
)
try:
    with claim_artifacts.claim_verifier_attempt_scope(
        root,
        attempt_kind="cold",
        attempt_request_id="budget-outbox-verifier",
        requirements_request_id="budget-outbox-requirements",
        failure_context={
            "catalog_build": catalog,
            "target_generation_id": target["target_generation_id"],
            "requirements_sha256": claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            ),
            "verifier_runtime": runtime,
            "baseline_cost": _baseline_cost(),
            "verifier_budget": budget,
        },
    ):
        llm_client._post_json(
            config,
            {"model": "fake-model", "messages": [], "max_tokens": 32},
            _request_budget=budget,
        )
        if mode == "ordinary_second":
            llm_client._post_json(
                config,
                {"model": "fake-model", "messages": [], "max_tokens": 32},
                _request_budget=budget,
            )
except OSError:
    if mode in {"ordinary", "ordinary_second"}:
        (root / "budget_after_error.json").write_text(
            json.dumps(budget.snapshot()), encoding="utf-8"
        )
        sys.exit(0)
    raise
raise AssertionError("crash probe did not exit")
'''

    def _run_probe(self, mode: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run(
                [sys.executable, "-c", self._CHILD, str(root), mode],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            expected_returncode = {"pre": 91, "post": 92, "first": 93}[mode]
            self.assertEqual(result.returncode, expected_returncode, result.stderr)
            marker = root / "network_calls.txt"
            if mode in {"pre", "first"}:
                self.assertFalse(marker.exists(), "pre-call crash must prevent HTTP")
            else:
                self.assertEqual(marker.read_text(encoding="utf-8"), "1")
            self.assertTrue(
                (root / claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX).is_file()
            )
            guarded_files = (
                claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS,
                claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT,
                claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX,
            )
            before_read = {
                name: (root / name).read_bytes()
                for name in guarded_files
            }
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "requires claim maintenance",
            ):
                claim_artifacts.read_claim_verifier_attempts(root)
            with self.assertRaisesRegex(
                claim_artifacts.ClaimEffectiveRecoveryPending,
                claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX,
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)
            self.assertEqual(
                {
                    name: (root / name).read_bytes()
                    for name in guarded_files
                },
                before_read,
            )

            automatic_recovery = None
            if mode in {"pre", "first"}:
                automatic_recovery = (
                    claim_reextract_attempts.recover_interrupted_attempts(root)
                )
                self.assertEqual(automatic_recovery["interrupted"], 1)
            else:
                recovered = claim_artifacts.recover_claim_budget_checkpoint_outbox(root)
                self.assertIsNotNone(recovered)
            self.assertFalse(
                (root / claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX).exists()
            )
            attempt_rows = claim_reextract_attempts.read_attempt_log(root).rows
            queue_checkpoint = next(
                row["checkpoint"]
                for row in reversed(attempt_rows)
                if row["event_kind"] == "budget_checkpoint"
            )
            verifier_checkpoint = claim_artifacts._read_verifier_attempt_checkpoint_unlocked(
                root
            )
            metrics = verifier_checkpoint["attempt_recovery"]["attempt_metrics"]
            self.assertEqual(queue_checkpoint["calls"], metrics["verifier_call_count"])
            self.assertEqual(queue_checkpoint["total_tokens"], metrics["verifier_tokens"])
            self.assertEqual(
                queue_checkpoint["usage_complete"],
                metrics["verifier_usage_complete"],
            )
            if mode in {"pre", "first"}:
                self.assertEqual(queue_checkpoint["status"], "reserved")
                self.assertGreater(queue_checkpoint["total_tokens"], 0)
                self.assertFalse(queue_checkpoint["usage_complete"])
            else:
                self.assertEqual(queue_checkpoint["status"], "settled")
                self.assertEqual(queue_checkpoint["total_tokens"], 17)
                self.assertTrue(queue_checkpoint["usage_complete"])

            before_replay = (root / claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS).read_bytes()
            self.assertIsNone(claim_artifacts.recover_claim_budget_checkpoint_outbox(root))
            self.assertEqual(
                (root / claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS).read_bytes(),
                before_replay,
            )
            if automatic_recovery is None:
                recovery = claim_reextract_attempts.recover_interrupted_attempts(root)
                self.assertEqual(recovery["interrupted"], 1)
            terminal = claim_reextract_attempts.read_attempt_log(root).rows[-1]
            self.assertEqual(terminal["usage"]["calls"], queue_checkpoint["calls"])
            self.assertEqual(
                terminal["usage"]["total_tokens"],
                queue_checkpoint["total_tokens"],
            )
            self.assertEqual(
                terminal["usage"]["usage_complete"],
                queue_checkpoint["usage_complete"],
            )
            # Recovery is deterministic and never re-enters the HTTP transport.
            self.assertEqual(
                marker.read_text(encoding="utf-8") if marker.exists() else "0",
                "0" if mode in {"pre", "first"} else "1",
            )

            verifier_rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(verifier_rows[-1]["attempt_metrics"], metrics | {
                "verifier_operation_failure_count": 1,
            })

    def test_pre_call_second_sink_kill_recovers_without_http(self) -> None:
        self._run_probe("pre")

    def test_pre_call_first_sink_kill_preserves_prefix_and_recovers_without_http(
        self,
    ) -> None:
        self._run_probe("first")

    def test_post_call_second_sink_kill_recovers_without_duplicate_http(self) -> None:
        self._run_probe("post")

    def test_second_sink_io_failure_is_reconciled_without_wedge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run(
                [sys.executable, "-c", self._CHILD, str(root), "ordinary"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "network_calls.txt").exists())
            self.assertFalse(
                (root / claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX).exists()
            )
            self.assertFalse(
                (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT).exists()
            )
            queue_rows = claim_reextract_attempts.read_attempt_log(root).rows
            checkpoint = next(
                row["checkpoint"]
                for row in reversed(queue_rows)
                if row["event_kind"] == "budget_checkpoint"
            )
            verifier_rows = claim_artifacts.read_claim_verifier_attempts(root)
            metrics = verifier_rows[-1]["attempt_metrics"]
            self.assertEqual(metrics["verifier_call_count"], checkpoint["calls"])
            self.assertEqual(metrics["verifier_tokens"], checkpoint["total_tokens"])
            self.assertEqual(
                metrics["verifier_usage_complete"],
                checkpoint["usage_complete"],
            )
            recovered = claim_reextract_attempts.recover_interrupted_attempts(root)
            self.assertEqual(recovered["interrupted"], 1)
            terminal = claim_reextract_attempts.read_attempt_log(root).rows[-1]
            self.assertEqual(terminal["usage"]["calls"], checkpoint["calls"])
            self.assertEqual(
                terminal["usage"]["total_tokens"],
                checkpoint["total_tokens"],
            )

    def test_later_pre_call_io_failure_cannot_regress_durable_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run(
                [sys.executable, "-c", self._CHILD, str(root), "ordinary_second"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "network_calls.txt").read_text(encoding="utf-8"),
                "1",
            )
            budget_after_error = json.loads(
                (root / "budget_after_error.json").read_text(encoding="utf-8")
            )
            self.assertEqual(budget_after_error["attempted_calls"], 2)
            self.assertGreater(budget_after_error["reserved_tokens"], 0)
            self.assertFalse(
                (root / claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX).exists()
            )
            self.assertFalse(
                (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT).exists()
            )
            queue_rows = claim_reextract_attempts.read_attempt_log(root).rows
            queue_checkpoint = next(
                row["checkpoint"]
                for row in reversed(queue_rows)
                if row["event_kind"] == "budget_checkpoint"
            )
            verifier_rows = claim_artifacts.read_claim_verifier_attempts(root)
            metrics = verifier_rows[-1]["attempt_metrics"]
            self.assertEqual(queue_checkpoint["calls"], 2)
            self.assertEqual(queue_checkpoint["status"], "reserved")
            self.assertEqual(
                queue_checkpoint["total_tokens"],
                budget_after_error["tokens"]
                + budget_after_error["reserved_tokens"],
            )
            self.assertEqual(
                queue_checkpoint["calls"], metrics["verifier_call_count"]
            )
            self.assertEqual(
                queue_checkpoint["total_tokens"], metrics["verifier_tokens"]
            )
            self.assertEqual(
                queue_checkpoint["usage_complete"],
                metrics["verifier_usage_complete"],
            )
            recovered = claim_reextract_attempts.recover_interrupted_attempts(root)
            self.assertEqual(recovered["interrupted"], 1)
            terminal = claim_reextract_attempts.read_attempt_log(root).rows[-1]
            self.assertEqual(terminal["usage"]["calls"], 2)
            self.assertEqual(
                terminal["usage"]["total_tokens"],
                metrics["verifier_tokens"],
            )
            self.assertFalse(terminal["usage"]["usage_complete"])

    def test_outbox_rejects_semantically_mismatched_projections(self) -> None:
        budget = llm_client.LLMRequestBudget(max_calls=4, max_tokens=100000)
        budget.reserve({"model": "fake-model", "messages": [], "max_tokens": 32})
        snapshot = budget.snapshot()
        checkpoint = claim_artifacts.claim_budget_checkpoint_payload(snapshot)
        self.assertIsNotNone(checkpoint)
        transaction_id = "a" * 32
        queue_event = {
            "schema": claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPT_SCHEMA,
            "attempt_id": "CRA-" + "1" * 16,
            "proposal_id": "CQP-" + "2" * 8 + "-" + "3" * 8,
            "claim_id": "CLM-" + "4" * 16,
            "claim_hash": "sha256:" + "5" * 64,
            "event_kind": "budget_checkpoint",
            "actor": "expert:test",
            "idempotency_key": (
                claim_artifacts.claim_budget_checkpoint_event_idempotency_key(
                    attempt_id="CRA-" + "1" * 16,
                    transition_id=transaction_id,
                    checkpoint=checkpoint,
                )
            ),
            "checkpoint": checkpoint,
        }
        outbox = {
            "schema": claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX_SCHEMA,
            "transaction_id": transaction_id,
            "verifier_nonce": "b" * 32,
            "created_at": "2026-08-01T00:00:00+00:00",
            "budget_snapshot": snapshot,
            "queue_event": queue_event,
        }
        outbox["outbox_sha256"] = claim_artifacts._sha256_payload(outbox)
        claim_artifacts._validate_budget_checkpoint_outbox(outbox)

        bad_checkpoint = copy.deepcopy(outbox)
        bad_checkpoint["queue_event"]["checkpoint"]["calls"] += 1
        bad_checkpoint["outbox_sha256"] = claim_artifacts._sha256_payload(
            {
                key: value
                for key, value in bad_checkpoint.items()
                if key != "outbox_sha256"
            }
        )
        with self.assertRaisesRegex(
            claim_artifacts.ClaimArtifactError,
            "projections do not match",
        ):
            claim_artifacts._validate_budget_checkpoint_outbox(bad_checkpoint)

        bad_transition = copy.deepcopy(outbox)
        bad_transition["transaction_id"] = "c" * 32
        bad_transition["outbox_sha256"] = claim_artifacts._sha256_payload(
            {
                key: value
                for key, value in bad_transition.items()
                if key != "outbox_sha256"
            }
        )
        with self.assertRaisesRegex(
            claim_artifacts.ClaimArtifactError,
            "projections do not match",
        ):
            claim_artifacts._validate_budget_checkpoint_outbox(bad_transition)

        bad_snapshot = copy.deepcopy(outbox)
        bad_snapshot["budget_snapshot"]["remaining_calls"] += 1
        bad_snapshot["outbox_sha256"] = claim_artifacts._sha256_payload(
            {
                key: value
                for key, value in bad_snapshot.items()
                if key != "outbox_sha256"
            }
        )
        with self.assertRaisesRegex(
            claim_artifacts.ClaimArtifactError,
            "inconsistent.*snapshot",
        ):
            claim_artifacts._validate_budget_checkpoint_outbox(bad_snapshot)

    def test_attempt_log_rejects_budget_call_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposal = _proposal()
            attempt = claim_reextract_attempts.attempt_id(
                proposal["proposal_id"], "budget-regression"
            )
            started = {
                **claim_queue_execution._common_event(
                    attempt_id=attempt,
                    proposal=proposal,
                    actor="expert:test",
                    event_kind="reextract_started",
                    detail="budget-regression",
                ),
                "request_idempotency_key": "budget-regression",
                "route": "openai_compatible",
                "model": "fake-model",
                "route_config_revision": _hash("route"),
                "budgets": {
                    "max_calls": 4,
                    "max_total_tokens": 100000,
                    "allow_semantic_verifier": True,
                },
                "preconditions": dict(proposal["execution_preconditions"]),
                "focus": dict(proposal["focus"]),
            }

            def checkpoint_event(calls: int) -> dict:
                payload = {
                    "phase": "pre_call",
                    "calls": calls,
                    "total_tokens": 100 * calls,
                    "usage_complete": False,
                    "status": "reserved",
                }
                return {
                    "schema": claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPT_SCHEMA,
                    **claim_queue_execution._common_event(
                        attempt_id=attempt,
                        proposal=proposal,
                        actor="expert:test",
                        event_kind="budget_checkpoint",
                        detail={"calls": calls},
                    ),
                    "checkpoint": payload,
                }

            claim_reextract_attempts.append_attempt_events(
                root,
                [started, checkpoint_event(2)],
            )
            before = (
                root / claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS
            ).read_bytes()
            with self.assertRaisesRegex(
                claim_reextract_attempts.ClaimReextractAttemptError,
                "calls regressed",
            ):
                claim_reextract_attempts.append_attempt_events(
                    root,
                    [checkpoint_event(1)],
                )
            self.assertEqual(
                (root / claim_reextract_attempts.CLAIM_REEXTRACT_ATTEMPTS).read_bytes(),
                before,
            )

if __name__ == "__main__":
    unittest.main()
