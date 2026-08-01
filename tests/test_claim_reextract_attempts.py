from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import claim_reextract_attempts as attempts
from claim_artifacts import atomic_write_jsonl, hash_json
from omission_actions import AI_SUPPLEMENTS


def _hash(value: str) -> str:
    return hash_json("claim-reextract-attempt-test/v1", value)


def _common(attempt_id: str, event_kind: str, suffix: str) -> dict:
    return {
        "attempt_id": attempt_id,
        "proposal_id": "CQP-12345678-9abcdef0",
        "claim_id": "CLM-0123456789abcdef",
        "claim_hash": _hash("claim"),
        "event_kind": event_kind,
        "actor": "expert:yyh",
        "idempotency_key": _hash(suffix),
    }


def _started(attempt_id: str) -> dict:
    return {
        **_common(attempt_id, "reextract_started", "started"),
        "request_idempotency_key": "request-1",
        "route": "openai_compatible",
        "model": "deepseek-chat",
        "route_config_revision": _hash("route-config"),
        "budgets": {
            "max_calls": 1,
            "max_total_tokens": 4000,
            "allow_semantic_verifier": False,
        },
        "preconditions": {"claim_effective_revision": _hash("revision")},
        "focus": {"kind": "text_span", "block_id": "B1", "start": 0, "end": 5},
    }


