import json
import tempfile
import unittest
from pathlib import Path

import claim_artifacts
import claim_review_actions
from tests.test_claim_artifacts import _catalog, _publish


class ClaimEffectiveHealthMigrationTests(unittest.TestCase):
    def test_pre_migration_health_sidecar_gets_additive_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_health = claim_review_actions._health_default()
            legacy_health.pop("effective_snapshot_migrations")
            (root / claim_artifacts.CLAIM_EFFECTIVE_HEALTH).write_text(
                json.dumps(legacy_health),
                encoding="utf-8",
            )

            loaded = claim_review_actions.read_effective_health(root)

            self.assertEqual(loaded["effective_snapshot_migrations"], [])

    def test_v1_to_v2_fold_records_one_auditable_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = _publish(root, _catalog())
            legacy = claim_artifacts.load_committed_shadow(root)
            shadow_metrics_before = (
                root / claim_artifacts.CLAIM_SHADOW_METRICS
            ).read_bytes()
            self.assertEqual(
                legacy["effective_meta"]["effective_snapshot_version"],
                claim_artifacts.LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            )

            migrated = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="phase1-migration-test",
            )
            health = claim_review_actions.read_effective_health(root)
            self.assertEqual(
                health["effective_snapshot_migrations"],
                [{
                    "base_generation_id": claim_artifacts.claim_base_generation_id(
                        generation
                    ),
                    "source_effective_snapshot_version": (
                        claim_artifacts.LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION
                    ),
                    "target_effective_snapshot_version": (
                        claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_VERSION
                    ),
                    "effective_run_id": migrated["effective_meta"]["run_id"],
                    "migrated_at": migrated["effective_meta"]["committed_at"],
                    "actor_trigger": "phase1-migration-test",
                }],
            )

            first_migration_history = list(
                health["effective_snapshot_migrations"]
            )
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="ordinary-refold",
            )
            refolded_health = claim_review_actions.read_effective_health(root)
            self.assertEqual(
                refolded_health["effective_snapshot_migrations"],
                first_migration_history,
            )
            self.assertEqual(
                (root / claim_artifacts.CLAIM_SHADOW_METRICS).read_bytes(),
                shadow_metrics_before,
            )


if __name__ == "__main__":
    unittest.main()
