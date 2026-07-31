from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import claim_artifacts
import claim_ledger
import claim_review_actions
import ai_review_actions
import claim_catalog
import llm_pipeline
import omission_actions
import review_state
from tests.test_claim_artifacts import (
    _catalog,
    _publish,
    _requirement,
    _shadow,
    _write_current_requirements_meta,
)


def _hash(label: str) -> str:
    return claim_artifacts.hash_json("claim-review-action-test/v1", label)


def _draft(index: int, *, event_kind: str = "target_invalidated") -> dict:
    after = "unknown" if event_kind == "target_invalidated" else "active"
    before = "active" if event_kind == "target_invalidated" else "unknown"
    claim_id = "CLM-0123456789abcdef"
    idempotency_key = _hash(f"idempotency-{index}")
    return {
        "schema": claim_ledger.CLAIM_REVIEW_EVENT_SCHEMA,
        "claim_id": claim_id,
        "claim_hash": _hash("claim"),
        "document_generation_id": _hash("document"),
        "catalog_generation_id": _hash("catalog"),
        "event_kind": event_kind,
        "eligibility_before": before,
        "eligibility_after": after,
        "actor": "system:claim-review-bridge",
        "recorded_at": f"2026-07-28T00:00:0{index}+00:00",
        "reason": "target_missing" if event_kind == "target_invalidated" else "target_restored",
        "trigger_kind": "target_set",
        "source_store": "ai_requirements.jsonl",
        "source_event_revision": _hash(f"source-{index}"),
        "target_review_revision": _hash(f"review-{index}"),
        "target_kind": "ai_requirement",
        "target_requirement_id": "AIR-1",
        "target_fingerprint": _hash("target"),
        "observed_target_fingerprint": None if event_kind == "target_invalidated" else _hash("target"),
        "linked_claim_ids": [claim_id],
        "idempotency_key": idempotency_key,
        "projection_mode": "bootstrap_base",
        "expected_base_claim_row_hash": _hash("base-row"),
        "expected_claim_effective_revision": None,
        "bridge_version": claim_ledger.CLAIM_REVIEW_BRIDGE_VERSION,
        "route": "deterministic",
    }


def _atomic_requirement(catalog: dict) -> dict:
    text = str(catalog["catalog"][0]["text"]).strip()
    return {
        "req_id": "AREQ-000001",
        "stable_req_id": "SREQ-0123456789ABCDEF",
        "source_id": "B1",
        "source_type": "paragraph",
        "source_refs": ["B1"],
        "section_path": ["4 Functions"],
        "domain": "meter",
        "object": "auxiliary output",
        "requirement_type": "functional",
        "requirement": text,
        "condition": None,
        "parameters": {},
        "verification_method": "inspection",
        "ambiguity": False,
        "confidence": 1.0,
        "generated_by": "claim-review-action-test",
    }


def _a_track_shadow(catalog: dict, requirement: dict) -> dict:
    shadow = copy.deepcopy(_shadow(catalog))
    authority = claim_ledger.a_track_effective_authority([requirement], [])
    target = authority["records"][0]
    group = shadow["groups"][0]
    edge = group["edges"][0]
    edge.update({
        "target_kind": "atomic_requirement",
        "target_generation_id": authority["target_set_hash"],
        "target_requirement_id": target["target_requirement_id"],
        "target_fingerprint": target["target_fingerprint"],
        "target_review_status": target["review"]["status"],
        "target_review_eligibility": target["review"]["eligibility"],
        "target_review_revision": target["review"]["target_review_revision"],
        "review_adapter_version": target["review"]["review_adapter_version"],
        "produced_evidence": target["evidence"],
    })
    edge_hash = claim_ledger._sha256({
        "claim_hash": group["claim_hash"],
        "target_id": edge["target_requirement_id"],
        "target_fingerprint": edge["target_fingerprint"],
        "produced_evidence": edge["produced_evidence"],
    })
    edge["edge_id"] = "CED-" + edge_hash.removeprefix("sha256:")[:16]
    group_hash = claim_ledger._sha256({
        "claim_hash": group["claim_hash"],
        "edges": [edge["edge_id"]],
        "validation_method": group["validation_method"],
    })
    group["coverage_group_id"] = (
        "CGR-" + group_hash.removeprefix("sha256:")[:16]
    )
    group["validation_input_hash"] = claim_ledger._sha256({
        "claim_hash": group["claim_hash"],
        "source_evidence": group["source_evidence"],
        "edges": [{
            "target_requirement_id": edge["target_requirement_id"],
            "target_fingerprint": edge["target_fingerprint"],
            "target_review_revision": edge["target_review_revision"],
            "relation": edge["relation"],
            "produced_evidence": edge["produced_evidence"],
        }],
        "prefilter": group["prefilter"],
        "validation_method": group["validation_method"],
        "verifier_runtime_fingerprint": group["verifier_runtime_fingerprint"],
        "validator_version": group["validator_version"],
    })
    shadow["ledger"] = [claim_ledger.reduce_claim(
        catalog["catalog"][0],
        validated_groups=[group],
        all_groups=[group],
    )]
    shadow["meta"].update({
        "delivery_track": "A",
        "target_kind": "atomic_requirement",
        "target_generation_id": authority["target_set_hash"],
        "target_review_authority_revision": authority[
            "requirement_review_state_hash"
        ],
    })
    return shadow


def _publish_a_track(root: Path, catalog: dict) -> dict:
    requirement = _atomic_requirement(catalog)
    claim_artifacts.atomic_write_jsonl(
        root / "atomic_requirements.jsonl",
        [requirement],
    )
    _write_current_requirements_meta(root)
    claim_artifacts.publish_shadow_generation(
        root,
        catalog,
        _a_track_shadow(catalog, requirement),
        run_id="a-track-run-1",
        requirements_sha256=claim_artifacts.file_sha256(
            root / "atomic_requirements.jsonl"
        ),
    )
    return requirement


class ClaimReviewEventLogTests(unittest.TestCase):
    def test_append_replays_hash_chain_and_absorbs_duplicate_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = claim_review_actions.append_claim_review_events(
                root,
                [_draft(1), _draft(2, event_kind="target_reactivated"), _draft(1)],
            )
            self.assertEqual(result["appended_count"], 2)
            snapshot = claim_review_actions.read_claim_review_events(root)
            self.assertEqual([row["event_seq"] for row in snapshot.rows], [1, 2])
            self.assertEqual(snapshot.rows[0]["prev_event_hash"], claim_artifacts.sha256_bytes(b""))
            self.assertEqual(snapshot.rows[1]["prev_event_hash"], snapshot.rows[0]["event_hash"])
            self.assertEqual(snapshot.last_event_hash, snapshot.rows[1]["event_hash"])
            self.assertEqual(
                snapshot.event_prefix_sha256,
                claim_artifacts.file_sha256(root / claim_artifacts.CLAIM_REVIEW_EVENTS),
            )

    def test_torn_tail_is_truncated_before_next_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_review_actions.append_claim_review_events(root, [_draft(1)])
            with (root / claim_artifacts.CLAIM_REVIEW_EVENTS).open("ab") as handle:
                handle.write(b'{"torn"')
            result = claim_review_actions.append_claim_review_events(
                root,
                [_draft(2, event_kind="target_reactivated")],
            )
            self.assertTrue(result["torn_tail_recovered"])
            self.assertIsNone(result["quarantine_file"])
            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).last_event_seq,
                2,
            )


