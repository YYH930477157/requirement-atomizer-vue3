from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import claim_artifacts
import claim_ledger
import claim_review_actions
from tests.test_claim_artifacts import (
    _catalog,
    _publish,
    _requirement,
    _semantic_negative_shadow,
    _write_current_requirements_meta,
)
from tests.test_claim_review_actions import _draft


def _hash(label: str) -> str:
    return claim_artifacts.hash_json("claim-review-event-v2-test/v1", label)


def _current(root: Path) -> tuple[dict, dict, dict, dict, list[dict]]:
    base = claim_artifacts.load_committed_claim_base(root)
    snapshot = claim_artifacts.load_committed_shadow(root)
    claim = base["catalog"][0]
    base_row = base["ledger"][0]
    effective = snapshot["effective_ledger"][0]
    groups = [
        group for group in base["groups"]
        if group["claim_id"] == claim["claim_id"]
    ]
    return base, snapshot, claim, base_row, groups


def _coverage_evidence(group: dict) -> dict:
    return {
        "kind": "coverage_group",
        "coverage_group_id": group["coverage_group_id"],
        "coverage_group_hash": (
            claim_review_actions.claim_coverage_group_hash(group)
        ),
    }


def _source_exclusion_evidence(claim: dict) -> dict:
    return {
        "kind": "source_exclusion",
        "source_locator": claim["locator"],
        "source_text_hash": (
            claim_review_actions.claim_source_evidence_hash(claim)
        ),
        "exclusion_reason": "informative",
    }


def _positive_negative_shadow(catalog: dict) -> dict:
    def unexpected(*_args, **_kwargs) -> dict:
        raise AssertionError("validated verbatim coverage must skip negative calls")

    shadow = claim_ledger.build_shadow_ledger(
        catalog,
        [_requirement(catalog)],
        semantic_negative_proposer=unexpected,
        semantic_negative_verifier=unexpected,
    )
    negative = copy.deepcopy(
        _semantic_negative_shadow(catalog)["negative_decisions"][0]
    )
    shadow["negative_decisions"] = [negative]
    shadow["ledger"] = [claim_ledger.reduce_claim(
        catalog["catalog"][0],
        validated_groups=shadow["groups"],
        validated_negative=negative,
        all_groups=shadow["groups"],
    )]
    shadow["metrics"].update({
        "covered_count": 0,
        "uncertain_count": 1,
        "semantic_negative_candidate_count": 1,
        "semantic_negative_validated_count": 1,
    })
    shadow["meta"].update({
        "resolution_status": "open",
        "termination_reason": "stalled_open",
    })
    return shadow


