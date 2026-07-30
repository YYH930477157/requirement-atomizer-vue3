from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import claim_artifacts
import claim_catalog
import claim_review_actions
import claim_structural_overrides
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

            # This is the post-registry/pre-rebuild state, including any rebuild
            # exception: the old exclusion can be read for audit but is never fresh.
            stale = claim_artifacts.load_committed_effective_snapshot(root)
            freshness = claim_review_actions.assess_effective_freshness(root, stale)
            self.assertFalse(freshness["effective_fresh"])
            self.assertIn("structural_override_changed", freshness["freshness_reasons"])
            self.assertFalse(claim_artifacts.committed_base_versions_are_current(stale))

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
            stale = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertFalse(
                claim_review_actions.assess_effective_freshness(root, stale)[
                    "effective_fresh"
                ]
            )

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


if __name__ == "__main__":
    unittest.main()