class ClaimReextractAttemptTests(unittest.TestCase):
    def test_v1_started_event_without_route_revision_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id(
                "CQP-12345678-9abcdef0",
                "request-1",
            )
            started = _started(current_id)
            started["schema"] = "claim-reextract-attempt/v1"
            started.pop("route_config_revision")
            attempts.append_attempt_events(root, [started])

            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(snapshot.rows[0]["schema"], "claim-reextract-attempt/v1")
        self.assertNotIn("route_config_revision", snapshot.rows[0])

    def test_hash_chained_lifecycle_and_idempotent_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            started = _started(current_id)
            attempts.append_attempt_events(root, [started])
            duplicate = attempts.append_attempt_events(root, [started])
            self.assertEqual(duplicate["appended_count"], 0)

            events = [
                {
                    **_common(current_id, "budget_checkpoint", "budget-pre"),
                    "checkpoint": {
                        "phase": "pre_call", "calls": 1, "total_tokens": 4000,
                        "usage_complete": False, "status": "reserved",
                    },
                },
                {
                    **_common(current_id, "budget_checkpoint", "budget-post"),
                    "checkpoint": {
                        "phase": "post_call", "calls": 1, "total_tokens": 523,
                        "usage_complete": True, "status": "settled",
                    },
                },
                {
                    **_common(current_id, "supplement_persisted", "supplement"),
                    "supplement_id": "SUP-0123456789ab",
                    "supplement_hash": _hash("supplement"),
                },
                {
                    **_common(current_id, "requirements_published", "requirements"),
                    "requirements_sha256": _hash("requirements"),
                    "target_publication_revision": _hash("publication"),
                },
                {
                    **_common(current_id, "base_rebuild_published", "base"),
                    "base_generation_id": _hash("base"),
                },
                {
                    **_common(current_id, "effective_folded", "effective"),
                    "document_effective_revision": _hash("document-effective"),
                    "claim_effective_revision": _hash("claim-effective"),
                    "effective_fresh": True,
                },
                {
                    **_common(current_id, "reextract_succeeded", "succeeded"),
                    "outcome": {"code": "covered", "message": "", "retryable": False},
                    "usage": {"calls": 1, "total_tokens": 523, "usage_complete": True},
                },
            ]
            attempts.append_attempt_events(root, events)
            snapshot = attempts.read_attempt_log(root)

        self.assertEqual(snapshot.last_event_seq, 8)
        self.assertEqual(snapshot.rows[-1]["prev_event_hash"], snapshot.rows[-2]["event_hash"])
        state = attempts.derive_attempt_states(snapshot.rows)[current_id]
        self.assertEqual(state["lifecycle"], "succeeded")
        self.assertTrue(state["effective_folded"])

    def test_requirements_without_fold_projects_rebuild_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [
                _started(current_id),
                {
                    **_common(current_id, "supplement_persisted", "supplement"),
                    "supplement_id": "SUP-0123456789ab",
                    "supplement_hash": _hash("supplement"),
                },
                {
                    **_common(current_id, "requirements_published", "requirements"),
                    "requirements_sha256": _hash("requirements"),
                    "target_publication_revision": _hash("publication"),
                },
            ])
            state = attempts.derive_attempt_states(
                attempts.read_attempt_log(root).rows
            )[current_id]

        self.assertEqual(state["lifecycle"], "rebuild_pending")

    def test_illegal_checkpoint_order_and_post_terminal_append_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "lacks a supplement",
            ):
                attempts.append_attempt_events(root, [{
                    **_common(current_id, "requirements_published", "requirements"),
                    "requirements_sha256": _hash("requirements"),
                    "target_publication_revision": _hash("publication"),
                }])

            attempts.append_attempt_events(root, [{
                **_common(current_id, "reextract_failed", "failed"),
                "outcome": {"code": "remote_error", "message": "boom", "retryable": True},
                "usage": {"calls": 1, "total_tokens": None, "usage_complete": False},
            }])
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "continues after a terminal",
            ):
                attempts.append_attempt_events(root, [{
                    **_common(current_id, "budget_checkpoint", "too-late"),
                    "checkpoint": {
                        "phase": "error", "calls": 1, "total_tokens": None,
                        "usage_complete": False, "status": "unknown",
                    },
                }])

    def test_torn_tail_is_never_silently_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            with (root / attempts.CLAIM_REEXTRACT_ATTEMPTS).open("ab") as handle:
                handle.write(b'{"schema":"claim-reextract-attempt/v1"')

            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "torn tail",
            ):
                attempts.read_attempt_log(root)

    def test_failed_atomic_append_preserves_committed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id(
                "CQP-12345678-9abcdef0",
                "request-1",
            )
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            before = path.read_bytes()
            event = {
                **_common(current_id, "budget_checkpoint", "atomic-failure"),
                "checkpoint": {
                    "phase": "pre_call",
                    "calls": 1,
                    "total_tokens": 4000,
                    "usage_complete": False,
                    "status": "reserved",
                },
            }

            with mock.patch.object(
                attempts,
                "atomic_write_jsonl",
                side_effect=OSError("replace unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "replace unavailable"):
                    attempts.append_attempt_events(root, [event])

            self.assertEqual(path.read_bytes(), before)
            snapshot = attempts.read_attempt_log(root)
            self.assertEqual(snapshot.last_event_seq, 1)
            self.assertEqual(len(snapshot.rows), 1)


class AttemptLogStableReadTests(unittest.TestCase):
    def test_stable_read_retries_transient_torn_tail_from_active_append(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            full = path.read_bytes()
            torn = full + b'{"schema":"claim-reextract-attempt/v1"'
            reads = iter([torn, torn + b"x", full, full])
            original = Path.read_bytes

            def fake_read(self: Path) -> bytes:
                if self == path:
                    return next(reads)
                return original(self)

            with mock.patch.object(Path, "read_bytes", fake_read):
                snapshot = attempts.read_attempt_log_stable(root, delay_seconds=0)

        self.assertEqual(snapshot.last_event_seq, 1)
        self.assertEqual(snapshot.prefix_bytes, full)

    def test_stable_read_does_not_call_identical_partial_bytes_permanent(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            full = path.read_bytes()
            torn = full + b'{"schema":"claim-reextract-attempt/v1"'
            reads = iter([torn, torn, full, full])
            original = Path.read_bytes

            def fake_read(self: Path) -> bytes:
                if self == path:
                    return next(reads)
                return original(self)

            with mock.patch.object(Path, "read_bytes", fake_read):
                snapshot = attempts.read_attempt_log_stable(
                    root, max_attempts=4, delay_seconds=0,
                )

        self.assertEqual(snapshot.last_event_seq, 1)
        self.assertEqual(snapshot.prefix_bytes, full)

    def test_stable_read_does_not_return_a_valid_but_changing_first_read(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_id = attempts.attempt_id(
                "CQP-12345678-9abcdef0", "request-1"
            )
            attempts.append_attempt_events(root, [_started(first_id)])
            path = root / attempts.CLAIM_REEXTRACT_ATTEMPTS
            first = path.read_bytes()
            attempts.append_attempt_events(root, [{
                **_common(first_id, "reextract_failed", "failed"),
                "outcome": {
                    "code": "test_failure",
                    "message": "fixture",
                    "retryable": False,
                },
                "usage": {
                    "calls": 0,
                    "total_tokens": 0,
                    "usage_complete": True,
                },
            }])
            second = path.read_bytes()
            reads = iter([first, second, second])
            original = Path.read_bytes

            def fake_read(self: Path) -> bytes:
                if self == path:
                    return next(reads)
                return original(self)

            with mock.patch.object(Path, "read_bytes", fake_read):
                snapshot = attempts.read_attempt_log_stable(
                    root, delay_seconds=0,
                )

        self.assertEqual(snapshot.last_event_seq, 2)
        self.assertEqual(snapshot.prefix_bytes, second)

    def test_stable_read_fails_closed_on_permanent_torn_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])
            with (root / attempts.CLAIM_REEXTRACT_ATTEMPTS).open("ab") as handle:
                handle.write(b'{"schema":"claim-reextract-attempt/v1"')

            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "torn tail",
            ):
                attempts.read_attempt_log_stable(
                    root, max_attempts=3, delay_seconds=0
                )

    def test_stable_read_matches_plain_read_when_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [_started(current_id)])

            plain = attempts.read_attempt_log(root)
            stable = attempts.read_attempt_log_stable(root, delay_seconds=0)

        self.assertEqual(plain.prefix_sha256, stable.prefix_sha256)
        self.assertEqual(plain.last_event_seq, stable.last_event_seq)

    def test_stable_read_of_missing_log_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = attempts.read_attempt_log_stable(Path(tmp), delay_seconds=0)
        self.assertEqual(snapshot.last_event_seq, 0)
        self.assertEqual(snapshot.rows, [])

    def test_recovery_terminalizes_orphaned_reserved_call_with_unknown_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            attempts.append_attempt_events(root, [
                _started(current_id),
                {
                    **_common(current_id, "budget_checkpoint", "budget-pre"),
                    "checkpoint": {
                        "phase": "pre_call",
                        "calls": 1,
                        "total_tokens": 0,
                        "usage_complete": True,
                        "status": "reserved",
                    },
                },
            ])

            recovered = attempts.recover_interrupted_attempts(root)
            second = attempts.recover_interrupted_attempts(root)
            rows = attempts.read_attempt_log(root).rows
            state = attempts.derive_attempt_states(rows)[current_id]

        self.assertEqual(recovered["interrupted"], 1)
        self.assertEqual(second["appended_count"], 0)
        self.assertEqual(state["lifecycle"], "interrupted")
        self.assertEqual(rows[-1]["event_kind"], "reextract_interrupted")
        self.assertEqual(rows[-1]["usage"], {
            "calls": 1,
            "total_tokens": None,
            "usage_complete": False,
        })

    def test_recovery_reconciles_published_patch_without_duplicate_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_id = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            row = {
                "ai_req_id": "AIR-recovered",
                "title": "Configurable output",
                "description": "The output is configurable.",
                "source_section": "4.1",
                "source_quote": "The output shall be configurable.",
                "source_block_ids": ["B1"],
            }
            patch = {
                "schema": "ai-supplement/v2",
                "supplement_id": "SUP-0123456789ab",
                "origin": {
                    "kind": "claim_queue",
                    "claim_id": "CLM-0123456789abcdef",
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "attempt_id": current_id,
                },
                "upserts": [row],
            }
            atomic_write_jsonl(root / AI_SUPPLEMENTS, [patch])
            atomic_write_jsonl(root / "ai_requirements.jsonl", [row])
            before = (root / "ai_requirements.jsonl").read_bytes()
            attempts.append_attempt_events(root, [
                _started(current_id),
                {
                    **_common(current_id, "budget_checkpoint", "budget-post"),
                    "checkpoint": {
                        "phase": "post_call",
                        "calls": 1,
                        "total_tokens": 523,
                        "usage_complete": True,
                        "status": "settled",
                    },
                },
            ])

            recovered = attempts.recover_interrupted_attempts(root)
            rows = attempts.read_attempt_log(root).rows
            state = attempts.derive_attempt_states(rows)[current_id]
            provenance = attempts.require_published_attempt(
                root,
                attempt_id=current_id,
                requirements_sha256=rows[-1]["requirements_sha256"],
            )
            after = (root / "ai_requirements.jsonl").read_bytes()

        self.assertEqual(recovered["recovered"], 1)
        self.assertEqual(state["lifecycle"], "rebuild_pending")
        self.assertEqual(
            [item["event_kind"] for item in rows[-2:]],
            ["supplement_persisted", "requirements_published"],
        )
        self.assertEqual(provenance["started"]["attempt_id"], current_id)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
