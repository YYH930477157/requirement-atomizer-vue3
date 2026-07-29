from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ai_review_actions
import claim_artifacts
import claim_catalog
import claim_ledger
import claim_review_actions
import claim_views
from tests.test_claim_artifacts import _catalog, _publish, _requirement
from tests.test_claim_review_actions import _publish_a_track


class ClaimViewTests(unittest.TestCase):
    def _seed(self, root: Path) -> dict:
        catalog = _catalog()
        _publish(root, catalog)
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="view-test-initial",
        )
        return catalog

    @staticmethod
    def _changed_catalog() -> dict:
        text = "The product shall provide a separately configurable auxiliary output."
        return claim_catalog.build_claim_catalog([{
            "block_id": "B1",
            "order": 1,
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
        }], [])

    def test_empty_directory_returns_consistent_unavailable_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payloads = [
                claim_views.build_claim_view(root, view)
                for view in (
                    "catalog",
                    "ledger",
                    "coverage_groups",
                    "metrics",
                    "review_events",
                    "queue",
                )
            ]

            self.assertTrue(all(not payload["available"] for payload in payloads))
            self.assertEqual(
                len({payload["document_effective_revision"] for payload in payloads}),
                1,
            )
            self.assertTrue(all(
                payload["freshness_reasons"] == ["claim_generation_unavailable"]
                for payload in payloads
            ))

    def test_six_views_share_one_committed_revision_and_fixed_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            catalog = claim_views.build_claim_view(root, "catalog", limit=25)
            ledger = claim_views.build_claim_view(root, "ledger", limit=25)
            groups = claim_views.build_claim_view(root, "coverage_groups")
            metrics = claim_views.build_claim_view(root, "metrics")
            events = claim_views.build_claim_view(root, "review_events")
            queue = claim_views.build_claim_view(root, "queue")
            payloads = [catalog, ledger, groups, metrics, events, queue]

            self.assertTrue(all(payload["available"] for payload in payloads))
            self.assertTrue(all(payload["effective_fresh"] for payload in payloads))
            self.assertEqual(
                len({payload["document_effective_revision"] for payload in payloads}),
                1,
            )
            self.assertEqual(catalog["rows"][0]["resolution"], "covered")
            self.assertEqual(ledger["rows"][0]["resolution"], "covered")
            self.assertEqual(groups["groups"][0]["effective_status"], "validated")
            self.assertEqual(metrics["effective_metrics"]["covered_count"], 1)
            self.assertEqual(events["events"], [])
            self.assertEqual(queue["proposals"], [])

    def test_rejection_is_visible_in_catalog_groups_events_and_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = self._seed(root)
            requirement = _requirement(catalog)
            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "rejected",
                actor="view-test",
                reason="reject",
                source_fingerprint_value=claim_ledger.target_source_fingerprint(
                    requirement
                ),
                review_subject_fingerprint_value=claim_ledger.target_fingerprint(
                    requirement
                ),
            )

            catalog_view = claim_views.build_claim_view(
                root,
                "catalog",
                resolution="uncertain",
            )
            group_view = claim_views.build_claim_view(
                root,
                "coverage_groups",
                claim_id=catalog_view["rows"][0]["claim_id"],
            )
            event_view = claim_views.build_claim_view(
                root,
                "review_events",
                claim_id=catalog_view["rows"][0]["claim_id"],
            )
            queue_view = claim_views.build_claim_view(root, "queue")

            self.assertEqual(catalog_view["total"], 1)
            self.assertEqual(group_view["groups"][0]["effective_status"], "invalid")
            self.assertEqual(group_view["groups"][0]["effective_reason"], "expert_rejected")
            self.assertEqual(event_view["events"][0]["event_kind"], "target_invalidated")
            self.assertEqual(queue_view["proposals"][0]["dry_run"], True)

    def test_event_view_hides_previous_generation_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._seed(root)
            requirement = _requirement(first)
            ai_review_actions.apply_ai_review_action(
                root,
                "AIR-1",
                "rejected",
                actor="view-rollover",
                reason="reject first generation",
                source_fingerprint_value=claim_ledger.target_source_fingerprint(
                    requirement
                ),
                review_subject_fingerprint_value=claim_ledger.target_fingerprint(
                    requirement
                ),
            )
            first_generation = claim_artifacts.load_committed_effective_snapshot(root)
            self.assertEqual(
                claim_views.build_claim_view(root, "review_events")["total"],
                1,
            )

            second = self._changed_catalog()
            claim_artifacts.atomic_write_jsonl(root / "ai_review_states.jsonl", [])
            _publish(root, second, run_id="view-rollover-2")
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="view-rollover-second-generation",
            )
            view = claim_views.build_claim_view(root, "review_events")
            current = claim_artifacts.load_committed_effective_snapshot(root)

        self.assertNotEqual(
            first_generation["generation_meta"]["document_generation_id"],
            current["generation_meta"]["document_generation_id"],
        )
        self.assertTrue(all(
            event["document_generation_id"]
            == current["generation_meta"]["document_generation_id"]
            and event["catalog_generation_id"]
            == current["generation_meta"]["catalog_generation_id"]
            for event in view["events"]
        ))
        self.assertNotIn(
            first_generation["generation_meta"]["document_generation_id"],
            [event["document_generation_id"] for event in view["events"]],
        )

    def test_live_target_drift_marks_views_stale_without_changing_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            before = claim_views.build_claim_view(root, "metrics")
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])

            after = claim_views.build_claim_view(root, "metrics")

            self.assertFalse(after["effective_fresh"])
            self.assertIn("target_set_changed", after["freshness_reasons"])
            self.assertEqual(
                after["document_effective_revision"],
                before["document_effective_revision"],
            )

    def test_read_view_refuses_pending_wal_without_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            journal = root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL
            journal.write_bytes(b'{"unfinished":true}')

            with self.assertRaises(claim_artifacts.ClaimEffectiveRecoveryPending):
                claim_views.build_claim_view(root, "metrics")

            self.assertEqual(journal.read_bytes(), b'{"unfinished":true}')

    def test_a_track_read_views_do_not_touch_authority_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish_a_track(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-read-only-view-test",
            )
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

            payloads = [
                claim_views.build_claim_view(root, view)
                for view in (
                    "catalog",
                    "ledger",
                    "coverage_groups",
                    "metrics",
                    "review_events",
                    "queue",
                )
            ]

            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        self.assertTrue(all(payload["available"] for payload in payloads))
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
