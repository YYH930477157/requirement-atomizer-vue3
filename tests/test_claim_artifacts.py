from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

import ai_extract
import claim_artifacts
import claim_catalog
import claim_ledger
import claim_review_actions
from llm_client import LLMClientConfig, LLMRequestBudget


def _catalog() -> dict:
    text = "The product shall provide user-programmable auxiliary outputs."
    block = {
        "block_id": "B1",
        "order": 1,
        "type": "paragraph",
        "text": text,
        "raw_text": text,
        "text_repair_checked": True,
        "text_repair_version": "identity-v1",
        "raw_to_repaired_spans": [{
            "raw_start": 0, "raw_end": len(text),
            "repaired_start": 0, "repaired_end": len(text),
            "operation": "equal",
        }],
        "section_path": ["4 Functions"],
        "noise": False,
    }
    return claim_catalog.build_claim_catalog([block], [])


def _requirement(catalog: dict) -> dict:
    source = catalog["catalog"][0]["text"].strip()
    return {
        "ai_req_id": "AIR-1",
        "title": "Auxiliary outputs",
        "description": source,
        "source_quote": source,
        "source_block_ids": ["B1"],
        "sub_items": [],
        "acceptance_criteria": [],
    }


def _shadow(catalog: dict) -> dict:
    return claim_ledger.build_shadow_ledger(catalog, [_requirement(catalog)])


def _write_current_requirements_meta(root: Path) -> None:
    ai_extract.write_ai_requirements_metadata(root, input_fingerprint="test-input")


def _baseline_cost() -> dict:
    return {
        "call_count": 1,
        "failed_call_count": 0,
        "total_tokens": 100,
        "usage_complete": True,
        "lineage_version": "test-baseline-lineage-v1",
        "lineage_fingerprint": "sha256:" + "9" * 64,
        "lineage_context": {"fixture": "claim-artifacts"},
        "lineage_match": True,
    }


def _semantic_negative_shadow(catalog: dict) -> dict:
    def proposer(_unit_id: str, claims: list[dict]) -> dict:
        claim = claims[0]
        text = str(claim["source_evidence"]["text"])
        return {
            "request_id": "negative-proposal-1",
            "usage_complete": True,
            "decisions": {claim["claim_id"]: {
                "non_normative": True,
                "reason": "informative",
                "evidence": [{"start": 0, "end": len(text), "text": text}],
            }},
        }

    def verifier(_unit_id: str, claims: list[dict]) -> dict:
        claim = claims[0]
        text = str(claim["source_evidence"]["text"])
        return {
            "request_id": "negative-verifier-1",
            "usage_complete": True,
            "decisions": {claim["claim_id"]: {
                "non_normative": True,
                "reason": "informative",
                "checks": {
                    name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                },
                "evidence": [{"start": 0, "end": len(text), "text": text}],
            }},
        }

    return claim_ledger.build_shadow_ledger(
        catalog,
        [],
        semantic_negative_proposer=proposer,
        semantic_negative_verifier=verifier,
    )


def _publish(root: Path, catalog: dict, shadow: dict | None = None, *, run_id: str = "run-1") -> dict:
    claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [_requirement(catalog)])
    _write_current_requirements_meta(root)
    return claim_artifacts.publish_shadow_generation(
        root,
        catalog,
        shadow or _shadow(catalog),
        run_id=run_id,
        requirements_sha256=claim_artifacts.file_sha256(root / "ai_requirements.jsonl"),
    )


def _effective_candidate(
    root: Path,
    *,
    invalidate_groups: bool = False,
) -> tuple[list[dict], list[dict], dict]:
    if invalidate_groups:
        import ai_review_actions

        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="effective-candidate-seed",
        )
        catalog = claim_artifacts.load_committed_claim_base(root)["catalog"]
        requirement = _requirement({"catalog": catalog})
        ai_review_actions.apply_ai_review_action(
            root,
            "AIR-1",
            "rejected",
            actor="test:effective-candidate",
            reason="fixture rejection",
            source_fingerprint_value=claim_ledger.target_source_fingerprint(
                requirement
            ),
            review_subject_fingerprint_value=claim_ledger.target_fingerprint(
                requirement
            ),
        )
        snapshot = claim_artifacts.load_committed_effective_snapshot(root)
        return (
            copy.deepcopy(snapshot["effective_ledger"]),
            copy.deepcopy(snapshot["queue_proposals"]),
            copy.deepcopy(snapshot["effective_meta"]),
        )

    base = claim_artifacts.load_committed_claim_base(root)
    authority = claim_review_actions._load_declared_authority(
        root, base["generation_meta"], readonly=True
    )
    events = claim_review_actions._scan_event_log_unlocked(root, repair=False)
    rows = claim_review_actions.derive_authoritative_effective_rows(
        base, authority, events.rows
    )
    queue = claim_review_actions._build_queue(root, base, rows, authority)
    from claim_effective_contract import (
        compute_document_effective_revision,
        compute_effective_authority_projection_hash,
        compute_effective_metrics,
    )

    authority_projection_hash = compute_effective_authority_projection_hash(rows)
    meta = {
        "run_id": "effective-test",
        "event_prefix_sha256": events.event_prefix_sha256,
        "last_event_seq": events.last_event_seq,
        "document_effective_revision": compute_document_effective_revision(
            base_generation_id=claim_artifacts.claim_base_generation_id(
                base["generation_meta"]
            ),
            last_event_seq=events.last_event_seq,
            event_prefix_sha256=events.event_prefix_sha256,
            target_set_hash=authority["target_set_hash"],
            requirement_review_state_hash=authority[
                "requirement_review_state_hash"
            ],
            authority_projection_hash=authority_projection_hash,
        ),
        "target_set_hash": authority["target_set_hash"],
        "target_publication_revision": authority["target_publication_revision"],
        "requirement_review_state_hash": authority[
            "requirement_review_state_hash"
        ],
        "authority_projection_hash": authority_projection_hash,
        "effective_ledger_schema": claim_ledger.CLAIM_EFFECTIVE_LEDGER_SCHEMA,
        "review_adapter_versions": claim_ledger.effective_review_adapter_versions(),
        "reducer_version": claim_ledger.CLAIM_EFFECTIVE_REDUCER_VERSION,
        "bridge_version": claim_ledger.CLAIM_REVIEW_BRIDGE_VERSION,
        "queue_version": claim_ledger.CLAIM_QUEUE_VERSION,
        "effective_metrics": compute_effective_metrics(rows),
        "migrated_from_version": None,
        "migration_id": None,
    }
    return rows, queue, meta


def _publish_semantic_negative(
    root: Path,
    catalog: dict,
    shadow: dict | None = None,
    *,
    run_id: str = "run-1",
) -> dict:
    claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])
    return claim_artifacts.publish_shadow_generation(
        root,
        catalog,
        shadow or _semantic_negative_shadow(catalog),
        run_id=run_id,
        requirements_sha256=claim_artifacts.file_sha256(root / "ai_requirements.jsonl"),
    )


def _verifier_shadow(
    catalog: dict,
    *,
    reusable_groups: list[dict] | None = None,
    malformed_response: bool = False,
) -> tuple[dict, LLMRequestBudget]:
    requirement = _requirement(catalog)
    requirement["description"] = "Auxiliary outputs can be configured by the user."
    budget = LLMRequestBudget(max_calls=4, max_tokens=100000)
    runtime = claim_ledger.semantic_verifier_runtime(
        route_mode="llm",
        enabled=True,
        rounds=1,
        budget_policy_version=LLMRequestBudget.VERSION,
        max_calls=4,
        max_total_tokens=100000,
    )

    def verifier(_unit_id: str, groups: list[dict]) -> dict:
        reservation = budget.reserve({"messages": [], "max_tokens": 1})
        budget.commit(reservation, {"total_tokens": 7})
        if malformed_response:
            return {}
        return {
            "request_id": "verify-1",
            "call_count": 1,
            "failed_call_count": 0,
            "tokens": 7,
            "usage_complete": True,
            "decisions": {
                groups[0]["coverage_group_id"]: {
                    "covered": True,
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                    },
                },
            },
        }

    return claim_ledger.build_shadow_ledger(
        catalog,
        [requirement],
        semantic_verifier=verifier,
        reusable_groups=reusable_groups,
        verifier_runtime=runtime,
        verifier_budget=budget,
        baseline_cost=_baseline_cost(),
    ), budget


