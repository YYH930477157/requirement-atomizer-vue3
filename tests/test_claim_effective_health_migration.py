import json
import tempfile
import unittest
from pathlib import Path

import claim_artifacts
import claim_review_actions
import api_server
import review_state
from tests.test_claim_artifacts import _catalog, _effective_candidate, _publish


class ClaimEffectiveHealthMigrationTests(unittest.TestCase):
    def test_pre_migration_health_sidecar_gets_additive_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_health = claim_review_actions._health_default()
            for field in (
                "authority_write_protocol_version",
                "legacy_authority_write_gap_count",
                "legacy_authority_write_gaps",
                "effective_snapshot_migrations",
            ):
                legacy_health.pop(field)
            (root / claim_artifacts.CLAIM_EFFECTIVE_HEALTH).write_text(
                json.dumps(legacy_health),
                encoding="utf-8",
            )

            loaded = claim_review_actions.read_effective_health(root)

            self.assertEqual(loaded["effective_snapshot_migrations"], [])
            self.assertEqual(
                loaded["authority_write_protocol_version"],
                review_state.CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION,
            )
            self.assertEqual(loaded["legacy_authority_write_gap_count"], 0)
            self.assertEqual(loaded["legacy_authority_write_gaps"], [])

    def test_legacy_authority_gap_has_monotonic_count_and_reason_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            first = claim_review_actions.record_legacy_authority_write_gap(
                root,
                route="legacy-import",
                reason="missing authority write token",
            )
            second = claim_review_actions.record_legacy_authority_write_gap(
                root,
                route="llm_pipeline.merge_review_states",
                reason="missing automatic merge preconditions",
            )

            self.assertEqual(first["legacy_authority_write_gap_count"], 1)
            self.assertEqual(second["legacy_authority_write_gap_count"], 2)
            self.assertEqual(
                second["authority_write_protocol_version"],
                review_state.CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION,
            )
            self.assertEqual(
                [row["occurrence"] for row in second["legacy_authority_write_gaps"]],
                [1, 2],
            )
            self.assertEqual(
                second["legacy_authority_write_gaps"][-1]["route"],
                "llm_pipeline.merge_review_states",
            )

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
                    "migration_id": migrated["effective_meta"]["migration_id"],
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
            self.assertEqual(
                migrated["effective_meta"]["migrated_from_version"],
                claim_artifacts.LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
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

    def test_health_backfills_migration_before_refold_after_authority_drift(self) -> None:
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crash_script = root / "crash_after_commit.py"
            repo = Path(__file__).resolve().parents[1]
            crash_script.write_text(
                "import os, sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "root = Path(sys.argv[2])\n"
                "from tests.test_claim_artifacts import _catalog, _publish\n"
                "import claim_review_actions\n"
                "_publish(root, _catalog())\n"
                "def _die(*args, **kwargs):\n"
                "    os._exit(0)\n"
                "claim_review_actions._write_effective_health = _die\n"
                "claim_review_actions.fold_effective_ledger(\n"
                "    root, actor_trigger='crash-window-test'\n"
                ")\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(crash_script), str(repo), str(root)],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])

            # The WAL committed the migrated snapshot; the process died before
            # the health write, so no migration record exists yet.
            snapshot = claim_artifacts.load_committed_effective_snapshot_readonly(
                root
            )
            committed_meta = dict(snapshot["effective_meta"])
            self.assertEqual(
                committed_meta["effective_snapshot_version"],
                claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            )
            self.assertTrue(committed_meta["migration_id"])
            health = claim_review_actions.read_effective_health(root)
            self.assertEqual(health["effective_snapshot_migrations"], [])

            # Authority advances before recovery. The next fold must persist
            # the old committed migration record before replacing its meta.
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])
            recovered = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="post-crash-refold",
            )
            self.assertFalse(recovered["publication_skipped"])
            health = claim_review_actions.read_effective_health(root)
            self.assertEqual(len(health["effective_snapshot_migrations"]), 1)
            record = health["effective_snapshot_migrations"][0]
            self.assertEqual(
                record["migration_id"], committed_meta["migration_id"]
            )
            self.assertEqual(
                record["source_effective_snapshot_version"],
                committed_meta["migrated_from_version"],
            )
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="post-crash-refold-2",
            )
            self.assertEqual(
                claim_review_actions.read_effective_health(root)[
                    "effective_snapshot_migrations"
                ],
                [record],
            )

    def test_real_v2_protocol_fixture_migrates_during_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="real-v2-fixture-seed",
            )
            meta_path = root / claim_artifacts.CLAIM_EFFECTIVE_META
            ledger_path = root / claim_artifacts.CLAIM_EFFECTIVE_LEDGER
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rows = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for row in rows:
                row["schema"] = "claim-effective-ledger/v1"
                row.pop("revision_inputs", None)
            claim_artifacts.atomic_write_jsonl(ledger_path, rows)
            meta.update({
                "artifact_protocol_version": (
                    claim_artifacts.PREVIOUS_CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
                ),
                "effective_artifact_version": (
                    claim_artifacts.PREVIOUS_CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
                ),
                "effective_snapshot_version": (
                    claim_artifacts.PREVIOUS_CLAIM_EFFECTIVE_SNAPSHOT_VERSION
                ),
                "effective_ledger_schema": "claim-effective-ledger/v1",
                "effective_ledger_sha256": claim_artifacts.file_sha256(ledger_path),
            })
            meta.pop("authority_projection_hash", None)
            meta.pop("migrated_from_version", None)
            meta.pop("migration_id", None)
            claim_artifacts._atomic_write_bytes(
                meta_path,
                claim_artifacts.canonical_json_value_bytes(meta),
            )

            historical = claim_artifacts.load_committed_shadow(root)
            self.assertEqual(
                historical["effective_meta"]["artifact_protocol_version"],
                "claim-effective-artifacts-v1",
            )
            migrated = api_server.run_claim_startup_maintenance(root)
            current = claim_artifacts.load_committed_effective_snapshot_readonly(root)

            self.assertTrue(migrated["ok"])
            self.assertEqual(
                current["effective_meta"]["effective_snapshot_version"],
                claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            )
            self.assertEqual(
                current["effective_meta"]["migrated_from_version"],
                claim_artifacts.PREVIOUS_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            )

    def test_stale_catalog_base_requires_rebuild_before_fold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            rows, queue, effective_meta = _effective_candidate(root)
            candidate = claim_artifacts.load_committed_claim_base(root)
            catalog_meta_path = root / claim_artifacts.CLAIM_CATALOG_META
            catalog_commit = json.loads(
                catalog_meta_path.read_text(encoding="utf-8")
            )
            catalog_commit["catalog_meta"]["catalog_version"] = "claim-catalog-v4"
            claim_artifacts.atomic_write_json(catalog_meta_path, catalog_commit)
            generation_path = root / claim_artifacts.CLAIM_GENERATION_META
            generation = json.loads(generation_path.read_text(encoding="utf-8"))
            generation["catalog_meta_sha256"] = claim_artifacts.file_sha256(
                catalog_meta_path
            )
            claim_artifacts.atomic_write_json(generation_path, generation)
            before = {
                name: (root / name).read_bytes()
                for name in claim_artifacts.CLAIM_EFFECTIVE_SNAPSHOT_FILES
                if (root / name).is_file()
            }

            result = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="stale-base-gate",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "base_migration_required")
            self.assertEqual(
                {
                    name: (root / name).read_bytes()
                    for name in before
                },
                before,
            )
            self.assertEqual(
                candidate["catalog_meta"]["catalog_version"],
                "claim-catalog-v5",
            )
            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "base_migration_required",
            ):
                claim_artifacts.publish_effective_snapshot(
                    root,
                    rows,
                    queue,
                    meta=effective_meta,
                )

    def test_current_effective_on_stale_base_is_rejected_by_loader_and_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            folded = claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="current-on-stale-base-seed",
            )
            self.assertTrue(folded["ok"])

            catalog_meta_path = root / claim_artifacts.CLAIM_CATALOG_META
            catalog_commit = json.loads(
                catalog_meta_path.read_text(encoding="utf-8")
            )
            catalog_commit["catalog_meta"]["catalog_version"] = "claim-catalog-v4"
            claim_artifacts.atomic_write_json(catalog_meta_path, catalog_commit)
            generation_path = root / claim_artifacts.CLAIM_GENERATION_META
            generation = json.loads(generation_path.read_text(encoding="utf-8"))
            generation["catalog_meta_sha256"] = claim_artifacts.file_sha256(
                catalog_meta_path
            )
            claim_artifacts.atomic_write_json(generation_path, generation)

            with self.assertRaisesRegex(
                claim_artifacts.ClaimArtifactError,
                "base_migration_required",
            ):
                claim_artifacts.load_committed_effective_snapshot_readonly(root)
            startup = api_server.run_claim_startup_maintenance(root)

        self.assertFalse(startup["ok"])
        self.assertEqual(startup["error"], "base_migration_required")


if __name__ == "__main__":
    unittest.main()
