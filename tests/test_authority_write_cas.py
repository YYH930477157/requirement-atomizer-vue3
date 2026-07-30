from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import ai_review_actions
import api_server
import claim_artifacts
import llm_pipeline
import review_state
from claim_ledger import atomic_target_fingerprint


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _b_requirement(requirement_id: str = "AIR-1") -> dict:
    return {
        "ai_req_id": requirement_id,
        "title": "Configurable output",
        "description": "The product shall support configurable indicator outputs.",
        "module": "interface",
        "source_section": "4.1",
        "source_quote": "Outputs can be configured by the operator.",
        "source_block_ids": ["BLK-1"],
    }


def _a_requirement(requirement_id: str = "SREQ-1") -> dict:
    return {
        "req_id": "AREQ-1",
        "stable_req_id": requirement_id,
        "source_id": "SRC-1",
        "source_type": "paragraph",
        "source_refs": ["SRC-1"],
        "section_path": ["4.1"],
        "domain": "interface",
        "object": "indicator output",
        "requirement_type": "functional",
        "requirement": "The product shall support configurable indicator outputs.",
        "condition": "",
        "parameters": {},
        "verification_method": "inspection",
    }


class BTrackAuthorityCASTests(unittest.TestCase):
    def test_write_revision_is_physical_and_semantic_revision_stays_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _b_requirement()
            _write_jsonl(root / "ai_requirements.jsonl", [requirement])

            initial = api_server.build_ai_requirements(root)[0]
            first = ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "accepted",
                source_fingerprint_value=initial["source_fingerprint"],
                review_subject_fingerprint_value=initial["review_subject_fingerprint"],
                expected_target_authority_write_revision=(
                    initial["target_authority_write_revision"]
                ),
            )
            accepted = api_server.build_ai_requirements(root)[0]
            second = ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "accepted",
                reason="same semantic decision, new audited row",
                source_fingerprint_value=accepted["source_fingerprint"],
                review_subject_fingerprint_value=accepted["review_subject_fingerprint"],
                expected_target_authority_write_revision=(
                    accepted["target_authority_write_revision"]
                ),
            )
            repeated = api_server.build_ai_requirements(root)[0]

            self.assertTrue(initial["target_review_revision"].startswith("sha256:"))
            self.assertTrue(initial["target_authority_write_revision"].startswith("sha256:"))
            self.assertNotEqual(
                initial["target_review_revision"], accepted["target_review_revision"]
            )
            self.assertEqual(
                accepted["target_review_revision"], repeated["target_review_revision"]
            )
            self.assertNotEqual(
                accepted["target_authority_write_revision"],
                repeated["target_authority_write_revision"],
            )
            self.assertEqual(
                first["target_authority_write_revision"],
                accepted["target_authority_write_revision"],
            )
            self.assertEqual(
                second["target_authority_write_revision"],
                repeated["target_authority_write_revision"],
            )

    def test_stale_revision_is_rejected_under_authority_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _b_requirement()
            _write_jsonl(root / "ai_requirements.jsonl", [requirement])
            row = api_server.build_ai_requirements(root)[0]
            stale = row["target_authority_write_revision"]
            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "accepted",
                source_fingerprint_value=row["source_fingerprint"],
                review_subject_fingerprint_value=row["review_subject_fingerprint"],
                expected_target_authority_write_revision=stale,
            )
            before = (root / "ai_review_states.jsonl").read_bytes()

            with self.assertRaises(ai_review_actions.AIReviewAuthorityConflict) as raised:
                ai_review_actions.apply_ai_review_action(
                    root,
                    "AIR-1",
                    "rejected",
                    source_fingerprint_value=row["source_fingerprint"],
                    review_subject_fingerprint_value=row["review_subject_fingerprint"],
                    expected_target_authority_write_revision=stale,
                )

            self.assertNotEqual(raised.exception.current_revision, stale)
            self.assertEqual((root / "ai_review_states.jsonl").read_bytes(), before)

    def test_unrelated_target_append_does_not_advance_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = ai_review_actions.read_ai_review_authority_snapshot(root)
            revision = ai_review_actions.ai_target_authority_write_revision("AIR-1", before)

            ai_review_actions.apply_ai_review_action(root, "AIR-2", "accepted")
            after = ai_review_actions.read_ai_review_authority_snapshot(root)

            self.assertEqual(
                revision,
                ai_review_actions.ai_target_authority_write_revision("AIR-1", after),
            )


