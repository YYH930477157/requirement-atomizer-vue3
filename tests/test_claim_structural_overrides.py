from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest import mock

import claim_artifacts
import claim_catalog
import claim_ledger
import claim_review_actions
import claim_structural_operations
import claim_structural_overrides
from llm_client import LLMClientConfig
from tests.test_claim_artifacts import _publish, _shadow
from tests.test_claim_catalog import _block


def _furniture_blocks() -> list[dict]:
    return [
        _block(
            f"F{page}",
            "CONFIDENTIAL",
            order=page,
            noise=True,
            page_number=page,
            pdf_regions=[{
                "page_number": page,
                "bbox": [10, 10, 100, 25],
                "page_width": 600,
                "page_height": 800,
            }],
        )
        for page in range(1, 4)
    ]


def _append(
    root: Path,
    build: dict,
    *,
    claim_index: int = 0,
    request_key: str = "override-request-1",
    expected_prefix: str | None = None,
) -> dict:
    claim = build["catalog"][claim_index]
    identity = claim_structural_overrides.current_structural_override_identity(root)
    return claim_structural_overrides.append_structural_override(
        root,
        claim_id=claim["claim_id"],
        claim_hash=claim["claim_hash"],
        document_generation_id=build["meta"]["document_generation_id"],
        catalog_generation_id=build["meta"]["catalog_generation_id"],
        prior_structural_reason="repeated_page_furniture",
        original_exclusion=claim["exclusion"],
        actor="expert:test",
        reason="verified content, not repeated page furniture",
        request_idempotency_key=request_key,
        expected_registry_prefix_sha256=(
            expected_prefix if expected_prefix is not None else identity["prefix_sha256"]
        ),
    )


class ClaimStructuralOverrideRegistryTests(unittest.TestCase):
    def test_registry_is_canonical_hash_chained_and_idempotent(self) -> None:
        build = claim_catalog.build_claim_catalog(_furniture_blocks(), [])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = _append(root, build)
            original = (root / claim_structural_overrides.CLAIM_STRUCTURAL_OVERRIDES).read_bytes()
            duplicate = _append(root, build)

            self.assertTrue(first["appended"])
            self.assertFalse(duplicate["appended"])
            self.assertEqual(
                (root / claim_structural_overrides.CLAIM_STRUCTURAL_OVERRIDES).read_bytes(),
                original,
            )
            snapshot = claim_structural_overrides.read_structural_overrides(root)
            self.assertEqual(snapshot.last_override_seq, 1)
            self.assertEqual(snapshot.rows[0]["registry_prefix_sha256"],
                             claim_artifacts.sha256_bytes(b""))
            self.assertEqual(snapshot.last_override_hash,
                             snapshot.rows[0]["override_hash"])
            self.assertEqual(snapshot.prefix_sha256,
                             claim_artifacts.sha256_bytes(original))

    def test_torn_or_schema_invalid_registry_is_rejected(self) -> None:
        build = claim_catalog.build_claim_catalog(_furniture_blocks(), [])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _append(root, build)
            path = root / claim_structural_overrides.CLAIM_STRUCTURAL_OVERRIDES
            valid = path.read_bytes()

            path.write_bytes(valid.removesuffix(b"\n"))
            with self.assertRaisesRegex(
                claim_structural_overrides.ClaimStructuralOverrideError,
                "torn tail",
            ):
                claim_structural_overrides.read_structural_overrides(root)

            row = json.loads(valid.decode("utf-8"))
            row["unexpected"] = True
            path.write_bytes(claim_artifacts.canonical_json_value_bytes(row) + b"\n")
            with self.assertRaises(claim_structural_overrides.ClaimStructuralOverrideError):
                claim_structural_overrides.read_structural_overrides(root)

    def test_prefix_cas_and_prohibited_reason_are_rejected(self) -> None:
        build = claim_catalog.build_claim_catalog(_furniture_blocks(), [])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty_prefix = claim_artifacts.sha256_bytes(b"")
            _append(root, build, expected_prefix=empty_prefix)
            with self.assertRaises(
                claim_structural_overrides.ClaimStructuralOverrideStale
            ):
                _append(
                    root,
                    build,
                    claim_index=1,
                    request_key="override-request-2",
                    expected_prefix=empty_prefix,
                )

            claim = build["catalog"][1]
            with self.assertRaisesRegex(
                claim_structural_overrides.ClaimStructuralOverrideError,
                "not runtime-overridable",
            ):
                claim_structural_overrides.append_structural_override(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    document_generation_id=build["meta"]["document_generation_id"],
                    catalog_generation_id=build["meta"]["catalog_generation_id"],
                    prior_structural_reason="empty",
                    original_exclusion={
                        "reason": "empty",
                        "rule_id": "catalog-empty",
                        "rule_version": claim_catalog.CLAIM_CATALOG_VERSION,
                        "evidence": {},
                    },
                    actor="expert:test",
                    reason="not empty",
                    request_idempotency_key="override-request-3",
                    expected_registry_prefix_sha256=(
                        claim_structural_overrides.current_structural_override_identity(root)[
                            "prefix_sha256"
                        ]
                    ),
                )


class ClaimStructuralOverrideCatalogTests(unittest.TestCase):
    def test_exact_override_changes_catalog_generation_and_eligibility(self) -> None:
        blocks = _furniture_blocks()
        before = claim_catalog.build_claim_catalog(blocks, [])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _append(root, before)
            registry = claim_structural_overrides.read_structural_overrides(root)
            after = claim_catalog.build_claim_catalog(
                blocks,
                [],
                structural_override_snapshot=registry,
            )

        self.assertEqual(
            before["meta"]["document_generation_id"],
            after["meta"]["document_generation_id"],
        )
        self.assertNotEqual(
            before["meta"]["catalog_generation_id"],
            after["meta"]["catalog_generation_id"],
        )
        self.assertEqual(after["meta"]["structural_override_applied_count"], 1)
        self.assertEqual(after["meta"]["structural_override_prefix_count"], 1)
        self.assertEqual(
            after["meta"]["structural_override_prefix_sha256"],
            registry.prefix_sha256,
        )
        self.assertEqual(after["catalog"][0]["eligibility"], "claim")
        self.assertIsNone(after["catalog"][0]["exclusion"])
        self.assertTrue(all(
            row["eligibility"] == "excluded" for row in after["catalog"][1:]
        ))

    def test_registry_advance_makes_old_snapshot_stale_until_base_rebuild(self) -> None:
        blocks = _furniture_blocks()
        before = claim_catalog.build_claim_catalog(blocks, [])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _publish(root, before, _shadow(before))
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="structural-override-before",
            )
            current = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertTrue(
                claim_review_actions.assess_effective_freshness(root, current)[
                    "effective_fresh"
                ]
            )

            claim = before["catalog"][0]
            registered = claim_structural_overrides.register_structural_override(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                expected_catalog_generation_id=before["meta"]["catalog_generation_id"],
                prior_structural_reason="repeated_page_furniture",
                actor="expert:test",
                reason="verified content, not page furniture",
                request_idempotency_key="registered-override-1",
            )
            self.assertTrue(registered["appended"])

            # Once structural authority advances, the old base is not a valid
            # current snapshot. Readers fail closed until the base is rebuilt.
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "base_migration_required",
            ):
                claim_artifacts.load_committed_effective_snapshot(root)

            rebuilt = claim_catalog.build_claim_catalog(
                blocks,
                [],
                structural_override_snapshot=(
                    claim_structural_overrides.read_structural_overrides(root)
                ),
            )
            _publish(root, rebuilt, _shadow(rebuilt), run_id="structural-rebuild-2")
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="structural-override-after",
            )
            fresh = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertTrue(
                claim_review_actions.assess_effective_freshness(root, fresh)[
                    "effective_fresh"
                ]
            )
            self.assertTrue(claim_artifacts.committed_base_versions_are_current(fresh))
            self.assertEqual(
                fresh["generation_meta"]["structural_override_prefix_sha256"],
                registered["registry"]["prefix_sha256"],
            )
            self.assertEqual(fresh["catalog"][0]["eligibility"], "claim")