class ClaimArtifactTests(unittest.TestCase):
    def test_catalog_probe_publication_supports_long_windows_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            while len(str(root)) < 162:
                remaining = 162 - len(str(root)) - 1
                if remaining <= 0:
                    break
                root /= "x" * min(50, remaining)
            root.mkdir(parents=True)
            catalog = _catalog()
            claim_artifacts.publish_catalog_probe(root, catalog)

            _publish(root, catalog, run_id="long-path-cold")
            published = claim_artifacts.load_committed_shadow(root)

            self.assertEqual(len(str(root)), 162)
            self.assertEqual(
                published["generation_meta"]["run_id"],
                "long-path-cold",
            )
            self.assertFalse(any(root.glob(".claim-publication-backup-*")))

    def test_legacy_v4_bootstrap_is_idempotent_and_cost_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = (
                "Auxiliary outputs can be configured by the user."
            )
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="requirements-root-v4",
                no_ledger_baseline_cost=_baseline_cost(),
            )
            shadow, _budget = _verifier_shadow(catalog)
            generation = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                shadow,
                run_id="legacy-generation-v4",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )

            catalog_meta_path = root / claim_artifacts.CLAIM_CATALOG_META
            catalog_meta = json.loads(catalog_meta_path.read_text(encoding="utf-8"))
            catalog_meta["artifact_protocol_version"] = "claim-artifacts-v4"
            claim_artifacts.atomic_write_json(catalog_meta_path, catalog_meta)
            generation.pop("attempt_chain")
            generation["artifact_protocol_version"] = "claim-artifacts-v4"
            generation["catalog_meta_sha256"] = claim_artifacts.file_sha256(
                catalog_meta_path
            )
            claim_artifacts.atomic_write_json(
                root / claim_artifacts.CLAIM_GENERATION_META,
                generation,
            )
            (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS).unlink()

            first = claim_artifacts.bootstrap_legacy_attempt_lineage(root)
            second = claim_artifacts.bootstrap_legacy_attempt_lineage(root)
            rows = claim_artifacts.read_claim_verifier_attempts(root)

            self.assertEqual(first, second)
            self.assertEqual(first["generation_run_id"], "legacy-generation-v4")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["attempt_status"], "incomplete")
            self.assertFalse(rows[0]["attempt_metrics"]["verifier_usage_complete"])
            self.assertIn("legacy_v4", rows[0]["error"])
            self.assertEqual(
                json.loads(
                    (root / claim_artifacts.CLAIM_GENERATION_META).read_text(
                        encoding="utf-8"
                    )
                )["artifact_protocol_version"],
                "claim-artifacts-v4",
            )

    def test_v5_attempt_lineage_can_seed_a_ledger_only_v6_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = _publish(root, _catalog(), run_id="v5-generation-1")
            generation["artifact_protocol_version"] = (
                claim_artifacts.PREVIOUS_CLAIM_ARTIFACT_PROTOCOL_VERSION
            )
            claim_artifacts.atomic_write_json(
                root / claim_artifacts.CLAIM_GENERATION_META,
                generation,
            )

            lineage = claim_artifacts.load_committed_attempt_lineage(root)

            self.assertEqual(lineage["generation_run_id"], "v5-generation-1")
            self.assertEqual(
                lineage["attempt_chain"]["attempt_id"],
                generation["attempt_chain"]["attempt_id"],
            )

    def test_catalog_probe_is_hash_bound_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = _catalog()
            meta = claim_artifacts.publish_catalog_probe(root, build)
            self.assertTrue((root / claim_artifacts.CLAIM_CATALOG).exists())
            self.assertEqual(meta["catalog_sha256"], claim_artifacts.file_sha256(
                root / claim_artifacts.CLAIM_CATALOG))
            loaded = claim_artifacts.load_catalog_probe(root)
            self.assertEqual(loaded["catalog"][0]["claim_id"], build["catalog"][0]["claim_id"])

    def test_shadow_generation_commits_all_hashes_and_effective_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [_requirement(catalog)])
            _write_current_requirements_meta(root)
            requirements_hash = claim_artifacts.file_sha256(root / "ai_requirements.jsonl")
            shadow = _shadow(catalog)
            meta = claim_artifacts.publish_shadow_generation(
                root, catalog, shadow, run_id="run-1", requirements_sha256=requirements_hash,
            )
            for name in (
                claim_artifacts.CLAIM_CATALOG,
                claim_artifacts.CLAIM_COVERAGE_GROUPS,
                claim_artifacts.CLAIM_LEDGER,
                claim_artifacts.CLAIM_EFFECTIVE_LEDGER,
                claim_artifacts.CLAIM_SHADOW_METRICS,
                claim_artifacts.CLAIM_GENERATION_META,
                claim_artifacts.CLAIM_EFFECTIVE_META,
            ):
                self.assertTrue((root / name).exists(), name)
            self.assertEqual(meta["run_id"], "run-1")
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(loaded["ledger"][0]["resolution"], "covered")
            self.assertEqual(loaded["effective_ledger"], loaded["ledger"])
            self.assertTrue(claim_artifacts.committed_shadow_versions_are_current(loaded))

    def test_effective_v2_publication_is_canonical_and_strictly_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root)

            published = claim_artifacts.publish_effective_snapshot(
                root,
                ledger,
                queue,
                meta=meta,
            )
            loaded = claim_artifacts.load_committed_effective_snapshot(root)

            self.assertEqual(loaded["effective_meta"], published)
            self.assertEqual(loaded["effective_ledger"], ledger)
            self.assertEqual(loaded["queue_proposals"], [])
            self.assertFalse(
                (root / claim_artifacts.CLAIM_EFFECTIVE_META).read_bytes().endswith(b"\n")
            )
            self.assertFalse(
                (root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).exists()
            )

    def test_readonly_effective_loader_never_recovers_a_pending_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root)
            claim_artifacts.publish_effective_snapshot(root, ledger, queue, meta=meta)
            journal = root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL
            journal.write_bytes(b'{"unfinished":true}')

            with self.assertRaises(claim_artifacts.ClaimEffectiveRecoveryPending):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

            self.assertEqual(journal.read_bytes(), b'{"unfinished":true}')

    def test_effective_publication_rejects_covered_without_valid_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root)
            ledger[0]["effective_facts"]["invalid_group_reasons"] = {
                group_id: "expert_rejected"
                for group_id in ledger[0]["coverage_group_ids"]
            }
            ledger[0]["effective_facts"]["valid_group_ids"] = []

            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_artifacts.publish_effective_snapshot(root, ledger, queue, meta=meta)

    def test_effective_publication_requires_queue_for_every_uncertain_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, _queue, meta = _effective_candidate(root, invalidate_groups=True)

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "complete uncertain-claim projection",
            ):
                claim_artifacts.publish_effective_snapshot(root, ledger, [], meta=meta)

    def test_effective_wal_rolls_back_each_partial_replace(self) -> None:
        for failed_name in (
            claim_artifacts.CLAIM_EFFECTIVE_LEDGER,
            claim_artifacts.CLAIM_QUEUE_PROPOSALS,
            claim_artifacts.CLAIM_EFFECTIVE_META,
        ):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _publish(root, _catalog())
                ledger, queue, meta = _effective_candidate(root, invalidate_groups=True)
                old = {
                    name: (root / name).read_bytes() if (root / name).is_file() else None
                    for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                }
                real_write = claim_artifacts._atomic_write_bytes

                def crash_on_production(path, payload):
                    target = Path(path)
                    if target.parent == root and target.name == failed_name:
                        raise RuntimeError("simulated effective replace crash")
                    return real_write(target, payload)

                with patch.object(
                    claim_artifacts,
                    "_atomic_write_bytes",
                    side_effect=crash_on_production,
                ):
                    with self.assertRaisesRegex(RuntimeError, "simulated"):
                        claim_artifacts.publish_effective_snapshot(
                            root,
                            ledger,
                            queue,
                            meta=meta,
                        )

                self.assertTrue(
                    (root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).is_file()
                )
                claim_artifacts.load_committed_shadow(root)
                self.assertFalse(
                    (root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).exists()
                )
                for name, payload in old.items():
                    path = root / name
                    if payload is None:
                        self.assertFalse(path.exists(), name)
                    else:
                        self.assertEqual(path.read_bytes(), payload, name)

    def test_effective_wal_rolls_back_when_commit_point_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root, invalidate_groups=True)
            old = {
                name: (root / name).read_bytes() if (root / name).is_file() else None
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
            }

            with patch.object(
                claim_artifacts,
                "_finish_effective_publication_unlocked",
                side_effect=RuntimeError("simulated pre-commit crash"),
            ):
                with self.assertRaisesRegex(RuntimeError, "pre-commit"):
                    claim_artifacts.publish_effective_snapshot(
                        root,
                        ledger,
                        queue,
                        meta=meta,
                    )

            claim_artifacts.load_committed_shadow(root)
            for name, payload in old.items():
                path = root / name
                if payload is None:
                    self.assertFalse(path.exists(), name)
                else:
                    self.assertEqual(path.read_bytes(), payload, name)

    def test_killed_effective_publisher_recovery_matrix_is_single_generation(self) -> None:
        crash_points = [
            ("before_replace", claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL, False),
            ("after_replace", claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL, False),
            ("before_replace", claim_artifacts.CLAIM_EFFECTIVE_LEDGER, False),
            ("after_replace", claim_artifacts.CLAIM_EFFECTIVE_LEDGER, False),
            ("before_replace", claim_artifacts.CLAIM_QUEUE_PROPOSALS, False),
            ("after_replace", claim_artifacts.CLAIM_QUEUE_PROPOSALS, False),
            ("before_replace", claim_artifacts.CLAIM_EFFECTIVE_META, False),
            ("after_replace", claim_artifacts.CLAIM_EFFECTIVE_META, False),
            ("before_unlink", claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL, False),
            ("after_unlink", claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL, True),
        ]
        script = r'''
import os
from pathlib import Path
import sys

import claim_artifacts
from tests.test_claim_artifacts import _effective_candidate

root = Path(sys.argv[1]).resolve()
crash_operation = sys.argv[2]
crash_name = sys.argv[3]
ledger, queue, meta = _effective_candidate(root)
original_replace = claim_artifacts._replace_with_retry
original_unlink = claim_artifacts._unlink_with_retry

def crash_at_replace(source, target):
    target = Path(target)
    matches = target.parent.resolve() == root and target.name == crash_name
    if matches and crash_operation == "before_replace":
        os._exit(93)
    original_replace(source, target)
    if matches and crash_operation == "after_replace":
        os._exit(94)

def crash_at_unlink(target):
    target = Path(target)
    matches = target.parent.resolve() == root and target.name == crash_name
    if matches and crash_operation == "before_unlink":
        os._exit(95)
    original_unlink(target)
    if matches and crash_operation == "after_unlink":
        os._exit(96)

claim_artifacts._replace_with_retry = crash_at_replace
claim_artifacts._unlink_with_retry = crash_at_unlink
claim_artifacts.publish_effective_snapshot(root, ledger, queue, meta=meta)
'''
        expected_exit_codes = {
            "before_replace": 93,
            "after_replace": 94,
            "before_unlink": 95,
            "after_unlink": 96,
        }

        for operation, name, committed_after_crash in crash_points:
            with self.subTest(operation=operation, name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _publish(root, _catalog(), run_id="effective-matrix-base")
                    prior_snapshot = {
                        snapshot_name: (
                            (root / snapshot_name).read_bytes()
                            if (root / snapshot_name).is_file()
                            else None
                        )
                        for snapshot_name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                    }
                    verifier_attempts = (
                        root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS
                    ).read_bytes()

                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            script,
                            str(root),
                            operation,
                            name,
                        ],
                        cwd=Path(__file__).resolve().parents[1],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode,
                        expected_exit_codes[operation],
                        result.stderr,
                    )

                    recovered = claim_artifacts.load_committed_shadow(root)
                    self.assertFalse(
                        (root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL).exists()
                    )
                    self.assertFalse(any(
                        root.glob(".claim-effective-publication-backup-*")
                    ))
                    self.assertEqual(
                        (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS).read_bytes(),
                        verifier_attempts,
                    )
                    self.assertFalse(
                        (root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).exists()
                    )

                    if committed_after_crash:
                        self.assertEqual(
                            recovered["effective_ledger"][0]["resolution"],
                            "covered",
                        )
                        self.assertEqual(recovered["queue_proposals"], [])
                        self.assertNotEqual(
                            {
                                snapshot_name: (
                                    (root / snapshot_name).read_bytes()
                                    if (root / snapshot_name).is_file()
                                    else None
                                )
                                for snapshot_name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                            },
                            prior_snapshot,
                        )
                    else:
                        self.assertEqual(
                            {
                                snapshot_name: (
                                    (root / snapshot_name).read_bytes()
                                    if (root / snapshot_name).is_file()
                                    else None
                                )
                                for snapshot_name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                            },
                            prior_snapshot,
                        )

    def test_publish_appends_hash_chained_verifier_attempt_and_binds_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = _publish(root, _catalog(), run_id="cold-request-1")

            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 1)
            event = rows[0]
            self.assertEqual(event["schema"], "claim-verifier-attempt/v2")
            self.assertEqual(event["event_seq"], 1)
            self.assertEqual(event["chain_attempt_seq"], 1)
            self.assertEqual(event["attempt_kind"], "cold")
            self.assertEqual(event["attempt_status"], "complete")
            self.assertEqual(
                event["previous_event_hash"],
                "sha256:" + hashlib.sha256(b"").hexdigest(),
            )
            event_without_hash = dict(event)
            event_hash = event_without_hash.pop("event_hash")
            self.assertEqual(
                event_hash,
                "sha256:" + hashlib.sha256(
                    claim_artifacts._canonical_json_bytes(event_without_hash)
                ).hexdigest(),
            )

            binding = generation["attempt_chain"]
            self.assertEqual(binding["ledger_file"], claim_artifacts.CLAIM_VERIFIER_ATTEMPTS)
            self.assertEqual(binding["ledger_prefix_count"], 1)
            self.assertEqual(
                binding["ledger_prefix_sha256"],
                claim_artifacts.file_sha256(root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS),
            )
            self.assertEqual(binding["chain_id"], event["chain_id"])
            self.assertEqual(binding["attempt_id"], event["attempt_id"])
            self.assertEqual(binding["attempt_count"], 1)
            self.assertEqual(binding["attempt_kind"], "cold")
            self.assertEqual(binding["attempt_status"], "complete")
            self.assertEqual(
                binding["source_locator"]["attempt_request_id"],
                "cold-request-1",
            )
            self.assertEqual(
                binding["source_locator"]["requirements_request_id"],
                "cold-request-1",
            )
            self.assertEqual(
                event["chain_identity"]["requirements_request_id"],
                "cold-request-1",
            )
            self.assertIsNone(binding["source_locator"]["reuse_generation_run_id"])
            self.assertIsNone(binding["source_locator"]["reuse_attempt_id"])

            schema = json.loads(
                (Path(__file__).parents[1] / "schemas" / "claim_verifier_attempt.schema.json")
                .read_text(encoding="utf-8")
            )
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(event)
            self.assertEqual(
                claim_artifacts.load_committed_shadow(root)["generation_meta"][
                    "attempt_chain"
                ],
                binding,
            )

    def test_cold_then_ledger_only_accumulates_cost_without_reusing_absolute_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = "Auxiliary outputs can be configured by the user."
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [requirement])
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="requirements-request-1",
                no_ledger_baseline_cost=_baseline_cost(),
            )

            cold_shadow, cold_budget = _verifier_shadow(catalog)
            cold = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                cold_shadow,
                run_id="cold-request-1",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            warm_shadow, warm_budget = _verifier_shadow(
                catalog,
                reusable_groups=cold_shadow["groups"],
            )
            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="ledger_only",
                attempt_request_id="refresh-request-2",
                requirements_request_id="requirements-request-1",
                reuse_generation_run_id="cold-request-1",
                reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
            ):
                warm = claim_artifacts.publish_shadow_generation(
                    root,
                    catalog,
                    warm_shadow,
                    run_id="refresh-request-2",
                    requirements_sha256=claim_artifacts.file_sha256(
                        root / "ai_requirements.jsonl"
                    ),
                )

            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["previous_event_hash"], rows[0]["event_hash"])
            self.assertEqual(rows[1]["chain_id"], rows[0]["chain_id"])
            self.assertEqual(rows[1]["chain_attempt_seq"], 2)
            self.assertEqual(rows[1]["attempt_kind"], "ledger_only")
            self.assertEqual(
                rows[1]["source_locator"]["source_generation_run_id"],
                "cold-request-1",
            )
            self.assertEqual(
                rows[1]["source_locator"]["source_attempt_id"],
                cold["attempt_chain"]["attempt_id"],
            )

            cumulative = warm["attempt_chain"]["cumulative_metrics"]
            self.assertEqual(cumulative["verifier_call_count"], 1)
            self.assertEqual(cumulative["verifier_tokens"], 7)
            self.assertEqual(cumulative["semantic_validation_reused_group_count"], 1)
            self.assertEqual(cumulative["semantic_verifier_candidate_count"], 2)
            self.assertEqual(
                cumulative["semantic_validation_reused_group_ratio"]["value"],
                0.5,
            )
            self.assertEqual(warm["attempt_chain"]["attempt_count"], 2)
            self.assertEqual(warm["attempt_chain"]["ledger_prefix_count"], 2)

            self.assertEqual(cold_budget.snapshot()["attempted_calls"], 1)
            self.assertEqual(warm_budget.snapshot()["attempted_calls"], 0)
            self.assertEqual(
                warm["shadow_meta"]["verifier_budget"]["attempted_calls"],
                0,
            )
            self.assertEqual(
                warm["shadow_meta"]["verifier_budget"]["remaining_calls"],
                4,
            )

    def test_identical_cold_outputs_from_distinct_requests_use_distinct_chains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [_requirement(catalog)],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="fixed-requirements-root",
            )
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            first = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                _shadow(catalog),
                run_id="cold-request-1",
                requirements_sha256=requirements_hash,
            )
            second = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                _shadow(catalog),
                run_id="cold-request-2",
                requirements_sha256=requirements_hash,
            )

            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]["chain_id"], rows[1]["chain_id"])
            self.assertEqual(first["attempt_chain"]["attempt_count"], 1)
            self.assertEqual(second["attempt_chain"]["attempt_count"], 1)
            self.assertEqual(
                rows[1]["chain_identity"]["requirements_request_id"],
                "fixed-requirements-root",
            )
            self.assertEqual(
                rows[1]["chain_identity"]["root_attempt_request_id"],
                "cold-request-2",
            )

    def test_ledger_only_attempt_cannot_reuse_unknown_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="cold-request-1")

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "reuses unknown attempt",
            ):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="ledger_only",
                    attempt_request_id="refresh-request-2",
                    requirements_request_id="cold-request-1",
                    reuse_generation_run_id="missing-generation",
                    reuse_attempt_id="sha256:" + "f" * 64,
                ):
                    claim_artifacts.publish_shadow_generation(
                        root,
                        catalog,
                        _shadow(catalog),
                        run_id="refresh-request-2",
                        requirements_sha256=claim_artifacts.file_sha256(
                            root / "ai_requirements.jsonl"
                        ),
                    )

            self.assertEqual(
                claim_artifacts.read_claim_verifier_attempts(root)[0]["attempt_id"],
                cold["attempt_chain"]["attempt_id"],
            )

    def test_attempt_scope_rejects_generation_and_requirements_request_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [_requirement(catalog)],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="requirements-request-1",
            )
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "request differs from generation run",
            ):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="cold",
                    attempt_request_id="another-generation",
                    requirements_request_id="requirements-request-1",
                ):
                    claim_artifacts.publish_shadow_generation(
                        root,
                        catalog,
                        _shadow(catalog),
                        run_id="generation-1",
                        requirements_sha256=requirements_hash,
                    )

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "requirements request differs from metadata",
            ):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="cold",
                    attempt_request_id="generation-2",
                    requirements_request_id="another-requirements-root",
                ):
                    claim_artifacts.publish_shadow_generation(
                        root,
                        catalog,
                        _shadow(catalog),
                        run_id="generation-2",
                        requirements_sha256=requirements_hash,
                    )

    def test_generation_write_failure_appends_status_correction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="generation-failure-1",
            )
            shadow = _shadow(catalog)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            original_write_json = claim_artifacts.atomic_write_json

            def fail_generation_meta(path: Path, payload: dict) -> None:
                if Path(path).name == claim_artifacts.CLAIM_GENERATION_META:
                    raise OSError("generation commit failed")
                original_write_json(path, payload)

            failure_context = {
                "catalog_build": catalog,
                "target_generation_id": shadow["meta"]["target_generation_id"],
                "requirements_sha256": requirements_hash,
                "verifier_runtime": shadow["meta"]["verifier_runtime"],
                "baseline_cost": dict(
                    json.loads(
                        (root / "ai_requirements.meta.json").read_text(encoding="utf-8")
                    )["no_ledger_baseline_cost"]
                ),
                "verifier_budget": None,
                "reused_group_count": 0,
            }
            with patch.object(
                claim_artifacts,
                "atomic_write_json",
                side_effect=fail_generation_meta,
            ):
                with self.assertRaisesRegex(OSError, "generation commit failed"):
                    with claim_artifacts.claim_verifier_attempt_scope(
                        root,
                        attempt_kind="cold",
                        attempt_request_id="generation-failure-1",
                        requirements_request_id="generation-failure-1",
                        failure_context=failure_context,
                    ):
                        claim_artifacts.publish_shadow_generation(
                            root,
                            catalog,
                            shadow,
                            run_id="generation-failure-1",
                            requirements_sha256=requirements_hash,
                        )

            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["attempt_id"], rows[1]["attempt_id"])
            self.assertEqual(rows[0]["attempt_status"], "complete")
            self.assertEqual(rows[1]["attempt_status"], "failed")
            self.assertEqual(rows[1]["supersedes_event_hash"], rows[0]["event_hash"])
            self.assertEqual(
                rows[1]["attempt_metrics"]["verifier_operation_failure_count"],
                1,
            )

    def test_failed_refresh_restores_prior_snapshot_and_exposes_full_cost_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="cold-request-1")
            prior_snapshot = {
                name: (root / name).read_bytes()
                for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
            }
            shadow = _shadow(catalog)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            requirements_meta = json.loads(
                (root / "ai_requirements.meta.json").read_text(encoding="utf-8")
            )
            original_write_json = claim_artifacts.atomic_write_json

            def fail_generation_meta(path: Path, payload: dict) -> None:
                if Path(path).name == claim_artifacts.CLAIM_GENERATION_META:
                    raise OSError("refresh generation commit failed")
                original_write_json(path, payload)

            failure_context = {
                "catalog_build": catalog,
                "target_generation_id": shadow["meta"]["target_generation_id"],
                "requirements_sha256": requirements_hash,
                "verifier_runtime": shadow["meta"]["verifier_runtime"],
                "baseline_cost": dict(
                    requirements_meta["no_ledger_baseline_cost"]
                ),
                "verifier_budget": None,
                "reused_group_count": 0,
            }
            with patch.object(
                claim_artifacts,
                "atomic_write_json",
                side_effect=fail_generation_meta,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "refresh generation commit failed",
                ):
                    with claim_artifacts.claim_verifier_attempt_scope(
                        root,
                        attempt_kind="ledger_only",
                        attempt_request_id="failed-refresh-2",
                        requirements_request_id="cold-request-1",
                        reuse_generation_run_id="cold-request-1",
                        reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
                        failure_context=failure_context,
                    ):
                        claim_artifacts.publish_shadow_generation(
                            root,
                            catalog,
                            shadow,
                            run_id="failed-refresh-2",
                            requirements_sha256=requirements_hash,
                        )

            self.assertEqual(
                {
                    name: (root / name).read_bytes()
                    for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
                },
                prior_snapshot,
            )
            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[-1]["attempt_status"], "failed")
            self.assertEqual(rows[-1]["supersedes_event_hash"], rows[-2]["event_hash"])

            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(
                loaded["generation_meta"]["attempt_chain"]["attempt_id"],
                cold["attempt_chain"]["attempt_id"],
            )
            self.assertEqual(
                loaded["generation_meta"]["attempt_chain"]["attempt_count"],
                1,
            )
            cost_chain = loaded["attempt_cost_chain"]
            self.assertEqual(cost_chain["chain_id"], cold["attempt_chain"]["chain_id"])
            self.assertEqual(cost_chain["attempt_count"], 2)
            self.assertEqual(cost_chain["tail_attempt_id"], rows[-1]["attempt_id"])
            self.assertEqual(cost_chain["tail_attempt_kind"], "ledger_only")
            self.assertEqual(cost_chain["tail_attempt_status"], "failed")
            self.assertEqual(
                cost_chain["cumulative_metrics"][
                    "verifier_operation_failure_count"
                ],
                1,
            )
            self.assertEqual(cost_chain["validated_full_ledger_count"], len(rows))
            self.assertEqual(
                cost_chain["validated_full_ledger_sha256"],
                claim_artifacts._sha256_bytes(claim_artifacts._jsonl_bytes(rows)),
            )

    def test_killed_publisher_is_recovered_from_durable_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="cold-request-1")
            prior_snapshot = {
                name: (root / name).read_bytes()
                for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
            }
            source = cold["attempt_chain"]["source_locator"]
            script = r'''
import os
from pathlib import Path
import sys

import claim_artifacts
from tests.test_claim_artifacts import _catalog, _shadow

root = Path(sys.argv[1])
catalog = _catalog()
shadow = _shadow(catalog)
committed = claim_artifacts.load_committed_shadow(root)
binding = committed["generation_meta"]["attempt_chain"]
original_write_json = claim_artifacts.atomic_write_json

def terminate_on_generation_meta(path, payload):
    if Path(path).name == claim_artifacts.CLAIM_GENERATION_META:
        os._exit(91)
    original_write_json(path, payload)

claim_artifacts.atomic_write_json = terminate_on_generation_meta
with claim_artifacts.claim_verifier_attempt_scope(
    root,
    attempt_kind="ledger_only",
    attempt_request_id="killed-refresh-2",
    requirements_request_id=sys.argv[2],
    reuse_generation_run_id="cold-request-1",
    reuse_attempt_id=binding["attempt_id"],
):
    claim_artifacts.publish_shadow_generation(
        root,
        catalog,
        shadow,
        run_id="killed-refresh-2",
        requirements_sha256=claim_artifacts.file_sha256(
            root / "ai_requirements.jsonl"
        ),
    )
'''
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(root),
                    str(source["requirements_request_id"]),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 91, result.stderr)
            self.assertTrue((root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).is_file())
            self.assertTrue((root / "claim_artifacts.lock").is_file())

            loaded = claim_artifacts.load_committed_shadow(root)

            self.assertEqual(loaded["generation_meta"]["run_id"], "cold-request-1")
            self.assertEqual(
                {
                    name: (root / name).read_bytes()
                    for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
                },
                prior_snapshot,
            )
            self.assertFalse((root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).exists())
            self.assertTrue((root / "claim_artifacts.lock").is_file())
            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(
                [row["attempt_status"] for row in rows],
                ["complete", "complete", "failed"],
            )
            self.assertEqual(rows[-1]["attempt_id"], rows[-2]["attempt_id"])
            self.assertEqual(
                loaded["attempt_cost_chain"]["tail_attempt_status"],
                "failed",
            )

    def test_kill_before_publication_journal_preserves_paid_verifier_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = (
                "Auxiliary outputs can be configured by the user."
            )
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="checkpoint-requirements-1",
                no_ledger_baseline_cost=_baseline_cost(),
            )
            cold_shadow, _cold_budget = _verifier_shadow(catalog)
            cold = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                cold_shadow,
                run_id="checkpoint-cold-1",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            source = cold["attempt_chain"]["source_locator"]
            script = r'''
import os
from pathlib import Path
import sys

import claim_artifacts
import claim_ledger
from llm_client import LLMRequestBudget
from tests.test_claim_artifacts import _baseline_cost, _catalog, _requirement

root = Path(sys.argv[1]).resolve()
catalog = _catalog()
committed = claim_artifacts.load_committed_shadow(root)
binding = committed["generation_meta"]["attempt_chain"]
runtime = claim_ledger.semantic_verifier_runtime(
    route_mode="llm",
    enabled=True,
    rounds=1,
    budget_policy_version=LLMRequestBudget.VERSION,
    max_calls=4,
    max_total_tokens=100000,
)
budget = LLMRequestBudget(max_calls=4, max_tokens=100000)
requirement = _requirement(catalog)
requirement["description"] = "Auxiliary outputs can be configured by the user."

def verifier(_unit_id, _groups):
    reservation = budget.reserve({"messages": [], "max_tokens": 1})
    budget.commit(reservation, {"total_tokens": 7})
    os._exit(91)

with claim_artifacts.claim_verifier_attempt_scope(
    root,
    attempt_kind="ledger_only",
    attempt_request_id="checkpoint-killed-2",
    requirements_request_id=sys.argv[2],
    reuse_generation_run_id="checkpoint-cold-1",
    reuse_attempt_id=binding["attempt_id"],
    failure_context={
        "catalog_build": catalog,
        "target_generation_id": committed["generation_meta"]["target_generation_id"],
        "requirements_sha256": claim_artifacts.file_sha256(
            root / "ai_requirements.jsonl"
        ),
        "verifier_runtime": runtime,
        "baseline_cost": _baseline_cost(),
        "verifier_budget": budget,
    },
):
    claim_ledger.publish_b_track_shadow(
        root,
        run_id="checkpoint-killed-2",
        route_mode="llm",
        extraction_status="success",
        catalog_build=catalog,
        requirements=[requirement],
        semantic_verifier=verifier,
        baseline_cost=_baseline_cost(),
        verifier_runtime=runtime,
        verifier_budget=budget,
    )
'''
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(root),
                    str(source["requirements_request_id"]),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 91, result.stderr)
            self.assertTrue(
                (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT).is_file()
            )
            self.assertFalse(
                (root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).exists()
            )

            loaded = claim_artifacts.load_committed_shadow(root)
            rows = claim_artifacts.read_claim_verifier_attempts(root)

            self.assertEqual(
                loaded["generation_meta"]["run_id"],
                "checkpoint-cold-1",
            )
            self.assertEqual([row["attempt_status"] for row in rows], ["complete", "failed"])
            self.assertEqual(rows[-1]["attempt_metrics"]["verifier_call_count"], 1)
            self.assertEqual(rows[-1]["attempt_metrics"]["verifier_tokens"], 7)
            self.assertEqual(
                rows[-1]["attempt_metrics"]["semantic_verifier_candidate_count"],
                1,
            )
            self.assertEqual(
                rows[-1]["attempt_metrics"][
                    "semantic_validation_reused_group_count"
                ],
                0,
            )
            self.assertEqual(
                rows[-1]["attempt_metrics"]["verifier_operation_failure_count"],
                1,
            )
            self.assertFalse(
                (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT).exists()
            )

    def test_recovery_records_failed_attempt_when_crash_precedes_attempt_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            shadow = _shadow(catalog)
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [_requirement(catalog)],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="first-crash",
            )
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="cold",
                attempt_request_id="first-crash",
                requirements_request_id="first-crash",
            ):
                recovery = claim_artifacts._shadow_verifier_attempt_recovery(
                    root,
                    catalog_meta=catalog["meta"],
                    shadow_meta=shadow["meta"],
                    metrics=shadow["metrics"],
                    run_id="first-crash",
                    requirements_sha256=requirements_hash,
                )
                claim_artifacts._begin_claim_publication_unlocked(
                    root,
                    run_id="first-crash",
                    attempt_recovery=recovery,
                )
                claim_artifacts.atomic_write_jsonl(
                    root / claim_artifacts.CLAIM_CATALOG,
                    catalog["catalog"],
                )

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "missing claim generation meta",
            ):
                claim_artifacts.load_committed_shadow(root)

            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["attempt_status"], "failed")
            self.assertEqual(
                rows[0]["attempt_metrics"]["verifier_operation_failure_count"],
                1,
            )
            self.assertFalse((root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).exists())
            self.assertTrue(all(
                not (root / name).exists()
                for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
            ))

    def test_recovery_monotonically_corrects_an_already_failed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="failed-correction-cold-1")
            shadow, _budget = _verifier_shadow(catalog, malformed_response=True)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="ledger_only",
                attempt_request_id="failed-correction-refresh-2",
                requirements_request_id=str(
                    cold["attempt_chain"]["source_locator"][
                        "requirements_request_id"
                    ]
                ),
                reuse_generation_run_id="failed-correction-cold-1",
                reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
            ):
                recovery = claim_artifacts._shadow_verifier_attempt_recovery(
                    root,
                    catalog_meta=catalog["meta"],
                    shadow_meta=shadow["meta"],
                    metrics=shadow["metrics"],
                    run_id="failed-correction-refresh-2",
                    requirements_sha256=requirements_hash,
                )
                claim_artifacts._begin_claim_publication_unlocked(
                    root,
                    run_id="failed-correction-refresh-2",
                    attempt_recovery=recovery,
                )
                first = claim_artifacts._append_shadow_verifier_attempt_unlocked(
                    root,
                    recovery=recovery,
                )
                recovered = claim_artifacts._recover_interrupted_publication_unlocked(
                    root
                )

            self.assertIsNotNone(recovered)
            self.assertEqual(first["attempt_id"], recovered["attempt_id"])
            matching = [
                row
                for row in claim_artifacts.read_claim_verifier_attempts(root)
                if row["attempt_id"] == first["attempt_id"]
            ]
            self.assertEqual(len(matching), 2)
            self.assertEqual(
                [
                    row["attempt_metrics"]["verifier_operation_failure_count"]
                    for row in matching
                ],
                [1, 2],
            )
            self.assertTrue(all(row["attempt_status"] == "failed" for row in matching))

    def test_killed_publisher_recovery_matrix_has_single_global_commit_point(self) -> None:
        crash_points = [
            ("replace", claim_artifacts.CLAIM_PUBLICATION_JOURNAL, False),
            ("replace", claim_artifacts.CLAIM_CATALOG, False),
            ("replace", claim_artifacts.CLAIM_CATALOG_META, False),
            ("replace", claim_artifacts.CLAIM_COVERAGE_GROUPS, False),
            ("replace", claim_artifacts.CLAIM_LEDGER, False),
            ("replace", claim_artifacts.CLAIM_SHADOW_METRICS, False),
            ("replace", claim_artifacts.CLAIM_VERIFIER_ATTEMPTS, False),
            ("replace", claim_artifacts.CLAIM_GENERATION_META, False),
            ("replace", claim_artifacts.CLAIM_EFFECTIVE_LEDGER, False),
            ("replace", claim_artifacts.CLAIM_EFFECTIVE_META, False),
            ("unlink", claim_artifacts.CLAIM_PUBLICATION_JOURNAL, True),
        ]
        script = r'''
import os
from pathlib import Path
import sys

import claim_artifacts
from tests.test_claim_artifacts import _catalog, _shadow

root = Path(sys.argv[1]).resolve()
requirements_request_id = sys.argv[2]
crash_operation = sys.argv[3]
crash_name = sys.argv[4]
catalog = _catalog()
shadow = _shadow(catalog)
committed = claim_artifacts.load_committed_shadow(root)
binding = committed["generation_meta"]["attempt_chain"]
original_replace = claim_artifacts._replace_with_retry
original_unlink = claim_artifacts._unlink_with_retry

def crash_after_replace(source, target):
    original_replace(source, target)
    target = Path(target)
    if (
        crash_operation == "replace"
        and target.parent.resolve() == root
        and target.name == crash_name
    ):
        os._exit(91)

def crash_after_unlink(target):
    original_unlink(target)
    target = Path(target)
    if (
        crash_operation == "unlink"
        and target.parent.resolve() == root
        and target.name == crash_name
    ):
        os._exit(92)

claim_artifacts._replace_with_retry = crash_after_replace
claim_artifacts._unlink_with_retry = crash_after_unlink
with claim_artifacts.claim_verifier_attempt_scope(
    root,
    attempt_kind="ledger_only",
    attempt_request_id="matrix-refresh-2",
    requirements_request_id=requirements_request_id,
    reuse_generation_run_id="matrix-cold-1",
    reuse_attempt_id=binding["attempt_id"],
):
    claim_artifacts.publish_shadow_generation(
        root,
        catalog,
        shadow,
        run_id="matrix-refresh-2",
        requirements_sha256=claim_artifacts.file_sha256(
            root / "ai_requirements.jsonl"
        ),
    )
'''
        for operation, name, committed_after_crash in crash_points:
            with self.subTest(operation=operation, name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    catalog = _catalog()
                    cold = _publish(root, catalog, run_id="matrix-cold-1")
                    prior_snapshot = {
                        snapshot_name: (root / snapshot_name).read_bytes()
                        for snapshot_name in claim_artifacts.CLAIM_SNAPSHOT_FILES
                    }
                    requirements_request_id = str(
                        cold["attempt_chain"]["source_locator"][
                            "requirements_request_id"
                        ]
                    )
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            script,
                            str(root),
                            requirements_request_id,
                            operation,
                            name,
                        ],
                        cwd=Path(__file__).resolve().parents[1],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode,
                        92 if operation == "unlink" else 91,
                        result.stderr,
                    )

                    loaded = claim_artifacts.load_committed_shadow(root)
                    self.assertFalse(
                        (root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).exists()
                    )
                    self.assertTrue((root / "claim_artifacts.lock").is_file())
                    self.assertFalse(any(
                        root.glob(".claim-publication-backup-*")
                    ))
                    if committed_after_crash:
                        self.assertEqual(
                            loaded["generation_meta"]["run_id"],
                            "matrix-refresh-2",
                        )
                        self.assertEqual(
                            loaded["attempt_cost_chain"]["tail_attempt_status"],
                            "complete",
                        )
                    else:
                        self.assertEqual(
                            loaded["generation_meta"]["run_id"],
                            "matrix-cold-1",
                        )
                        self.assertEqual(
                            {
                                snapshot_name: (root / snapshot_name).read_bytes()
                                for snapshot_name in claim_artifacts.CLAIM_SNAPSHOT_FILES
                            },
                            prior_snapshot,
                        )
                        self.assertEqual(
                            loaded["attempt_cost_chain"]["tail_attempt_status"],
                            "failed",
                        )

    def test_corrupt_publication_backup_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog, run_id="cold-1")
            shadow = _shadow(catalog)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            recovery = claim_artifacts._shadow_verifier_attempt_recovery(
                root,
                catalog_meta=catalog["meta"],
                shadow_meta=shadow["meta"],
                metrics=shadow["metrics"],
                run_id="corrupt-backup-2",
                requirements_sha256=requirements_hash,
            )
            journal = claim_artifacts._begin_claim_publication_unlocked(
                root,
                run_id="corrupt-backup-2",
                attempt_recovery=recovery,
            )
            backup_dir = claim_artifacts._publication_backup_dir(
                root,
                journal["transaction_id"],
            )
            (backup_dir / claim_artifacts.CLAIM_LEDGER).write_bytes(b"corrupt\n")
            current_generation = (root / claim_artifacts.CLAIM_GENERATION_META).read_bytes()

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "hash mismatch for publication backup claim_ledger.jsonl",
            ):
                claim_artifacts.load_committed_shadow(root)
            self.assertTrue(
                (root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).is_file()
            )
            self.assertEqual(
                (root / claim_artifacts.CLAIM_GENERATION_META).read_bytes(),
                current_generation,
            )

    def test_corrupt_prepublication_cost_checkpoint_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="checkpoint-corrupt-cold-1")
            shadow = _shadow(catalog)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="ledger_only",
                attempt_request_id="checkpoint-corrupt-refresh-2",
                requirements_request_id=str(
                    cold["attempt_chain"]["source_locator"][
                        "requirements_request_id"
                    ]
                ),
                reuse_generation_run_id="checkpoint-corrupt-cold-1",
                reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
            ):
                recovery = claim_artifacts._shadow_verifier_attempt_recovery(
                    root,
                    catalog_meta=catalog["meta"],
                    shadow_meta=shadow["meta"],
                    metrics=shadow["metrics"],
                    run_id="checkpoint-corrupt-refresh-2",
                    requirements_sha256=requirements_hash,
                )
                claim_artifacts._begin_verifier_attempt_checkpoint_unlocked(
                    root,
                    run_id="checkpoint-corrupt-refresh-2",
                    attempt_recovery=recovery,
                )
                checkpoint_path = (
                    root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT
                )
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint["updated_at"] = "tampered"
                claim_artifacts.atomic_write_json(checkpoint_path, checkpoint)

                with self.assertRaisesRegex(
                    claim_artifacts.ClaimArtifactError,
                    "checkpoint hash mismatch",
                ):
                    claim_artifacts.load_committed_shadow(root)

    def test_recovery_is_idempotent_after_attempt_correction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="recovery-cold-1")
            shadow = _shadow(catalog)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="ledger_only",
                attempt_request_id="interrupted-recovery-2",
                requirements_request_id=str(
                    cold["attempt_chain"]["source_locator"][
                        "requirements_request_id"
                    ]
                ),
                reuse_generation_run_id="recovery-cold-1",
                reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
            ):
                recovery = claim_artifacts._shadow_verifier_attempt_recovery(
                    root,
                    catalog_meta=catalog["meta"],
                    shadow_meta=shadow["meta"],
                    metrics=shadow["metrics"],
                    run_id="interrupted-recovery-2",
                    requirements_sha256=requirements_hash,
                )
                claim_artifacts._begin_claim_publication_unlocked(
                    root,
                    run_id="interrupted-recovery-2",
                    attempt_recovery=recovery,
                )
                claim_artifacts._append_shadow_verifier_attempt_unlocked(
                    root,
                    recovery=recovery,
                )
                claim_artifacts.atomic_write_jsonl(
                    root / claim_artifacts.CLAIM_LEDGER,
                    [],
                )

            with patch.object(
                claim_artifacts,
                "_finish_claim_publication_unlocked",
                side_effect=OSError("recovery cleanup interrupted"),
            ):
                with self.assertRaisesRegex(OSError, "cleanup interrupted"):
                    claim_artifacts._recover_interrupted_publication_unlocked(root)

            first_rows = claim_artifacts._read_claim_verifier_attempts_unlocked(
                root,
                allow_missing=False,
            )
            self.assertEqual(len(first_rows), 3)
            self.assertEqual(first_rows[-1]["attempt_status"], "failed")
            self.assertTrue(
                (root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).is_file()
            )

            claim_artifacts._recover_interrupted_publication_unlocked(root)
            second_rows = claim_artifacts._read_claim_verifier_attempts_unlocked(
                root,
                allow_missing=False,
            )
            self.assertEqual(second_rows, first_rows)
            self.assertFalse(
                (root / claim_artifacts.CLAIM_PUBLICATION_JOURNAL).exists()
            )
            self.assertEqual(
                claim_artifacts.load_committed_shadow(root)["generation_meta"][
                    "run_id"
                ],
                "recovery-cold-1",
            )

    def test_catalog_probe_cannot_invalidate_committed_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog, run_id="committed-1")
            prior_snapshot = {
                name: (root / name).read_bytes()
                for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
            }

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "cannot replace an existing claim generation",
            ):
                claim_artifacts.publish_catalog_probe(root, catalog)

            self.assertEqual(
                {
                    name: (root / name).read_bytes()
                    for name in claim_artifacts.CLAIM_SNAPSHOT_FILES
                },
                prior_snapshot,
            )
            self.assertEqual(
                claim_artifacts.load_committed_shadow(root)["generation_meta"][
                    "run_id"
                ],
                "committed-1",
            )

    def test_reader_waits_for_publication_and_never_observes_mixed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="reader-cold-1")
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            entered = threading.Event()
            release = threading.Event()
            writer_errors: list[BaseException] = []
            reader_results: list[dict] = []
            original_publish_catalog = claim_artifacts._publish_catalog_probe_unlocked

            def paused_publish_catalog(out_dir: Path, build: dict) -> dict:
                result = original_publish_catalog(out_dir, build)
                entered.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("test did not release paused publisher")
                return result

            def publish() -> None:
                try:
                    with claim_artifacts.claim_verifier_attempt_scope(
                        root,
                        attempt_kind="ledger_only",
                        attempt_request_id="reader-refresh-2",
                        requirements_request_id=str(
                            cold["attempt_chain"]["source_locator"][
                                "requirements_request_id"
                            ]
                        ),
                        reuse_generation_run_id="reader-cold-1",
                        reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
                    ):
                        claim_artifacts.publish_shadow_generation(
                            root,
                            catalog,
                            _shadow(catalog),
                            run_id="reader-refresh-2",
                            requirements_sha256=requirements_hash,
                        )
                except BaseException as exc:
                    writer_errors.append(exc)

            def read() -> None:
                reader_results.append(claim_artifacts.load_committed_shadow(root))

            with patch.object(
                claim_artifacts,
                "_publish_catalog_probe_unlocked",
                side_effect=paused_publish_catalog,
            ):
                writer = threading.Thread(target=publish)
                writer.start()
                self.assertTrue(entered.wait(timeout=10))
                reader = threading.Thread(target=read)
                reader.start()
                time.sleep(0.05)
                self.assertTrue(reader.is_alive())
                release.set()
                writer.join(timeout=10)
                reader.join(timeout=10)

            self.assertFalse(writer.is_alive())
            self.assertFalse(reader.is_alive())
            self.assertEqual(writer_errors, [])
            self.assertEqual(len(reader_results), 1)
            self.assertEqual(
                reader_results[0]["generation_meta"]["run_id"],
                "reader-refresh-2",
            )

    def test_live_publication_lock_is_not_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            root.mkdir(parents=True, exist_ok=True)
            lock_path = root / "claim_artifacts.lock"
            script = r'''
import sys
import time
from pathlib import Path
import claim_artifacts

with claim_artifacts.claim_publication_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    time.sleep(30)
'''
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                with patch.object(
                    claim_artifacts,
                    "_PUBLICATION_LOCK_TIMEOUT_S",
                    0.05,
                ):
                    with self.assertRaisesRegex(TimeoutError, "timed out"):
                        with claim_artifacts.claim_publication_lock(root):
                            self.fail("a live publication lock was stolen")
            finally:
                if child.poll() is None:
                    child.terminate()
                child.communicate(timeout=5)

            with claim_artifacts.claim_publication_lock(root):
                pass
            owner = json.loads(lock_path.read_text(encoding="ascii"))
            self.assertEqual(owner["pid"], os.getpid())
            self.assertTrue(lock_path.is_file())

    def test_empty_publication_lock_carrier_is_reinitialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            lock_path = root / "claim_artifacts.lock"
            lock_path.write_bytes(b"")
            with claim_artifacts.claim_publication_lock(root):
                pass
            owner = json.loads(lock_path.read_text(encoding="ascii"))
            self.assertEqual(owner["pid"], os.getpid())
            self.assertEqual(len(owner["nonce"]), 32)
            self.assertTrue(lock_path.is_file())

    def test_publication_lock_replaces_stale_owner_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            lock_path = root / "claim_artifacts.lock"
            lock_path.write_text(
                json.dumps({
                    "pid": os.getpid(),
                    "process_identity": "stale-process-birth",
                    "nonce": "a" * 32,
                }),
                encoding="ascii",
            )
            with patch.object(
                claim_artifacts,
                "_process_identity",
                return_value="current-process-birth",
            ):
                with claim_artifacts.claim_publication_lock(root):
                    pass
            owner = json.loads(lock_path.read_text(encoding="ascii"))
            self.assertEqual(
                owner["process_identity"],
                "current-process-birth",
            )
            self.assertTrue(lock_path.is_file())

    def test_publication_lock_owner_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            lock_path = root / "claim_artifacts.lock"
            successor = {
                "pid": os.getpid(),
                "process_identity": claim_artifacts._process_identity(os.getpid()) or "",
                "nonce": "b" * 32,
            }
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "owner changed",
            ):
                with claim_artifacts.claim_publication_lock(root):
                    handle = claim_artifacts._PUBLICATION_LOCK_STATES[root]["handle"]
                    claim_artifacts._write_publication_lock_owner(handle, successor)
            self.assertTrue(lock_path.is_file())
            self.assertEqual(
                json.loads(lock_path.read_text(encoding="ascii")),
                successor,
            )

    def test_failed_tail_does_not_invalidate_committed_prefix_or_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="cold-request-1")
            shadow = _shadow(catalog)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            requirements_meta = json.loads(
                (root / "ai_requirements.meta.json").read_text(encoding="utf-8")
            )
            failure_context = {
                "catalog_build": catalog,
                "target_generation_id": shadow["meta"]["target_generation_id"],
                "requirements_sha256": requirements_hash,
                "verifier_runtime": shadow["meta"]["verifier_runtime"],
                "baseline_cost": dict(requirements_meta["no_ledger_baseline_cost"]),
                "verifier_budget": None,
                "reused_group_count": 0,
            }
            with self.assertRaisesRegex(RuntimeError, "refresh failed"):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="ledger_only",
                    attempt_request_id="failed-refresh-2",
                    requirements_request_id="cold-request-1",
                    reuse_generation_run_id="cold-request-1",
                    reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
                    failure_context=failure_context,
                ):
                    raise RuntimeError("refresh failed")

            committed = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(committed["generation_meta"]["run_id"], "cold-request-1")
            self.assertEqual(len(claim_artifacts.read_claim_verifier_attempts(root)), 2)

            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="ledger_only",
                attempt_request_id="recovered-refresh-3",
                requirements_request_id="cold-request-1",
                reuse_generation_run_id="cold-request-1",
                reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
            ):
                recovered = claim_artifacts.publish_shadow_generation(
                    root,
                    catalog,
                    shadow,
                    run_id="recovered-refresh-3",
                    requirements_sha256=requirements_hash,
                )
            self.assertEqual(recovered["attempt_chain"]["attempt_count"], 3)
            self.assertEqual(
                recovered["attempt_chain"]["cumulative_metrics"][
                    "verifier_operation_failure_count"
                ],
                1,
            )
            self.assertEqual(
                claim_artifacts.load_committed_shadow(root)["generation_meta"]["run_id"],
                "recovered-refresh-3",
            )

    def test_failed_attempt_remains_visible_after_successful_warm_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = "Auxiliary outputs can be configured by the user."
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [requirement])
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                no_ledger_baseline_cost=_baseline_cost(),
            )

            failed_shadow, _ = _verifier_shadow(catalog, malformed_response=True)
            failed = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                failed_shadow,
                run_id="failed-request-1",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            self.assertEqual(failed["attempt_chain"]["attempt_status"], "failed")

            warm_shadow, _ = _verifier_shadow(catalog)
            with claim_artifacts.claim_verifier_attempt_scope(
                root,
                attempt_kind="ledger_only",
                attempt_request_id="refresh-request-2",
                requirements_request_id="failed-request-1",
                reuse_generation_run_id="failed-request-1",
                reuse_attempt_id=failed["attempt_chain"]["attempt_id"],
            ):
                warm = claim_artifacts.publish_shadow_generation(
                    root,
                    catalog,
                    warm_shadow,
                    run_id="refresh-request-2",
                    requirements_sha256=claim_artifacts.file_sha256(
                        root / "ai_requirements.jsonl"
                    ),
                )

            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(
                [row["attempt_status"] for row in rows],
                ["failed", "complete"],
            )
            self.assertEqual(
                warm["attempt_chain"]["cumulative_metrics"][
                    "verifier_operation_failure_count"
                ],
                1,
            )
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(
                loaded["generation_meta"]["attempt_chain"]["attempt_count"],
                2,
            )

    def test_tampered_verifier_attempt_hash_chain_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            rows = claim_artifacts.read_claim_verifier_attempts(root)
            rows[0]["attempt_metrics"]["verifier_tokens"] += 1
            claim_artifacts.atomic_write_jsonl(
                root / claim_artifacts.CLAIM_VERIFIER_ATTEMPTS,
                rows,
            )

            with self.assertRaises(claim_artifacts.ClaimArtifactError) as raised:
                claim_artifacts.read_claim_verifier_attempts(root)
            self.assertIn("attempt event hash", str(raised.exception))

    def test_failed_scope_records_budget_calls_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [requirement])
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                no_ledger_baseline_cost=_baseline_cost(),
            )
            budget = LLMRequestBudget(max_calls=2, max_tokens=100000)
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 11})
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=2,
                max_total_tokens=100000,
            )
            target = claim_ledger.b_track_authority_state([requirement], {})

            with self.assertRaisesRegex(RuntimeError, "publication failed"):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="cold",
                    attempt_request_id="failed-request",
                    requirements_request_id="requirements-request",
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
                    raise RuntimeError("publication failed")

            event = claim_artifacts.read_claim_verifier_attempts(root)[0]
            self.assertEqual(event["attempt_metrics"]["verifier_call_count"], 1)
            self.assertEqual(event["attempt_metrics"]["verifier_tokens"], 11)
            self.assertTrue(event["attempt_metrics"]["verifier_usage_complete"])

    def test_failed_checkpoint_attachment_keeps_existing_budget_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="checkpoint-owner-request",
                no_ledger_baseline_cost=_baseline_cost(),
            )
            target = claim_ledger.b_track_authority_state([requirement], {})
            budget = LLMRequestBudget(max_calls=2, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=2,
                max_total_tokens=100000,
            )
            observed_calls: list[int] = []
            budget.set_checkpoint(
                lambda snapshot: observed_calls.append(
                    int(snapshot["attempted_calls"])
                )
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "already has a checkpoint",
            ):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="cold",
                    attempt_request_id="checkpoint-owner-request",
                    requirements_request_id="checkpoint-owner-request",
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
                    self.fail("scope must not start with a pre-owned budget")

            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 3})
            budget.set_checkpoint(None)
            self.assertEqual(observed_calls, [0, 1, 1])
            self.assertFalse(
                (root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT).exists()
            )

    def test_same_process_orphan_checkpoint_recovers_after_failure_log_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="same-process-cold-1")
            requirement = _requirement(catalog)
            target = claim_ledger.b_track_authority_state([requirement], {})
            budget = LLMRequestBudget(max_calls=2, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=2,
                max_total_tokens=100000,
            )

            with patch.object(
                claim_artifacts,
                "_finalize_verifier_attempt_checkpoint_unlocked",
                side_effect=PermissionError("attempt ledger is busy"),
            ):
                with self.assertRaisesRegex(
                    claim_artifacts.ClaimArtifactError,
                    "failed to persist verifier attempt failure",
                ):
                    with claim_artifacts.claim_verifier_attempt_scope(
                        root,
                        attempt_kind="ledger_only",
                        attempt_request_id="same-process-refresh-2",
                        requirements_request_id=str(
                            cold["attempt_chain"]["source_locator"][
                                "requirements_request_id"
                            ]
                        ),
                        reuse_generation_run_id="same-process-cold-1",
                        reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
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
                        raise RuntimeError("scope failed before publication")

            checkpoint = root / claim_artifacts.CLAIM_VERIFIER_ATTEMPT_CHECKPOINT
            self.assertTrue(checkpoint.is_file())
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertFalse(checkpoint.exists())
            self.assertEqual(
                loaded["generation_meta"]["run_id"],
                "same-process-cold-1",
            )
            self.assertEqual(
                loaded["attempt_cost_chain"]["tail_attempt_status"],
                "failed",
            )

    def test_failed_publication_records_actual_candidate_and_reuse_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = (
                "Auxiliary outputs can be configured by the user."
            )
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                run_id="candidate-accounting-request",
                no_ledger_baseline_cost=_baseline_cost(),
            )
            target = claim_ledger.b_track_authority_state([requirement], {})
            budget = LLMRequestBudget(max_calls=2, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=2,
                max_total_tokens=100000,
            )

            def verifier(_unit_id: str, groups: list[dict]) -> dict:
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, {"total_tokens": 7})
                group_id = str(groups[0]["coverage_group_id"])
                return {
                    "request_id": "candidate-accounting-verify-1",
                    "call_count": 1,
                    "failed_call_count": 0,
                    "tokens": 7,
                    "usage_complete": True,
                    "decisions": {
                        group_id: {
                            "covered": True,
                            "checks": {
                                name: True
                                for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                            },
                        }
                    },
                }

            with patch.object(
                claim_artifacts,
                "publish_shadow_generation",
                side_effect=RuntimeError("crash before publication"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash before publication"):
                    with claim_artifacts.claim_verifier_attempt_scope(
                        root,
                        attempt_kind="cold",
                        attempt_request_id="candidate-accounting-request",
                        requirements_request_id="candidate-accounting-request",
                        failure_context={
                            "catalog_build": catalog,
                            "target_generation_id": target["target_generation_id"],
                            "requirements_sha256": claim_artifacts.file_sha256(
                                root / "ai_requirements.jsonl"
                            ),
                            "verifier_runtime": runtime,
                            "baseline_cost": _baseline_cost(),
                            "verifier_budget": budget,
                            "candidate_group_count": 3,
                            "reused_group_count": 3,
                        },
                    ):
                        claim_ledger.publish_b_track_shadow(
                            root,
                            run_id="candidate-accounting-request",
                            route_mode="llm",
                            extraction_status="success",
                            catalog_build=catalog,
                            requirements=[requirement],
                            semantic_verifier=verifier,
                            reusable_groups=[{
                                "coverage_group_id": "not-a-current-group"
                            }],
                            baseline_cost=_baseline_cost(),
                            verifier_runtime=runtime,
                            verifier_budget=budget,
                        )

            event = claim_artifacts.read_claim_verifier_attempts(root)[0]
            metrics = event["attempt_metrics"]
            self.assertEqual(metrics["verifier_call_count"], 1)
            self.assertEqual(metrics["verifier_tokens"], 7)
            self.assertEqual(metrics["semantic_verifier_candidate_count"], 1)
            self.assertEqual(metrics["semantic_validation_reused_group_count"], 0)

    def test_live_verifier_checkpoint_blocks_authoritative_snapshot_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            cold = _publish(root, catalog, run_id="active-checkpoint-cold-1")
            requirement = _requirement(catalog)
            target = claim_ledger.b_track_authority_state([requirement], {})
            budget = LLMRequestBudget(max_calls=2, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=2,
                max_total_tokens=100000,
            )

            with self.assertRaisesRegex(RuntimeError, "stop active verifier"):
                with claim_artifacts.claim_verifier_attempt_scope(
                    root,
                    attempt_kind="ledger_only",
                    attempt_request_id="active-checkpoint-refresh-2",
                    requirements_request_id=str(
                        cold["attempt_chain"]["source_locator"][
                            "requirements_request_id"
                        ]
                    ),
                    reuse_generation_run_id="active-checkpoint-cold-1",
                    reuse_attempt_id=cold["attempt_chain"]["attempt_id"],
                    failure_context={
                        "catalog_build": catalog,
                        "target_generation_id": target["target_generation_id"],
                        "requirements_sha256": claim_artifacts.file_sha256(
                            root / "ai_requirements.jsonl"
                        ),
                        "verifier_runtime": runtime,
                        "baseline_cost": _baseline_cost(),
                        "verifier_budget": budget,
                        "reused_group_count": 0,
                    },
                ):
                    reservation = budget.reserve({"messages": [], "max_tokens": 1})
                    budget.commit(reservation, {"total_tokens": 7})
                    with self.assertRaisesRegex(
                        claim_artifacts.ClaimArtifactError,
                        "verifier attempt checkpoint is active",
                    ):
                        claim_artifacts.load_committed_shadow(root)
                    raise RuntimeError("stop active verifier")

            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(
                loaded["generation_meta"]["run_id"],
                "active-checkpoint-cold-1",
            )
            self.assertEqual(
                loaded["attempt_cost_chain"]["tail_attempt_status"],
                "failed",
            )
            cumulative = loaded["attempt_cost_chain"]["cumulative_metrics"]
            self.assertEqual(cumulative["verifier_call_count"], 1)
            self.assertEqual(cumulative["verifier_tokens"], 7)

    def test_concurrent_shadow_publishers_do_not_lose_attempt_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            shadow = _shadow(catalog)
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [_requirement(catalog)],
            )
            _write_current_requirements_meta(root)
            requirements_hash = claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            )
            errors: list[BaseException] = []

            def publish(run_id: str) -> None:
                try:
                    claim_artifacts.publish_shadow_generation(
                        root,
                        catalog,
                        shadow,
                        run_id=run_id,
                        requirements_sha256=requirements_hash,
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            threads = [
                threading.Thread(target=publish, args=(f"concurrent-{index}",))
                for index in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)

            self.assertEqual(errors, [])
            rows = claim_artifacts.read_claim_verifier_attempts(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["event_seq"] for row in rows], [1, 2])
            self.assertEqual(rows[1]["previous_event_hash"], rows[0]["event_hash"])
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(
                loaded["generation_meta"]["attempt_chain"]["ledger_prefix_count"],
                2,
            )

    def test_old_target_prompt_lineage_marks_committed_shadow_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [_requirement(catalog)]
            )
            metadata = ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
            )
            metadata["producer_lineage"]["extract_prompt_version"] = "ai-extract-v21"
            claim_artifacts.atomic_write_json(root / "ai_requirements.meta.json", metadata)
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                _shadow(catalog),
                run_id="old-target-prompt",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )

            loaded = claim_artifacts.load_committed_shadow(root)

            self.assertFalse(
                claim_artifacts.committed_shadow_versions_are_current(loaded)
            )

    def test_missing_target_producer_lineage_marks_committed_shadow_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [_requirement(catalog)]
            )
            claim_artifacts.atomic_write_json(root / "ai_requirements.meta.json", {
                "schema": "ai-requirements-final/v1",
                "input_fingerprint": "test-input",
            })
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                _shadow(catalog),
                run_id="missing-target-lineage",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )

            loaded = claim_artifacts.load_committed_shadow(root)

            self.assertFalse(
                claim_artifacts.committed_shadow_versions_are_current(loaded)
            )

    def test_missing_target_metadata_marks_committed_shadow_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [_requirement(catalog)]
            )
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                _shadow(catalog),
                run_id="missing-target-metadata",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )

            loaded = claim_artifacts.load_committed_shadow(root)

            self.assertIsNone(loaded["requirements_meta"])
            self.assertFalse(
                claim_artifacts.committed_shadow_versions_are_current(loaded)
            )

    def test_changed_live_target_metadata_does_not_invalidate_committed_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            metadata = json.loads(
                (root / "ai_requirements.meta.json").read_text(encoding="utf-8")
            )
            metadata["producer_lineage"]["extract_prompt_version"] = "ai-extract-v21"
            claim_artifacts.atomic_write_json(root / "ai_requirements.meta.json", metadata)

            loaded = claim_artifacts.load_committed_claim_base(root)

            self.assertIsNone(loaded["requirements_meta"])
            self.assertTrue(claim_artifacts.committed_base_versions_are_current(loaded))

    def test_tampered_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            with (root / claim_artifacts.CLAIM_LEDGER).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"claim_id": "tampered"}) + "\n")
            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_artifacts.load_committed_shadow(root)

    def test_changed_live_target_requirements_do_not_invalidate_committed_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [_requirement(catalog)])
            _write_current_requirements_meta(root)
            requirements_hash = claim_artifacts.file_sha256(root / "ai_requirements.jsonl")
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                _shadow(catalog),
                run_id="run-1",
                requirements_sha256=requirements_hash,
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [{"id": "R2"}])
            loaded = claim_artifacts.load_committed_claim_base(root)

            self.assertEqual(loaded["requirements"], [])
            self.assertTrue(claim_artifacts.committed_base_versions_are_current(loaded))

    def test_changed_review_authority_does_not_invalidate_committed_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [requirement])
            _write_current_requirements_meta(root)
            requirements_hash = claim_artifacts.file_sha256(root / "ai_requirements.jsonl")
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                claim_ledger.build_shadow_ledger(catalog, [requirement]),
                run_id="run-1",
                requirements_sha256=requirements_hash,
            )
            claim_artifacts.atomic_write_jsonl(root / "ai_review_states.jsonl", [{
                "ai_req_id": "AIR-1",
                "status": "rejected",
                "source_fingerprint": claim_ledger.target_source_fingerprint(requirement),
                "review_subject_fingerprint": claim_ledger.target_fingerprint(requirement),
            }])
            loaded = claim_artifacts.load_committed_claim_base(root)

            self.assertEqual(loaded["ledger"], claim_ledger.build_shadow_ledger(
                catalog,
                [requirement],
            )["ledger"])
            self.assertTrue(claim_artifacts.committed_base_versions_are_current(loaded))

    def test_changed_source_artifact_invalidates_committed_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(root / "blocks.jsonl", [{"block_id": "B1"}])
            _publish(root, catalog)
            claim_artifacts.atomic_write_jsonl(root / "blocks.jsonl", [{"block_id": "B2"}])
            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_artifacts.load_committed_shadow(root)

    def test_ledger_version_change_only_marks_shadow_version_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            loaded = claim_artifacts.load_committed_shadow(root)
            with patch.object(claim_ledger, "CLAIM_REDUCER_VERSION", "claim-reducer-vNEXT"):
                self.assertFalse(claim_artifacts.committed_shadow_versions_are_current(loaded))

    def test_environment_managed_verifier_policy_change_marks_only_shadow_stale(self) -> None:
        config = LLMClientConfig(
            base_url="http://example.test", model="model-a", max_tokens=6144,
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "RATOMIZER_CLAIM_SHADOW_VERIFY": "1",
            "RATOMIZER_CLAIM_SHADOW_VERIFY_ROUNDS": "1",
            "RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_CALLS": "4",
            "RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS": "100000",
        }, clear=False):
            root = Path(tmp)
            catalog = _catalog()
            budget = LLMRequestBudget(max_calls=4, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                config=config,
                policy_source="environment",
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=4,
                max_total_tokens=100000,
            )

            def verifier(_unit, _groups):
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, {"total_tokens": 1})
                return {}

            shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [_requirement(catalog)],
                semantic_verifier=verifier,
                verifier_runtime=runtime,
                verifier_budget=budget,
            )
            _publish(root, catalog, shadow)
            loaded = claim_artifacts.load_committed_shadow(root)
            with patch("ai_extract.config_for_route", return_value=config):
                self.assertTrue(claim_artifacts.committed_shadow_versions_are_current(loaded))
                with patch.dict(os.environ, {
                    "RATOMIZER_CLAIM_SHADOW_VERIFY_ROUNDS": "2",
                }, clear=False):
                    self.assertFalse(
                        claim_artifacts.committed_shadow_versions_are_current(loaded)
                    )
                    self.assertTrue(
                        claim_artifacts.committed_shadow_versions_are_current(
                            loaded,
                            require_environment_match=False,
                        )
                    )

    def test_operation_failure_metric_survives_publish_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = "Auxiliary outputs can be configured by the user."
            budget = LLMRequestBudget(max_calls=1, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=1,
                max_total_tokens=100000,
            )

            def verifier(_unit_id: str, _groups: list[dict]) -> dict:
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, {"total_tokens": 7})
                return {}

            shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [requirement],
                semantic_verifier=verifier,
                verifier_runtime=runtime,
                verifier_budget=budget,
            )
            self.assertEqual(shadow["metrics"]["verifier_operation_failure_count"], 1)
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [requirement]
            )
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                shadow,
                run_id="operation-failure",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(loaded["metrics"]["verifier_operation_failure_count"], 1)

    def test_environment_runtime_freshness_uses_extract_token_floor(self) -> None:
        low_config = LLMClientConfig(
            base_url="http://example.test", model="model-a", max_tokens=1024,
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "RATOMIZER_CLAIM_SHADOW_VERIFY": "1",
            "RATOMIZER_CLAIM_SHADOW_VERIFY_ROUNDS": "1",
            "RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_CALLS": "4",
            "RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS": "100000",
        }, clear=False):
            root = Path(tmp)
            catalog = _catalog()
            budget = LLMRequestBudget(max_calls=4, max_tokens=100000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                config=LLMClientConfig(
                    base_url=low_config.base_url,
                    model=low_config.model,
                    max_tokens=6144,
                ),
                policy_source="environment",
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=4,
                max_total_tokens=100000,
            )

            def verifier(_unit, _groups):
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, {"total_tokens": 1})
                return {}

            shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [_requirement(catalog)],
                semantic_verifier=verifier,
                verifier_runtime=runtime,
                verifier_budget=budget,
            )
            _publish(root, catalog, shadow)
            loaded = claim_artifacts.load_committed_shadow(root)

            with patch("ai_extract.config_for_route", return_value=low_config):
                self.assertTrue(
                    claim_artifacts.committed_shadow_versions_are_current(loaded)
                )

    def test_missing_commit_meta_is_not_treated_as_a_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_artifacts.atomic_write_jsonl(root / claim_artifacts.CLAIM_LEDGER, [{"claim_id": "C"}])
            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_artifacts.load_committed_shadow(root)

    def test_windows_permission_error_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.json"
            real_replace = os.replace
            calls = 0

            def flaky_replace(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError("reader lock")
                real_replace(source, destination)

            with patch("claim_artifacts.os.replace", side_effect=flaky_replace):
                claim_artifacts.atomic_write_json(target, {"ok": True})
            self.assertGreaterEqual(calls, 2)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})

    def test_directory_orchestrator_binds_final_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.publish_catalog_probe(root, catalog)
            requirement = {
                "ai_req_id": "AIR-1",
                "title": "Auxiliary outputs",
                "description": catalog["catalog"][0]["text"].strip(),
                "source_quote": catalog["catalog"][0]["text"].strip(),
                "source_block_ids": ["B1"],
                "sub_items": [],
                "acceptance_criteria": [],
            }
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [requirement])
            result = claim_ledger.publish_b_track_shadow(
                root,
                run_id="run-2",
                route_mode="openai_compatible",
                extraction_status="success",
                catalog_build=catalog,
            )
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(result["generation_meta"]["requirements_sha256"],
                             claim_artifacts.file_sha256(root / "ai_requirements.jsonl"))
            self.assertEqual(loaded["ledger"][0]["resolution"], "covered")

    def test_publish_rejects_cross_file_reference_corruption_before_replacing_current(self) -> None:
        mutations = {
            "unknown claim": lambda shadow: shadow["groups"][0].update({"claim_id": "CLM-deadbeefdeadbeef"}),
            "claim hash mismatch": lambda shadow: shadow["groups"][0].update({
                "claim_hash": "sha256:" + "0" * 64,
            }),
            "unknown ledger group": lambda shadow: shadow["ledger"][0].update({
                "coverage_group_ids": ["CGR-deadbeefdeadbeef"],
            }),
            "target generation mismatch": lambda shadow: shadow["groups"][0]["edges"][0].update({
                "target_generation_id": "sha256:" + "1" * 64,
            }),
            "coverage group input hash": lambda shadow: shadow["groups"][0].update({
                "validation_input_hash": "sha256:" + "2" * 64,
            }),
            "coverage runtime fingerprint": lambda shadow: shadow["groups"][0].update({
                "verifier_runtime_fingerprint": "sha256:" + "3" * 64,
            }),
            "deterministic obligation check": lambda shadow: shadow["groups"][0][
                "validator_checks"
            ].update({"target_obligation_framing": False}),
            "coverage edge identity": lambda shadow: shadow["groups"][0]["edges"][0].update({
                "edge_id": "CED-deadbeefdeadbeef",
            }),
            "coverage source evidence": lambda shadow: shadow["groups"][0]["source_evidence"].update({
                "text": "unrelated source text",
            }),
            "target review status": lambda shadow: shadow["groups"][0]["edges"][0].update({
                "target_review_status": "rejected",
            }),
            "coverage proposal basis": lambda shadow: shadow["groups"][0].update({
                "proposal_basis": [],
            }),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                _publish(root, catalog, run_id="current")
                broken = json.loads(json.dumps(_shadow(catalog)))
                mutate(broken)
                with self.assertRaises(claim_artifacts.ClaimArtifactError):
                    _publish(root, catalog, broken, run_id="broken")
                loaded = claim_artifacts.load_committed_shadow(root)
                self.assertEqual(loaded["generation_meta"]["run_id"], "current")

    def test_publish_rejects_semantic_negative_graph_corruption(self) -> None:
        mutations = {
            "nested claim ID": lambda negative, _shadow: negative.update({
                "claim_id": "CLM-deadbeefdeadbeef",
            }),
            "nested claim hash": lambda negative, _shadow: negative.update({
                "claim_hash": "sha256:" + "0" * 64,
            }),
            "nested document generation": lambda negative, _shadow: negative.update({
                "document_generation_id": "sha256:" + "1" * 64,
            }),
            "nested catalog generation": lambda negative, _shadow: negative.update({
                "catalog_generation_id": "sha256:" + "2" * 64,
            }),
            "nested runtime fingerprint": lambda negative, _shadow: negative.update({
                "verifier_runtime_fingerprint": "sha256:" + "3" * 64,
            }),
            "validation input hash": lambda negative, _shadow: negative.update({
                "validation_input_hash": "sha256:" + "4" * 64,
            }),
            "stale validation evidence": lambda negative, _shadow: (
                negative["validation"]["evidence"][0].update({"text": "unrelated"})
            ),
            "non-independent request": lambda negative, _shadow: (
                negative["validation"].update({
                    "request_id": negative["proposal"]["request_id"],
                })
            ),
            "stale effective revision": lambda negative, _shadow: (
                negative["proposal"].update({"rationale": "tampered rationale"})
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                _publish_semantic_negative(root, catalog, run_id="current")
                broken = copy.deepcopy(_semantic_negative_shadow(catalog))
                negative = broken["ledger"][0]["semantic_negative"]
                mutate(negative, broken)
                with self.assertRaises(claim_artifacts.ClaimArtifactError):
                    _publish_semantic_negative(root, catalog, broken, run_id="broken")
                loaded = claim_artifacts.load_committed_shadow(root)
                self.assertEqual(loaded["generation_meta"]["run_id"], "current")

    def test_publish_rejects_runtime_with_non_replayable_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            broken = copy.deepcopy(_shadow(catalog))
            broken["meta"]["verifier_runtime"]["fingerprint"] = "sha256:" + "5" * 64
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [_requirement(catalog)])
            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_artifacts.publish_shadow_generation(
                    root,
                    catalog,
                    broken,
                    run_id="broken-runtime",
                    requirements_sha256=claim_artifacts.file_sha256(
                        root / "ai_requirements.jsonl"),
                )

    def test_publish_rejects_budget_meta_or_metric_tampering(self) -> None:
        mutations = {
            "budget attempts": lambda shadow: shadow["meta"]["verifier_budget"].update({
                "attempted_calls": 1,
            }),
            "budget termination": lambda shadow: shadow["meta"].update({
                "termination_reason": "budget_exhausted",
            }),
            "budget denial without termination": lambda shadow: (
                shadow["meta"]["verifier_budget"].update({
                    "denied": True,
                    "exhaustion_reason": "external_budget_exhausted",
                }),
                shadow["metrics"].update({
                    "verifier_budget_denied": True,
                    "verifier_budget_exhaustion_reason": "external_budget_exhausted",
                }),
            ),
            "metrics calls": lambda shadow: shadow["metrics"].update({
                "verifier_call_count": 1,
            }),
            "missing operation failures": lambda shadow: shadow["metrics"].pop(
                "verifier_operation_failure_count"
            ),
            "negative operation failures": lambda shadow: shadow["metrics"].update({
                "verifier_operation_failure_count": -1,
            }),
            "string operation failures": lambda shadow: shadow["metrics"].update({
                "verifier_operation_failure_count": "1",
            }),
            "operation failure with passing cost": lambda shadow: shadow["metrics"].update({
                "verifier_operation_failure_count": 1,
                "verifier_cost_gate_status": "pass",
                "phase0_cost_gate_met": True,
            }),
            "missing baseline lineage": lambda shadow: shadow["metrics"].pop(
                "no_ledger_baseline_lineage_match"
            ),
            "string baseline lineage": lambda shadow: shadow["metrics"].update({
                "no_ledger_baseline_lineage_match": "true",
            }),
            "mismatched lineage with passing cost": lambda shadow: shadow["metrics"].update({
                "no_ledger_baseline_lineage_match": False,
                "verifier_cost_gate_status": "pass",
                "phase0_cost_gate_met": True,
            }),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                broken = copy.deepcopy(_shadow(catalog))
                mutate(broken)
                claim_artifacts.atomic_write_jsonl(
                    root / "ai_requirements.jsonl", [_requirement(catalog)]
                )
                with self.assertRaises(claim_artifacts.ClaimArtifactError):
                    claim_artifacts.publish_shadow_generation(
                        root,
                        catalog,
                        broken,
                        run_id="broken-budget",
                        requirements_sha256=claim_artifacts.file_sha256(
                            root / "ai_requirements.jsonl"
                        ),
                    )

    def test_publish_binds_baseline_denominators_and_usage_to_requirements_meta(self) -> None:
        mutations = {
            "call count": (
                "no_ledger_baseline_call_count",
                1000,
            ),
            "failed call count": (
                "no_ledger_baseline_failed_call_count",
                999,
            ),
            "tokens": (
                "no_ledger_baseline_tokens",
                100000,
            ),
            "usage completeness": (
                "no_ledger_baseline_usage_complete",
                False,
            ),
        }
        for label, (field, value) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                requirement = _requirement(catalog)
                requirement["description"] = (
                    "Auxiliary outputs can be configured by the user."
                )
                claim_artifacts.atomic_write_jsonl(
                    root / "ai_requirements.jsonl",
                    [requirement],
                )
                ai_extract.write_ai_requirements_metadata(
                    root,
                    input_fingerprint="test-input",
                    no_ledger_baseline_cost=_baseline_cost(),
                )
                shadow, _ = _verifier_shadow(catalog)
                shadow["metrics"][field] = value

                with self.assertRaisesRegex(
                    claim_artifacts.ClaimArtifactError,
                    "baseline accounting differs",
                ):
                    claim_artifacts.publish_shadow_generation(
                        root,
                        catalog,
                        shadow,
                        run_id="tampered-baseline",
                        requirements_sha256=claim_artifacts.file_sha256(
                            root / "ai_requirements.jsonl"
                        ),
                    )

    def test_load_rejects_hash_consistent_baseline_denominator_tampering(self) -> None:
        for field, value in (
            ("no_ledger_baseline_call_count", 1000),
            ("no_ledger_baseline_failed_call_count", 999),
            ("no_ledger_baseline_tokens", 100000),
            ("no_ledger_baseline_usage_complete", False),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = _catalog()
                requirement = _requirement(catalog)
                requirement["description"] = (
                    "Auxiliary outputs can be configured by the user."
                )
                claim_artifacts.atomic_write_jsonl(
                    root / "ai_requirements.jsonl",
                    [requirement],
                )
                ai_extract.write_ai_requirements_metadata(
                    root,
                    input_fingerprint="test-input",
                    no_ledger_baseline_cost=_baseline_cost(),
                )
                shadow, _ = _verifier_shadow(catalog)
                claim_artifacts.publish_shadow_generation(
                    root,
                    catalog,
                    shadow,
                    run_id="valid-baseline",
                    requirements_sha256=claim_artifacts.file_sha256(
                        root / "ai_requirements.jsonl"
                    ),
                )

                metrics_path = root / claim_artifacts.CLAIM_SHADOW_METRICS
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
                metrics[field] = value
                claim_artifacts.atomic_write_json(metrics_path, metrics)

                generation_path = root / claim_artifacts.CLAIM_GENERATION_META
                generation = json.loads(generation_path.read_text(encoding="utf-8"))
                generation["shadow_metrics_sha256"] = claim_artifacts.file_sha256(
                    metrics_path
                )
                claim_artifacts.atomic_write_json(generation_path, generation)

                effective_path = root / claim_artifacts.CLAIM_EFFECTIVE_META
                effective = json.loads(effective_path.read_text(encoding="utf-8"))
                effective["generation_meta_sha256"] = claim_artifacts.file_sha256(
                    generation_path
                )
                claim_artifacts.atomic_write_json(effective_path, effective)

                with self.assertRaisesRegex(
                    claim_artifacts.ClaimArtifactError,
                    "baseline accounting differs",
                ):
                    claim_artifacts.load_committed_shadow(root)

    def test_lineage_mismatch_requires_incomplete_baseline_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            baseline = _baseline_cost()
            baseline.update({"lineage_match": False, "usage_complete": False})
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                no_ledger_baseline_cost=baseline,
            )
            shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [requirement],
                baseline_cost=baseline,
            )
            generation = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                shadow,
                run_id="lineage-mismatch",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertFalse(
                loaded["metrics"]["no_ledger_baseline_lineage_match"]
            )
            self.assertFalse(
                loaded["metrics"]["no_ledger_baseline_usage_complete"]
            )
            self.assertEqual(generation["attempt_chain"]["attempt_status"], "complete")

    def test_current_lineage_mismatch_may_downgrade_bound_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            metadata_baseline = _baseline_cost()
            current_baseline = {
                **metadata_baseline,
                "lineage_match": False,
                "usage_complete": False,
            }
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [requirement],
            )
            ai_extract.write_ai_requirements_metadata(
                root,
                input_fingerprint="test-input",
                no_ledger_baseline_cost=metadata_baseline,
            )
            shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [requirement],
                baseline_cost=current_baseline,
            )
            generation = claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                shadow,
                run_id="current-lineage-mismatch",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )

            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertFalse(loaded["metrics"]["no_ledger_baseline_lineage_match"])
            self.assertFalse(loaded["metrics"]["no_ledger_baseline_usage_complete"])
            self.assertEqual(generation["attempt_chain"]["attempt_status"], "complete")

    def test_cost_metrics_reject_completed_zero_token_verifier_calls(self) -> None:
        metrics = copy.deepcopy(_shadow(_catalog())["metrics"])
        metrics.update({
            "verifier_call_count": 1,
            "verifier_tokens": 0,
            "independent_verifier_call_count": 1,
            "independent_verifier_tokens": 0,
            "verifier_usage_complete": True,
            "no_ledger_baseline_lineage_match": True,
            "verifier_cost_gate_status": "pass",
            "phase0_cost_gate_met": True,
        })
        self.assertFalse(
            claim_artifacts._shadow_cost_metrics_are_well_formed(metrics)
        )

        metrics.update({
            "verifier_usage_complete": False,
            "verifier_cost_gate_status": "insufficient_data",
            "phase0_cost_gate_met": None,
        })
        self.assertTrue(
            claim_artifacts._shadow_cost_metrics_are_well_formed(metrics)
        )

    def test_reported_token_overrun_is_persisted_as_budget_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            requirement = _requirement(catalog)
            requirement["description"] = "Auxiliary outputs can be configured by the user."
            budget = LLMRequestBudget(max_calls=1, max_tokens=1000)
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=1,
                max_total_tokens=1000,
            )

            def verifier(_unit_id: str, groups: list[dict]) -> dict:
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, {"total_tokens": 2000})
                return {
                    "request_id": "verify-overrun",
                    "call_count": 1,
                    "failed_call_count": 0,
                    "tokens": 2000,
                    "usage_complete": True,
                    "decisions": {
                        groups[0]["coverage_group_id"]: {
                            "covered": True,
                            "checks": {
                                name: True
                                for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                            },
                        },
                    },
                }

            shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [requirement],
                semantic_verifier=verifier,
                verifier_runtime=runtime,
                verifier_budget=budget,
            )
            self.assertEqual(shadow["meta"]["resolution_status"], "resolved")
            self.assertEqual(shadow["meta"]["termination_reason"], "budget_exhausted")
            self.assertTrue(shadow["meta"]["verifier_budget"]["denied"])
            self.assertEqual(
                shadow["meta"]["verifier_budget"]["exhaustion_reason"],
                "reported_token_budget_exceeded",
            )

            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [requirement]
            )
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                shadow,
                run_id="reported-token-overrun",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(
                loaded["generation_meta"]["shadow_meta"]["termination_reason"],
                "budget_exhausted",
            )
            self.assertTrue(
                loaded["generation_meta"]["shadow_meta"]["verifier_budget"]["denied"]
            )

    def test_load_rejects_hash_consistent_semantic_negative_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish_semantic_negative(root, catalog)

            ledger = claim_artifacts._read_jsonl(
                root / claim_artifacts.CLAIM_LEDGER, label="ledger")
            ledger[0]["semantic_negative"]["claim_hash"] = "sha256:" + "6" * 64
            claim_artifacts.atomic_write_jsonl(root / claim_artifacts.CLAIM_LEDGER, ledger)
            claim_artifacts.atomic_write_jsonl(
                root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER, ledger)

            generation = json.loads(
                (root / claim_artifacts.CLAIM_GENERATION_META).read_text(encoding="utf-8"))
            effective = json.loads(
                (root / claim_artifacts.CLAIM_EFFECTIVE_META).read_text(encoding="utf-8"))
            generation["ledger_sha256"] = claim_artifacts.file_sha256(
                root / claim_artifacts.CLAIM_LEDGER)
            claim_artifacts.atomic_write_json(
                root / claim_artifacts.CLAIM_GENERATION_META, generation)
            effective.update({
                "generation_meta_sha256": claim_artifacts.file_sha256(
                    root / claim_artifacts.CLAIM_GENERATION_META),
                "base_ledger_sha256": generation["ledger_sha256"],
                "effective_ledger_sha256": claim_artifacts.file_sha256(
                    root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER),
            })
            claim_artifacts.atomic_write_json(
                root / claim_artifacts.CLAIM_EFFECTIVE_META, effective)

            with self.assertRaises(claim_artifacts.ClaimArtifactError) as raised:
                claim_artifacts.load_committed_shadow(root)
            self.assertIn("semantic negative", str(raised.exception))

    def test_source_alignment_versions_participate_in_shadow_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            loaded = claim_artifacts.load_committed_shadow(root)
            self.assertTrue(claim_artifacts.committed_shadow_versions_are_current(loaded))

            import source_spans

            for name in (
                "SOURCE_ALIGNMENT_VERSION",
                "SOURCE_TRANSFORMATION_POLICY_VERSION",
                "SOURCE_TRANSFORMATION_RULESET_VERSION",
            ):
                with self.subTest(name=name), patch.object(source_spans, name, "changed"):
                    self.assertFalse(
                        claim_artifacts.committed_shadow_versions_are_current(loaded)
                    )

    def test_b_track_publication_requires_requirements_hash_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [_requirement(catalog)])
            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_artifacts.publish_shadow_generation(
                    root, catalog, _shadow(catalog), run_id="unbound",
                )

    def test_publication_lock_serializes_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()

            def first() -> None:
                with claim_artifacts.claim_publication_lock(root):
                    first_entered.set()
                    release_first.wait(2)

            def second() -> None:
                first_entered.wait(2)
                with claim_artifacts.claim_publication_lock(root):
                    second_entered.set()

            one = threading.Thread(target=first)
            two = threading.Thread(target=second)
            one.start()
            two.start()
            self.assertTrue(first_entered.wait(1))
            time.sleep(0.05)
            self.assertFalse(second_entered.is_set())
            release_first.set()
            one.join(2)
            two.join(2)
            self.assertTrue(second_entered.is_set())