class ATrackAuthorityCASTests(unittest.TestCase):
    def test_aba_changes_write_revision_but_restores_semantic_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _a_requirement()
            _write_jsonl(root / "atomic_requirements.jsonl", [requirement])

            initial = api_server.enrich_requirements([requirement], root)[0]
            accepted_state = review_state.apply_expert_decision(
                root,
                "SREQ-1",
                "accepted",
                actor="expert",
                expected_target_fingerprint=initial["target_fingerprint"],
                expected_target_authority_write_revision=(
                    initial["target_authority_write_revision"]
                ),
            )
            accepted = api_server.enrich_requirements([requirement], root)[0]
            rejected_state = review_state.apply_expert_decision(
                root,
                "SREQ-1",
                "rejected",
                actor="expert",
                expected_target_fingerprint=accepted["target_fingerprint"],
                expected_target_authority_write_revision=(
                    accepted["target_authority_write_revision"]
                ),
            )
            rejected = api_server.enrich_requirements([requirement], root)[0]
            restored_state = review_state.apply_expert_decision(
                root,
                "SREQ-1",
                "accepted",
                actor="expert",
                expected_target_fingerprint=rejected["target_fingerprint"],
                expected_target_authority_write_revision=(
                    rejected["target_authority_write_revision"]
                ),
            )
            restored = api_server.enrich_requirements([requirement], root)[0]

            self.assertEqual(accepted["target_review_revision"], restored["target_review_revision"])
            self.assertNotEqual(
                accepted["target_authority_write_revision"],
                restored["target_authority_write_revision"],
            )
            self.assertEqual(
                accepted_state["target_authority_write_revision"],
                accepted["target_authority_write_revision"],
            )
            self.assertEqual(
                rejected_state["target_authority_write_revision"],
                rejected["target_authority_write_revision"],
            )
            self.assertEqual(
                restored_state["target_authority_write_revision"],
                restored["target_authority_write_revision"],
            )

    def test_stale_revision_or_target_fingerprint_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _a_requirement()
            _write_jsonl(root / "atomic_requirements.jsonl", [requirement])
            row = api_server.enrich_requirements([requirement], root)[0]
            stale = row["target_authority_write_revision"]
            review_state.apply_expert_decision(
                root,
                "SREQ-1",
                "accepted",
                actor="expert",
                expected_target_fingerprint=row["target_fingerprint"],
                expected_target_authority_write_revision=stale,
            )
            before = (root / "review_states.jsonl").read_bytes()

            with self.assertRaises(review_state.ReviewAuthorityConflict):
                review_state.apply_expert_decision(
                    root,
                    "SREQ-1",
                    "rejected",
                    actor="expert",
                    expected_target_fingerprint=row["target_fingerprint"],
                    expected_target_authority_write_revision=stale,
                )
            self.assertEqual((root / "review_states.jsonl").read_bytes(), before)

            current = api_server.enrich_requirements([requirement], root)[0]
            changed = {**requirement, "requirement": "Changed subject."}
            _write_jsonl(root / "atomic_requirements.jsonl", [changed])
            with self.assertRaises(review_state.ReviewAuthorityConflict):
                review_state.apply_expert_decision(
                    root,
                    "SREQ-1",
                    "rejected",
                    actor="expert",
                    expected_target_fingerprint=current["target_fingerprint"],
                    expected_target_authority_write_revision=(
                        current["target_authority_write_revision"]
                    ),
                )
            self.assertNotEqual(
                current["target_fingerprint"], atomic_target_fingerprint(changed)
            )
            self.assertEqual((root / "review_states.jsonl").read_bytes(), before)