class ClaimStructuralOverrideConfirmationTests(unittest.TestCase):
    def _published(self, root: Path) -> tuple[list[dict], dict, dict]:
        blocks = _furniture_blocks()
        build = claim_catalog.build_claim_catalog(blocks, [])
        _publish(root, build, _shadow(build))
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="structural-confirmation-initial",
        )
        snapshot = claim_artifacts.load_committed_effective_snapshot(root)
        return blocks, build, snapshot

    def test_failed_rebuild_keeps_audited_override_pending_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._published(root)
            claim = build["catalog"][0]
            effective = snapshot["effective_ledger"][0]
            revision = effective["claim_effective_revision"]
            call = {
                "claim_id": claim["claim_id"],
                "claim_hash": claim["claim_hash"],
                "expected_catalog_generation_id": build["meta"]["catalog_generation_id"],
                "expected_claim_effective_revision": revision,
                "prior_structural_reason": "repeated_page_furniture",
                "actor": "expert:test",
                "reason": "verified source content",
                "request_idempotency_key": "confirm-override-1",
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 2,
                "verifier_max_total_tokens": 4000,
            }
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=RuntimeError("base rebuild failed"),
            ) as refresh:
                result = claim_structural_overrides.confirm_structural_override(
                    root,
                    **call,
                )
                retry = claim_structural_overrides.confirm_structural_override(
                    root,
                    **call,
                )

            self.assertEqual(result["status"], "rebuild_pending")
            self.assertFalse(result["effective_fresh"])
            self.assertIn("base rebuild failed", result["error"])
            self.assertEqual(retry["status"], "rebuild_pending")
            self.assertEqual(refresh.call_count, 2)
            refresh.assert_called_with(
                root,
                route="openai_compatible",
                allow_llm=True,
                verifier_max_calls=2,
                verifier_max_total_tokens=4000,
                verifier_request_budget=mock.ANY,
                resolved_route_config=mock.ANY,
                shadow_built_hook=mock.ANY,
                extra_reusable_groups=None,
                extra_reusable_negatives=None,
                operation_lock_held=True,
            )
            registry = claim_structural_overrides.read_structural_overrides(root)
            events = claim_review_actions.read_claim_review_events(root).rows
            structural_events = [
                row for row in events
                if row.get("event_kind") == "structural_falsification"
            ]
            self.assertEqual(registry.last_override_seq, 1)
            self.assertEqual(len(structural_events), 1)
            self.assertEqual(
                structural_events[0]["override_hash"],
                registry.rows[0]["override_hash"],
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "base_migration_required",
            ):
                claim_artifacts.load_committed_effective_snapshot(root)

    def test_success_requires_a_fresh_rebuilt_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._published(root)
            claim = build["catalog"][0]
            revision = snapshot["effective_ledger"][0]["claim_effective_revision"]

            def rebuild(*_args, **_kwargs):
                rebuilt = claim_catalog.build_claim_catalog(
                    blocks,
                    [],
                    structural_override_snapshot=(
                        claim_structural_overrides.read_structural_overrides(root)
                    ),
                )
                _publish(root, rebuilt, _shadow(rebuilt), run_id="confirm-rebuild-2")
                claim_review_actions.fold_effective_ledger(
                    root,
                    actor_trigger="structural-confirmation-rebuilt",
                )
                return {"kind": "claim_shadow_refresh", "ledger_only": True}

            with patch("ai_extract.refresh_claim_shadow", side_effect=rebuild):
                result = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    expected_catalog_generation_id=build["meta"][
                        "catalog_generation_id"
                    ],
                    expected_claim_effective_revision=revision,
                    prior_structural_reason="repeated_page_furniture",
                    actor="expert:test",
                    reason="verified source content",
                    request_idempotency_key="confirm-override-success-1",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "rebuilt")
            self.assertTrue(result["effective_fresh"])
            current = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertEqual(current["catalog"][0]["eligibility"], "claim")
            self.assertNotEqual(
                current["generation_meta"]["catalog_generation_id"],
                build["meta"]["catalog_generation_id"],
            )

    def test_llm_authorization_requires_explicit_positive_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._published(root)
            claim = build["catalog"][0]
            with self.assertRaisesRegex(
                claim_structural_overrides.ClaimStructuralOverrideError,
                "positive verifier",
            ):
                claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    expected_catalog_generation_id=build["meta"][
                        "catalog_generation_id"
                    ],
                    expected_claim_effective_revision=(
                        snapshot["effective_ledger"][0]["claim_effective_revision"]
                    ),
                    prior_structural_reason="repeated_page_furniture",
                    actor="expert:test",
                    reason="verified source content",
                    request_idempotency_key="confirm-override-budget-1",
                    allow_llm=True,
                    route="openai_compatible",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=4000,
                )

    def test_route_preflight_binds_credential_and_resolved_config(self) -> None:
        config = LLMClientConfig(
            base_url="https://llm.example/v1",
            model="test-model",
            api_key_env="STRUCTURAL_TEST_KEY",
            max_tokens=100000,
        )
        with patch(
            "ai_extract.config_for_route", return_value=config,
        ), patch.dict(os.environ, {"STRUCTURAL_TEST_KEY": "first-key"}):
            first = claim_structural_overrides._route_preflight(
                "openai_compatible", True,
            )
            os.environ["STRUCTURAL_TEST_KEY"] = "rotated-key"
            rotated = claim_structural_overrides._route_preflight(
                "openai_compatible", True,
            )

        self.assertEqual(first["model"], "test-model")
        self.assertIsNotNone(first["config"])
        self.assertNotEqual(
            first["route_config_revision"],
            rotated["route_config_revision"],
        )