class EffectiveContractTamperTests(unittest.TestCase):
    """Forged revisions/metrics must be rejected at publish AND on read."""

    def _seed(self, root: Path) -> tuple[list[dict], list[dict], dict]:
        _publish(root, _catalog())
        ledger, queue, meta = _effective_candidate(root)
        claim_artifacts.publish_effective_snapshot(root, ledger, queue, meta=meta)
        return ledger, queue, meta

    @staticmethod
    def _forged(label: str) -> str:
        return claim_artifacts.hash_json("claim-effective-tamper/v1", label)

    def _rewrite_committed(
        self,
        root: Path,
        *,
        meta_tamper=None,
        row_tamper=None,
    ) -> None:
        meta = json.loads(
            (root / claim_artifacts.CLAIM_EFFECTIVE_META).read_text(encoding="utf-8")
        )
        rows = [
            json.loads(line)
            for line in (root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        if row_tamper is not None:
            rows = [row_tamper(dict(row)) for row in rows]
            claim_artifacts.atomic_write_jsonl(
                root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER, rows,
            )
            meta["effective_ledger_sha256"] = claim_artifacts.file_sha256(
                root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER
            )
        if meta_tamper is not None:
            meta = meta_tamper(meta)
        claim_artifacts._atomic_write_bytes(
            root / claim_artifacts.CLAIM_EFFECTIVE_META,
            claim_artifacts.canonical_json_value_bytes(meta),
        )

    def _rewrite_coherent_forgery(
        self,
        root: Path,
        rows: list[dict],
        meta: dict,
    ) -> None:
        from claim_effective_contract import (
            compute_claim_effective_revision,
            compute_document_effective_revision,
            compute_effective_authority_projection_hash,
            compute_effective_metrics,
            compute_effective_state_hash,
        )

        for row in rows:
            row["revision_inputs"]["effective_state_hash"] = (
                compute_effective_state_hash(row)
            )
            row["claim_effective_revision"] = compute_claim_effective_revision(
                row["revision_inputs"]
            )
        projection_hash = compute_effective_authority_projection_hash(rows)
        meta.update({
            "authority_projection_hash": projection_hash,
            "effective_metrics": compute_effective_metrics(rows),
        })
        meta["document_effective_revision"] = compute_document_effective_revision(
            base_generation_id=meta["base_generation_id"],
            last_event_seq=meta["last_event_seq"],
            event_prefix_sha256=meta["event_prefix_sha256"],
            target_set_hash=meta["target_set_hash"],
            requirement_review_state_hash=meta["requirement_review_state_hash"],
            authority_projection_hash=projection_hash,
        )
        claim_artifacts.atomic_write_jsonl(
            root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER, rows
        )
        meta["effective_ledger_sha256"] = claim_artifacts.file_sha256(
            root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER
        )
        claim_artifacts._atomic_write_bytes(
            root / claim_artifacts.CLAIM_EFFECTIVE_META,
            claim_artifacts.canonical_json_value_bytes(meta),
        )

    def test_publish_rejects_forged_document_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root)
            forged = {**meta, "document_effective_revision": self._forged("doc")}
            names = (
                claim_artifacts.CLAIM_EFFECTIVE_LEDGER,
                claim_artifacts.CLAIM_EFFECTIVE_META,
            )
            before = {name: (root / name).read_bytes() for name in names}
            queue_name = claim_artifacts.CLAIM_QUEUE_PROPOSALS
            queue_existed = (root / queue_name).exists()
            queue_before = (
                (root / queue_name).read_bytes() if queue_existed else None
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "event inputs|does not recompute",
            ):
                claim_artifacts.publish_effective_snapshot(
                    root, ledger, queue, meta=forged,
                )
            after = {name: (root / name).read_bytes() for name in names}
            self.assertEqual(after, before)
            self.assertEqual((root / queue_name).exists(), queue_existed)
            if queue_existed:
                self.assertEqual((root / queue_name).read_bytes(), queue_before)

    def test_publish_rejects_forged_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root)
            forged = {**meta, "effective_metrics": {"fixture": True}}
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "metrics do not recompute"
            ):
                claim_artifacts.publish_effective_snapshot(
                    root, ledger, queue, meta=forged,
                )

    def test_publish_rejects_forged_claim_revision_and_revision_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            ledger, queue, meta = _effective_candidate(root)
            forged_revision = [
                {**ledger[0], "claim_effective_revision": self._forged("claim")}
            ]
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "does not recompute"
            ):
                claim_artifacts.publish_effective_snapshot(
                    root, forged_revision, queue, meta=meta,
                )
            forged_inputs = copy.deepcopy(ledger)
            forged_inputs[0]["revision_inputs"]["base_claim_row_hash"] = (
                self._forged("base-row")
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "revision inputs"
            ):
                claim_artifacts.publish_effective_snapshot(
                    root, forged_inputs, queue, meta=meta,
                )

    def test_loader_rejects_tampered_document_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            self._rewrite_committed(
                root,
                meta_tamper=lambda meta: {
                    **meta,
                    "document_effective_revision": self._forged("doc"),
                },
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "does not recompute"
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_loader_rejects_tampered_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            self._rewrite_committed(
                root,
                meta_tamper=lambda meta: {
                    **meta,
                    "effective_metrics": {
                        **meta["effective_metrics"],
                        "covered_count": 0,
                    },
                },
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "metrics do not recompute"
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_loader_rejects_tampered_claim_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            self._rewrite_committed(
                root,
                row_tamper=lambda row: {
                    **row,
                    "claim_effective_revision": self._forged("claim"),
                },
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "does not recompute"
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_loader_rejects_tampered_revision_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)

            def tamper(row: dict) -> dict:
                row["revision_inputs"] = {
                    **row["revision_inputs"],
                    "ordered_relevant_event_hashes": [self._forged("event")],
                }
                return row

            self._rewrite_committed(root, row_tamper=tamper)
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "event inputs|does not recompute",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_loader_rejects_missing_revision_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            self._rewrite_committed(
                root,
                row_tamper=lambda row: {
                    key: value
                    for key, value in row.items() if key != "revision_inputs"
                },
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError, "revision_inputs"
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_publish_rejects_coherently_forged_authority_projection(self) -> None:
        from claim_effective_contract import (
            CLAIM_AUTHORITY_PROJECTION_VERSION,
            compute_claim_effective_revision,
            compute_document_effective_revision,
            compute_effective_authority_projection_hash,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            rows, queue, meta = _effective_candidate(root)
            forged_review = self._forged("linked-target-review")
            rows[0]["revision_inputs"]["linked_targets"][0][
                "target_review_revision"
            ] = forged_review
            inputs = rows[0]["revision_inputs"]
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
            rows[0]["claim_effective_revision"] = compute_claim_effective_revision(
                inputs
            )
            projection_hash = compute_effective_authority_projection_hash(rows)
            meta["authority_projection_hash"] = projection_hash
            meta["document_effective_revision"] = compute_document_effective_revision(
                base_generation_id=claim_artifacts.claim_base_generation_id(
                    claim_artifacts.load_committed_claim_base(root)["generation_meta"]
                ),
                last_event_seq=meta["last_event_seq"],
                event_prefix_sha256=meta["event_prefix_sha256"],
                target_set_hash=meta["target_set_hash"],
                requirement_review_state_hash=meta[
                    "requirement_review_state_hash"
                ],
                authority_projection_hash=projection_hash,
            )

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "authoritative reduction",
            ):
                claim_artifacts.publish_effective_snapshot(
                    root, rows, queue, meta=meta
                )

    def test_loader_rejects_coherent_no_event_invalid_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            rows = copy.deepcopy(
                claim_artifacts.load_committed_effective_snapshot(root)[
                    "effective_ledger"
                ]
            )
            meta = json.loads(
                (root / claim_artifacts.CLAIM_EFFECTIVE_META).read_text(
                    encoding="utf-8"
                )
            )
            group_ids = list(rows[0]["coverage_group_ids"])
            base = claim_artifacts.load_committed_claim_base(root)
            adjusted_groups = []
            for group in base["groups"]:
                adjusted = copy.deepcopy(group)
                adjusted["status"] = "invalid"
                adjusted["invalid_reason"] = "target_missing"
                adjusted_groups.append(adjusted)
            reduced = claim_ledger.reduce_claim(
                base["catalog"][0],
                validated_groups=[],
                validated_negative=base["ledger"][0].get("semantic_negative"),
                all_groups=adjusted_groups,
            )
            rows[0].update({
                field: reduced[field]
                for field in (
                    "resolution", "classification", "classification_status",
                    "exclusion_kind", "invalid_reasons",
                )
            })
            rows[0]["effective_facts"].update({
                "valid_group_ids": [],
                "invalid_group_reasons": {
                    group_id: "target_missing" for group_id in group_ids
                },
                "active_resolution_facts": [],
            })
            from claim_effective_contract import (
                compute_claim_effective_revision,
                compute_effective_state_hash,
            )

            rows[0]["revision_inputs"]["effective_state_hash"] = (
                compute_effective_state_hash(rows[0])
            )
            rows[0]["claim_effective_revision"] = (
                compute_claim_effective_revision(rows[0]["revision_inputs"])
            )
            authority = claim_review_actions._load_declared_authority(
                root, base["generation_meta"], readonly=True
            )
            forged_queue = claim_review_actions._build_queue(
                root, base, rows, authority
            )
            claim_artifacts.atomic_write_jsonl(
                root / claim_artifacts.CLAIM_QUEUE_PROPOSALS,
                forged_queue,
            )
            meta["queue_count"] = len(forged_queue)
            meta["queue_sha256"] = claim_artifacts.file_sha256(
                root / claim_artifacts.CLAIM_QUEUE_PROPOSALS
            )
            self._rewrite_coherent_forgery(root, rows, meta)

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "authoritative reduction",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_loader_rejects_coherent_no_event_semantic_exclusion(self) -> None:
        from claim_effective_contract import CLAIM_AUTHORITY_PROJECTION_VERSION
        from tests.test_claim_review_event_v2 import _source_exclusion_evidence

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            base = claim_artifacts.load_committed_claim_base(root)
            snapshot = claim_artifacts.load_committed_effective_snapshot(root)
            claim = base["catalog"][0]
            positive_fact = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base["ledger"][0],
                base["groups"],
            )["positive"][0]
            claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="excluded_non_normative",
                reason="fixture exclusion",
                evidence=_source_exclusion_evidence(claim),
                actor="test:forgery",
                expected_claim_effective_revision=(
                    snapshot["effective_ledger"][0]["claim_effective_revision"]
                ),
                supersedes_fact_hashes=[positive_fact],
            )
            excluded = claim_artifacts.load_committed_effective_snapshot(root)
            rows = copy.deepcopy(excluded["effective_ledger"])
            meta = copy.deepcopy(excluded["effective_meta"])
            (root / claim_artifacts.CLAIM_REVIEW_EVENTS).write_bytes(b"")
            inputs = rows[0]["revision_inputs"]
            inputs["ordered_relevant_event_hashes"] = []
            rows[0]["last_relevant_event_seq"] = 0
            inputs["authority_projection_hash"] = claim_artifacts.hash_json(
                CLAIM_AUTHORITY_PROJECTION_VERSION,
                {
                    "ordered_relevant_event_hashes": [],
                    "linked_targets": inputs["linked_targets"],
                    "expert_overlay": inputs["expert_overlay"],
                },
            )
            meta["last_event_seq"] = 0
            meta["event_prefix_sha256"] = "sha256:" + hashlib.sha256(b"").hexdigest()
            self._rewrite_coherent_forgery(root, rows, meta)

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "authoritative reduction",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_loader_rejects_coherent_forgery_after_authority_drift(self) -> None:
        from claim_effective_contract import CLAIM_AUTHORITY_PROJECTION_VERSION

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            snapshot = claim_artifacts.load_committed_effective_snapshot(root)
            rows = copy.deepcopy(snapshot["effective_ledger"])
            meta = copy.deepcopy(snapshot["effective_meta"])

            inputs = rows[0]["revision_inputs"]
            inputs["linked_targets"][0]["target_review_revision"] = self._forged(
                "coherent-authority-drift"
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
            self._rewrite_coherent_forgery(root, rows, meta)
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "authority changed",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)

    def test_current_snapshot_rejects_legacy_queue_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            _rows, queue, _meta = _effective_candidate(
                root, invalidate_groups=True
            )
            proposal = copy.deepcopy(queue[0])
            proposal["schema"] = "claim-queue-proposal/v1"
            proposal.pop("claim_hash")
            proposal.pop("execution_preconditions")
            proposal_hash = claim_artifacts.hash_json(
                "claim-queue-proposal-id/v1",
                {
                    "claim_id": proposal["claim_id"],
                    "claim_effective_revision": proposal[
                        "claim_effective_revision"
                    ],
                    "action": "needs_extraction",
                    "queue_version": proposal["queue_version"],
                },
            )
            proposal["proposal_id"] = (
                f"CQP-{claim_artifacts.digest_hex(proposal['claim_source_fingerprint'])[:8]}-"
                f"{claim_artifacts.digest_hex(proposal_hash)[:8]}"
            )
            claim_artifacts.atomic_write_jsonl(
                root / claim_artifacts.CLAIM_QUEUE_PROPOSALS,
                [proposal],
            )
            meta = json.loads(
                (root / claim_artifacts.CLAIM_EFFECTIVE_META).read_text(
                    encoding="utf-8"
                )
            )
            meta["queue_sha256"] = claim_artifacts.file_sha256(
                root / claim_artifacts.CLAIM_QUEUE_PROPOSALS
            )
            claim_artifacts._atomic_write_bytes(
                root / claim_artifacts.CLAIM_EFFECTIVE_META,
                claim_artifacts.canonical_json_value_bytes(meta),
            )

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "queue proposal schema",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)


if __name__ == "__main__":
    unittest.main()