class AutomaticAuthorityMergeCASTests(unittest.TestCase):
    @staticmethod
    def _generated_state(requirement_id: str = "SREQ-1") -> dict:
        return {
            "requirement_id": requirement_id,
            "status": "accepted",
            "history": [{
                "from_status": "candidate",
                "to_status": "llm_reviewed",
                "actor": "llm_pipeline",
                "reason": "decision=accept",
                "timestamp": "2026-07-29T00:00:00+00:00",
            }, {
                "from_status": "llm_reviewed",
                "to_status": "accepted",
                "actor": "llm_pipeline",
                "reason": "low-risk acceptance",
                "timestamp": "2026-07-29T00:00:01+00:00",
            }],
            "metadata": {
                "stable_req_id": requirement_id,
                "req_id": "AREQ-1",
            },
        }

    def test_automatic_merge_binds_and_commits_a_protected_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _a_requirement()
            _write_jsonl(root / "atomic_requirements.jsonl", [requirement])
            requirements, preconditions = (
                llm_pipeline._load_automatic_review_snapshot(root, limit=0)
            )

            result = llm_pipeline._commit_automatic_review_states(
                root,
                [self._generated_state()],
                expected_preconditions=preconditions,
            )
            saved = review_state._read_jsonl(root / "review_states.jsonl")[0]
            binding = saved["metadata"]["automatic_authority_write"]

        self.assertEqual(requirements, [requirement])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(
            binding["protocol_version"],
            review_state.CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION,
        )
        self.assertEqual(
            binding["preconditions_hash"],
            preconditions["preconditions_hash"],
        )

    def test_automatic_merge_rejects_concurrent_authority_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jsonl(root / "atomic_requirements.jsonl", [_a_requirement()])
            _requirements, preconditions = (
                llm_pipeline._load_automatic_review_snapshot(root, limit=0)
            )
            review_state.apply_expert_decision(
                root,
                "SREQ-1",
                "rejected",
                actor="expert",
                reason="concurrent expert decision",
            )
            authority_before = (root / "review_states.jsonl").read_bytes()

            result = llm_pipeline._commit_automatic_review_states(
                root,
                [self._generated_state()],
                expected_preconditions=preconditions,
            )
            authority_after = (root / "review_states.jsonl").read_bytes()

        self.assertEqual(result["status"], "needs_reconfirmation")
        self.assertIn("target_or_authority_changed", result["reason"])
        self.assertEqual(result["states"][0]["status"], "rejected")
        self.assertEqual(authority_after, authority_before)

    def test_automatic_merge_rejects_concurrent_target_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _a_requirement()
            _write_jsonl(root / "atomic_requirements.jsonl", [requirement])
            _requirements, preconditions = (
                llm_pipeline._load_automatic_review_snapshot(root, limit=0)
            )
            _write_jsonl(
                root / "atomic_requirements.jsonl",
                [{**requirement, "requirement": "The changed product shall fail closed."}],
            )

            result = llm_pipeline._commit_automatic_review_states(
                root,
                [self._generated_state()],
                expected_preconditions=preconditions,
            )
            authority_exists = (root / "review_states.jsonl").exists()

        self.assertEqual(result["status"], "needs_reconfirmation")
        self.assertIn("target_publication_changed", result["reason"])
        self.assertFalse(authority_exists)

    def test_missing_automatic_target_reads_authority_under_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jsonl(root / "atomic_requirements.jsonl", [_a_requirement()])
            _requirements, preconditions = (
                llm_pipeline._load_automatic_review_snapshot(root, limit=0)
            )
            _write_jsonl(root / "review_states.jsonl", [self._generated_state()])
            _write_jsonl(root / "atomic_requirements.jsonl", [])
            lock_active = False
            real_lock = llm_pipeline.review_state_lock
            real_read_jsonl = llm_pipeline.read_jsonl

            @contextmanager
            def observed_lock(*args, **kwargs):
                nonlocal lock_active
                with real_lock(*args, **kwargs):
                    lock_active = True
                    try:
                        yield
                    finally:
                        lock_active = False

            def observed_read_jsonl(path):
                if Path(path).name == "review_states.jsonl":
                    self.assertTrue(lock_active)
                return real_read_jsonl(path)

            with (
                patch.object(llm_pipeline, "review_state_lock", observed_lock),
                patch.object(llm_pipeline, "read_jsonl", observed_read_jsonl),
            ):
                result = llm_pipeline._commit_automatic_review_states(
                    root,
                    [self._generated_state()],
                    expected_preconditions=preconditions,
                )

        self.assertEqual(result["status"], "needs_reconfirmation")
        self.assertIn("missing or ambiguous", result["reason"])

    def test_legacy_automatic_merge_without_tokens_skips_and_records_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jsonl(root / "atomic_requirements.jsonl", [_a_requirement()])

            result = llm_pipeline._commit_automatic_review_states(
                root,
                [self._generated_state()],
                expected_preconditions=None,
            )
            health = json.loads(
                (root / claim_artifacts.CLAIM_EFFECTIVE_HEALTH).read_text(
                    encoding="utf-8"
                )
            )
            authority_exists = (root / "review_states.jsonl").exists()

        self.assertEqual(result["status"], "needs_reconfirmation")
        self.assertFalse(authority_exists)
        self.assertEqual(health["legacy_authority_write_gap_count"], 1)
        self.assertEqual(
            health["legacy_authority_write_gaps"][0]["route"],
            "llm_pipeline.merge_review_states",
        )

