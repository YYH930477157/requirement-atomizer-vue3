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
            self.assertTrue(all(
                payload["structural_candidate_decision_registry"]["prefix_count"]
                == 0
                for payload in payloads
            ))
            self.assertEqual(
                len({payload["document_effective_revision"] for payload in payloads}),
                1,
            )
            self.assertEqual(
                len({
                    payload["structural_candidate_decision_registry"][
                        "prefix_sha256"
                    ]
                    for payload in payloads
                }),
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
            self.assertEqual(queue_view["proposals"][0]["dry_run"], False)

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

    def test_live_target_drift_makes_ordinary_view_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            claim_artifacts.atomic_write_jsonl(root / "ai_requirements.jsonl", [])

            with self.assertRaises(claim_artifacts.ClaimEffectiveAuthorityChanged):
                claim_views.build_claim_view(root, "metrics")

    def test_a_track_target_drift_makes_cached_view_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish_a_track(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="a-track-cache-drift-test",
            )
            self.assertTrue(
                claim_views.build_claim_view(root, "metrics")["effective_fresh"]
            )
            claim_artifacts.atomic_write_jsonl(
                root / "atomic_requirements.jsonl",
                [],
            )

            with self.assertRaises(claim_artifacts.ClaimEffectiveAuthorityChanged):
                claim_views.build_claim_view(root, "metrics")

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


def _sha(seed: int) -> str:
    return "sha256:" + f"{seed:064x}"


class ClaimViewSnapshotCacheTests(unittest.TestCase):
    def _seed(self, root: Path) -> None:
        _publish(root, _catalog())
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="view-cache-seed",
        )

    def _seed_table(self, root: Path) -> None:
        # 当前结构契约（table-structure-v3）的表块——迁移门只认 build_table_artifacts
        # 的真实结构证据；手工拼的 legacy 块会落 base_migration_required 且 fold 拒绝
        from atomize import build_table_artifacts
        from requirement_kb import KnowledgeRepository

        block, table_items, table_cells = build_table_artifacts(
            [
                ["Requirement", "Value"],
                ["Output", "The product shall provide a configurable output."],
            ],
            table_id="TBL-000001",
            block_id="B1",
            order=1,
            table_title="Requirements",
            section_path=["4 Functions"],
            knowledge_bases=KnowledgeRepository.from_paths([]),
        )
        claim_artifacts.atomic_write_jsonl(root / "blocks.jsonl", [block])
        claim_artifacts.atomic_write_jsonl(root / "table_items.jsonl", table_items)
        claim_artifacts.atomic_write_jsonl(
            root / "table_cell_items.jsonl", table_cells
        )
        _publish(root, claim_catalog.build_catalog_from_directory(root))
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="view-table-cache-seed",
        )

    def test_six_views_share_one_snapshot_load_per_revision(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            original = claim_views.load_committed_effective_snapshot_readonly
            calls: list[dict] = []
            with mock.patch.object(
                claim_views,
                "load_committed_effective_snapshot_readonly",
                side_effect=lambda *args, **kwargs: (
                    calls.append({"args": args}),
                    original(*args, **kwargs),
                )[1],
            ):
                for view in (
                    "catalog",
                    "ledger",
                    "coverage_groups",
                    "metrics",
                    "review_events",
                    "queue",
                ):
                    claim_views.build_claim_view(root, view)
            self.assertEqual(len(calls), 1)

    def test_attempt_log_append_invalidates_the_cached_snapshot(self) -> None:
        from unittest import mock

        import claim_reextract_attempts as attempts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            original = claim_views.load_committed_effective_snapshot_readonly
            calls: list[dict] = []
            with mock.patch.object(
                claim_views,
                "load_committed_effective_snapshot_readonly",
                side_effect=lambda *args, **kwargs: (
                    calls.append({"args": args}),
                    original(*args, **kwargs),
                )[1],
            ):
                claim_views.build_claim_view(root, "queue")
                attempt_id = attempts.attempt_id(
                    "CQP-12345678-9abcdef0", "cache-probe"
                )
                attempts.append_attempt_events(root, [{
                    "attempt_id": attempt_id,
                    "proposal_id": "CQP-12345678-9abcdef0",
                    "claim_id": "CLM-0123456789abcdef",
                    "claim_hash": claim_artifacts.hash_json(
                        "claim-view-cache/v1", "claim"
                    ),
                    "event_kind": "reextract_started",
                    "actor": "expert:yyh",
                    "idempotency_key": claim_artifacts.hash_json(
                        "claim-view-cache/v1", "started"
                    ),
                    "request_idempotency_key": "cache-probe",
                    "route": "openai_compatible",
                    "model": "deepseek-chat",
                    "route_config_revision": claim_artifacts.hash_json(
                        "claim-view-cache/v1", "route-config"
                    ),
                    "budgets": {
                        "max_calls": 1,
                        "max_total_tokens": 4000,
                        "allow_semantic_verifier": False,
                    },
                    "preconditions": {
                        "claim_effective_revision": claim_artifacts.hash_json(
                            "claim-view-cache/v1", "revision"
                        ),
                    },
                    "focus": {
                        "kind": "text_span",
                        "block_id": "B1",
                        "start": 0,
                        "end": 5,
                    },
                }])
                second = claim_views.build_claim_view(root, "queue")
            self.assertEqual(len(calls), 2)
            self.assertEqual(second["attempt_event_count"], 1)

    def test_structural_decision_sidecar_change_invalidates_cached_snapshot(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            original = claim_views.load_committed_effective_snapshot_readonly
            calls: list[dict] = []
            with mock.patch.object(
                claim_views,
                "load_committed_effective_snapshot_readonly",
                side_effect=lambda *args, **kwargs: (
                    calls.append({"args": args}),
                    original(*args, **kwargs),
                )[1],
            ):
                claim_views.build_claim_view(root, "metrics")
                decisions = root / "claim_structural_decisions"
                decisions.mkdir()
                sidecar = decisions / "decision.json"
                sidecar.write_bytes(b'{"a":1}')
                claim_views.build_claim_view(root, "metrics")
                sidecar.write_bytes(b'{"b":1}')
                claim_views.build_claim_view(root, "metrics")

        self.assertEqual(len(calls), 3)

    def test_pending_journal_is_never_served_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            claim_views.build_claim_view(root, "metrics")
            journal = root / claim_artifacts.CLAIM_EFFECTIVE_PUBLICATION_JOURNAL
            journal.write_bytes(b'{"unfinished":true}')
            with self.assertRaises(claim_artifacts.ClaimEffectiveRecoveryPending):
                claim_views.build_claim_view(root, "metrics")

    def test_pending_budget_outbox_is_never_served_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            claim_views.build_claim_view(root, "metrics")
            outbox = root / claim_artifacts.CLAIM_BUDGET_CHECKPOINT_OUTBOX
            outbox.write_bytes(b'{"unfinished":true}')
            with self.assertRaises(claim_artifacts.ClaimEffectiveRecoveryPending):
                claim_views.build_claim_view(root, "metrics")

    def test_all_committed_payload_changes_invalidate_cache(self) -> None:
        payload_names = (
            claim_artifacts.CLAIM_CATALOG,
            claim_artifacts.CLAIM_CATALOG_META,
            claim_artifacts.CLAIM_COVERAGE_GROUPS,
            claim_artifacts.CLAIM_LEDGER,
            claim_artifacts.CLAIM_SHADOW_METRICS,
            claim_artifacts.CLAIM_EFFECTIVE_LEDGER,
            claim_artifacts.CLAIM_EFFECTIVE_META,
            claim_artifacts.CLAIM_QUEUE_PROPOSALS,
        )
        for name in payload_names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._seed(root)
                claim_views.build_claim_view(root, "metrics")
                path = root / name
                path.write_bytes(path.read_bytes() + b" ")

                with self.assertRaises(claim_artifacts.ClaimArtifactError):
                    claim_views.build_claim_view(root, "metrics")

    def test_table_items_tamper_invalidates_cache_and_reaches_loader(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_table(root)
            original = claim_views.load_committed_effective_snapshot_readonly
            calls: list[Path] = []
            with mock.patch.object(
                claim_views,
                "load_committed_effective_snapshot_readonly",
                side_effect=lambda *args, **kwargs: (
                    calls.append(Path(args[0])),
                    original(*args, **kwargs),
                )[1],
            ):
                before = claim_views.build_claim_view(root, "metrics")
                table_items = root / "table_items.jsonl"
                table_items.write_bytes(table_items.read_bytes() + b" ")

                with self.assertRaises(claim_artifacts.ClaimArtifactError):
                    claim_views.build_claim_view(root, "metrics")

        self.assertTrue(before["available"])
        self.assertEqual(len(calls), 2)

    def test_concurrent_views_single_flight_one_snapshot_load(self) -> None:
        import time
        from concurrent.futures import ThreadPoolExecutor
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            original = claim_views.load_committed_effective_snapshot_readonly
            calls: list[Path] = []

            def delayed_load(*args, **kwargs):
                calls.append(Path(args[0]))
                time.sleep(0.05)
                return original(*args, **kwargs)

            views = (
                "catalog",
                "ledger",
                "coverage_groups",
                "metrics",
                "review_events",
                "queue",
            )
            with mock.patch.object(
                claim_views,
                "load_committed_effective_snapshot_readonly",
                side_effect=delayed_load,
            ), ThreadPoolExecutor(max_workers=len(views)) as executor:
                payloads = list(executor.map(
                    lambda view: claim_views.build_claim_view(root, view),
                    views,
                ))

        self.assertEqual(len(calls), 1)
        self.assertTrue(all(payload["available"] for payload in payloads))

    def test_snapshot_cache_is_bounded_lru(self) -> None:
        from unittest import mock

        directories = [tempfile.TemporaryDirectory() for _ in range(3)]
        try:
            with claim_views._CONTEXT_CACHE_GUARD:
                claim_views._CONTEXT_CACHE.clear()
            with mock.patch.object(
                claim_views,
                "_CONTEXT_CACHE_MAX_ENTRIES",
                2,
            ):
                for directory in directories:
                    root = Path(directory.name)
                    self._seed(root)
                    claim_views.build_claim_view(root, "metrics")
                with claim_views._CONTEXT_CACHE_GUARD:
                    self.assertEqual(len(claim_views._CONTEXT_CACHE), 2)
                    cached_roots = set(claim_views._CONTEXT_CACHE)
                self.assertNotIn(Path(directories[0].name).resolve(), cached_roots)
        finally:
            for directory in directories:
                directory.cleanup()
    @staticmethod
    def _context(*, proposals=(), events=(), ledger=(), groups=()) -> dict:
        effective_meta = {
            "document_effective_revision": _sha(1),
            "base_generation_id": _sha(2),
            "event_prefix_sha256": _sha(3),
            "last_event_seq": len(events),
            "effective_metrics": {"uncertain_count": 0},
        }
        generation_meta = {
            "document_generation_id": _sha(4),
            "catalog_generation_id": _sha(5),
            "shadow_meta": {},
        }
        snapshot = {
            "effective_meta": effective_meta,
            "generation_meta": generation_meta,
            "queue_proposals": list(proposals),
            "effective_ledger": [],
            "ledger": list(ledger),
            "groups": list(groups),
            "metrics": {},
            "catalog": [],
        }
        return {
            "snapshot": snapshot,
            "effective": effective_meta,
            "generation": generation_meta,
            "freshness": {"effective_fresh": True, "freshness_reasons": []},
            "events": list(events),
            "health": {},
        }

    def test_queue_pages_cover_251_proposals_without_gaps_or_duplicates(self) -> None:
        proposals = [
            {
                "claim_id": f"CLM-{index:016x}",
                "proposal_id": f"CQP-{index:08x}-00000000",
            }
            for index in range(251)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(proposals=proposals)
            seen: list[str] = []
            offset = 0
            while True:
                payload = claim_views.build_claim_queue_view(
                    Path(tmp), context, limit=100, offset=offset,
                )
                self.assertEqual(payload["total"], 251)
                self.assertEqual(payload["limit"], 100)
                self.assertEqual(payload["offset"], offset)
                seen.extend(
                    str(row["proposal_id"]) for row in payload["proposals"]
                )
                if offset + 100 >= 251:
                    break
                offset += 100

        expected = [
            row["proposal_id"]
            for row in sorted(
                proposals,
                key=lambda row: (row["claim_id"], row["proposal_id"]),
            )
        ]
        self.assertEqual(seen, expected)
        self.assertEqual(len(set(seen)), 251)

    def test_coverage_group_pages_are_stable_and_complete(self) -> None:
        groups = [
            {
                "claim_id": f"CLM-{index % 7:016x}",
                "coverage_group_id": f"CGR-{index:08x}-0000",
            }
            for index in range(150)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(groups=groups)
            seen: list[str] = []
            for offset in (0, 100):
                payload = claim_views.build_claim_coverage_group_view(
                    Path(tmp), context, limit=100, offset=offset,
                )
                self.assertEqual(payload["total"], 150)
                seen.extend(
                    str(row["coverage_group_id"]) for row in payload["groups"]
                )

        expected = [
            row["coverage_group_id"]
            for row in sorted(
                groups,
                key=lambda row: (row["claim_id"], row["coverage_group_id"]),
            )
        ]
        self.assertEqual(seen, expected)
        self.assertEqual(len(set(seen)), 150)

    def test_review_event_pages_cover_more_than_one_page_in_seq_order(self) -> None:
        ledger = [{
            "claim_id": "CLM-0000000000000001",
            "claim_hash": _sha(9),
        }]
        events = [
            {
                "claim_id": "CLM-0000000000000001",
                "claim_hash": _sha(9),
                "document_generation_id": _sha(4),
                "catalog_generation_id": _sha(5),
                "event_seq": index,
            }
            for index in range(1, 151)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(events=events, ledger=ledger)
            seen: list[int] = []
            for offset in (0, 100):
                payload = claim_views.build_claim_review_event_view(
                    Path(tmp), context, limit=100, offset=offset,
                )
                self.assertEqual(payload["total"], 150)
                seen.extend(int(row["event_seq"]) for row in payload["events"])

        self.assertEqual(seen, list(range(1, 151)))

    def test_compat_omissions_paginate_independently_of_proposals(self) -> None:
        import omission_actions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocks = [
                {"block_id": f"B{index}", "text": f"omitted block {index}"}
                for index in range(3)
            ]
            claim_artifacts.atomic_write_jsonl(root / "blocks.jsonl", blocks)
            states = [
                {
                    "omission_id": omission_actions.make_omission_id(
                        block["block_id"], block["text"],
                    ),
                    "block_id": block["block_id"],
                    "status": "needs_extraction",
                    "reason": "test omission",
                }
                for block in blocks
            ]
            claim_artifacts.atomic_write_jsonl(
                root / omission_actions.OMISSION_STATES, states,
            )

            context = self._context()
            first = claim_views.build_claim_queue_view(
                root, context, compat_limit=2,
            )
            rest = claim_views.build_claim_queue_view(
                root, context, compat_limit=2, compat_offset=2,
            )
            unpaged = claim_views.build_claim_queue_view(root, context)

        self.assertEqual(first["compat_omission_total"], 3)
        self.assertEqual(len(first["compat_omissions"]), 2)
        self.assertEqual(first["compat_omission_limit"], 2)
        self.assertEqual(first["compat_omission_offset"], 0)
        self.assertEqual(len(rest["compat_omissions"]), 1)
        self.assertEqual(rest["compat_omission_offset"], 2)
        self.assertEqual(len(unpaged["compat_omissions"]), 3)
        paged_ids = [
            row["omission_id"]
            for row in (*first["compat_omissions"], *rest["compat_omissions"])
        ]
        self.assertEqual(
            paged_ids,
            [row["omission_id"] for row in unpaged["compat_omissions"]],
        )
        self.assertEqual(
            first["compat_omission_revision"], unpaged["compat_omission_revision"],
        )


if __name__ == "__main__":
    unittest.main()
