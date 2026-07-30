from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ai_extract
import claim_queue_execution as execution
import claim_reextract_attempts
import omission_actions
from claim_artifacts import atomic_write_jsonl, hash_json
from llm_client import LLMClientConfig, LLMConnectionError


def _hash(label: str) -> str:
    return hash_json("claim-queue-execution-test/v1", label)


def _proposal() -> dict:
    claim_hash = _hash("claim")
    return {
        "schema": "claim-queue-proposal/v2",
        "proposal_id": "CQP-12345678-9abcdef0",
        "claim_id": "CLM-0123456789abcdef",
        "claim_hash": claim_hash,
        "parent_block_id": "B1",
        "claim_effective_revision": _hash("old-effective"),
        "expected_ledger_state": "uncertain",
        "focus": {
            "kind": "text_span",
            "adapter_version": "claim-focus-adapter-v1",
            "claim_id": "CLM-0123456789abcdef",
            "claim_hash": claim_hash,
            "block_id": "B1",
            "parent_block_fingerprint": _hash("block"),
            "start": 0,
            "end": 30,
            "text_hash": _hash("text"),
            "text": "The output shall be configurable.",
        },
        "execution_preconditions": {
            "claim_effective_revision": _hash("old-effective"),
            "target_publication_revision": _hash("old-publication"),
        },
    }


def _final_snapshot(proposal: dict) -> dict:
    return {
        "generation_meta": {
            "document_generation_id": _hash("document"),
            "catalog_generation_id": _hash("catalog"),
            "catalog_sha256": _hash("catalog-file"),
            "coverage_groups_sha256": _hash("groups-file"),
            "ledger_sha256": _hash("ledger-file"),
        },
        "effective_meta": {
            "document_effective_revision": _hash("new-document-effective"),
        },
        "effective_ledger": [{
            "claim_id": proposal["claim_id"],
            "resolution": "covered",
            "claim_effective_revision": _hash("new-claim-effective"),
        }],
    }