class StructuralOperationResumeTests(unittest.TestCase):
    def _seed(self, root: Path) -> tuple[list[dict], dict, dict]:
        blocks = _furniture_blocks()
        build = claim_catalog.build_claim_catalog(blocks, [])
        _publish(root, build, _shadow(build))
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="structural-resume-seed",
        )
        snapshot = claim_artifacts.load_committed_effective_snapshot(root)
        return blocks, build, snapshot

    def _call(self, build: dict, snapshot: dict, key: str) -> dict:
        claim = build["catalog"][0]
        return {
            "claim_id": claim["claim_id"],
            "claim_hash": claim["claim_hash"],
            "expected_catalog_generation_id": build["meta"][
                "catalog_generation_id"
            ],
            "expected_claim_effective_revision": snapshot["effective_ledger"][0][
                "claim_effective_revision"
            ],
            "prior_structural_reason": "repeated_page_furniture",
            "actor": "expert:test",
            "reason": "verified source content",
            "request_idempotency_key": key,
            "allow_llm": False,
            "route": "stub",
            "verifier_max_calls": 0,
            "verifier_max_total_tokens": 0,
        }

    @staticmethod
    def _rebuild(root: Path, blocks: list[dict]) -> dict:
        rebuilt = claim_catalog.build_claim_catalog(
            blocks,
            [],
            structural_override_snapshot=(
                claim_structural_overrides.read_structural_overrides(root)
            ),
        )
        _publish(root, rebuilt, _shadow(rebuilt), run_id="resume-rebuild")
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="structural-resume-rebuild",
        )
        return {"kind": "claim_shadow_refresh", "ledger_only": True}

    def _operation_rows(self, root: Path) -> list[dict]:
        from claim_structural_operations import (
            CLAIM_STRUCTURAL_OPERATIONS,
            read_operation_log,
        )

        self.assertTrue((root / CLAIM_STRUCTURAL_OPERATIONS).is_file())
        return read_operation_log(root).rows

    def _kinds(self, root: Path) -> list[str]:
        return [str(row["event_kind"]) for row in self._operation_rows(root)]

    def _assert_single_operation_closed(self, root: Path) -> None:
        kinds = self._kinds(root)
        self.assertEqual(kinds.count("operation_started"), 1)
        self.assertEqual(kinds.count("operation_succeeded"), 1)
        from claim_structural_operations import (
            derive_operation_states,
            read_operation_log,
        )

        states = derive_operation_states(read_operation_log(root).rows)
        self.assertEqual(len(states), 1)
        state = next(iter(states.values()))
        self.assertEqual(state["lifecycle"], "succeeded")

    def test_crash_at_registry_resume_completes_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-registry")
            with patch(
                "claim_structural_overrides.register_structural_override",
                side_effect=RuntimeError("crash at registry"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash at registry"):
                    claim_structural_overrides.confirm_structural_override(
                        root, **call,
                    )
            self.assertEqual(self._kinds(root), ["operation_started"])

            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks
                ),
            ):
                result = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash=call["claim_hash"],
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=result_operation_id(root, call),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "rebuilt")
            self._assert_single_operation_closed(root)

    def test_crash_at_audit_resume_skips_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-audit")
            with patch(
                "claim_review_actions.append_claim_review_events",
                side_effect=RuntimeError("crash at audit"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash at audit"):
                    claim_structural_overrides.confirm_structural_override(
                        root, **call,
                    )
            self.assertEqual(
                self._kinds(root),
                ["operation_started", "override_registered"],
            )
            registry_bytes = (
                root / claim_structural_overrides.CLAIM_STRUCTURAL_OVERRIDES
            ).read_bytes()

            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks
                ),
            ) as refresh:
                result = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=result_operation_id(root, call),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(refresh.call_count, 1)
            self.assertEqual(
                (
                    root / claim_structural_overrides.CLAIM_STRUCTURAL_OVERRIDES
                ).read_bytes(),
                registry_bytes,
            )
            self._assert_single_operation_closed(root)

    def test_crash_after_paid_call_resume_reuses_verifier_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = {
                **self._call(build, snapshot, "resume-paid"),
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 2,
                "verifier_max_total_tokens": 4000,
            }
            checkpoint_groups: list[dict] = []
            calls: list[dict] = []

            def crashy_refresh(root_dir, **kwargs):
                calls.append(kwargs)
                budget = kwargs["verifier_request_budget"]
                reservation = budget.reserve({"messages": [], "max_tokens": 1})
                budget.commit(reservation, {"total_tokens": 7})
                rebuilt_catalog = claim_catalog.build_claim_catalog(
                    blocks,
                    [],
                    structural_override_snapshot=(
                        claim_structural_overrides.read_structural_overrides(root)
                    ),
                )
                checkpoint_shadow = _shadow(rebuilt_catalog)
                paid_group = checkpoint_shadow["groups"][0]
                paid_group.update({
                    "status": "validated",
                    "validator_request_id": "verify-paid-1",
                    "validator_checks": {
                        name: True
                        for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                    },
                    "validator_reason": "independently entailed",
                    "validation_source": {
                        "generation_run_id": "structural-paid-test",
                        "request_id": "verify-paid-1",
                    },
                })
                checkpoint_groups[:] = [
                    claim_structural_overrides._minimal_reusable_group(paid_group)
                ]
                hook = kwargs.get("shadow_built_hook")
                if hook is not None:
                    hook(checkpoint_shadow)
                raise RuntimeError("crash after paid call")

            with patch(
                "ai_extract.refresh_claim_shadow", side_effect=crashy_refresh,
            ):
                pending = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
            self.assertEqual(pending["status"], "rebuild_pending")
            operation_id = pending["operation_id"]
            self.assertEqual(
                self._kinds(root),
                [
                    "operation_started",
                    "override_registered",
                    "audit_appended",
                    "budget_checkpoint",
                    "budget_checkpoint",
                    "verifier_checkpoint",
                    "operation_failed",
                ],
            )

            def successful_refresh(root_dir, **kwargs):
                calls.append(kwargs)
                return self._rebuild(root_dir, blocks)

            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=successful_refresh,
            ):
                result = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=operation_id,
                )
            self.assertTrue(result["ok"])
            # The resume restores the original paid identity and reuses the
            # checkpointed decisions instead of re-billing the verifier.
            resumed = calls[-1]
            self.assertEqual(resumed["allow_llm"], True)
            self.assertEqual(resumed["verifier_max_calls"], 2)
            self.assertEqual(resumed["verifier_max_total_tokens"], 4000)
            self.assertEqual(resumed["extra_reusable_groups"], checkpoint_groups)
            self._assert_single_operation_closed(root)

    def test_prepublication_rebuild_errors_resume_deterministically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            for label, crash in (
                ("base publication", RuntimeError("crash at base publication")),
                ("effective fold", RuntimeError("crash at effective fold")),
            ):
                with self.subTest(crash_point=label):
                    key = f"resume-{label.replace(' ', '-')}"
                    call = self._call(build, snapshot, key)
                    fresh_root = root / label
                    fresh_root.mkdir()
                    blocks2, build2, snapshot2 = self._seed(fresh_root)
                    call = self._call(build2, snapshot2, key)
                    # This probe covers an exception raised by refresh before it has
                    # durably published anything. The separate test below exercises
                    # the materially different post-publication crash window.
                    with patch(
                        "ai_extract.refresh_claim_shadow",
                        side_effect=crash,
                    ):
                        pending = (
                            claim_structural_overrides
                            .confirm_structural_override(fresh_root, **call)
                        )
                    self.assertEqual(pending["status"], "rebuild_pending")
                    operation_id = pending["operation_id"]
                    with patch(
                        "ai_extract.refresh_claim_shadow",
                        side_effect=lambda root_dir, **_kwargs: self._rebuild(
                            root_dir, blocks2
                        ),
                    ):
                        result = (
                            claim_structural_overrides
                            .confirm_structural_override(
                                fresh_root,
                                claim_id=call["claim_id"],
                                claim_hash="",
                                expected_catalog_generation_id="",
                                expected_claim_effective_revision="",
                                prior_structural_reason="",
                                actor="",
                                reason="",
                                request_idempotency_key="",
                                allow_llm=False,
                                route="stub",
                                verifier_max_calls=0,
                                verifier_max_total_tokens=0,
                                operation_id=operation_id,
                            )
                        )
                    self.assertTrue(result["ok"], label)
                    kinds = [
                        str(row["event_kind"])
                        for row in self._operation_rows(fresh_root)
                    ]
                    self.assertEqual(kinds.count("operation_started"), 1, label)
                    self.assertEqual(
                        kinds.count("operation_succeeded"), 1, label,
                    )

    def test_crash_after_durable_publication_recovers_before_stale_preflight(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-durable-publication")

            def publish_then_crash(root_dir, **_kwargs):
                self._rebuild(root_dir, blocks)
                raise RuntimeError("crash after durable publication")

            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=publish_then_crash,
            ):
                pending = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
            self.assertEqual(pending["status"], "rebuild_pending")

            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=AssertionError(
                    "durable publication recovery must not rebuild through the LLM path"
                ),
            ) as refresh:
                recovered = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=pending["operation_id"],
                )

            self.assertTrue(recovered["ok"])
            self.assertTrue(recovered["idempotent_replay"])
            refresh.assert_not_called()
            kinds = [
                str(row["event_kind"])
                for row in self._operation_rows(root)
            ]
            self.assertEqual(kinds.count("base_rebuild_published"), 1)
            self.assertEqual(kinds.count("effective_folded"), 1)
            self.assertEqual(kinds.count("operation_succeeded"), 1)
            self.assertNotIn("operation_aborted_stale", kinds)

    def test_process_exit_after_base_commit_recovers_without_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-os-exit-publication")
            child_input = root / "structural-crash-input.json"
            claim_artifacts.atomic_write_json(
                child_input,
                {"blocks": blocks, "call": call},
            )
            script = r'''
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import claim_catalog
import claim_structural_overrides
from tests.test_claim_artifacts import _publish, _shadow

root = Path(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
blocks = payload["blocks"]

def publish_then_exit(root_dir, **_kwargs):
    rebuilt = claim_catalog.build_claim_catalog(
        blocks,
        [],
        structural_override_snapshot=(
            claim_structural_overrides.read_structural_overrides(root)
        ),
    )
    _publish(root, rebuilt, _shadow(rebuilt), run_id="os-exit-base-commit")
    os._exit(91)

with patch("ai_extract.refresh_claim_shadow", side_effect=publish_then_exit):
    claim_structural_overrides.confirm_structural_override(
        root, **payload["call"],
    )
raise SystemExit(99)
'''
            completed = subprocess.run(
                [sys.executable, "-c", script, str(root), str(child_input)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                91,
                completed.stdout + completed.stderr,
            )
            crashed_kinds = self._kinds(root)
            self.assertNotIn("operation_failed", crashed_kinds)
            self.assertNotIn("base_rebuild_published", crashed_kinds)
            # The operation lease deliberately has a short initialization grace so a
            # second process cannot steal a just-created, not-yet-populated lock. Age
            # this dead child's complete lease past that grace and verify PID-based
            # reclamation as part of the recovery path.
            operation_lock = root / "ai_extraction_operation.lock"
            self.assertTrue(operation_lock.is_file())
            old = operation_lock.stat().st_mtime - 3
            os.utime(operation_lock, (old, old))

            operation_id = claim_structural_operations.make_operation_id(
                call["request_idempotency_key"]
            )
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=AssertionError(
                    "durable base recovery must not run extraction again"
                ),
            ) as refresh:
                recovered = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=operation_id,
                )

            self.assertTrue(recovered["ok"])
            self.assertTrue(recovered["idempotent_replay"])
            refresh.assert_not_called()
            kinds = self._kinds(root)
            self.assertEqual(kinds.count("operation_started"), 1)
            self.assertEqual(kinds.count("base_rebuild_published"), 1)
            self.assertEqual(kinds.count("effective_folded"), 1)
            self.assertEqual(kinds.count("operation_succeeded"), 1)
            self.assertNotIn("operation_failed", kinds)

    def test_folded_replay_keeps_transient_artifact_failure_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-transient-effective-read")
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks,
                ),
            ):
                completed = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )

            operation_id = completed["operation_id"]
            operation_path = (
                root / claim_structural_operations.CLAIM_STRUCTURAL_OPERATIONS
            )
            rows = claim_structural_operations.read_operation_log(root).rows
            self.assertEqual(rows[-1]["event_kind"], "operation_succeeded")
            claim_artifacts.atomic_write_jsonl(operation_path, rows[:-1])
            before = operation_path.read_bytes()

            with patch(
                "claim_artifacts.load_committed_effective_snapshot_readonly",
                side_effect=PermissionError("snapshot is temporarily locked"),
            ):
                with self.assertRaisesRegex(PermissionError, "temporarily locked"):
                    claim_structural_overrides.confirm_structural_override(
                        root,
                        claim_id=call["claim_id"],
                        claim_hash="",
                        expected_catalog_generation_id="",
                        expected_claim_effective_revision="",
                        prior_structural_reason="",
                        actor="",
                        reason="",
                        request_idempotency_key="",
                        allow_llm=False,
                        route="stub",
                        verifier_max_calls=0,
                        verifier_max_total_tokens=0,
                        operation_id=operation_id,
                    )
            self.assertEqual(operation_path.read_bytes(), before)
            state = claim_structural_operations.derive_operation_states(
                claim_structural_operations.read_operation_log(root).rows
            )[operation_id]
            self.assertFalse(state["closed"])

            recovered = claim_structural_overrides.confirm_structural_override(
                root,
                claim_id=call["claim_id"],
                claim_hash="",
                expected_catalog_generation_id="",
                expected_claim_effective_revision="",
                prior_structural_reason="",
                actor="",
                reason="",
                request_idempotency_key="",
                allow_llm=False,
                route="stub",
                verifier_max_calls=0,
                verifier_max_total_tokens=0,
                operation_id=operation_id,
            )
            self.assertTrue(recovered["ok"])
            self.assertEqual(self._kinds(root).count("operation_succeeded"), 1)

    def test_folded_replay_closes_only_confirmed_authority_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-confirmed-effective-drift")
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks,
                ),
            ):
                completed = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
            operation_id = completed["operation_id"]
            operation_path = (
                root / claim_structural_operations.CLAIM_STRUCTURAL_OPERATIONS
            )
            rows = claim_structural_operations.read_operation_log(root).rows
            claim_artifacts.atomic_write_jsonl(operation_path, rows[:-1])

            with patch(
                "claim_structural_overrides._effective_binding",
                side_effect=claim_structural_overrides.ClaimStructuralOverrideStale(
                    "effective claim no longer belongs to this operation"
                ),
            ):
                with self.assertRaisesRegex(
                    claim_structural_overrides.ClaimStructuralOverrideStale,
                    "no longer belongs",
                ):
                    claim_structural_overrides.confirm_structural_override(
                        root,
                        claim_id=call["claim_id"],
                        claim_hash="",
                        expected_catalog_generation_id="",
                        expected_claim_effective_revision="",
                        prior_structural_reason="",
                        actor="",
                        reason="",
                        request_idempotency_key="",
                        allow_llm=False,
                        route="stub",
                        verifier_max_calls=0,
                        verifier_max_total_tokens=0,
                        operation_id=operation_id,
                    )
            state = claim_structural_operations.derive_operation_states(
                claim_structural_operations.read_operation_log(root).rows
            )[operation_id]
            self.assertTrue(state["closed"])
            self.assertEqual(
                state["lifecycle"], "recovery_failed_post_publication",
            )

    def test_succeeded_operation_replays_without_rework(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-succeeded")
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks
                ),
            ) as refresh:
                first = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
            self.assertTrue(first["ok"])
            replay = claim_structural_overrides.confirm_structural_override(
                root,
                claim_id=call["claim_id"],
                claim_hash="",
                expected_catalog_generation_id="",
                expected_claim_effective_revision="",
                prior_structural_reason="",
                actor="",
                reason="",
                request_idempotency_key="",
                allow_llm=False,
                route="stub",
                verifier_max_calls=0,
                verifier_max_total_tokens=0,
                operation_id=first["operation_id"],
            )
            self.assertTrue(replay["ok"])
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(refresh.call_count, 1)
            self._assert_single_operation_closed(root)

    def test_succeeded_replay_treats_transient_artifact_failure_as_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "replay-transient-artifact-read")
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks,
                ),
            ):
                completed = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
            operation_path = (
                root / claim_structural_operations.CLAIM_STRUCTURAL_OPERATIONS
            )
            before = operation_path.read_bytes()

            with patch(
                "claim_artifacts.load_committed_effective_snapshot_readonly",
                side_effect=PermissionError("snapshot is temporarily locked"),
            ):
                with self.assertRaisesRegex(PermissionError, "temporarily locked"):
                    claim_structural_overrides.confirm_structural_override(
                        root,
                        claim_id=call["claim_id"],
                        claim_hash="",
                        expected_catalog_generation_id="",
                        expected_claim_effective_revision="",
                        prior_structural_reason="",
                        actor="",
                        reason="",
                        request_idempotency_key="",
                        allow_llm=False,
                        route="stub",
                        verifier_max_calls=0,
                        verifier_max_total_tokens=0,
                        operation_id=completed["operation_id"],
                    )
            self.assertEqual(operation_path.read_bytes(), before)

            replay = claim_structural_overrides.confirm_structural_override(
                root,
                claim_id=call["claim_id"],
                claim_hash="",
                expected_catalog_generation_id="",
                expected_claim_effective_revision="",
                prior_structural_reason="",
                actor="",
                reason="",
                request_idempotency_key="",
                allow_llm=False,
                route="stub",
                verifier_max_calls=0,
                verifier_max_total_tokens=0,
                operation_id=completed["operation_id"],
            )
            self.assertTrue(replay["ok"])
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(operation_path.read_bytes(), before)

    def test_stale_resume_records_terminal_abort(self) -> None:
        from claim_structural_operations import (
            derive_operation_states,
            read_operation_log,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "resume-stale-terminal")
            with patch(
                "claim_structural_overrides.register_structural_override",
                side_effect=RuntimeError("crash before authority write"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash before authority write",
                ):
                    claim_structural_overrides.confirm_structural_override(
                        root, **call,
                    )

            operation_id = result_operation_id(root, call)
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl", [],
            )
            with self.assertRaises(
                claim_structural_overrides.ClaimStructuralOverrideStale,
            ):
                claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=operation_id,
                )

            state = derive_operation_states(
                read_operation_log(root).rows,
            )[operation_id]
            self.assertTrue(state["closed"])
            self.assertEqual(state["lifecycle"], "aborted_stale")
            self.assertEqual(
                state["terminal"]["outcome"]["code"],
                "authority_changed",
            )

    def test_route_revision_change_aborts_before_any_paid_retry(self) -> None:
        from claim_structural_operations import (
            derive_operation_states,
            read_operation_log,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._seed(root)
            call = {
                **self._call(build, snapshot, "resume-route-change"),
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 2,
                "verifier_max_total_tokens": 4000,
            }
            first_route = {
                "route_config_revision": "sha256:" + "a" * 64,
                "model": "model-a",
                "config": object(),
            }
            with patch(
                "claim_structural_overrides._route_preflight",
                return_value=first_route,
            ), patch(
                "claim_structural_overrides.register_structural_override",
                side_effect=RuntimeError("crash before authority write"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash before authority write",
                ):
                    claim_structural_overrides.confirm_structural_override(
                        root, **call,
                    )

            operation_id = result_operation_id(root, call)
            changed_route = {
                "route_config_revision": "sha256:" + "b" * 64,
                "model": "model-b",
                "config": object(),
            }
            with patch(
                "claim_structural_overrides._route_preflight",
                return_value=changed_route,
            ), patch("ai_extract.refresh_claim_shadow") as refresh:
                with self.assertRaisesRegex(
                    claim_structural_overrides.ClaimStructuralOverrideStale,
                    "route configuration changed",
                ):
                    claim_structural_overrides.confirm_structural_override(
                        root,
                        claim_id=call["claim_id"],
                        claim_hash="",
                        expected_catalog_generation_id="",
                        expected_claim_effective_revision="",
                        prior_structural_reason="",
                        actor="",
                        reason="",
                        request_idempotency_key="",
                        allow_llm=False,
                        route="stub",
                        verifier_max_calls=0,
                        verifier_max_total_tokens=0,
                        operation_id=operation_id,
                    )

            refresh.assert_not_called()
            state = derive_operation_states(
                read_operation_log(root).rows,
            )[operation_id]
            self.assertTrue(state["closed"])
            self.assertEqual(state["lifecycle"], "aborted_stale")

    def test_stale_initial_preflight_never_creates_an_operation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "stale-before-start")
            call["expected_claim_effective_revision"] = "sha256:" + "f" * 64

            with self.assertRaises(
                claim_structural_overrides.ClaimStructuralOverrideStale
            ):
                claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )

            from claim_structural_operations import read_operation_log

            self.assertEqual(read_operation_log(root).rows, [])

    def test_concurrent_duplicate_enters_refresh_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "concurrent-one-executor")
            entered = threading.Event()
            release = threading.Event()
            results: list[dict] = []
            errors: list[BaseException] = []

            def rebuild(root_dir, **_kwargs):
                entered.set()
                release.wait(5)
                return self._rebuild(root_dir, blocks)

            def execute() -> None:
                try:
                    results.append(
                        claim_structural_overrides.confirm_structural_override(
                            root, **call,
                        )
                    )
                except BaseException as exc:  # pragma: no cover - assertion below
                    errors.append(exc)

            with patch(
                "ai_extract.refresh_claim_shadow", side_effect=rebuild,
            ) as refresh:
                first = threading.Thread(target=execute)
                second = threading.Thread(target=execute)
                first.start()
                self.assertTrue(entered.wait(3))
                second.start()
                release.set()
                first.join(10)
                second.join(10)

            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertTrue(all(result["ok"] for result in results))
            self.assertEqual(refresh.call_count, 1)
            self._assert_single_operation_closed(root)

    def test_reserved_paid_call_requires_reconfirmation_and_never_auto_retries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._seed(root)
            call = {
                **self._call(build, snapshot, "reserved-needs-reconfirm"),
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 2,
                "verifier_max_total_tokens": 100000,
            }

            def uncertain_remote(_root, **kwargs):
                budget = kwargs["verifier_request_budget"]
                budget.reserve({"messages": [], "max_tokens": 32})
                raise RuntimeError("process died after reserve")

            route_config = object()
            with patch(
                "claim_structural_overrides._route_preflight",
                return_value={
                    "route_config_revision": "sha256:" + "a" * 64,
                    "model": "test-model",
                    "config": route_config,
                },
            ), patch(
                "ai_extract.refresh_claim_shadow", side_effect=uncertain_remote,
            ) as refresh:
                result = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                retry = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=result["operation_id"],
                )

            self.assertEqual(result["status"], "needs_reconfirmation")
            self.assertTrue(result["needs_reconfirmation"])
            self.assertTrue(result["verifier_budget"]["unknown_remote_result"])
            self.assertEqual(retry["status"], "needs_reconfirmation")
            self.assertEqual(refresh.call_count, 1)
            self.assertIs(
                refresh.call_args.kwargs["resolved_route_config"],
                route_config,
            )

    def test_reconfirmed_unknown_call_then_local_failure_is_rebuild_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._seed(root)
            call = {
                **self._call(build, snapshot, "reconfirmed-local-failure"),
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 2,
                "verifier_max_total_tokens": 100000,
            }

            def uncertain_remote(_root, **kwargs):
                kwargs["verifier_request_budget"].reserve({
                    "messages": [], "max_tokens": 32,
                })
                raise RuntimeError("process died after reserve")

            refresh_attempts = 0

            def refresh_sequence(root_dir, **kwargs):
                nonlocal refresh_attempts
                refresh_attempts += 1
                if refresh_attempts == 1:
                    return uncertain_remote(root_dir, **kwargs)
                raise RuntimeError("local rebuild failed before another paid call")

            route_config = object()
            with patch(
                "claim_structural_overrides._route_preflight",
                return_value={
                    "route_config_revision": "sha256:" + "a" * 64,
                    "model": "test-model",
                    "config": route_config,
                },
            ), patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=refresh_sequence,
            ) as refresh:
                first = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                resumed = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=first["operation_id"],
                    reconfirm_paid_work=True,
                )

            self.assertEqual(first["status"], "needs_reconfirmation")
            self.assertEqual(resumed["status"], "rebuild_pending")
            self.assertFalse(resumed["needs_reconfirmation"])
            self.assertEqual(refresh.call_count, 2)
            state = claim_structural_operations.derive_operation_states(
                claim_structural_operations.read_operation_log(root).rows,
            )[first["operation_id"]]
            self.assertEqual(state["lifecycle"], "failed")

    def test_reconfirmed_operation_requires_confirmation_after_a_new_paid_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _blocks, build, snapshot = self._seed(root)
            call = {
                **self._call(build, snapshot, "reconfirmed-new-paid-attempt"),
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 2,
                "verifier_max_total_tokens": 100000,
            }

            def uncertain_remote(_root, **kwargs):
                kwargs["verifier_request_budget"].reserve({
                    "messages": [], "max_tokens": 32,
                })
                raise RuntimeError("process died after reserve")

            with patch(
                "claim_structural_overrides._route_preflight",
                return_value={
                    "route_config_revision": "sha256:" + "a" * 64,
                    "model": "test-model",
                    "config": object(),
                },
            ), patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=uncertain_remote,
            ) as refresh:
                first = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                resumed = claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=first["operation_id"],
                    reconfirm_paid_work=True,
                )

            self.assertEqual(first["status"], "needs_reconfirmation")
            self.assertEqual(resumed["status"], "needs_reconfirmation")
            self.assertTrue(resumed["needs_reconfirmation"])
            self.assertEqual(resumed["verifier_budget"]["attempted_calls"], 2)
            self.assertTrue(resumed["verifier_budget"]["unknown_remote_result"])
            self.assertEqual(refresh.call_count, 2)

    def test_succeeded_replay_fails_closed_and_retryable_when_effective_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "replay-missing-artifact")
            with patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=lambda root_dir, **_kwargs: self._rebuild(
                    root_dir, blocks,
                ),
            ):
                first = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
            (root / claim_artifacts.CLAIM_EFFECTIVE_META).unlink()

            # Missing artifacts are not evidence that the completed operation's
            # authority changed. Keep the closed operation immutable and surface a
            # recoverable I/O failure so maintenance/retry can restore the snapshot.
            with self.assertRaises(FileNotFoundError):
                claim_structural_overrides.confirm_structural_override(
                    root,
                    claim_id=call["claim_id"],
                    claim_hash="",
                    expected_catalog_generation_id="",
                    expected_claim_effective_revision="",
                    prior_structural_reason="",
                    actor="",
                    reason="",
                    request_idempotency_key="",
                    allow_llm=False,
                    route="stub",
                    verifier_max_calls=0,
                    verifier_max_total_tokens=0,
                    operation_id=first["operation_id"],
                )