class ClaimReviewEventV2Tests(unittest.TestCase):
    def _publish_positive_negative_conflict(
        self,
        root: Path,
    ) -> tuple[dict, dict, dict, dict, list[dict]]:
        catalog = _catalog()
        _publish(root, catalog, _positive_negative_shadow(catalog))
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="event-v2-base-conflict",
        )
        current = _current(root)
        self.assertEqual(current[3]["resolution"], "uncertain")
        self.assertIn(
            "positive_negative_conflict",
            current[3]["invalid_reasons"],
        )
        return current

    def test_conflicting_base_rejects_adjudication_without_supersession(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base, snapshot, claim, _base_row, groups = (
                self._publish_positive_negative_conflict(root)
            )
            before = claim_review_actions.read_claim_review_events(root).rows

            with self.assertRaisesRegex(
                claim_review_actions.ClaimAdjudicationCasMismatch,
                "missing an active fact",
            ):
                claim_review_actions.apply_claim_adjudication(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    adjudication="covered",
                    reason="resolve the verifier conflict",
                    evidence=_coverage_evidence(groups[0]),
                    actor="expert:yyh",
                    expected_claim_effective_revision=(
                        snapshot["effective_ledger"][0][
                            "claim_effective_revision"
                        ]
                    ),
                )

            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).rows,
                before,
            )

    def test_conflicting_base_rejects_single_side_supersession(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base, snapshot, claim, base_row, groups = (
                self._publish_positive_negative_conflict(root)
            )
            facts = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )
            before = claim_review_actions.read_claim_review_events(root).rows

            with self.assertRaisesRegex(
                claim_review_actions.ClaimAdjudicationCasMismatch,
                "missing an active fact",
            ):
                claim_review_actions.apply_claim_adjudication(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    adjudication="covered",
                    reason="one-sided supersession is insufficient",
                    evidence=_coverage_evidence(groups[0]),
                    actor="expert:yyh",
                    expected_claim_effective_revision=(
                        snapshot["effective_ledger"][0][
                            "claim_effective_revision"
                        ]
                    ),
                    supersedes_fact_hashes=facts["positive"],
                )

            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).rows,
                before,
            )

    def test_conflicting_base_closes_only_after_both_sides_are_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base, snapshot, claim, base_row, groups = (
                self._publish_positive_negative_conflict(root)
            )
            facts = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )
            all_facts = sorted(facts["positive"] + facts["negative"])

            result = claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="covered",
                reason="the current target evidence is normative and complete",
                evidence=_coverage_evidence(groups[0]),
                actor="expert:yyh",
                expected_claim_effective_revision=(
                    snapshot["effective_ledger"][0][
                        "claim_effective_revision"
                    ]
                ),
                supersedes_fact_hashes=all_facts,
            )
            effective = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]

        self.assertTrue(result["ok"])
        self.assertEqual(effective["resolution"], "covered")
        self.assertEqual(
            effective["effective_facts"]["superseded_base_fact_hashes"],
            all_facts,
        )

    def test_v1_prefix_is_byte_identical_when_v2_continues_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = _draft(1)
            legacy["schema"] = claim_ledger.LEGACY_CLAIM_REVIEW_EVENT_SCHEMA
            first = claim_review_actions.append_claim_review_events(root, [legacy])
            prefix = (root / claim_artifacts.CLAIM_REVIEW_EVENTS).read_bytes()

            second = claim_review_actions.append_claim_review_events(
                root,
                [_draft(2, event_kind="target_reactivated")],
            )
            raw = (root / claim_artifacts.CLAIM_REVIEW_EVENTS).read_bytes()
            rows = claim_review_actions.read_claim_review_events(root).rows

        self.assertTrue(raw.startswith(prefix))
        self.assertEqual(raw[: len(prefix)], prefix)
        self.assertEqual(rows[0]["schema"], "claim-review-event/v1")
        self.assertEqual(rows[1]["schema"], "claim-review-event/v2")
        self.assertEqual(rows[1]["prev_event_hash"], rows[0]["event_hash"])
        self.assertEqual(first["appended_count"], 1)
        self.assertEqual(second["appended_count"], 1)

    def test_malformed_v2_discriminated_variant_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = _draft(1)
            malformed["adjudication"] = "covered"
            with self.assertRaises(claim_artifacts.ClaimArtifactError):
                claim_review_actions.append_claim_review_events(
                    root,
                    [malformed],
                )
            self.assertFalse((root / claim_artifacts.CLAIM_REVIEW_EVENTS).exists())

    def test_torn_tail_recovery_keeps_mixed_version_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = _draft(1)
            legacy["schema"] = claim_ledger.LEGACY_CLAIM_REVIEW_EVENT_SCHEMA
            claim_review_actions.append_claim_review_events(root, [legacy])
            path = root / claim_artifacts.CLAIM_REVIEW_EVENTS
            valid_prefix = path.read_bytes()
            with path.open("ab") as handle:
                handle.write(b'{"schema":"claim-review-event/v2"')

            result = claim_review_actions.append_claim_review_events(
                root,
                [_draft(2, event_kind="target_reactivated")],
            )
            raw = path.read_bytes()
            rows = claim_review_actions.read_claim_review_events(root).rows

        self.assertTrue(result["torn_tail_recovered"])
        self.assertTrue(raw.startswith(valid_prefix))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["prev_event_hash"], rows[0]["event_hash"])

    def test_structural_operation_event_does_not_change_claim_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="event-v2-initial",
            )
            base, snapshot, claim, base_row, _groups = _current(root)
            effective = snapshot["effective_ledger"][0]
            before = effective["claim_effective_revision"]
            generation = base["generation_meta"]
            draft = {
                "schema": claim_ledger.CLAIM_REVIEW_EVENT_SCHEMA,
                "claim_id": claim["claim_id"],
                "claim_hash": claim["claim_hash"],
                "document_generation_id": generation["document_generation_id"],
                "catalog_generation_id": generation["catalog_generation_id"],
                "event_kind": "structural_falsification",
                "actor": "expert",
                "reason": "verified repeated furniture false positive",
                "idempotency_key": _hash("structural-operation"),
                "expected_base_claim_row_hash": claim_artifacts.hash_json(
                    "claim-base-row/v1", base_row
                ),
                "expected_claim_effective_revision": before,
                "prior_structural_reason": "repeated_page_furniture",
                "override_id": "CSO-0123456789abcdef",
                "override_hash": _hash("override"),
                "route": "deterministic",
            }
            claim_review_actions.append_claim_review_events(
                root,
                [draft],
                base_by_claim={claim["claim_id"]: base_row},
                effective_by_claim={claim["claim_id"]: effective},
            )
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="event-v2-structural-audit",
            )
            after = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]

        self.assertEqual(after["claim_effective_revision"], before)
        self.assertEqual(after["last_relevant_event_seq"], 0)

    def test_expert_reopen_and_later_covered_supersession(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="event-v2-expert-initial",
            )
            base, snapshot, claim, base_row, groups = _current(root)
            revision = snapshot["effective_ledger"][0][
                "claim_effective_revision"
            ]
            positive_fact = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )["positive"][0]
            reopened = claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="reopen",
                reason="coverage needs expert correction",
                evidence=_source_exclusion_evidence(claim),
                actor="expert:yyh",
                expected_claim_effective_revision=revision,
                supersedes_fact_hashes=[positive_fact],
            )
            reopened_row = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]
            self.assertEqual(reopened_row["resolution"], "uncertain")
            self.assertIn("expert_reopen", reopened_row["invalid_reasons"])

            with self.assertRaises(
                claim_review_actions.ClaimAdjudicationCasMismatch
            ):
                claim_review_actions.apply_claim_adjudication(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    adjudication="covered",
                    reason="stale concurrent decision",
                    evidence=_coverage_evidence(groups[0]),
                    actor="expert:other",
                    expected_claim_effective_revision=revision,
                )

            restored = claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="covered",
                reason="current coverage group is sufficient",
                evidence=_coverage_evidence(groups[0]),
                actor="expert:yyh",
                expected_claim_effective_revision=(
                    reopened_row["claim_effective_revision"]
                ),
                supersedes_fact_hashes=[reopened["event"]["event_hash"]],
            )
            restored_row = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]

        self.assertTrue(restored["ok"])
        self.assertEqual(restored_row["resolution"], "covered")

    def test_redundant_reopen_on_group_less_uncertain_claim_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            claim_review_actions.fold_effective_ledger(
                root, actor_trigger="event-v2-before-group-less-base",
            )
            _base, snapshot, claim, base_row, groups = _current(root)
            positive_fact = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )["positive"][0]
            reopened = claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="reopen",
                reason="coverage needs correction before base regeneration",
                evidence=_source_exclusion_evidence(claim),
                actor="expert:yyh",
                expected_claim_effective_revision=(
                    snapshot["effective_ledger"][0]["claim_effective_revision"]
                ),
                supersedes_fact_hashes=[positive_fact],
            )
            reopened_row = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]

            empty_shadow = claim_ledger.build_shadow_ledger(catalog, [])
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [],
            )
            _write_current_requirements_meta(root)
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                empty_shadow,
                run_id="run-group-less",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            result = claim_review_actions.fold_effective_ledger(
                root, actor_trigger="event-v2-group-less-replay",
            )
            after = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]

        self.assertTrue(reopened["ok"])
        self.assertIn("expert_reopen", reopened_row["invalid_reasons"])
        self.assertEqual(result["effective_metrics"]["uncertain_count"], 1)
        self.assertEqual(after["resolution"], "uncertain")
        self.assertEqual(after["invalid_reasons"], [])
        self.assertEqual(after["last_relevant_event_seq"], 1)
        self.assertNotEqual(
            after["claim_effective_revision"],
            reopened_row["claim_effective_revision"],
        )

    def test_historical_reopen_replaces_proposed_group_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = _catalog()
            _publish(root, catalog)
            claim_review_actions.fold_effective_ledger(
                root, actor_trigger="event-v2-before-proposed-base",
            )
            _base, snapshot, claim, base_row, groups = _current(root)
            positive_fact = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )["positive"][0]
            claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="reopen",
                reason="coverage needs correction before target translation",
                evidence=_source_exclusion_evidence(claim),
                actor="expert:yyh",
                expected_claim_effective_revision=(
                    snapshot["effective_ledger"][0]["claim_effective_revision"]
                ),
                supersedes_fact_hashes=[positive_fact],
            )

            translated = _requirement(catalog)
            translated["description"] = (
                "The device shall allow operators to configure auxiliary output behavior."
            )
            claim_artifacts.atomic_write_jsonl(
                root / "ai_requirements.jsonl",
                [translated],
            )
            _write_current_requirements_meta(root)
            proposed_shadow = claim_ledger.build_shadow_ledger(
                catalog,
                [translated],
                route_mode="stub",
            )
            claim_artifacts.publish_shadow_generation(
                root,
                catalog,
                proposed_shadow,
                run_id="run-proposed",
                requirements_sha256=claim_artifacts.file_sha256(
                    root / "ai_requirements.jsonl"
                ),
            )
            result = claim_review_actions.fold_effective_ledger(
                root, actor_trigger="event-v2-proposed-group-replay",
            )
            committed = claim_artifacts.load_committed_shadow(root)
            after = committed["effective_ledger"][0]

        self.assertEqual(committed["groups"][0]["status"], "proposed")
        self.assertEqual(result["effective_metrics"]["uncertain_count"], 1)
        self.assertEqual(after["invalid_reasons"], ["expert_reopen"])
        self.assertEqual(
            set(after["effective_facts"]["invalid_group_reasons"].values()),
            {"expert_reopen"},
        )

    def test_expert_exclusion_builds_valid_semantic_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="event-v2-exclusion-initial",
            )
            _base, snapshot, claim, base_row, groups = _current(root)
            positive_fact = claim_review_actions.claim_base_resolution_fact_hashes(
                claim,
                base_row,
                groups,
            )["positive"][0]
            claim_review_actions.apply_claim_adjudication(
                root,
                claim_id=claim["claim_id"],
                claim_hash=claim["claim_hash"],
                adjudication="excluded_non_normative",
                reason="source is informative context",
                evidence=_source_exclusion_evidence(claim),
                actor="expert:yyh",
                expected_claim_effective_revision=(
                    snapshot["effective_ledger"][0]["claim_effective_revision"]
                ),
                supersedes_fact_hashes=[positive_fact],
            )
            row = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]

        self.assertEqual(row["resolution"], "excluded")
        self.assertEqual(row["exclusion_kind"], "semantic")
        self.assertEqual(row["semantic_negative"]["status"], "validated")
        self.assertEqual(
            row["semantic_negative"]["validation"]["reason"],
            "informative",
        )

    def test_stale_source_evidence_is_rejected_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _publish(root, _catalog())
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="event-v2-stale-evidence-initial",
            )
            _base, snapshot, claim, _base_row, _groups = _current(root)
            evidence = _source_exclusion_evidence(claim)
            evidence["source_text_hash"] = _hash("stale-source")

            with self.assertRaisesRegex(
                claim_review_actions.ClaimReviewActionError,
                "evidence is stale",
            ):
                claim_review_actions.apply_claim_adjudication(
                    root,
                    claim_id=claim["claim_id"],
                    claim_hash=claim["claim_hash"],
                    adjudication="reopen",
                    reason="stale evidence must fail",
                    evidence=evidence,
                    actor="expert:yyh",
                    expected_claim_effective_revision=(
                        snapshot["effective_ledger"][0][
                            "claim_effective_revision"
                        ]
                    ),
                    supersedes_fact_hashes=[_hash("not-used")],
                )
            self.assertEqual(
                claim_review_actions.read_claim_review_events(root).rows,
                [],
            )