class StrictClaimFocusCritiqueTests(unittest.TestCase):
    FOCUS = "Indicator output | user configurable"
    UNRELATED = "Alarm output | fixed"

    @staticmethod
    def _row(title: str, quote: str) -> dict:
        return {
            "title": title,
            "description": title,
            "source_section": "4.1",
            "source_quote": quote,
            "source_block_ids": ["B1"],
            "module": "interface",
            "type": "functional",
            "priority": "P1",
            "labels": ["interface"],
            "sub_items": [],
            "acceptance_criteria": [],
        }

    def _section(self) -> dict:
        return {
            "section_id": "4.1",
            "heading": "4.1 Outputs",
            "text": f"{self.UNRELATED}\n{self.FOCUS}",
            "block_ids": ["B1"],
        }

    def test_strict_focus_keeps_only_requirement_quoted_from_focus(self) -> None:
        prompts: list[str] = []

        def chat(_system: str, user: str) -> dict:
            prompts.append(user)
            return {
                "requirements": [
                    self._row("Fixed alarm output", self.UNRELATED),
                    self._row("Configurable indicator output", self.FOCUS),
                ],
                "supplements": [],
            }

        extra, applied = ai_extract.critique_section(
            self._section(),
            [],
            chat,
            focus_lines=[self.FOCUS],
            strict_focus=True,
        )

        self.assertEqual(applied, 0)
        self.assertEqual([row["source_quote"] for row in extra], [self.FOCUS])
        self.assertIn(self.FOCUS, prompts[0])
        self.assertNotIn(self.UNRELATED, prompts[0])

    def test_claim_strategy_fingerprint_tracks_focus_critique_version(self) -> None:
        before = omission_actions.claim_supplement_strategy_fingerprint(
            "model-x",
            focus_adapter_version="claim-focus-adapter-v1",
        )

        with mock.patch.object(
            ai_extract,
            "CLAIM_FOCUS_CRITIQUE_VERSION",
            "claim-focus-critique-v999",
        ):
            after = omission_actions.claim_supplement_strategy_fingerprint(
                "model-x",
                focus_adapter_version="claim-focus-adapter-v1",
            )

        self.assertNotEqual(after, before)

    def test_claim_mode_with_only_unrelated_rows_fails_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = str(self._section()["text"])
            block = {
                "block_id": "B1", "order": 1, "type": "table",
                "text": source, "section_path": ["4.1 Outputs"],
            }
            atomic_write_jsonl(root / "blocks.jsonl", [block])
            atomic_write_jsonl(root / ai_extract.AI_REQUIREMENTS, [])
            before = (root / ai_extract.AI_REQUIREMENTS).read_bytes()
            start = source.index(self.FOCUS)
            focus = {
                "kind": "text_span",
                "adapter_version": "claim-focus-adapter-v1",
                "claim_id": "CLM-0123456789abcdef",
                "claim_hash": _hash("claim"),
                "block_id": "B1",
                "parent_block_fingerprint": _hash("block"),
                "start": start,
                "end": start + len(self.FOCUS),
                "text_hash": _hash("text"),
                "text": self.FOCUS,
            }
            config = LLMClientConfig(
                base_url="https://example.invalid/v1",
                model="deepseek-chat",
                max_tokens=128,
                max_retries=0,
            )
            budget = execution.LLMRequestBudget(max_calls=2, max_tokens=20000)
            callbacks: list[str] = []

            def chat_with_meta(_config, _system, _user, *, request_budget):
                self.assertIs(request_budget, budget)
                return {
                    "requirements": [self._row("Fixed alarm output", self.UNRELATED)],
                    "supplements": [],
                }, {
                    "usage": {"total_tokens": 41},
                    "usage_complete": True,
                    "call_count": 1,
                    "failed_call_count": 0,
                }

            with mock.patch(
                "api_server.final_ai_requirements_are_stale", return_value=False,
            ), mock.patch.object(
                ai_extract, "ai_requirements_producer_is_current", return_value=True,
            ), mock.patch.object(
                omission_actions, "_find_target_section",
                return_value=([block], self._section(), [self._section()]),
            ), mock.patch.object(
                ai_extract, "config_for_route", return_value=config,
            ), mock.patch(
                "llm_client.apply_min_tokens", side_effect=lambda value, _purpose: value,
            ), mock.patch.object(
                ai_extract, "build_doc_context", return_value="unrelated document context",
            ), mock.patch.object(
                ai_extract, "write_compliance_requirements", return_value={},
            ), mock.patch.object(
                ai_extract, "refresh_ai_extract_quality",
                return_value={"failed_sections": 0, "failed_section_ids": []},
            ), mock.patch.object(
                ai_extract, "write_ai_requirements_metadata",
            ), mock.patch.object(
                ai_extract, "rebuild_merged_spec", return_value={"written": []},
            ), self.assertRaises(omission_actions.OmissionNoResultError):
                omission_actions.targeted_reextract(
                    root,
                    block_id="B1",
                    actor="expert:yyh",
                    route="openai_compatible",
                    expected_source_fingerprint=(
                        omission_actions.omission_source_fingerprint("B1", source)
                    ),
                    claim_execution={
                        "proposal_id": "CQP-12345678-9abcdef0",
                        "attempt_id": "CRA-0123456789abcdef",
                        "claim_id": "CLM-0123456789abcdef",
                        "claim_hash": _hash("claim"),
                        "focus": focus,
                        "request_budget": budget,
                        "pre_publish_check": lambda: callbacks.append("cas"),
                        "on_supplement_persisted": (
                            lambda _patch: callbacks.append("supplement")
                        ),
                        "on_requirements_published": (
                            lambda _rows: callbacks.append("requirements")
                        ),
                        "chat_with_meta": chat_with_meta,
                    },
                )

            self.assertEqual((root / ai_extract.AI_REQUIREMENTS).read_bytes(), before)
            self.assertFalse((root / omission_actions.AI_SUPPLEMENTS).exists())
            self.assertEqual(callbacks, [])


class ClaimQueueExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LLMClientConfig(
            base_url="https://example.invalid/v1",
            model="deepseek-chat",
            max_tokens=128,
            max_retries=0,
        )

    def _run(
        self,
        root: Path,
        targeted,
        *,
        validator=None,
        refresh=None,
    ):
        proposal = _proposal()
        expected = proposal["claim_effective_revision"]
        atomic_write_jsonl(root / "blocks.jsonl", [{
            "block_id": "B1",
            "text": "The output shall be configurable.",
        }])
        atomic_write_jsonl(root / ai_extract.AI_REQUIREMENTS, [])
        validator = validator or mock.Mock(
            return_value=({}, proposal, {"resolution": "uncertain"})
        )
        refresh = refresh or mock.Mock(return_value={
            "kind": "claim_shadow_refresh",
            "claim_shadow": {"effective_fresh": True},
        })
        with mock.patch.object(
            execution, "_validate_current_proposal", validator,
        ), mock.patch.object(
            ai_extract, "config_for_route", return_value=self.config,
        ), mock.patch.object(
            execution, "apply_min_tokens", side_effect=lambda value, _purpose: value,
        ), mock.patch.object(
            execution, "targeted_reextract", side_effect=targeted,
        ), mock.patch.object(
            ai_extract, "refresh_claim_shadow", refresh,
        ), mock.patch.object(
            execution, "load_committed_effective_snapshot",
            return_value=_final_snapshot(proposal),
        ), mock.patch.object(
            execution, "assess_effective_freshness",
            return_value={"effective_fresh": True, "freshness_reasons": []},
        ), mock.patch.object(
            execution, "_load_b_track_authority",
            return_value={"target_publication_revision": _hash("new-publication")},
        ):
            result = execution.execute_claim_queue_proposal(
                root,
                proposal_id=proposal["proposal_id"],
                expected_claim_effective_revision=expected,
                expected_ledger_state="uncertain",
                actor="expert:yyh",
                allow_llm=True,
                route="openai_compatible",
                maximum_calls=4,
                total_token_budget=20000,
                request_idempotency_key="request-1",
            )
        return result, refresh

    @staticmethod
    def _successful_targeted(root: Path):
        def run(*_args, **kwargs):
            current = kwargs["claim_execution"]
            budget = current["request_budget"]
            reservation = budget.reserve({"model": "x", "max_tokens": 32})
            budget.commit(reservation, {"total_tokens": 73})
            current["pre_publish_check"]()
            patch = {
                "supplement_id": "SUP-0123456789ab",
                "origin": {"kind": "claim_queue"},
            }
            current["on_supplement_persisted"](patch)
            atomic_write_jsonl(root / ai_extract.AI_REQUIREMENTS, [{
                "ai_req_id": "AIR-1",
                "title": "Configurable output",
            }])
            current["on_requirements_published"]([])
            return {"schema": "claim-reextract-mutation/v1", "requirements": 1}

        return run

    def test_success_records_every_checkpoint_and_leaves_omission_log_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            omission_path = root / "omission_states.jsonl"
            omission_path.write_bytes(b'{"legacy":true}\n')
            before = omission_path.read_bytes()
            result, refresh = self._run(root, self._successful_targeted(root))
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            after = omission_path.read_bytes()

        kinds = [row["event_kind"] for row in rows]
        self.assertEqual(kinds[0], "reextract_started")
        self.assertIn("budget_checkpoint", kinds)
        self.assertLess(kinds.index("supplement_persisted"), kinds.index("requirements_published"))
        self.assertLess(kinds.index("requirements_published"), kinds.index("base_rebuild_published"))
        self.assertLess(kinds.index("base_rebuild_published"), kinds.index("effective_folded"))
        self.assertEqual(kinds[-1], "reextract_succeeded")
        self.assertEqual(result["lifecycle"], "executed")
        self.assertEqual(result["resolution"], "covered")
        self.assertEqual(after, before)
        refresh.assert_called_once()
        self.assertIsNotNone(refresh.call_args.kwargs["verifier_request_budget"])

    def test_remote_failure_is_terminal_and_does_not_publish_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fail(*_args, **kwargs):
                budget = kwargs["claim_execution"]["request_budget"]
                reservation = budget.reserve({"model": "x", "max_tokens": 32})
                budget.fail(reservation)
                raise LLMConnectionError("offline")

            with self.assertRaises(execution.ClaimQueueExecutionRemoteError):
                self._run(root, fail)
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            requirements = (root / ai_extract.AI_REQUIREMENTS).read_bytes()

        self.assertEqual(rows[-1]["event_kind"], "reextract_failed")
        self.assertEqual(rows[-1]["outcome"]["code"], "remote_error")
        self.assertEqual(requirements, b"")

    def test_second_cas_failure_records_paid_stale_abort_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposal = _proposal()
            validator = mock.Mock(side_effect=[
                ({}, proposal, {"resolution": "uncertain"}),
                execution.ClaimQueueExecutionConflict("changed"),
            ])

            def stale(*_args, **kwargs):
                current = kwargs["claim_execution"]
                budget = current["request_budget"]
                reservation = budget.reserve({"model": "x", "max_tokens": 32})
                budget.commit(reservation, {"total_tokens": 41})
                current["pre_publish_check"]()

            with self.assertRaises(execution.ClaimQueueExecutionConflict):
                self._run(root, stale, validator=validator)
            rows = claim_reextract_attempts.read_attempt_log(root).rows

        self.assertEqual(rows[-1]["event_kind"], "reextract_aborted_stale")
        self.assertEqual(rows[-1]["usage"]["total_tokens"], 41)
        self.assertFalse(any(row["event_kind"] == "requirements_published" for row in rows))

    def test_post_publication_refresh_failure_projects_rebuild_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refresh = mock.Mock(side_effect=RuntimeError("fold unavailable"))
            with self.assertRaises(execution.ClaimQueueExecutionUnavailable) as raised:
                self._run(
                    root,
                    self._successful_targeted(root),
                    refresh=refresh,
                )
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            state = claim_reextract_attempts.derive_attempt_states(rows)
            current = next(iter(state.values()))

        self.assertEqual(raised.exception.result["lifecycle"], "rebuild_pending")
        self.assertEqual(current["lifecycle"], "rebuild_pending")
        self.assertEqual(rows[-1]["event_kind"], "requirements_published")

    def test_same_idempotency_key_replays_terminal_without_revalidating_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, _refresh = self._run(root, self._successful_targeted(root))
            proposal = _proposal()
            route_config = mock.Mock(
                side_effect=AssertionError("terminal replay must not load LLM config")
            )
            with mock.patch.object(
                ai_extract, "config_for_route", route_config,
            ), mock.patch.object(
                execution, "load_committed_effective_snapshot",
                return_value=_final_snapshot(proposal),
            ), mock.patch.object(
                execution, "assess_effective_freshness",
                return_value={"effective_fresh": True, "freshness_reasons": []},
            ), mock.patch.object(
                execution,
                "_validate_current_proposal",
                side_effect=AssertionError("terminal replay must not require a live proposal"),
            ):
                second = execution.execute_claim_queue_proposal(
                    root,
                    proposal_id=proposal["proposal_id"],
                    expected_claim_effective_revision=proposal[
                        "claim_effective_revision"
                    ],
                    expected_ledger_state="uncertain",
                    actor="expert:yyh",
                    allow_llm=True,
                    route="openai_compatible",
                    maximum_calls=4,
                    total_token_budget=20000,
                    request_idempotency_key="request-1",
                )
            rows = claim_reextract_attempts.read_attempt_log(root).rows

        self.assertEqual(second["attempt_id"], first["attempt_id"])
        self.assertTrue(second["idempotent_replay"])
        route_config.assert_not_called()
        self.assertEqual(
            sum(row["event_kind"] == "reextract_started" for row in rows),
            1,
        )

    def test_rebuild_pending_retry_is_deterministic_and_does_not_repeat_paid_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_refresh = mock.Mock(side_effect=RuntimeError("fold unavailable"))
            with self.assertRaises(execution.ClaimQueueExecutionUnavailable):
                self._run(
                    root,
                    self._successful_targeted(root),
                    refresh=first_refresh,
                )
            proposal = _proposal()
            second_refresh = mock.Mock(return_value={
                "kind": "claim_shadow_refresh",
                "claim_shadow": {"effective_fresh": True},
            })
            route_config = mock.Mock(
                side_effect=AssertionError(
                    "deterministic recovery must not require LLM configuration"
                )
            )
            with mock.patch.object(
                ai_extract, "config_for_route", route_config,
            ), mock.patch.object(
                execution, "_load_b_track_authority",
                return_value={"target_publication_revision": _hash("new-publication")},
            ), mock.patch.object(
                ai_extract, "refresh_claim_shadow", second_refresh,
            ), mock.patch.object(
                execution, "load_committed_effective_snapshot",
                return_value=_final_snapshot(proposal),
            ), mock.patch.object(
                execution, "assess_effective_freshness",
                return_value={"effective_fresh": True, "freshness_reasons": []},
            ), mock.patch.object(
                execution,
                "targeted_reextract",
                side_effect=AssertionError("recovery must not repeat extraction"),
            ):
                recovered = execution.execute_claim_queue_proposal(
                    root,
                    proposal_id=proposal["proposal_id"],
                    expected_claim_effective_revision=proposal[
                        "claim_effective_revision"
                    ],
                    expected_ledger_state="uncertain",
                    actor="expert:yyh",
                    allow_llm=True,
                    route="openai_compatible",
                    maximum_calls=4,
                    total_token_budget=20000,
                    request_idempotency_key="request-1",
                )
            rows = claim_reextract_attempts.read_attempt_log(root).rows

        self.assertEqual(recovered["lifecycle"], "executed")
        self.assertEqual(
            sum(row["event_kind"] == "reextract_started" for row in rows),
            1,
        )
        self.assertEqual(rows[-1]["event_kind"], "reextract_succeeded")
        route_config.assert_not_called()
        self.assertIsNone(second_refresh.call_args.kwargs["route"])
        self.assertFalse(second_refresh.call_args.kwargs["allow_llm"])

    def test_terminal_replay_repairs_stale_queue_without_llm_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, self._successful_targeted(root))
            proposal = _proposal()
            stale = _final_snapshot(proposal)
            stale["effective_ledger"][0]["resolution"] = "uncertain"
            stale["queue_proposals"] = [{
                "proposal_id": proposal["proposal_id"],
                "claim_id": proposal["claim_id"],
                "claim_effective_revision": stale["effective_ledger"][0][
                    "claim_effective_revision"
                ],
                "lifecycle": "rebuild_pending",
                "latest_attempt": {
                    "attempt_id": "CRA-stale",
                    "lifecycle": "rebuild_pending",
                },
            }]
            projected = copy.deepcopy(stale)
            attempt_id = execution.make_attempt_id(
                proposal["proposal_id"], "request-1"
            )
            projected["queue_proposals"][0].update({
                "lifecycle": "executed",
                "latest_attempt": {
                    "attempt_id": attempt_id,
                    "lifecycle": "succeeded",
                },
            })
            route_config = mock.Mock(
                side_effect=AssertionError("terminal replay must not load LLM config")
            )
            fold = mock.Mock(return_value={"ok": True})
            with mock.patch.object(
                ai_extract, "config_for_route", route_config,
            ), mock.patch.object(
                execution, "load_committed_effective_snapshot",
                side_effect=[stale, projected],
            ), mock.patch.object(
                execution, "assess_effective_freshness",
                return_value={"effective_fresh": True, "freshness_reasons": []},
            ), mock.patch(
                "claim_review_actions.fold_effective_ledger", fold,
            ):
                result = execution.execute_claim_queue_proposal(
                    root,
                    proposal_id=proposal["proposal_id"],
                    expected_claim_effective_revision=proposal[
                        "claim_effective_revision"
                    ],
                    expected_ledger_state="uncertain",
                    actor="expert:yyh",
                    allow_llm=True,
                    route="openai_compatible",
                    maximum_calls=4,
                    total_token_budget=20000,
                    request_idempotency_key="request-1",
                )

        self.assertTrue(result["idempotent_replay"])
        route_config.assert_not_called()
        fold.assert_called_once()

    def test_real_claim_mode_uses_usage_bearing_chat_and_never_writes_omissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = "The output shall be configurable by the operator."
            block = {
                "block_id": "B1",
                "order": 1,
                "type": "paragraph",
                "text": source,
                "section_path": ["4 Functions"],
            }
            atomic_write_jsonl(root / "blocks.jsonl", [block])
            atomic_write_jsonl(root / ai_extract.AI_REQUIREMENTS, [])
            omission_path = root / omission_actions.OMISSION_STATES
            omission_path.write_bytes(b'{"legacy":true}\n')
            before = omission_path.read_bytes()
            focus = {
                "kind": "text_span",
                "adapter_version": "claim-focus-adapter-v1",
                "claim_id": "CLM-0123456789abcdef",
                "claim_hash": _hash("claim"),
                "block_id": "B1",
                "parent_block_fingerprint": _hash("block"),
                "start": 0,
                "end": len(source),
                "text_hash": _hash("text"),
                "text": source,
            }
            section = {
                "section_id": "S1",
                "heading": "4 Functions",
                "text": source,
                "block_ids": ["B1"],
            }
            budget = execution.LLMRequestBudget(max_calls=2, max_tokens=20000)
            seen_budget = []
            callbacks: list[str] = []
            baseline_cost = {
                "call_count": 1,
                "failed_call_count": 0,
                "total_tokens": 123,
                "usage_complete": True,
                "lineage_version": "no-ledger-baseline-lineage-v2",
                "lineage_fingerprint": _hash("baseline"),
                "lineage_context": {"input_fingerprint": "input"},
                "lineage_match": True,
            }

            def chat_with_meta(_config, _system, _user, *, request_budget):
                seen_budget.append(request_budget)
                return {"rows": [{
                    "title": "Configurable output",
                    "description": source,
                    "source_section": "4",
                    "source_quote": source,
                    "source_block_ids": ["B1"],
                    "module": "interface",
                    "sub_items": [],
                    "acceptance_criteria": [],
                }]}, {
                    "usage": {"total_tokens": 88},
                    "usage_complete": True,
                    "call_count": 1,
                    "failed_call_count": 0,
                }

            def critique(_section, _existing, chat, *_args, **_kwargs):
                payload = chat("system", "user")
                return payload["rows"], []

            with mock.patch(
                "api_server.final_ai_requirements_are_stale", return_value=False,
            ), mock.patch.object(
                ai_extract, "ai_requirements_producer_is_current", return_value=True,
            ), mock.patch.object(
                omission_actions, "_find_target_section",
                return_value=([block], section, [section]),
            ), mock.patch.object(
                ai_extract, "config_for_route", return_value=self.config,
            ), mock.patch(
                "llm_client.apply_min_tokens", side_effect=lambda value, _purpose: value,
            ), mock.patch.object(
                ai_extract, "build_doc_context", return_value="",
            ), mock.patch.object(
                ai_extract, "critique_section", side_effect=critique,
            ), mock.patch.object(
                ai_extract, "write_compliance_requirements", return_value={},
            ), mock.patch.object(
                ai_extract, "refresh_ai_extract_quality",
                return_value={
                    "failed_sections": 0,
                    "failed_section_ids": [],
                    "failed_section_block_ids": [],
                    "no_ledger_baseline_cost": baseline_cost,
                },
            ), mock.patch.object(
                ai_extract, "write_ai_requirements_metadata",
            ) as metadata_writer, mock.patch.object(
                ai_extract, "rebuild_merged_spec", return_value={"written": []},
            ):
                result = omission_actions.targeted_reextract(
                    root,
                    block_id="B1",
                    actor="expert:yyh",
                    route="openai_compatible",
                    expected_source_fingerprint=(
                        omission_actions.omission_source_fingerprint("B1", source)
                    ),
                    claim_execution={
                        "proposal_id": "CQP-12345678-9abcdef0",
                        "attempt_id": "CRA-0123456789abcdef",
                        "claim_id": "CLM-0123456789abcdef",
                        "claim_hash": _hash("claim"),
                        "focus": focus,
                        "request_budget": budget,
                        "pre_publish_check": lambda: callbacks.append("cas"),
                        "on_supplement_persisted": (
                            lambda _patch: callbacks.append("supplement")
                        ),
                        "on_requirements_published": (
                            lambda _rows: callbacks.append("requirements")
                        ),
                        "chat_with_meta": chat_with_meta,
                    },
                )
            after = omission_path.read_bytes()
            requirements = ai_extract.read_jsonl(root / ai_extract.AI_REQUIREMENTS)

        self.assertEqual(result["schema"], "claim-reextract-mutation/v1")
        self.assertEqual(callbacks, ["cas", "supplement", "requirements"])
        self.assertEqual(seen_budget, [budget])
        self.assertEqual(len(requirements), 1)
        self.assertEqual(after, before)
        self.assertEqual(
            metadata_writer.call_args.kwargs["no_ledger_baseline_cost"],
            baseline_cost,
        )
        self.assertEqual(
            result["supplement"]["strategy_version"],
            omission_actions.CLAIM_AI_SUPPLEMENT_VERSION,
        )
        self.assertEqual(result["supplement"]["origin"]["kind"], "claim_queue")

    def test_unsupported_supplement_version_reports_replay_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic_write_jsonl(root / "blocks.jsonl", [{
                "block_id": "B1", "text": "Source",
            }])
            atomic_write_jsonl(root / omission_actions.AI_SUPPLEMENTS, [{
                "supplement_id": "SUP-unsupported",
                "strategy_version": "ai-supplement-v999",
                "block_id": "B1",
            }])
            diagnostics: list[dict] = []
            rows = omission_actions.apply_supplement_patches(
                root,
                [],
                diagnostics=diagnostics,
            )

        self.assertEqual(rows, [])
        self.assertEqual(diagnostics[0]["reason"], "unsupported_strategy_version")


if __name__ == "__main__":
    unittest.main()