class EffectiveFoldTests(unittest.TestCase):
    def test_historical_append_cas_does_not_block_same_claim_on_new_base(self) -> None:
        base_row = {
            "claim_id": "CLM-0123456789abcdef",
            "claim_hash": _hash("claim"),
            "document_generation_id": _hash("document"),
            "catalog_generation_id": _hash("catalog"),
        }
        event = {
            **base_row,
            "event_kind": "expert_adjudication",
            "expected_base_claim_row_hash": _hash("previous-base-row"),
        }

        relevant = claim_review_actions._relevant_events([event], base_row)

        self.assertEqual(relevant, [event])

    def test_document_effective_revision_is_sensitive_to_all_authority_inputs(self) -> None:
        baseline_inputs = {
            "base_generation_id": _hash("base-generation"),
            "last_event_seq": 3,
            "event_prefix_sha256": _hash("event-prefix"),
            "target_set_hash": _hash("target-set"),
            "requirement_review_state_hash": _hash("review-state"),
            "authority_projection_hash": _hash("authority-projection"),
        }
        baseline = claim_review_actions._document_effective_revision(
            **baseline_inputs
        )
        mutations = {
            "base_generation_id": _hash("base-generation-next"),
            "last_event_seq": 4,
            "event_prefix_sha256": _hash("event-prefix-next"),
            "target_set_hash": _hash("target-set-next"),
            "requirement_review_state_hash": _hash("review-state-next"),
            "authority_projection_hash": _hash("authority-projection-next"),
        }

        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = dict(baseline_inputs)
                changed[field] = value
                self.assertNotEqual(
                    claim_review_actions._document_effective_revision(**changed),
                    baseline,
                )

    def test_b_track_hook_failure_persists_authority_and_records_fold_lag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())

            with patch(
                "claim_review_actions.reconcile_claim_review_events",
                side_effect=RuntimeError("injected B-track hook failure"),
            ):
                result = ai_review_actions.apply_ai_review_action(
                    root,
                    "AIR-1",
                    "rejected",
                    actor="test",
                    reason="failure injection",
                )

            self.assertEqual(result["status"], "rejected")
            self.assertEqual(
                ai_review_actions.read_ai_review_states(root)["AIR-1"]["status"],
                "rejected",
            )
            health = claim_review_actions.read_effective_health(root)
            self.assertEqual(health["bridge_fold_lag"], 1)
            self.assertIn("injected B-track hook failure", health["last_error"])

    def test_b_track_hook_releases_authority_lock_before_fold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            lock_active = False
            real_lock = ai_review_actions._ai_review_state_lock

            @contextmanager
            def observed_lock(*args, **kwargs):
                nonlocal lock_active
                with real_lock(*args, **kwargs):
                    lock_active = True
                    try:
                        yield
                    finally:
                        lock_active = False

            def observed_fold(*args, **kwargs):
                self.assertFalse(lock_active)
                self.assertEqual(kwargs["authority_hook_track"], "B")
                return {"ok": True}

            with (
                patch.object(
                    ai_review_actions,
                    "_ai_review_state_lock",
                    observed_lock,
                ),
                patch.object(
                    claim_review_actions,
                    "fold_effective_ledger",
                    side_effect=observed_fold,
                ),
            ):
                result = ai_review_actions.apply_ai_review_action(
                    root,
                    "AIR-1",
                    "rejected",
                    actor="test",
                    reason="lock-order probe",
                )

        self.assertEqual(result["status"], "rejected")

    def test_a_track_hook_failure_persists_authority_and_records_fold_lag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())

            with patch(
                "claim_review_actions.reconcile_claim_review_events",
                side_effect=RuntimeError("injected A-track hook failure"),
            ):
                result = review_state.apply_expert_decision(
                    root,
                    requirement["stable_req_id"],
                    "rejected",
                    actor="expert",
                    reason="failure injection",
                )

            self.assertEqual(result["status"], "rejected")
            states = review_state.read_review_authority_snapshot(root)["states"]
            self.assertEqual(states[0]["status"], "rejected")
            health = claim_review_actions.read_effective_health(root)
            self.assertEqual(health["bridge_fold_lag"], 1)
            self.assertIn("injected A-track hook failure", health["last_error"])

    def test_a_track_hook_releases_authority_lock_before_fold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())
            lock_active = False
            real_lock = review_state.review_state_lock

            @contextmanager
            def observed_lock(*args, **kwargs):
                nonlocal lock_active
                with real_lock(*args, **kwargs):
                    lock_active = True
                    try:
                        yield
                    finally:
                        lock_active = False

            def observed_fold(*args, **kwargs):
                self.assertFalse(lock_active)
                self.assertEqual(kwargs["authority_hook_track"], "A")
                return {"ok": True}

            with (
                patch.object(review_state, "review_state_lock", observed_lock),
                patch.object(
                    claim_review_actions,
                    "fold_effective_ledger",
                    side_effect=observed_fold,
                ),
            ):
                result = review_state.apply_expert_decision(
                    root,
                    requirement["stable_req_id"],
                    "rejected",
                    actor="expert",
                    reason="lock-order probe",
                )

        self.assertEqual(result["status"], "rejected")

    def test_a_and_b_authority_writes_racing_fold_finish_without_deadlock(self) -> None:
        for track in ("A", "B"):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if track == "A":
                    requirement = _publish_a_track(root, _catalog())
                    authority_module = review_state
                    authority_lock_name = "review_state_lock"
                else:
                    _publish(root, _catalog())
                    requirement = None
                    authority_module = ai_review_actions
                    authority_lock_name = "_ai_review_state_lock"

                fold_waiting_for_authority = threading.Event()
                writer_holds_authority = threading.Event()
                errors: list[BaseException] = []
                real_authority_lock = getattr(
                    authority_module,
                    authority_lock_name,
                )
                real_load_authority = claim_review_actions._load_declared_authority
                gated_fold_thread_id: int | None = None
                gate_used = False

                @contextmanager
                def observed_authority_lock(*args, **kwargs):
                    with real_authority_lock(*args, **kwargs):
                        if threading.current_thread().name == f"{track}-writer":
                            writer_holds_authority.set()
                        yield

                def gated_load_authority(*args, **kwargs):
                    nonlocal gate_used
                    if (
                        threading.get_ident() == gated_fold_thread_id
                        and not gate_used
                    ):
                        gate_used = True
                        self.assertIn(root, claim_artifacts._PUBLICATION_LOCK_STATES)
                        fold_waiting_for_authority.set()
                        if not writer_holds_authority.wait(timeout=5):
                            raise AssertionError(
                                "authority writer did not reach the injected lock point"
                            )
                    return real_load_authority(*args, **kwargs)

                def run_fold() -> None:
                    nonlocal gated_fold_thread_id
                    gated_fold_thread_id = threading.get_ident()
                    try:
                        claim_review_actions.fold_effective_ledger(
                            root,
                            actor_trigger=f"{track.lower()}-concurrent-fold",
                        )
                    except BaseException as exc:  # surfaced in the test thread
                        errors.append(exc)

                def run_writer() -> None:
                    try:
                        if track == "A":
                            assert requirement is not None
                            review_state.apply_expert_decision(
                                root,
                                requirement["stable_req_id"],
                                "rejected",
                                actor="expert",
                                reason="controlled lock-order race",
                            )
                        else:
                            ai_review_actions.apply_ai_review_action(
                                root,
                                "AIR-1",
                                "rejected",
                                actor="expert",
                                reason="controlled lock-order race",
                            )
                    except BaseException as exc:  # surfaced in the test thread
                        errors.append(exc)

                with (
                    patch.object(
                        authority_module,
                        authority_lock_name,
                        observed_authority_lock,
                    ),
                    patch.object(
                        claim_review_actions,
                        "_load_declared_authority",
                        side_effect=gated_load_authority,
                    ),
                ):
                    fold_thread = threading.Thread(
                        target=run_fold,
                        name=f"{track}-fold",
                        daemon=True,
                    )
                    fold_thread.start()
                    self.assertTrue(
                        fold_waiting_for_authority.wait(timeout=5),
                        "fold did not reach the injected authority boundary",
                    )
                    writer_thread = threading.Thread(
                        target=run_writer,
                        name=f"{track}-writer",
                        daemon=True,
                    )
                    writer_thread.start()
                    fold_thread.join(timeout=10)
                    writer_thread.join(timeout=10)

                self.assertFalse(fold_thread.is_alive(), "fold deadlocked")
                self.assertFalse(writer_thread.is_alive(), "authority write deadlocked")
                self.assertEqual(errors, [])
                self.assertTrue(writer_holds_authority.is_set())

    def test_automatic_merge_acquires_extraction_before_review_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())
            _requirements, preconditions = llm_pipeline._load_automatic_review_snapshot(
                root,
                limit=0,
            )
            generated_state = {
                "requirement_id": requirement["stable_req_id"],
                "status": "accepted",
                "history": [{
                    "from_status": "candidate",
                    "to_status": "accepted",
                    "actor": "llm_pipeline",
                    "reason": "controlled lock-order probe",
                    "timestamp": "2026-07-29T00:00:00+00:00",
                }],
                "metadata": {
                    "stable_req_id": requirement["stable_req_id"],
                    "req_id": requirement["req_id"],
                },
            }
            extraction_active = False
            review_entries = 0
            real_extraction_lock = omission_actions.extraction_operation_lock
            real_review_lock = llm_pipeline.review_state_lock

            @contextmanager
            def observed_extraction_lock(*args, **kwargs):
                nonlocal extraction_active
                with real_extraction_lock(*args, **kwargs):
                    extraction_active = True
                    try:
                        yield
                    finally:
                        extraction_active = False

            @contextmanager
            def observed_review_lock(*args, **kwargs):
                nonlocal review_entries
                self.assertTrue(
                    extraction_active,
                    "automatic merge acquired review authority before extraction lease",
                )
                review_entries += 1
                with real_review_lock(*args, **kwargs):
                    yield

            with (
                patch.object(
                    omission_actions,
                    "extraction_operation_lock",
                    observed_extraction_lock,
                ),
                patch.object(
                    llm_pipeline,
                    "review_state_lock",
                    observed_review_lock,
                ),
            ):
                result = llm_pipeline._commit_automatic_review_states(
                    root,
                    [generated_state],
                    expected_preconditions=preconditions,
                )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(review_entries, 1)

    def test_authority_hooks_do_not_cross_declared_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_root = Path(tmp) / "a"
            requirement = _publish_a_track(a_root, _catalog())
            a_before = {
                name: (a_root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                if (a_root / name).is_file()
            }
            ai_review_actions.apply_ai_review_action(
                a_root,
                "AIR-unrelated",
                "rejected",
                actor="test",
                reason="must not drive A-track producer",
            )
            a_after = {
                name: (a_root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                if (a_root / name).is_file()
            }

            b_root = Path(tmp) / "b"
            _publish(b_root, _catalog())
            b_before = {
                name: (b_root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                if (b_root / name).is_file()
            }
            review_state.apply_expert_decision(
                b_root,
                requirement["stable_req_id"],
                "rejected",
                actor="expert",
                reason="must not drive B-track producer",
            )
            b_after = {
                name: (b_root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                if (b_root / name).is_file()
            }

        self.assertEqual(a_after, a_before)
        self.assertEqual(b_after, b_before)

    def test_effective_version_bump_keeps_base_current_and_only_refolds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="effective-version-seed",
            )
            base = claim_artifacts.load_committed_claim_base(root)
            effective = claim_artifacts.load_committed_effective_snapshot(root)
            base_files = {
                name: (root / name).read_bytes()
                for name in (
                    claim_artifacts.CLAIM_CATALOG,
                    claim_artifacts.CLAIM_CATALOG_META,
                    claim_artifacts.CLAIM_COVERAGE_GROUPS,
                    claim_artifacts.CLAIM_LEDGER,
                    claim_artifacts.CLAIM_SHADOW_METRICS,
                    claim_artifacts.CLAIM_GENERATION_META,
                )
            }

            with (
                patch.object(
                    claim_ledger,
                    "CLAIM_EFFECTIVE_REDUCER_VERSION",
                    "claim-effective-reducer-vNEXT",
                ),
                patch.object(
                    claim_review_actions,
                    "CLAIM_EFFECTIVE_REDUCER_VERSION",
                    "claim-effective-reducer-vNEXT",
                ),
                patch(
                    "claim_effective_contract.CLAIM_EFFECTIVE_REDUCER_VERSION",
                    "claim-effective-reducer-vNEXT",
                ),
                patch("ai_extract.refresh_claim_shadow") as refresh_shadow,
                patch("claim_ledger.build_shadow_ledger") as rebuild_shadow,
            ):
                self.assertTrue(
                    claim_artifacts.committed_base_versions_are_current(base)
                )
                self.assertFalse(
                    claim_artifacts.effective_versions_are_current(effective)
                )
                claim_review_actions.fold_effective_ledger(
                    root,
                    actor_trigger="effective-version-bump",
                )
                refolded = claim_artifacts.load_committed_effective_snapshot(root)
                self.assertTrue(
                    claim_artifacts.effective_versions_are_current(refolded)
                )
                refresh_shadow.assert_not_called()
                rebuild_shadow.assert_not_called()

            self.assertEqual(
                {
                    name: (root / name).read_bytes()
                    for name in base_files
                },
                base_files,
            )

    def test_unrelated_claim_event_does_not_change_effective_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            texts = (
                ("B1", "The product shall provide user-programmable auxiliary outputs."),
                ("B2", "The product shall provide a configurable indicator channel."),
            )
            blocks = []
            requirements = []
            for index, (block_id, text) in enumerate(texts, start=1):
                blocks.append({
                    "block_id": block_id,
                    "order": index,
                    "type": "paragraph",
                    "text": text,
                    "raw_text": text,
                    "text_repair_checked": True,
                    "text_repair_version": "identity-v1",
                    "raw_to_repaired_spans": [{
                        "raw_start": 0,
                        "raw_end": len(text),
                        "repaired_start": 0,
                        "repaired_end": len(text),
                        "operation": "equal",
                    }],
                    "section_path": ["4 Functions"],
                    "noise": False,
                })
                requirements.append({
                    "ai_req_id": f"AIR-{index}",
                    "title": f"Requirement {index}",
                    "description": text,
                    "source_quote": text,
                    "source_block_ids": [block_id],
                    "sub_items": [],
                    "acceptance_criteria": [],
                })
            catalog = claim_catalog.build_claim_catalog(blocks, [])
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                requirements,
            )
            _write_current_requirements_meta(root)
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                claim_ledger.build_shadow_ledger(catalog, requirements),
                run_id="two-claim-run",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="two-claim-seed",
            )
            before = {
                row["claim_id"]: row["claim_effective_revision"]
                for row in claim_artifacts.load_committed_effective_snapshot(root)[
                    "effective_ledger"
                ]
            }
            first_requirement = requirements[0]

            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "rejected",
                actor="test",
                reason="reject first target only",
                source_fingerprint_value=claim_ledger.target_source_fingerprint(
                    first_requirement
                ),
                review_subject_fingerprint_value=claim_ledger.target_fingerprint(
                    first_requirement
                ),
            )
            after_rows = claim_artifacts.load_committed_effective_snapshot(root)[
                "effective_ledger"
            ]
            after = {
                row["claim_id"]: row["claim_effective_revision"]
                for row in after_rows
            }
            claim_ids_by_block = {
                str(row["locator"]["block_id"]): str(row["claim_id"])
                for row in catalog["catalog"]
            }

            self.assertNotEqual(
                after[claim_ids_by_block["B1"]],
                before[claim_ids_by_block["B1"]],
            )
            self.assertEqual(
                after[claim_ids_by_block["B2"]],
                before[claim_ids_by_block["B2"]],
            )
    def test_a_track_legacy_review_without_fingerprints_is_unknown(self) -> None:
        requirement = _atomic_requirement(_catalog())
        authority = claim_ledger.a_track_effective_authority(
            [requirement],
            [{
                "requirement_id": requirement["stable_req_id"],
                "status": "rejected",
                "history": [],
                "metadata": {},
            }],
        )
        review = authority["records"][0]["review"]
        self.assertEqual(review["eligibility"], "unknown")
        self.assertEqual(review["reason"], "legacy_review_without_fingerprint")

    def test_target_hash_and_parse_use_the_same_bytes_on_both_tracks(self) -> None:
        for track in ("A", "B"):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                if track == "A":
                    _publish_a_track(root, catalog)
                    target = root / "atomic_requirements.jsonl"
                    loader = claim_review_actions._load_a_track_authority
                    changed_key = "requirement"
                else:
                    _publish(root, catalog)
                    target = root / "ai_requirements.jsonl"
                    loader = claim_review_actions._load_b_track_authority
                    changed_key = "description"

                first = target.read_bytes()
                first_row = json.loads(first.splitlines()[0].decode("utf-8"))
                changed_row = dict(first_row)
                changed_row[changed_key] = str(changed_row[changed_key]) + " Changed."
                second = claim_artifacts.canonical_json_value_bytes(changed_row) + b"\n"
                original_read_bytes = Path.read_bytes
                target_reads = 0

                def swap_after_first_read(path: Path) -> bytes:
                    nonlocal target_reads
                    if path == target:
                        target_reads += 1
                        return first if target_reads == 1 else second
                    return original_read_bytes(path)

                with patch.object(Path, "read_bytes", new=swap_after_first_read):
                    authority = loader(root)

                self.assertEqual(target_reads, 1)
                self.assertEqual(authority["requirements"], [first_row])
                self.assertEqual(
                    authority["target_file_sha256"],
                    claim_artifacts.sha256_bytes(first),
                )

    def test_readonly_authority_rejects_target_change_on_both_tracks(self) -> None:
        for track in ("A", "B"):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                if track == "A":
                    _publish_a_track(root, catalog)
                    target = root / "atomic_requirements.jsonl"
                    loader = claim_review_actions._load_a_track_authority
                else:
                    _publish(root, catalog)
                    target = root / "ai_requirements.jsonl"
                    loader = claim_review_actions._load_b_track_authority

                first = target.read_bytes()
                second = first + b"\n"
                original_read_bytes = Path.read_bytes
                target_reads = 0

                def change_before_confirmation(path: Path) -> bytes:
                    nonlocal target_reads
                    if path == target:
                        target_reads += 1
                        return first if target_reads == 1 else second
                    return original_read_bytes(path)

                with patch.object(
                    Path,
                    "read_bytes",
                    new=change_before_confirmation,
                ):
                    with self.assertRaisesRegex(
                        claim_review_actions.ClaimReviewActionError,
                        "changed during read-only authority read",
                    ):
                        loader(root, readonly=True)

                self.assertEqual(target_reads, 2)

    def test_effective_only_fold_never_calls_verifier_or_mutates_authority_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            (root / "decide_trace.jsonl").write_bytes(
                b'{"frozen_contract":"must-remain-byte-identical"}\n'
            )
            watched = (
                "ai_requirements.jsonl",
                "ai_review_states.jsonl",
                "atomic_requirements.jsonl",
                "review_states.jsonl",
                "omission_states.jsonl",
                "decide_trace.jsonl",
                claim_artifacts.CLAIM_SHADOW_METRICS,
                claim_artifacts.CLAIM_VERIFIER_ATTEMPTS,
            )
            before = {
                name: (root / name).read_bytes()
                if (root / name).is_file() else None
                for name in watched
            }

            with (
                patch(
                    "ai_extract.refresh_claim_shadow",
                    side_effect=AssertionError("effective fold invoked base refresh"),
                ),
                patch(
                    "claim_ledger.build_shadow_ledger",
                    side_effect=AssertionError("effective fold invoked verifier path"),
                ),
                patch(
                    "llm_client.chat_json",
                    side_effect=AssertionError("effective fold invoked LLM"),
                ),
            ):
                result = claim_review_actions.fold_effective_ledger(
                    root,
                    actor_trigger="zero-verifier-regression",
                )

            after = {
                name: (root / name).read_bytes()
                if (root / name).is_file() else None
                for name in watched
            }

        self.assertEqual(result["event_append_count"], 0)
        self.assertEqual(after, before)

    def test_fold_and_recovery_acquire_publication_before_authority(self) -> None:
        for track in ("A", "B"):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if track == "A":
                    _publish_a_track(root, _catalog())
                    authority_module = review_state
                    authority_lock_name = "review_state_lock"
                else:
                    _publish(root, _catalog())
                    authority_module = ai_review_actions
                    authority_lock_name = "_ai_review_state_lock"

                authority_entries = 0
                recovery_entries = 0
                real_authority_lock = getattr(
                    authority_module,
                    authority_lock_name,
                )
                real_recovery = (
                    claim_artifacts._recover_interrupted_effective_publication_unlocked
                )

                @contextmanager
                def observed_authority_lock(*args, **kwargs):
                    nonlocal authority_entries
                    self.assertIn(root, claim_artifacts._PUBLICATION_LOCK_STATES)
                    authority_entries += 1
                    with real_authority_lock(*args, **kwargs):
                        yield

                def observed_recovery(target_root):
                    nonlocal recovery_entries
                    self.assertIn(root, claim_artifacts._PUBLICATION_LOCK_STATES)
                    recovery_entries += 1
                    return real_recovery(target_root)

                with (
                    patch.object(
                        authority_module,
                        authority_lock_name,
                        observed_authority_lock,
                    ),
                    patch.object(
                        claim_artifacts,
                        "_recover_interrupted_effective_publication_unlocked",
                        side_effect=observed_recovery,
                    ),
                ):
                    result = claim_review_actions.fold_effective_ledger(
                        root,
                        actor_trigger=f"{track.lower()}-lock-order-probe",
                    )

                self.assertTrue(result["ok"])
                self.assertGreater(authority_entries, 0)
                self.assertGreater(recovery_entries, 0)

    def test_second_identical_fold_reuses_effective_snapshot_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            first = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="double-fold-first",
            )
            first_snapshot = claim_artifacts.load_committed_effective_snapshot_readonly(
                root
            )
            first_event_bytes = (
                root / claim_artifacts.CLAIM_REVIEW_EVENTS
            ).read_bytes() if (
                root / claim_artifacts.CLAIM_REVIEW_EVENTS
            ).is_file() else None
            first_effective_bytes = {
                name: (root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
            }

            second = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="double-fold-second",
            )
            second_snapshot = claim_artifacts.load_committed_effective_snapshot_readonly(
                root
            )
            second_event_bytes = (
                root / claim_artifacts.CLAIM_REVIEW_EVENTS
            ).read_bytes() if (
                root / claim_artifacts.CLAIM_REVIEW_EVENTS
            ).is_file() else None
            second_effective_bytes = {
                name: (root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
            }

        self.assertEqual(first["event_append_count"], 0)
        self.assertEqual(second["event_append_count"], 0)
        self.assertTrue(second["publication_skipped"])
        self.assertEqual(second_event_bytes, first_event_bytes)
        self.assertEqual(
            [row["claim_effective_revision"] for row in second_snapshot["effective_ledger"]],
            [row["claim_effective_revision"] for row in first_snapshot["effective_ledger"]],
        )
        self.assertEqual(second_effective_bytes, first_effective_bytes)

    def test_interrupted_effective_fold_records_lag_then_clears_on_recovery(self) -> None:
        script = r'''
import os
from pathlib import Path
import sys

import claim_artifacts
import claim_review_actions

root = Path(sys.argv[1]).resolve()
original_replace = claim_artifacts._replace_with_retry

def crash_after_effective_ledger(source, target):
    original_replace(source, target)
    target = Path(target)
    if (
        target.parent.resolve() == root
        and target.name == claim_artifacts.CLAIM_EFFECTIVE_LEDGER
    ):
        os._exit(97)

claim_artifacts._replace_with_retry = crash_after_effective_ledger
claim_review_actions.fold_effective_ledger(
    root,
    actor_trigger="interrupted-health-child",
)
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="interrupted-health-seed",
            )
            with patch(
                "claim_review_actions.fold_effective_ledger",
                return_value={"ok": True},
            ):
                ai_review_actions.apply_ai_review_action(
                    root,
                    "AIR-1",
                    "rejected",
                    actor="test",
                    reason="authority committed before interrupted fold",
                )
            verifier_before = (
                root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS
            ).read_bytes()

            killed = subprocess.run(
                [sys.executable, "-c", script, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(killed.returncode, 97, killed.stderr)
            self.assertTrue(
                (root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).is_file()
            )

            health_writes = []
            real_health_write = claim_review_actions._write_effective_health

            def capture_health(target_root, health):
                health_writes.append(copy.deepcopy(health))
                return real_health_write(target_root, health)

            with patch.object(
                claim_review_actions,
                "_write_effective_health",
                side_effect=capture_health,
            ):
                recovered = claim_review_actions.fold_effective_ledger(
                    root,
                    actor_trigger="interrupted-health-recovery",
                )

            final_health = claim_review_actions.read_effective_health(root)
            verifier_after = (
                root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS
            ).read_bytes()

        self.assertTrue(recovered["ok"])
        self.assertGreaterEqual(len(health_writes), 2)
        self.assertEqual(health_writes[0]["bridge_fold_lag"], 1)
        self.assertEqual(health_writes[-1]["bridge_fold_lag"], 0)
        self.assertIsNotNone(health_writes[0]["last_failure_at"])
        self.assertEqual(final_health["bridge_fold_lag"], 0)
        self.assertIsNotNone(final_health["last_failure_at"])
        self.assertIsNone(final_health["last_error"])
        self.assertEqual(verifier_after, verifier_before)

    def test_reconcile_scale_uses_identity_indexes_not_rows_times_all_links(self) -> None:
        target_count = 500
        history_count = 2000
        requirements = []
        for index in range(target_count):
            text = f"The product shall support configurable output channel {index}."
            requirements.append({
                "ai_req_id": f"AIR-{index:04d}",
                "title": f"Output {index}",
                "description": text,
                "source_quote": text,
                "source_block_ids": [f"B{index:04d}"],
                "sub_items": [],
                "acceptance_criteria": [],
            })
        authority = claim_ledger.b_track_effective_authority(requirements, {})
        records_by_id = {
            row["target_requirement_id"]: row for row in authority["records"]
        }
        links = {}
        ledger = []
        for index, record in enumerate(authority["records"]):
            claim_id = f"CLM-{index:016x}"
            key = (
                "ai_requirement",
                record["target_requirement_id"],
                record["target_fingerprint"],
            )
            links[key] = claim_review_actions.TargetLink(
                target_kind=key[0],
                target_requirement_id=key[1],
                target_fingerprint=key[2],
                claim_ids=(claim_id,),
                baseline_eligibility="active",
            )
            ledger.append({
                "schema": "claim-ledger/v3",
                "claim_id": claim_id,
                "claim_hash": claim_artifacts.hash_json(
                    "claim-reconcile-scale-claim/v1", index
                ),
            })
        ordered_records = []
        for index in range(history_count):
            record = records_by_id[f"AIR-{index % target_count:04d}"]
            ordered_records.append({
                "source_event_revision": claim_artifacts.hash_json(
                    "claim-reconcile-scale-event/v1", index
                ),
                "state": {
                    "ai_req_id": record["target_requirement_id"],
                    "status": (
                        "rejected"
                        if (index // target_count) % 2 == 0
                        else "accepted"
                    ),
                    "source_fingerprint": record["source_fingerprint"],
                    "review_subject_fingerprint": record["target_fingerprint"],
                },
            })
        authority = {
            **authority,
            "target_source_store": "ai_requirements.jsonl",
            "review_source_store": "ai_review_states.jsonl",
            "target_publication_revision": claim_artifacts.hash_json(
                "claim-reconcile-scale/v1", "target-publication"
            ),
            "review_snapshot": {
                "ordered_records": ordered_records,
                "source_records": {},
                "authority_file_sha256": claim_artifacts.hash_json(
                    "claim-reconcile-scale/v1", "review-authority"
                ),
            },
        }
        base = {
            "generation_meta": {
                "document_generation_id": claim_artifacts.hash_json(
                    "claim-reconcile-scale/v1", "document"
                ),
                "catalog_generation_id": claim_artifacts.hash_json(
                    "claim-reconcile-scale/v1", "catalog"
                ),
            },
            "ledger": ledger,
        }
        base_by_claim = {row["claim_id"]: row for row in ledger}
        workload = {
            "history_record_count": 0,
            "link_index_insert_count": 0,
            "link_candidate_check_count": 0,
            "event_index_insert_count": 0,
        }

        drafts = claim_review_actions._historical_b_track_review_drafts(
            base,
            authority,
            links,
            base_by_claim,
            {},
            workload,
        )

        self.assertEqual(len(drafts), history_count)
        self.assertEqual(workload["history_record_count"], history_count)
        self.assertEqual(workload["link_index_insert_count"], target_count)
        self.assertEqual(workload["link_candidate_check_count"], history_count)
        self.assertLess(
            workload["link_candidate_check_count"],
            history_count * target_count,
        )

        event_rows = []
        link_keys = list(links)
        for index in range(history_count):
            key = link_keys[index % target_count]
            event_rows.append({
                "target_kind": key[0],
                "target_requirement_id": key[1],
                "target_fingerprint": key[2],
                "trigger_kind": "target_set",
                "eligibility_after": "active",
                "observed_target_fingerprint": key[2],
                "event_hash": claim_artifacts.hash_json(
                    "claim-reconcile-scale-current-event/v1", index
                ),
            })
        current_workload = {
            "history_record_count": 0,
            "link_index_insert_count": 0,
            "link_candidate_check_count": 0,
            "event_index_insert_count": 0,
        }
        current = claim_review_actions._current_transition_drafts(
            base,
            authority,
            links,
            event_rows,
            base_by_claim,
            {},
            current_workload,
        )

        self.assertEqual(current, [])
        self.assertEqual(current_workload["event_index_insert_count"], history_count)

    def test_a_track_offline_history_reconciles_every_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())
            requirement_id = requirement["stable_req_id"]
            history = [
                {
                    "from_status": "candidate",
                    "to_status": "rejected",
                    "actor": "expert",
                    "reason": "reject",
                    "timestamp": "2026-07-28T01:00:00+00:00",
                },
                {
                    "from_status": "rejected",
                    "to_status": "accepted",
                    "actor": "expert",
                    "reason": "restore",
                    "timestamp": "2026-07-28T01:01:00+00:00",
                },
            ]
            with review_state.review_state_lock(root):
                review_state._atomic_write_jsonl(
                    root / "review_states.jsonl",
                    [{
                        "requirement_id": requirement_id,
                        "status": "accepted",
                        "history": history,
                        "metadata": {
                            "req_id": requirement["req_id"],
                            "stable_req_id": requirement_id,
                            "source_fingerprint": (
                                claim_ledger.atomic_target_source_fingerprint(
                                    requirement
                                )
                            ),
                            "review_subject_fingerprint": (
                                claim_ledger.atomic_target_fingerprint(requirement)
                            ),
                        },
                    }],
                )

            result = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-offline-reconcile",
            )

            self.assertEqual(result["event_append_count"], 2)
            self.assertEqual(result["effective_metrics"]["covered_count"], 1)
            events = claim_review_actions.read_claim_review_events(root).rows
            self.assertEqual(
                [event["event_kind"] for event in events],
                ["target_invalidated", "target_reactivated"],
            )
            self.assertTrue(all(
                event["target_kind"] == "atomic_requirement"
                and event["source_store"] == "review_states.jsonl"
                for event in events
            ))
            self.assertEqual(
                [event["source_event_revision"] for event in events],
                [
                    claim_artifacts.hash_json(
                        "claim-source-event-revision/v1",
                        {
                            "source_store": "review_states.jsonl",
                            "requirement_id": requirement_id,
                            "history_index": index,
                            "history_event": event,
                        },
                    )
                    for index, event in enumerate(history)
                ],
            )
            repeated = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-idempotency",
            )
            self.assertEqual(repeated["event_append_count"], 0)

    def test_a_track_complete_bad_authority_row_is_audited_but_valid_state_folds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-audit-gap-initial",
            )
            history = [{
                "from_status": "candidate",
                "to_status": "rejected",
                "actor": "expert",
                "reason": "reject",
                "timestamp": "2026-07-28T01:00:00+00:00",
            }]
            valid_state = {
                "requirement_id": requirement["stable_req_id"],
                "status": "rejected",
                "history": history,
                "metadata": {
                    "req_id": requirement["req_id"],
                    "stable_req_id": requirement["stable_req_id"],
                },
            }
            (root / "review_states.jsonl").write_text(
                "not-json\n" + json.dumps(valid_state) + "\n",
                encoding="utf-8",
            )

            result = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-audit-gap",
            )
            snapshot = review_state.read_review_authority_snapshot_readonly(root)
            effective = claim_artifacts.load_committed_effective_snapshot(root)
            event_kinds = [
                event["event_kind"]
                for event in claim_review_actions.read_claim_review_events(root).rows
            ]

        self.assertTrue(result["health"]["authority_audit_gap"])
        self.assertEqual(effective["effective_ledger"][0]["resolution"], "uncertain")
        self.assertEqual(snapshot["states"], [valid_state])
        self.assertEqual(snapshot["audit_gaps"][0]["physical_line_number"], 1)
        self.assertEqual(event_kinds, ["target_invalidated"])

    def test_a_track_expert_hook_reopens_and_restores_validated_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-initial",
            )

            review_state.apply_expert_decision(
                root,
                requirement["stable_req_id"],
                "rejected",
                actor="expert",
                reason="reject",
            )
            rejected = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertEqual(rejected["effective_ledger"][0]["resolution"], "uncertain")
            self.assertEqual(len(rejected["queue_proposals"]), 1)

            review_state.apply_expert_decision(
                root,
                requirement["stable_req_id"],
                "accepted",
                actor="expert",
                reason="restore",
            )
            restored = claim_artifacts.load_committed_effective_snapshot(root)
            row = restored["effective_ledger"][0]
            self.assertEqual(row["resolution"], "covered")
            self.assertEqual(restored["queue_proposals"], [])
            self.assertEqual(
                row["effective_facts"]["reused_validation_group_ids"],
                row["coverage_group_ids"],
            )
            self.assertEqual(
                [event["event_kind"] for event in (
                    claim_review_actions.read_claim_review_events(root).rows
                )],
                ["target_invalidated", "target_reactivated"],
            )

    def test_a_track_live_target_drift_is_folded_without_review_event_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirement = _publish_a_track(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-initial",
            )
            committed = claim_artifacts.load_committed_effective_snapshot(root)

            changed = dict(requirement)
            changed["requirement"] = requirement["requirement"] + " Changed."
            claim_artifacts.atomic_write_jsonl(
                root / "atomic_requirements.jsonl",
                [changed],
            )
            freshness = claim_review_actions.assess_effective_freshness(
                root,
                committed,
            )
            self.assertFalse(freshness["effective_fresh"])
            self.assertIn("target_set_changed", freshness["freshness_reasons"])

            invalidated = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-target-changed",
            )
            self.assertEqual(invalidated["effective_metrics"]["uncertain_count"], 1)
            claim_artifacts.atomic_write_jsonl(
                root / "atomic_requirements.jsonl",
                [requirement],
            )
            restored = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-target-restored",
            )
            self.assertEqual(restored["effective_metrics"]["covered_count"], 1)
            events = claim_review_actions.read_claim_review_events(root).rows
            self.assertEqual(
                [event["trigger_kind"] for event in events],
                ["target_set", "target_set"],
            )
            self.assertEqual(
                [event["event_kind"] for event in events],
                ["target_invalidated", "target_reactivated"],
            )

    def test_review_rejection_reopens_and_reactivation_reuses_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="initial",
            )
            requirement = _requirement(catalog)
            fingerprints = {
                "source_fingerprint_value": claim_ledger.target_source_fingerprint(
                    requirement
                ),
                "review_subject_fingerprint_value": claim_ledger.target_fingerprint(
                    requirement
                ),
            }

            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "rejected",
                actor="test",
                reason="reject",
                **fingerprints,
            )
            rejected_snapshot = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertEqual(
                rejected_snapshot["effective_ledger"][0]["resolution"],
                "uncertain",
            )
            self.assertEqual(len(rejected_snapshot["queue_proposals"]), 1)

            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "accepted",
                actor="test",
                reason="restore",
                **fingerprints,
            )
            restored_snapshot = claim_artifacts.load_committed_effective_snapshot(root)
            row = restored_snapshot["effective_ledger"][0]
            self.assertEqual(row["resolution"], "covered")
            self.assertEqual(restored_snapshot["queue_proposals"], [])
            self.assertEqual(
                row["effective_facts"]["reused_validation_group_ids"],
                row["coverage_group_ids"],
            )
            self.assertEqual(
                [event["event_kind"] for event in (
                    claim_review_actions.read_claim_review_events(root).rows
                )],
                ["target_invalidated", "target_reactivated"],
            )
            idempotent = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="idempotency-check",
            )
            self.assertEqual(idempotent["event_append_count"], 0)
            self.assertTrue(idempotent["publication_skipped"])
            self.assertEqual(
                claim_artifacts.load_committed_effective_snapshot(root)[
                    "effective_ledger"
                ][0]["effective_facts"]["reused_validation_group_ids"],
                row["coverage_group_ids"],
            )

    def test_projection_append_rejects_a_stale_effective_precondition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="projection-cas-seed",
            )
            base = claim_artifacts.load_committed_claim_base(root)
            snapshot = claim_artifacts.load_committed_shadow(root)
            base_by_claim = {
                str(row["claim_id"]): row for row in base["ledger"]
            }
            effective_by_claim = {
                str(row["claim_id"]): row
                for row in snapshot["effective_ledger"]
            }
            link = next(iter(claim_review_actions._target_links(base).values()))
            draft = claim_review_actions._event_drafts_for_transition(
                link=link,
                before="active",
                after="rejected",
                reason="expert_rejected",
                trigger_kind="review_authority",
                source_store="ai_review_states.jsonl",
                source_event_revision=_hash("stale-projection-source"),
                target_review_revision=_hash("stale-projection-review"),
                observed_target_fingerprint=link.target_fingerprint,
                base=base,
                base_by_claim=base_by_claim,
                effective_by_claim=effective_by_claim,
            )[0]
            draft["expected_claim_effective_revision"] = _hash("obsolete")

            with self.assertRaises(claim_review_actions.ClaimProjectionCasMismatch):
                claim_review_actions.append_claim_review_events(
                    root,
                    [draft],
                    base_by_claim=base_by_claim,
                    effective_by_claim=effective_by_claim,
                )

            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).rows,
                [],
            )

    def test_fold_retries_a_projection_cas_conflict_at_the_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="projection-cas-retry-seed",
            )
            original = claim_review_actions.reconcile_claim_review_events
            calls = 0

            def conflict_once(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise claim_review_actions.ClaimProjectionCasMismatch(
                        "simulated stale projection"
                    )
                return original(*args, **kwargs)

            with patch(
                "claim_review_actions.reconcile_claim_review_events",
                side_effect=conflict_once,
            ):
                result = claim_review_actions.fold_effective_ledger(
                    root,
                    actor_trigger="projection-cas-retry",
                )

            self.assertEqual(calls, 2)
            self.assertEqual(result["attempt"], 2)
            self.assertFalse(result["health"]["authority_cas_gap"])

    def test_target_missing_restore_missing_cycle_has_distinct_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            original = (root / "ai_requirements.jsonl").read_bytes()
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="initial",
            )

            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])
            first_missing = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="target-missing",
            )
            (root / "ai_requirements.jsonl").write_bytes(original)
            restored = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="target-restored",
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])
            second_missing = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="target-missing-again",
            )

            self.assertEqual(first_missing["effective_metrics"]["uncertain_count"], 1)
            self.assertEqual(restored["effective_metrics"]["covered_count"], 1)
            self.assertEqual(second_missing["effective_metrics"]["uncertain_count"], 1)
            events = claim_review_actions.read_claim_review_events(root).rows
            self.assertEqual(
                [event["event_kind"] for event in events],
                ["target_invalidated", "target_reactivated", "target_invalidated"],
            )
            self.assertEqual(len({event["source_event_revision"] for event in events}), 3)
            self.assertTrue(all(event["trigger_kind"] == "target_set" for event in events))

    def test_refold_rejects_forged_revision_instead_of_auditing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="forged-revision-seed",
            )
            meta_path = root / claim_artifacts.CLAIM_EFFECTIVE_META
            ledger_path = root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rows = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            forged_revision = _hash("forged-effective-revision")
            rows[0]["claim_effective_revision"] = forged_revision
            claim_artifacts.atomic_write_jsonl(ledger_path, rows)
            meta["effective_ledger_sha256"] = claim_artifacts.file_sha256(
                ledger_path
            )
            claim_artifacts._atomic_write_bytes(
                meta_path,
                claim_artifacts.canonical_json_value_bytes(meta),
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "claim effective revision does not recompute",
            ):
                claim_review_actions.fold_effective_ledger(
                    root,
                    actor_trigger="forged-revision-refold",
                )

            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).rows,
                [],
            )

    def test_authority_drift_refold_derives_cas_instead_of_reusing_forgery(self) -> None:
        from claim_effective_contract import (
            CLAIM_AUTHORITY_PROJECTION_VERSION,
            compute_claim_effective_revision,
            compute_document_effective_revision,
            compute_effective_authority_projection_hash,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="coherent-forgery-seed",
            )
            snapshot = claim_artifacts.load_committed_effective_snapshot(root)
            rows = copy.deepcopy(snapshot["effective_ledger"])
            meta = copy.deepcopy(snapshot["effective_meta"])
            inputs = rows[0]["revision_inputs"]
            inputs["linked_targets"][0]["target_review_revision"] = _hash(
                "forged-linked-target-revision"
            )
            inputs["authority_projection_hash"] = claim_artifacts.hash_json(
                CLAIM_AUTHORITY_PROJECTION_VERSION,
                {
                    "ordered_relevant_event_hashes": inputs[
                        "ordered_relevant_event_hashes"
                    ],
                    "linked_targets": inputs["linked_targets"],
                    "expert_overlay": inputs["expert_overlay"],
                },
            )
            forged_revision = compute_claim_effective_revision(inputs)
            rows[0]["claim_effective_revision"] = forged_revision
            projection_hash = compute_effective_authority_projection_hash(rows)
            meta["authority_projection_hash"] = projection_hash
            meta["document_effective_revision"] = compute_document_effective_revision(
                base_generation_id=meta["base_generation_id"],
                last_event_seq=meta["last_event_seq"],
                event_prefix_sha256=meta["event_prefix_sha256"],
                target_set_hash=meta["target_set_hash"],
                requirement_review_state_hash=meta[
                    "requirement_review_state_hash"
                ],
                authority_projection_hash=projection_hash,
            )
            claim_artifacts.atomic_write_jsonl(
                root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER,
                rows,
            )
            meta["effective_ledger_sha256"] = claim_artifacts.file_sha256(
                root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER
            )
            claim_artifacts._atomic_write_bytes(
                root / claim_artifacts.CLAIM_EFFECTIVE_META,
                claim_artifacts.canonical_json_value_bytes(meta),
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])

            result = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="coherent-forgery-refold",
            )

            self.assertEqual(result["event_append_count"], 1)
            event = claim_review_actions.read_claim_review_events(root).rows[0]
            self.assertNotEqual(
                event["expected_claim_effective_revision"],
                forged_revision,
            )
            self.assertEqual(event["event_kind"], "target_invalidated")

    def test_freshness_reports_live_target_drift_without_folding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="initial",
            )
            committed = claim_artifacts.load_committed_effective_snapshot_readonly(
                root
            )
            self.assertTrue(
                claim_review_actions.assess_effective_freshness(root, committed)[
                    "effective_fresh"
                ]
            )

            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])
            stale = claim_review_actions.assess_effective_freshness(root, committed)

            self.assertFalse(stale["effective_fresh"])
            self.assertIn("target_set_changed", stale["freshness_reasons"])
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "authority changed",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_target_observation_change_is_audited_while_review_stays_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            original = (root / "ai_requirements.jsonl").read_bytes()
            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "rejected",
                actor="legacy-test",
                reason="legacy row without fingerprints",
            )
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="legacy-review",
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="target-missing",
            )
            (root / "ai_requirements.jsonl").write_bytes(original)
            result = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="target-restored",
            )

            self.assertEqual(result["event_append_count"], 1)
            events = claim_review_actions.read_claim_review_events(root).rows
            target_events = [
                event for event in events if event["trigger_kind"] == "target_set"
            ]
            self.assertEqual(len(target_events), 2)
            self.assertEqual(
                [event["observed_target_fingerprint"] for event in target_events],
                [
                    None,
                    claim_artifacts.canonical_target_fingerprint(
                        claim_ledger.target_fingerprint(_requirement(_catalog()))
                    ),
                ],
            )
            self.assertTrue(all(
                event["eligibility_before"] == "unknown"
                and event["eligibility_after"] == "unknown"
                for event in target_events
            ))

    def test_complete_bad_suffix_is_quarantined_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_review_actions.append_claim_review_events(root, [_draft(1)])
            with (root / claim_artifacts.CLAIM_REVIEW_EVENTS).open("ab") as handle:
                handle.write(b"{}\n")
            with self.assertRaises(claim_review_actions.ClaimReviewActionError):
                claim_review_actions.read_claim_review_events(root)

            result = claim_review_actions.append_claim_review_events(
                root,
                [_draft(2, event_kind="target_reactivated")],
            )
            self.assertIsNotNone(result["quarantine_file"])
            quarantine = root / str(result["quarantine_file"])
            self.assertEqual(quarantine.read_bytes(), b"{}\n")
            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).last_event_seq,
                2,
            )


if __name__ == "__main__":
    unittest.main()