class ActiveResolutionFactContractTests(unittest.TestCase):
    def _seed_covered(
        self,
        root: Path,
    ) -> tuple[dict, dict, dict, dict, list[dict]]:
        catalog = _catalog()
        _publish(root, catalog)
        claim_review_actions.fold_effective_ledger(
            root,
            actor_trigger="fact-contract-seed",
        )
        return _current(root)

    @staticmethod
    def _revision(snapshot: dict, claim: dict) -> str:
        return str(snapshot["effective_ledger"][0]["claim_effective_revision"])

    def _adjudicate(
        self,
        root: Path,
        *,
        adjudication: str,
        evidence: dict,
        reason: str,
        supersedes: list[str] | None = None,
        key: str,
    ) -> dict:
        _base, snapshot, claim, _base_row, _groups = _current(root)
        return claim_review_actions.apply_claim_adjudication(
            root,
            claim_id=claim["claim_id"],
            claim_hash=claim["claim_hash"],
            adjudication=adjudication,
            reason=reason,
            evidence=evidence,
            actor="expert:yyh",
            expected_claim_effective_revision=self._revision(snapshot, claim),
            supersedes_fact_hashes=supersedes or [],
            request_idempotency_key=key,
        )

    @staticmethod
    def _active_hashes(root: Path) -> set[str]:
        effective = claim_artifacts.load_committed_shadow(root)[
            "effective_ledger"
        ][0]
        return {
            str(fact["fact_hash"])
            for fact in effective["effective_facts"]["active_resolution_facts"]
        }

    def test_excluded_must_supersede_all_active_covered_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base, _snapshot, _claim, _base_row, groups = self._seed_covered(root)
            first = self._adjudicate(
                root,
                adjudication="covered",
                evidence=_coverage_evidence(groups[0]),
                reason="first independent coverage confirmation",
                key="fact-contract-e1",
            )
            second = self._adjudicate(
                root,
                adjudication="covered",
                evidence=_coverage_evidence(groups[0]),
                reason="second independent coverage confirmation",
                key="fact-contract-e2",
            )
            active = self._active_hashes(root)
            first_hash = str(first["event"]["event_hash"])
            second_hash = str(second["event"]["event_hash"])
            self.assertTrue({first_hash, second_hash}.issubset(active))
            self.assertEqual(len(active), 3)

            _base, _snapshot, claim, _base_row, _groups = _current(root)
            with self.assertRaisesRegex(
                claim_review_actions.ClaimAdjudicationCasMismatch,
                "missing an active fact",
            ):
                self._adjudicate(
                    root,
                    adjudication="excluded_non_normative",
                    evidence=_source_exclusion_evidence(claim),
                    reason="dropping one active covered fact must fail",
                    supersedes=sorted(active - {second_hash}),
                    key="fact-contract-x-partial",
                )

            closed = self._adjudicate(
                root,
                adjudication="excluded_non_normative",
                evidence=_source_exclusion_evidence(claim),
                reason="all active covered facts are explicitly closed",
                supersedes=sorted(active),
                key="fact-contract-x-full",
            )
            self.assertTrue(closed["ok"])
            effective = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]
            self.assertEqual(effective["resolution"], "excluded")

            with self.assertRaisesRegex(
                claim_review_actions.ClaimAdjudicationCasMismatch,
                "inactive or historical fact",
            ):
                self._adjudicate(
                    root,
                    adjudication="reopen",
                    evidence=_source_exclusion_evidence(claim),
                    reason="reusing a superseded hash must fail",
                    supersedes=sorted(
                        self._active_hashes(root) | {first_hash}
                    ),
                    key="fact-contract-reopen-stale",
                )

    def test_projection_and_view_expose_facts_and_required_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_covered(root)

            import claim_views

            row = claim_views.build_claim_view(root, "catalog")["rows"][0]
            effective = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]
            expected_facts = effective["effective_facts"][
                "active_resolution_facts"
            ]
            self.assertEqual(row["active_resolution_facts"], expected_facts)
            self.assertTrue(all(
                set(fact) == {"fact_hash", "kind", "polarity"}
                for fact in row["active_resolution_facts"]
            ))
            required = row["required_supersedes_fact_hashes"]
            self.assertEqual(
                set(required),
                {"covered", "excluded_non_normative", "reopen"},
            )
            base_positive = {
                fact["fact_hash"]
                for fact in expected_facts
                if fact["polarity"] == "positive"
            }
            self.assertEqual(required["covered"], [])
            self.assertEqual(
                set(required["excluded_non_normative"]), base_positive
            )
            self.assertEqual(set(required["reopen"]), base_positive)

    def test_audit_conflict_closes_only_by_superseding_the_audit_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _base, _snapshot, claim, base_row, groups = self._seed_covered(root)
            confirmed = self._adjudicate(
                root,
                adjudication="covered",
                evidence=_coverage_evidence(groups[0]),
                reason="independent coverage confirmation",
                key="fact-contract-audit-e1",
            )
            _base, snapshot, claim, base_row, _groups = _current(root)
            known = self._active_hashes(root)
            audit_draft = {
                "schema": "claim-review-event/v2",
                "claim_id": claim["claim_id"],
                "claim_hash": claim["claim_hash"],
                "document_generation_id": claim["document_generation_id"],
                "catalog_generation_id": claim["catalog_generation_id"],
                "event_kind": "audit_conflict",
                "actor": "auditor:zz",
                "reason": "two active facts disagree",
                "idempotency_key": _hash("audit-conflict-1"),
                "expected_base_claim_row_hash": claim_artifacts.hash_json(
                    "claim-base-row/v1", base_row
                ),
                "expected_claim_effective_revision": self._revision(
                    snapshot, claim
                ),
                "conflicting_fact_hashes": sorted(known),
                "evidence": [_coverage_evidence(groups[0])],
                "route": "expert",
            }
            base_by_claim = {
                str(row["claim_id"]): row
                for row in claim_artifacts.load_committed_claim_base(root)[
                    "ledger"
                ]
            }
            effective_by_claim = {
                str(row["claim_id"]): row
                for row in snapshot["effective_ledger"]
            }
            claim_review_actions.append_claim_review_events(
                root,
                [audit_draft],
                base_by_claim=base_by_claim,
                effective_by_claim=effective_by_claim,
            )
            claim_review_actions.fold_effective_ledger(
                root,
                actor_trigger="fact-contract-audit",
            )
            effective = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]
            self.assertEqual(effective["resolution"], "uncertain")
            active_facts = effective["effective_facts"][
                "active_resolution_facts"
            ]
            audit_hash = next(
                fact["fact_hash"]
                for fact in active_facts
                if fact["kind"] == "audit_conflict"
            )
            active = self._active_hashes(root)

            with self.assertRaisesRegex(
                claim_review_actions.ClaimAdjudicationCasMismatch,
                "missing an active fact",
            ):
                self._adjudicate(
                    root,
                    adjudication="covered",
                    evidence=_coverage_evidence(groups[0]),
                    reason="closing without the audit fact must fail",
                    supersedes=sorted(active - {audit_hash}),
                    key="fact-contract-audit-partial",
                )

            closed = self._adjudicate(
                root,
                adjudication="covered",
                evidence=_coverage_evidence(groups[0]),
                reason="audit conflict reviewed and closed",
                supersedes=sorted(active),
                key="fact-contract-audit-close",
            )
            self.assertTrue(closed["ok"])
            effective = claim_artifacts.load_committed_shadow(root)[
                "effective_ledger"
            ][0]
            self.assertEqual(effective["resolution"], "covered")
            self.assertNotIn(audit_hash, self._active_hashes(root))


if __name__ == "__main__":
    unittest.main()
