from __future__ import annotations

import multiprocessing
import tempfile
import threading
import time
import unittest
from pathlib import Path

import claim_artifacts
import claim_structural_operations as operations


def _request(*, reason: str = "verified source content") -> dict:
    return {
        "claim_id": "CLM-1111111111111111",
        "claim_hash": "sha256:" + "1" * 64,
        "expected_catalog_generation_id": "sha256:" + "2" * 64,
        "expected_claim_effective_revision": "sha256:" + "3" * 64,
        "prior_structural_reason": "repeated_page_furniture",
        "actor": "expert:test",
        "reason": reason,
        "request_idempotency_key": "structural-request-1",
        "allow_llm": False,
        "route": "stub",
        "verifier_max_calls": 0,
        "verifier_max_total_tokens": 0,
        "preconditions": {
            "document_effective_revision": "sha256:" + "4" * 64,
            "event_prefix_sha256": "sha256:" + "5" * 64,
            "last_event_seq": 0,
            "target_generation_id": "sha256:" + "6" * 64,
            "target_review_authority_revision": "sha256:" + "7" * 64,
            "route_config_revision": None,
            "route_model": None,
        },
    }


def _event_key(operation_id: str, kind: str, detail: str = "") -> str:
    return claim_artifacts.hash_json(
        "test-claim-structural-operation-event/v1",
        {"operation_id": operation_id, "kind": kind, "detail": detail},
    )


def _acquire_in_child(root: str, acquired_path: str) -> None:
    with operations.structural_execution_lease(
        Path(root), operation_id="CSOP-child", timeout_s=5.0,
    ):
        Path(acquired_path).write_text("acquired", encoding="ascii")