class StructuralVerifierRetryPersistenceTests(unittest.TestCase):
    """Paid retry-then-success persists one durable verifier checkpoint."""

    def _seed(self, root: Path) -> tuple[list[dict], dict, dict]:
        blocks = _furniture_blocks()
        build = claim_catalog.build_claim_catalog(blocks, [])
        claim_artifacts.atomic_write_jsonl(root / "blocks.jsonl", blocks)
        requirement = {
            "ai_req_id": "AIR-1",
            "title": "Auxiliary outputs",
            "description": "辅助输出可由用户编程。",
            "source_quote": "CONFIDENTIAL",
            "source_block_ids": ["F1"],
            "sub_items": [],
            "acceptance_criteria": [],
        }
        claim_artifacts.atomic_write_jsonl(
            root / "ai_requirements.jsonl", [requirement],
        )
        import ai_extract

        ai_extract.write_ai_requirements_metadata(
            root,
            input_fingerprint=ai_extract.extraction_input_fingerprint(root),
        )
        shadow = claim_ledger.build_shadow_ledger(build, [requirement])
        claim_artifacts.publish_shadow_generation(
            root,
            build,
            shadow,
            run_id="paid-retry-seed",
            requirements_sha256=claim_artifacts.file_sha256(
                root / "ai_requirements.jsonl"
            ),
        )
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="paid-retry-seed",
        )
        snapshot = claim_artifacts.load_committed_effective_snapshot(root)
        return blocks, build, snapshot

    def _call(self, build: dict, snapshot: dict, key: str) -> dict:
        claim = build["catalog"][0]
        return {
            "claim_id": claim["claim_id"],
            "claim_hash": claim["claim_hash"],
            "expected_catalog_generation_id": build["meta"][
                "catalog_generation_id"
            ],
            "expected_claim_effective_revision": snapshot["effective_ledger"][0][
                "claim_effective_revision"
            ],
            "prior_structural_reason": "repeated_page_furniture",
            "actor": "expert:test",
            "reason": "verified source content",
            "request_idempotency_key": key,
            "allow_llm": True,
            "route": "openai_compatible",
            "verifier_max_calls": 4,
            "verifier_max_total_tokens": 40000,
        }

    @staticmethod
    def _config() -> LLMClientConfig:
        return LLMClientConfig(
            base_url="https://llm.example.invalid/v1",
            model="paid-retry-model",
            api_key_env="",
            max_tokens=4096,
            timeout_s=5.0,
            max_retries=0,
        )

    @staticmethod
    def _http_error(code: int, retry_after: str | None = None):
        import email.message
        import urllib.error

        headers = email.message.Message()
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        return urllib.error.HTTPError(
            "https://llm.example.invalid/v1/chat/completions",
            code,
            f"HTTP {code}",
            headers,
            None,
        )

    @staticmethod
    def _success_response(get_body):
        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                body = get_body()
                return json.dumps(body, ensure_ascii=False).encode("utf-8")

        return _Response()

    @staticmethod
    def _verifier_payload(request, claim_checks) -> dict:
        import re as _re

        raw = request.data.decode("utf-8") if isinstance(
            request.data, bytes
        ) else str(request.data)
        match = _re.search(r"CGR-[0-9a-f]{16}", raw)
        group_id = match.group(0) if match else ""
        content = json.dumps({
            "decisions": [{
                "coverage_group_id": group_id,
                "covered": True,
                "checks": claim_checks,
                "reason": "normative coverage confirmed after retry",
            }],
        }, ensure_ascii=False)
        return {
            "choices": [{
                "message": {"content": content, "finish_reason": "stop"},
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    def _paid_refresh(self, blocks: list[dict]):
        """Refresh double: real HTTP verifier + budget accounting, self-consistent shadow.

        The semantic verifier closure drives a real ``chat_json_with_meta`` call so
        budget accounting records the HTTP retry sequence (429→200 inside one call,
        or an all-failed 500 across a reconfirmation). ``build_shadow_ledger`` keeps
        the validated coverage group and its base ledger row self-consistent, so
        ``persist_decision`` can durably checkpoint a recovered decision without
        re-billing and without tripping the "row differs from reduction" guard.
        """
        import ai_extract
        from llm_client import LLMConnectionError, LLMRequestBudget, chat_json_with_meta
        from tests.test_claim_artifacts import _requirement

        def refresh(root_dir, **kwargs):
            budget = kwargs.get("verifier_request_budget")
            hook = kwargs.get("shadow_built_hook")
            config = ai_extract.config_for_route("openai_compatible")

            def verifier(_unit_id: str, groups: list[dict]) -> dict:
                try:
                    chat_json_with_meta(
                        config,
                        "coverage verifier",
                        "verify batch 1",
                        request_budget=budget,
                    )
                except LLMConnectionError:
                    return {}
                return {
                    "request_id": "verify-paid-1",
                    "call_count": 1,
                    "failed_call_count": 0,
                    "tokens": 7,
                    "usage_complete": True,
                    "decisions": {
                        groups[0]["coverage_group_id"]: {
                            "covered": True,
                            "checks": {
                                name: True
                                for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                            },
                        }
                    },
                }

            rebuilt = claim_catalog.build_claim_catalog(
                blocks,
                [],
                structural_override_snapshot=(
                    claim_structural_overrides.read_structural_overrides(root_dir)
                ),
            )
            runtime = claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                budget_policy_version=LLMRequestBudget.VERSION,
                max_calls=4,
                max_total_tokens=40000,
            )
            shadow = claim_ledger.build_shadow_ledger(
                rebuilt,
                [_requirement(rebuilt)],
                semantic_verifier=verifier,
                verifier_runtime=runtime,
                verifier_budget=budget,
            )
            if hook is not None:
                hook(shadow)
            _publish(root_dir, rebuilt, shadow, run_id="paid-rebuild")
            claim_review_actions.fold_effective_ledger(
                root_dir,
                actor_trigger="paid-retry-rebuild",
            )
            return {"kind": "claim_shadow_refresh", "ledger_only": True}

        return refresh

    def _resume_call(self, call: dict, operation_id: str, **extra) -> dict:
        return {
            "claim_id": call["claim_id"],
            "claim_hash": "",
            "expected_catalog_generation_id": "",
            "expected_claim_effective_revision": "",
            "prior_structural_reason": "",
            "actor": "",
            "reason": "",
            "request_idempotency_key": "",
            "allow_llm": True,
            "route": "openai_compatible",
            "verifier_max_calls": 4,
            "verifier_max_total_tokens": 40000,
            "operation_id": operation_id,
            **extra,
        }

    def test_http_500_then_200_persists_one_checkpoint_and_no_rebill(self) -> None:
        checks = {
            name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "paid-retry-500-200")
            responses = iter([
                self._http_error(500),
                "ok",
            ])

            def http_side(request, timeout=None):
                item = next(responses)
                if isinstance(item, Exception):
                    raise item
                return self._success_response(
                    lambda: self._verifier_payload(request, checks)
                )

            with patch(
                "ai_extract.config_for_route", return_value=self._config(),
            ), patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=self._paid_refresh(blocks),
            ), patch(
                "llm_client.urllib.request.urlopen",
                side_effect=http_side,
            ) as http:
                pending = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                self.assertEqual(pending["status"], "needs_reconfirmation")
                kinds = self._kinds(root)
                self.assertNotIn("verifier_checkpoint", kinds)
                self.assertIn("operation_reconfirmation_required", kinds)

                result = claim_structural_overrides.confirm_structural_override(
                    root,
                    **self._resume_call(
                        call,
                        pending["operation_id"],
                        reconfirm_paid_work=True,
                    ),
                )
                self.assertTrue(result["ok"], result.get("error"))
                self.assertEqual(result["status"], "rebuilt")
                self.assertEqual(http.call_count, 2)

                kinds = self._kinds(root)
                self.assertEqual(kinds.count("verifier_checkpoint"), 1)
                self.assertEqual(kinds.count("operation_succeeded"), 1)
                from claim_structural_operations import (
                    derive_operation_states,
                    read_operation_log,
                )

                state = derive_operation_states(
                    read_operation_log(root).rows
                )[result["operation_id"]]
                latest_budget = dict(state["latest_budget"])
                self.assertEqual(latest_budget["attempted_calls"], 2)
                self.assertEqual(latest_budget["failed_calls"], 1)

                replay = claim_structural_overrides.confirm_structural_override(
                    root,
                    **self._resume_call(call, result["operation_id"]),
                )
                self.assertTrue(replay["ok"])
                self.assertEqual(http.call_count, 2)

    def test_http_429_then_200_recovers_inside_one_call(self) -> None:
        checks = {
            name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "paid-retry-429-200")
            responses = iter([
                self._http_error(429, retry_after="0"),
                "ok",
            ])

            def http_side(request, timeout=None):
                item = next(responses)
                if isinstance(item, Exception):
                    raise item
                return self._success_response(
                    lambda: self._verifier_payload(request, checks)
                )

            with patch(
                "ai_extract.config_for_route", return_value=self._config(),
            ), patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=self._paid_refresh(blocks),
            ), patch(
                "llm_client.urllib.request.urlopen",
                side_effect=http_side,
            ) as http:
                result = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                self.assertTrue(result["ok"], result.get("error"))
                self.assertEqual(http.call_count, 2)
                from claim_structural_operations import (
                    derive_operation_states,
                    read_operation_log,
                )

                state = derive_operation_states(
                    read_operation_log(root).rows
                )[result["operation_id"]]
                latest_budget = dict(state["latest_budget"])
                self.assertEqual(latest_budget["attempted_calls"], 2)
                self.assertEqual(latest_budget["failed_calls"], 1)
                self.assertEqual(self._kinds(root).count("verifier_checkpoint"), 1)

    def test_all_failed_round_stays_fail_closed_without_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "paid-retry-all-failed")
            with patch(
                "ai_extract.config_for_route", return_value=self._config(),
            ), patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=self._paid_refresh(blocks),
            ), patch(
                "llm_client.urllib.request.urlopen",
                side_effect=self._http_error(500),
            ) as http:
                pending = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                self.assertEqual(pending["status"], "needs_reconfirmation")
                retry = claim_structural_overrides.confirm_structural_override(
                    root,
                    **self._resume_call(
                        call,
                        pending["operation_id"],
                        reconfirm_paid_work=True,
                    ),
                )
                self.assertNotEqual(retry["status"], "rebuilt")
                kinds = self._kinds(root)
                self.assertNotIn("verifier_checkpoint", kinds)
                self.assertNotIn("operation_succeeded", kinds)
                self.assertGreaterEqual(http.call_count, 2)

    def test_unsettled_reservation_stays_fail_closed(self) -> None:
        checks = {
            name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
        }

        class _UnsettledBudget:
            def __init__(self, **_kwargs) -> None:
                pass

            @classmethod
            def from_settled_snapshot(cls, _snapshot):
                return cls()

            def reserve(self, _payload) -> str:
                return "reservation-1"

            def commit(self, *_args) -> None:
                return None

            def fail(self, *_args) -> None:
                return None

            def set_checkpoint(self, _callback) -> None:
                return None

            def snapshot(self) -> dict:
                return {
                    "version": "llm-request-budget-v1",
                    "max_calls": 4,
                    "max_tokens": 40000,
                    "attempted_calls": 1,
                    "failed_calls": 0,
                    "tokens": 0,
                    "reserved_tokens": 512,
                    "remaining_calls": 3,
                    "remaining_tokens": 39488,
                    "usage_complete": False,
                    "denied": False,
                    "termination_reason": "",
                    "status": "reserved",
                }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocks, build, snapshot = self._seed(root)
            call = self._call(build, snapshot, "paid-retry-unsettled")
            with patch(
                "ai_extract.config_for_route", return_value=self._config(),
            ), patch(
                "llm_client.LLMRequestBudget", _UnsettledBudget,
            ), patch(
                "ai_extract.refresh_claim_shadow",
                side_effect=self._paid_refresh(blocks),
            ), patch(
                "llm_client.urllib.request.urlopen",
                side_effect=lambda request, timeout=None: self._success_response(
                    lambda: self._verifier_payload(request, checks)
                ),
            ):
                pending = claim_structural_overrides.confirm_structural_override(
                    root, **call,
                )
                self.assertNotEqual(pending["status"], "rebuilt")
                kinds = self._kinds(root)
                self.assertNotIn("verifier_checkpoint", kinds)
                self.assertNotIn("operation_succeeded", kinds)

    def _kinds(self, root: Path) -> list[str]:
        from claim_structural_operations import read_operation_log

        return [str(row["event_kind"]) for row in read_operation_log(root).rows]