class AuthorityCASHTTPTests(unittest.TestCase):
    def _post(self, root: Path, path: str, payload: dict) -> tuple[int, dict]:
        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.path = path
        handler.headers = {api_server.TOKEN_HEADER: "token"}
        handler.allowed_origins = set()
        handler.local_token = "token"
        handler.output_dir = root
        handler.read_json_body = lambda: payload
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))
        handler.send_error = lambda status, message="": responses.append(
            (status, {"error": message})
        )
        with patch("api_server._rebuilder"):
            handler.do_POST()
        self.assertEqual(len(responses), 1)
        return responses[0]

    def test_a_track_endpoint_requires_tokens_and_returns_current_revision_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _a_requirement()
            _write_jsonl(root / "atomic_requirements.jsonl", [requirement])

            status, _payload = self._post(root, "/review-actions", {
                "requirement_id": "SREQ-1",
                "status": "accepted",
            })
            self.assertEqual(status, 400)

            row = api_server.enrich_requirements([requirement], root)[0]
            request = {
                "requirement_id": "SREQ-1",
                "status": "accepted",
                "expected_target_fingerprint": row["target_fingerprint"],
                "expected_target_publication_revision": (
                    row["target_publication_revision"]
                ),
                "expected_target_authority_write_revision": (
                    row["target_authority_write_revision"]
                ),
            }
            status, saved = self._post(root, "/review-actions", request)
            self.assertEqual(status, 200)
            self.assertNotEqual(
                saved["target_authority_write_revision"],
                request["expected_target_authority_write_revision"],
            )

            status, conflict = self._post(root, "/review-actions", {
                **request,
                "status": "rejected",
            })
            self.assertEqual(status, 409)
            self.assertTrue(conflict["needs_reconfirmation"])
            self.assertEqual(
                conflict["target_authority_write_revision"],
                saved["target_authority_write_revision"],
            )

    def test_b_track_endpoint_requires_revision_and_returns_current_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _b_requirement()
            _write_jsonl(root / "ai_requirements.jsonl", [requirement])
            row = api_server.build_ai_requirements(root)[0]

            status, _payload = self._post(root, "/ai-review-actions", {
                "ai_req_id": "AIR-1",
                "status": "accepted",
                "source_fingerprint": row["source_fingerprint"],
                "review_subject_fingerprint": row["review_subject_fingerprint"],
            })
            self.assertEqual(status, 400)

            request = {
                "ai_req_id": "AIR-1",
                "status": "accepted",
                "source_fingerprint": row["source_fingerprint"],
                "review_subject_fingerprint": row["review_subject_fingerprint"],
                "expected_target_fingerprint": row["target_fingerprint"],
                "expected_target_publication_revision": (
                    row["target_publication_revision"]
                ),
                "expected_target_authority_write_revision": (
                    row["target_authority_write_revision"]
                ),
            }
            status, saved = self._post(root, "/ai-review-actions", request)
            self.assertEqual(status, 200)

            status, conflict = self._post(root, "/ai-review-actions", {
                **request,
                "status": "rejected",
            })
            self.assertEqual(status, 409)
            self.assertTrue(conflict["needs_reconfirmation"])
            self.assertEqual(
                conflict["target_authority_write_revision"],
                saved["target_authority_write_revision"],
            )


if __name__ == "__main__":
    unittest.main()