class ClaimStructuralOperationLogTests(unittest.TestCase):
    def test_get_or_create_is_atomic_and_binds_the_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request()
            results: list[dict] = []
            barrier = threading.Barrier(2)

            def create() -> None:
                barrier.wait()
                results.append(operations.get_or_create_operation(root, request))

            threads = [threading.Thread(target=create) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(results), 2)
            self.assertEqual(sum(bool(row["created"]) for row in results), 1)
            snapshot = operations.read_operation_log(root)
            self.assertEqual(
                [row["event_kind"] for row in snapshot.rows],
                ["operation_started"],
            )
            with self.assertRaises(operations.ClaimStructuralOperationConflict):
                operations.get_or_create_operation(
                    root, _request(reason="a different authorized payload"),
                )

    def test_same_claim_cannot_have_two_active_operations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            operations.get_or_create_operation(root, _request())
            other = {
                **_request(),
                "request_idempotency_key": "structural-request-2",
            }
            with self.assertRaises(operations.ClaimStructuralOperationConflict):
                operations.get_or_create_operation(root, other)

    def test_fsm_rejects_early_success_and_duplicate_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            created = operations.get_or_create_operation(root, _request())
            operation_id = created["operation_id"]
            with self.assertRaises(operations.ClaimStructuralOperationError):
                operations.append_operation_events(root, [{
                    "operation_id": operation_id,
                    "event_kind": "operation_succeeded",
                    "idempotency_key": _event_key(operation_id, "early-success"),
                    "outcome": {
                        "code": "rebuilt", "message": "", "retryable": False,
                    },
                    "binding": {
                        "override_hash": "sha256:" + "8" * 64,
                        "base_generation_id": "sha256:" + "9" * 64,
                        "document_effective_revision": "sha256:" + "a" * 64,
                        "claim_effective_revision": "sha256:" + "b" * 64,
                        "effective_meta_sha256": "sha256:" + "c" * 64,
                    },
                }])

            operations.append_operation_events(root, [{
                "operation_id": operation_id,
                "event_kind": "override_registered",
                "idempotency_key": _event_key(operation_id, "override"),
                "override_id": "CSO-1111111111111111",
                "override_hash": "sha256:" + "8" * 64,
                "registry_prefix_sha256": "sha256:" + "9" * 64,
                "registry_prefix_count": 1,
            }, {
                "operation_id": operation_id,
                "event_kind": "audit_appended",
                "idempotency_key": _event_key(operation_id, "audit"),
                "audit_event_hash": "sha256:" + "d" * 64,
                "event_prefix_sha256": "sha256:" + "e" * 64,
                "last_event_seq": 1,
            }])
            with self.assertRaises(operations.ClaimStructuralOperationError):
                operations.append_operation_events(root, [{
                    "operation_id": operation_id,
                    "event_kind": "audit_appended",
                    "idempotency_key": _event_key(operation_id, "audit-2"),
                    "audit_event_hash": "sha256:" + "f" * 64,
                    "event_prefix_sha256": "sha256:" + "0" * 64,
                    "last_event_seq": 2,
                }])

    def test_budget_checkpoint_cannot_expand_original_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request()
            request.update({
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 1,
                "verifier_max_total_tokens": 1000,
            })
            request["preconditions"].update({
                "route_config_revision": "sha256:" + "a" * 64,
                "route_model": "test-model",
            })
            operation_id = operations.get_or_create_operation(
                root, request,
            )["operation_id"]
            operations.append_operation_events(root, [{
                "operation_id": operation_id,
                "event_kind": "override_registered",
                "idempotency_key": _event_key(operation_id, "override"),
                "override_id": "CSO-1111111111111111",
                "override_hash": "sha256:" + "8" * 64,
                "registry_prefix_sha256": "sha256:" + "9" * 64,
                "registry_prefix_count": 1,
            }, {
                "operation_id": operation_id,
                "event_kind": "audit_appended",
                "idempotency_key": _event_key(operation_id, "audit"),
                "audit_event_hash": "sha256:" + "d" * 64,
                "event_prefix_sha256": "sha256:" + "e" * 64,
                "last_event_seq": 1,
            }])
            forged = {
                "version": "llm-request-budget-v1",
                "max_calls": 2,
                "max_tokens": 1000,
                "attempted_calls": 1,
                "failed_calls": 0,
                "tokens": 0,
                "reserved_tokens": 100,
                "remaining_calls": 1,
                "remaining_tokens": 900,
                "usage_complete": True,
                "denied": False,
                "termination_reason": "",
                "status": "reserved",
            }
            with self.assertRaisesRegex(
                operations.ClaimStructuralOperationError,
                "changed its authorization",
            ):
                operations.append_operation_events(root, [{
                    "operation_id": operation_id,
                    "event_kind": "budget_checkpoint",
                    "idempotency_key": _event_key(
                        operation_id, "forged-budget",
                    ),
                    "checkpoint": forged,
                }])

    def test_execution_lease_serializes_threads_and_processes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            entered = threading.Event()
            release = threading.Event()
            second_entered = threading.Event()

            def first() -> None:
                with operations.structural_execution_lease(
                    root, operation_id="CSOP-first", timeout_s=5.0,
                ):
                    entered.set()
                    release.wait(5)

            def second() -> None:
                entered.wait(5)
                with operations.structural_execution_lease(
                    root, operation_id="CSOP-second", timeout_s=5.0,
                ):
                    second_entered.set()

            first_thread = threading.Thread(target=first)
            second_thread = threading.Thread(target=second)
            first_thread.start()
            second_thread.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(second_entered.wait(0.2))
            release.set()
            first_thread.join(5)
            second_thread.join(5)
            self.assertTrue(second_entered.is_set())

            acquired = root / "child-acquired"
            with operations.structural_execution_lease(
                root, operation_id="CSOP-parent", timeout_s=5.0,
            ):
                process = multiprocessing.Process(
                    target=_acquire_in_child,
                    args=(str(root), str(acquired)),
                )
                process.start()
                time.sleep(0.3)
                self.assertFalse(acquired.exists())
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(acquired.is_file())


if __name__ == "__main__":
    unittest.main()