class StructuralOperationLogDefenseTests(unittest.TestCase):
    def _started_row(self, root: Path, key: str = "defense-op") -> str:
        from claim_structural_operations import (
            get_or_create_operation,
            make_operation_id,
        )

        def h(label: str) -> str:
            return claim_artifacts.hash_json("defense/v1", label)

        operation_id = make_operation_id(key)
        get_or_create_operation(
            root,
            {
                "claim_id": "CLM-0123456789abcdef",
                "claim_hash": h("claim"),
                "expected_catalog_generation_id": h("catalog"),
                "expected_claim_effective_revision": h("effective"),
                "prior_structural_reason": "repeated_page_furniture",
                "actor": "expert:test",
                "reason": "defense probe",
                "request_idempotency_key": key,
                "allow_llm": True,
                "route": "openai_compatible",
                "verifier_max_calls": 4,
                "verifier_max_total_tokens": 4000,
                "preconditions": {
                    "document_effective_revision": h("document-effective"),
                    "event_prefix_sha256": h("event-prefix"),
                    "last_event_seq": 0,
                    "target_generation_id": h("target-generation"),
                    "target_review_authority_revision": h("target-authority"),
                    "route_config_revision": h("route-config"),
                    "route_model": "defense-model",
                },
            },
            execution_fence=h("fence"),
        )
        return operation_id

    def _verifier_checkpoint_event(
        self,
        operation_id: str,
        *,
        suffix: str,
        budget_event_hash: str,
        budget: dict,
        override_hash: str,
    ) -> dict:
        def h(label: str) -> str:
            return claim_artifacts.hash_json("defense/v1", label)

        return {
            "operation_id": operation_id,
            "event_kind": "verifier_checkpoint",
            "idempotency_key": h(f"verifier-{suffix}"),
            "decision_artifact": (
                f"claim_structural_decisions/{'a' * 64}.json"
            ),
            "decision_artifact_sha256": h(f"decision-artifact-{suffix}"),
            "decision_payload_hash": h(f"decision-payload-{suffix}"),
            "binding": {
                "claim_id": "CLM-0123456789abcdef",
                "claim_hash": h("claim"),
                "expected_catalog_generation_id": h("catalog"),
                "expected_claim_effective_revision": h("effective"),
                "target_generation_id": h("target-generation"),
                "target_review_authority_revision": h("target-authority"),
                "override_hash": override_hash,
                "route_config_revision": h("route-config"),
                "route_model": "defense-model",
                "verifier_runtime_fingerprint": h("runtime"),
                "budget_event_hash": budget_event_hash,
                "budget_checkpoint_hash": claim_artifacts.hash_json(
                    "claim-structural-budget-checkpoint/v1", budget,
                ),
            },
        }

    def test_budget_checkpoint_after_verifier_checkpoint_is_rejected(self) -> None:
        from claim_structural_operations import (
            ClaimStructuralOperationError,
            append_operation_events,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            operation_id = self._started_row(root)
            override_hash = claim_artifacts.hash_json("defense/v1", "override")
            budget = {
                "version": "llm-request-budget-v1",
                "max_calls": 4,
                "max_tokens": 4000,
                "attempted_calls": 1,
                "failed_calls": 0,
                "tokens": 7,
                "reserved_tokens": 0,
                "usage_complete": True,
                "remaining_calls": 3,
                "remaining_tokens": 3993,
                "denied": False,
                "termination_reason": "",
                "status": "settled",
            }
            append_operation_events(root, [
                {
                    "operation_id": operation_id,
                    "event_kind": "override_registered",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "registered"
                    ),
                    "override_id": "CSO-0123456789abcdef",
                    "override_hash": override_hash,
                    "registry_prefix_sha256": claim_artifacts.sha256_bytes(b""),
                    "registry_prefix_count": 1,
                },
                {
                    "operation_id": operation_id,
                    "event_kind": "audit_appended",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "audit"
                    ),
                    "audit_event_hash": claim_artifacts.hash_json(
                        "defense/v1", "audit-event"
                    ),
                    "event_prefix_sha256": claim_artifacts.sha256_bytes(b""),
                    "last_event_seq": 1,
                },
                {
                    "operation_id": operation_id,
                    "event_kind": "budget_checkpoint",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "budget-1"
                    ),
                    "checkpoint": budget,
                },
            ])
            # The verifier binding must name the latest budget event hash.
            bad = self._verifier_checkpoint_event(
                operation_id,
                suffix="bad-binding",
                budget_event_hash=claim_artifacts.hash_json(
                    "defense/v1", "wrong-budget"
                ),
                budget=budget,
                override_hash=override_hash,
            )
            with self.assertRaisesRegex(
                ClaimStructuralOperationError,
                "decision binding is invalid",
            ):
                append_operation_events(root, [bad])

            from claim_structural_operations import read_operation_log

            budget_event_hash = read_operation_log(root).rows[-1]["event_hash"]
            good = self._verifier_checkpoint_event(
                operation_id,
                suffix="good-binding",
                budget_event_hash=budget_event_hash,
                budget=budget,
                override_hash=override_hash,
            )
            append_operation_events(root, [good])
            with self.assertRaisesRegex(
                ClaimStructuralOperationError,
                "budget checkpoint follows a verifier decision checkpoint",
            ):
                append_operation_events(root, [{
                    "operation_id": operation_id,
                    "event_kind": "budget_checkpoint",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "budget-2"
                    ),
                    "checkpoint": {
                        **budget,
                        "attempted_calls": 2,
                        "remaining_calls": 2,
                    },
                }])

    def test_unconfirmed_paid_work_compares_checkpoint_budget_binding(self) -> None:
        import claim_structural_confirmation as confirmation
        from claim_structural_operations import append_operation_events

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            operation_id = self._started_row(root)
            append_operation_events(root, [
                {
                    "operation_id": operation_id,
                    "event_kind": "override_registered",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "registered-b"
                    ),
                    "override_id": "CSO-0123456789abcdef",
                    "override_hash": claim_artifacts.hash_json(
                        "defense/v1", "override-b"
                    ),
                    "registry_prefix_sha256": claim_artifacts.sha256_bytes(b""),
                    "registry_prefix_count": 1,
                },
                {
                    "operation_id": operation_id,
                    "event_kind": "audit_appended",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "audit-b"
                    ),
                    "audit_event_hash": claim_artifacts.hash_json(
                        "defense/v1", "audit-event-b"
                    ),
                    "event_prefix_sha256": claim_artifacts.sha256_bytes(b""),
                    "last_event_seq": 1,
                },
            ])
            budget = {
                "version": "llm-request-budget-v1",
                "max_calls": 4,
                "max_tokens": 4000,
                "attempted_calls": 1,
                "failed_calls": 0,
                "tokens": 7,
                "reserved_tokens": 0,
                "usage_complete": True,
                "remaining_calls": 3,
                "remaining_tokens": 3993,
                "denied": False,
                "termination_reason": "",
                "status": "settled",
            }
            append_operation_events(root, [{
                "operation_id": operation_id,
                "event_kind": "budget_checkpoint",
                "idempotency_key": claim_artifacts.hash_json(
                    "defense/v1", "budget-b1"
                ),
                "checkpoint": budget,
            }])
            from claim_structural_operations import (
                derive_operation_states,
                read_operation_log,
            )

            state = derive_operation_states(read_operation_log(root).rows)[
                operation_id
            ]
            self.assertTrue(confirmation._has_unconfirmed_paid_work(state))
            budget_event_hash = state["latest_budget_event"]["event_hash"]
            append_operation_events(root, [
                self._verifier_checkpoint_event(
                    operation_id,
                    suffix="b",
                    budget_event_hash=budget_event_hash,
                    budget=budget,
                    override_hash=claim_artifacts.hash_json(
                        "defense/v1", "override-b"
                    ),
                ),
            ])
            state = derive_operation_states(read_operation_log(root).rows)[
                operation_id
            ]
            self.assertFalse(confirmation._has_unconfirmed_paid_work(state))

            state["checkpoints"]["verifier_checkpoint"]["binding"][
                "budget_event_hash"
            ] = claim_artifacts.hash_json("defense/v1", "other-budget")
            self.assertTrue(confirmation._has_unconfirmed_paid_work(state))

    def test_stale_terminalizer_splits_pre_and_post_publication(self) -> None:
        import claim_structural_confirmation as confirmation
        from claim_structural_operations import (
            append_operation_events,
            derive_operation_states,
            read_operation_log,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            operation_id = self._started_row(root)
            stale = claim_structural_overrides.ClaimStructuralOverrideStale(
                "catalog generation changed"
            )
            state = derive_operation_states(read_operation_log(root).rows)[
                operation_id
            ]
            confirmation._terminalize_stale(
                root,
                operation_id=operation_id,
                state=state,
                error=stale,
                append_events=append_operation_events,
            )
            state = derive_operation_states(read_operation_log(root).rows)[
                operation_id
            ]
            self.assertEqual(state["lifecycle"], "aborted_stale")
            self.assertTrue(state["closed"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            operation_id = self._started_row(root, key="defense-post")
            append_operation_events(root, [
                {
                    "operation_id": operation_id,
                    "event_kind": "override_registered",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "registered-post"
                    ),
                    "override_id": "CSO-0123456789abcdef",
                    "override_hash": claim_artifacts.hash_json(
                        "defense/v1", "override-post"
                    ),
                    "registry_prefix_sha256": claim_artifacts.sha256_bytes(b""),
                    "registry_prefix_count": 1,
                },
                {
                    "operation_id": operation_id,
                    "event_kind": "audit_appended",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "audit-post"
                    ),
                    "audit_event_hash": claim_artifacts.hash_json(
                        "defense/v1", "audit-event-post"
                    ),
                    "event_prefix_sha256": claim_artifacts.sha256_bytes(b""),
                    "last_event_seq": 1,
                },
            ])
            state = derive_operation_states(read_operation_log(root).rows)[
                operation_id
            ]
            base_generation_id = claim_artifacts.hash_json(
                "defense/v1", "base-generation-post",
            )
            from claim_structural_operations import ClaimStructuralOperationError

            with self.assertRaisesRegex(
                ClaimStructuralOperationError,
                "requires a published base",
            ):
                append_operation_events(root, [{
                    "operation_id": operation_id,
                    "event_kind": "operation_recovery_failed_post_publication",
                    "idempotency_key": claim_artifacts.hash_json(
                        "defense/v1", "forged-post-publication",
                    ),
                    "outcome": {
                        "code": "authority_changed",
                        "message": "forged stage two terminal",
                        "retryable": False,
                    },
                    "usage": None,
                    "binding": {"base_generation_id": base_generation_id},
                }])
            append_operation_events(root, [{
                "operation_id": operation_id,
                "event_kind": "base_rebuild_published",
                "idempotency_key": claim_artifacts.hash_json(
                    "defense/v1", "base-published-post",
                ),
                "base_generation_id": base_generation_id,
            }])
            state = derive_operation_states(read_operation_log(root).rows)[
                operation_id
            ]
            confirmation._terminalize_stale(
                root,
                operation_id=operation_id,
                state=state,
                error=stale,
                append_events=append_operation_events,
            )
            rows = read_operation_log(root).rows
            state = derive_operation_states(rows)[operation_id]
            self.assertEqual(
                state["lifecycle"], "recovery_failed_post_publication"
            )
            self.assertTrue(state["closed"])
            self.assertEqual(
                rows[-1]["event_kind"],
                "operation_recovery_failed_post_publication",
            )
            self.assertEqual(
                rows[-1]["binding"],
                {"base_generation_id": base_generation_id},
            )

    def test_v2_operation_rows_remain_readable_after_v3_bump(self) -> None:
        from claim_structural_operations import (
            CLAIM_STRUCTURAL_OPERATIONS,
            read_operation_log,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._started_row(root, key="legacy-v2-row")
            path = root / CLAIM_STRUCTURAL_OPERATIONS
            row = json.loads(path.read_text(encoding="utf-8").strip())
            row["schema"] = "claim-structural-operation/v2"
            row["event_hash"] = claim_artifacts.hash_json(
                row["schema"],
                {key: value for key, value in row.items() if key != "event_hash"},
            )
            path.write_bytes(
                claim_artifacts.canonical_json_value_bytes(row) + b"\n"
            )

            loaded = read_operation_log(root)

            self.assertEqual(len(loaded.rows), 1)
            self.assertEqual(
                loaded.rows[0]["schema"], "claim-structural-operation/v2"
            )


def result_operation_id(root: Path, call: dict) -> str:
    from claim_structural_operations import make_operation_id

    return make_operation_id(call["request_idempotency_key"])


if __name__ == "__main__":
    unittest.main()
