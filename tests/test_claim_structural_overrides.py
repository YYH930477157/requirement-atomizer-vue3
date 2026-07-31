from __future__ import annotations

import json
import os
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

    def test_crash_at_base_publication_and_fold_resume_replays_deterministically(
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

    def test_succeeded_replay_fails_closed_when_effective_artifact_is_missing(self) -> None:
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

            with self.assertRaises(
                claim_structural_overrides.ClaimStructuralOverrideStale
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
                    operation_id=first["operation_id"],
                )


def result_operation_id(root: Path, call: dict) -> str:
    from claim_structural_operations import make_operation_id

    return make_operation_id(call["request_idempotency_key"])


if __name__ == "__main__":
    unittest.main()
