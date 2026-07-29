from __future__ import annotations

import copy
import json
import unittest

import claim_catalog
import claim_ledger
from llm_client import LLMBudgetExceeded, LLMClientConfig, LLMRequestBudget


def _block(block_id: str, text: str, *, order: int = 1) -> dict:
    return {
        "block_id": block_id,
        "order": order,
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
    }


def _requirement(
    requirement_id: str,
    *,
    description: str,
    source_quote: str,
    block_ids: list[str] | None = None,
    **extra: object,
) -> dict:
    row = {
        "ai_req_id": requirement_id,
        "title": "Requirement",
        "description": description,
        "source_quote": source_quote,
        "source_block_ids": block_ids or ["B1"],
        "sub_items": [],
        "acceptance_criteria": [],
    }
    row.update(extra)
    return row


def _verified_baseline_cost(
    *,
    call_count: int = 10,
    total_tokens: int = 1000,
) -> dict:
    return {
        "call_count": call_count,
        "failed_call_count": 0,
        "total_tokens": total_tokens,
        "usage_complete": True,
        "lineage_match": True,
        "lineage_version": "test-lineage-v1",
        "lineage_fingerprint": "sha256:" + "a" * 64,
        "lineage_context": {"input_fingerprint": "b" * 64},
    }


class ProtectedFactPrefilterTests(unittest.TestCase):
    def test_missing_code_number_and_unit_are_rejected_without_verifier(self) -> None:
        claim = "Use OBIS 1-0:1.8.0.255 and retain 12 months at 230 V."
        evidence = [{"text": "保留 12 个月的数据。"}]
        result = claim_ledger.reject_only_prefilter(claim, evidence)
        self.assertEqual(result["status"], "reject")
        kinds = {fact["kind"] for fact in result["missing_protected_facts"]}
        self.assertIn("code", kinds)
        self.assertIn("unit_value", kinds)

    def test_preserved_facts_pass_but_do_not_validate_semantics(self) -> None:
        claim = "The port shall operate at 230 V for 12 months."
        evidence = [{"text": "端口参数为 230 V，记录期限为 12 months。"}]
        result = claim_ledger.reject_only_prefilter(claim, evidence)
        self.assertEqual(result["status"], "pass")
        self.assertNotIn("validated", result)

    def test_no_protected_facts_is_not_applicable(self) -> None:
        result = claim_ledger.reject_only_prefilter(
            "Auxiliary outputs are user-programmable.",
            [{"text": "辅助输出可由用户编程。"}],
        )
        self.assertEqual(result["status"], "not_applicable")

    def test_controlled_term_uses_only_declared_aliases(self) -> None:
        aliases = {"auxiliary output": ["辅助输出"]}
        passed = claim_ledger.reject_only_prefilter(
            "The auxiliary output is configurable.",
            [{"text": "辅助输出可以配置。"}],
            controlled_term_aliases=aliases,
        )
        rejected = claim_ledger.reject_only_prefilter(
            "The auxiliary output is configurable.",
            [{"text": "端口可以配置。"}],
            controlled_term_aliases=aliases,
        )
        self.assertEqual(passed["status"], "pass")
        self.assertEqual(rejected["status"], "reject")


class EvidenceLocatorTests(unittest.TestCase):
    def test_cross_language_evidence_is_locatable_without_equaling_source(self) -> None:
        requirement = _requirement(
            "AIR-1",
            description="辅助输出可通过用户程序配置。",
            source_quote="Auxiliary outputs are user-programmable.",
        )
        evidence = claim_ledger.target_evidence(requirement)
        description = next(row for row in evidence if row["field"] == "description")
        self.assertEqual(description["text"], "辅助输出可通过用户程序配置。")
        self.assertTrue(claim_ledger.evidence_is_current(description, requirement))
        self.assertNotEqual(description["text"], requirement["source_quote"])

    def test_sub_item_and_acceptance_paths_include_item_index(self) -> None:
        requirement = _requirement(
            "AIR-1",
            description="主描述",
            source_quote="source",
            sub_items=[{"label": "a", "text": "子项 A"}],
            acceptance_criteria=["验收 A"],
        )
        evidence = claim_ledger.target_evidence(requirement)
        self.assertIn(("sub_items", 0), {(row["field"], row["item_index"]) for row in evidence})
        self.assertIn(("acceptance_criteria", 0),
                      {(row["field"], row["item_index"]) for row in evidence})


class EffectiveAuthorityIdentityTests(unittest.TestCase):
    def test_b_track_review_revision_excludes_timestamp_and_free_form_rationale(self) -> None:
        requirement = _requirement(
            "AIR-1",
            description="该产品应支持配置指示通道。",
            source_quote="The indicator channel can be configured by the operator.",
        )
        source = claim_ledger.target_source_fingerprint(requirement)
        subject = claim_ledger.target_fingerprint(requirement)
        first = claim_ledger.b_track_effective_authority([requirement], {
            "AIR-1": {
                "ai_req_id": "AIR-1",
                "status": "accepted",
                "source_fingerprint": source,
                "review_subject_fingerprint": subject,
                "reason": "first rationale",
                "recorded_at": "2026-07-28T00:00:00+00:00",
            },
        })
        second = claim_ledger.b_track_effective_authority([requirement], {
            "AIR-1": {
                "ai_req_id": "AIR-1",
                "status": "accepted",
                "source_fingerprint": source,
                "review_subject_fingerprint": subject,
                "reason": "rewritten rationale",
                "recorded_at": "2026-07-29T00:00:00+00:00",
            },
        })
        self.assertEqual(
            first["records"][0]["review"]["target_review_revision"],
            second["records"][0]["review"]["target_review_revision"],
        )
        self.assertEqual(
            first["requirement_review_state_hash"],
            second["requirement_review_state_hash"],
        )

    def test_b_track_legacy_review_is_unknown_and_duplicate_target_is_ambiguous(self) -> None:
        requirement = _requirement(
            "AIR-1", description="需求", source_quote="Requirement",
        )
        legacy = claim_ledger.b_track_effective_authority([requirement], {
            "AIR-1": {"ai_req_id": "AIR-1", "status": "accepted"},
        })
        self.assertEqual(legacy["records"][0]["review"]["eligibility"], "unknown")
        self.assertTrue(legacy["records"][0]["review"]["needs_reconfirmation"])

        duplicate = claim_ledger.b_track_effective_authority(
            [requirement, copy.deepcopy(requirement)],
            {},
        )
        self.assertTrue(all(
            row["review"]["reason"] == "duplicate_target_requirement_id"
            and row["review"]["eligibility"] == "unknown"
            for row in duplicate["records"]
        ))

    def test_semantic_validation_identity_excludes_review_but_includes_both_locators(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )
        group = claim_ledger.build_shadow_ledger(catalog, [requirement])["groups"][0]
        baseline = claim_ledger.semantic_validation_fingerprint(group)

        review_only = copy.deepcopy(group)
        review_only["edges"][0]["target_review_revision"] = "sha256:" + "f" * 64
        self.assertEqual(
            claim_ledger.semantic_validation_fingerprint(review_only),
            baseline,
        )

        source_locator_changed = copy.deepcopy(group)
        source_locator_changed["source_evidence"]["claim_start"] += 1
        self.assertNotEqual(
            claim_ledger.semantic_validation_fingerprint(source_locator_changed),
            baseline,
        )

        target_locator_changed = copy.deepcopy(group)
        target_locator_changed["edges"][0]["produced_evidence"][0]["start"] += 1
        self.assertNotEqual(
            claim_ledger.semantic_validation_fingerprint(target_locator_changed),
            baseline,
        )

    def test_semantic_validation_reuse_skips_dirty_legacy_target_fingerprint(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1",
            description="Auxiliary outputs are user-programmable.",
            source_quote=source,
        )
        current = claim_ledger.build_shadow_ledger(catalog, [requirement])["groups"][0]
        previous = copy.deepcopy(current)
        previous.update({
            "status": "validated",
            "validator_request_id": "REQ-legacy-validation",
            "validation_source": {
                "request_id": "REQ-legacy-validation",
                "generation_run_id": "legacy-run",
            },
        })
        previous["edges"][0]["target_fingerprint"] = "legacy-not-a-canonical-hash"

        reused = claim_ledger._reuse_semantic_validation([current], [previous])

        self.assertEqual(reused, 0)
        self.assertEqual(current["status"], "proposed")
        self.assertFalse(current["validation_reused"])


class SemanticVerifierAdapterTests(unittest.TestCase):
    def test_obligation_framing_prompt_distinguishes_governing_wrapper_from_neighbor(self) -> None:
        prompt = " ".join(claim_ledger._SEMANTIC_VERIFIER_SYSTEM.split())
        self.assertIn("syntactically governs", prompt)
        self.assertIn("colon-headed capability complement", prompt)
        self.assertIn("unrelated neighboring sentence or clause", prompt)

    def test_target_obligation_framing_is_a_required_coverage_check(self) -> None:
        self.assertIn(
            "target_obligation_framing",
            claim_ledger.SEMANTIC_COVERAGE_CHECKS,
        )
        checks = {
            name: name != "target_obligation_framing"
            for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
        }
        self.assertFalse(claim_ledger._semantic_checks_complete({"checks": checks}))

    def test_adapter_batches_requests_and_uses_transport_usage_once(self) -> None:
        seen: list[tuple[str, dict]] = []

        def chat(system: str, user: str) -> tuple[dict, dict]:
            payload = __import__("json").loads(user)
            seen.append((system, payload))
            group_ref = payload["groups"][0][0]
            return ({
                "decisions": [[group_ref, True, [True] * len(
                    claim_ledger.SEMANTIC_COVERAGE_CHECKS
                )]],
            }, {
                "usage": {"total_tokens": 37},
                "usage_complete": True,
            })

        verifier = claim_ledger.make_semantic_coverage_verifier(chat)
        result = verifier("UNIT-1", [{
            "coverage_group_id": "CGR-1",
            "source_evidence": {"text": "source"},
            "edges": [],
        }])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1]["batch_id"], "UNIT-1")
        self.assertEqual(seen[0][1]["schema"], "claim-coverage-verifier-request/v2")
        self.assertEqual(result["tokens"], 37)
        self.assertTrue(result["usage_complete"])
        self.assertEqual(result["operation_failure_count"], 0)
        self.assertTrue(result["decisions"]["CGR-1"]["covered"])

    def test_adapter_marks_zero_token_provider_usage_incomplete(self) -> None:
        def chat(_system: str, user: str) -> tuple[dict, dict]:
            payload = __import__("json").loads(user)
            group_ref = payload["groups"][0][0]
            return ({
                "decisions": [[group_ref, True, [True] * len(
                    claim_ledger.SEMANTIC_COVERAGE_CHECKS
                )]],
            }, {
                "usage": {"total_tokens": 0},
                "usage_complete": True,
                "call_count": 1,
            })

        result = claim_ledger.make_semantic_coverage_verifier(chat)(
            "UNIT-1", [{"coverage_group_id": "CGR-1"}],
        )

        self.assertEqual(result["call_count"], 1)
        self.assertEqual(result["tokens"], 0)
        self.assertFalse(result["usage_complete"])

    def test_budget_exhaustion_is_not_converted_to_failed_adapter_result(self) -> None:
        budget = LLMRequestBudget(max_calls=1, max_tokens=100000)

        def chat(_system: str, _user: str) -> tuple[dict, dict]:
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 1})
            return ({"decisions": []}, {
                "usage": {"total_tokens": 1},
                "usage_complete": True,
            })

        verifier = claim_ledger.make_semantic_coverage_verifier(chat, rounds=2)
        with self.assertRaises(LLMBudgetExceeded):
            verifier("UNIT-1", [{"coverage_group_id": "CGR-1"}])

    def test_adapter_drops_duplicate_or_unknown_decisions(self) -> None:
        def chat(_system: str, _user: str) -> tuple[dict, dict]:
            decision = {"coverage_group_id": "CGR-1", "covered": True, "checks": {}}
            return ({"decisions": [decision, decision, {
                "coverage_group_id": "CGR-other", "covered": True, "checks": {},
            }]}, {"usage": {"total_tokens": 1}, "usage_complete": True})

        result = claim_ledger.make_semantic_coverage_verifier(chat)(
            "UNIT-1", [{"coverage_group_id": "CGR-1"}],
        )
        self.assertEqual(result["decisions"], {})
        self.assertEqual(result["operation_failure_count"], 1)

    def test_adapter_rejects_non_boolean_covered_without_coercing_to_unknown(self) -> None:
        def tuple_chat(_system: str, user: str) -> tuple[dict, dict]:
            payload = __import__("json").loads(user)
            group_ref = payload["groups"][0][0]
            return ({
                "decisions": [[group_ref, "yes", [True] * len(
                    claim_ledger.SEMANTIC_COVERAGE_CHECKS
                )]],
            }, {"usage": {"total_tokens": 1}, "usage_complete": True})

        def object_chat(_system: str, _user: str) -> tuple[dict, dict]:
            return ({
                "decisions": [{
                    "coverage_group_id": "CGR-1",
                    "covered": 1,
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                    },
                }],
            }, {"usage": {"total_tokens": 1}, "usage_complete": True})

        for chat in (tuple_chat, object_chat):
            with self.subTest(response_shape=chat.__name__):
                result = claim_ledger.make_semantic_coverage_verifier(chat)(
                    "UNIT-1", [{"coverage_group_id": "CGR-1"}],
                )
                self.assertEqual(result["decisions"], {})
                self.assertEqual(result["operation_failure_count"], 1)

    def test_adapter_rejects_incomplete_or_inconsistent_object_decisions(self) -> None:
        valid_checks = {
            name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
        }
        malformed = (
            {"coverage_group_id": "CGR-1", "checks": valid_checks},
            {"coverage_group_id": "CGR-1", "covered": True},
            {
                "coverage_group_id": "CGR-1",
                "covered": True,
                "checks": {**valid_checks, "unexpected": True},
            },
            {
                "coverage_group_id": "CGR-1",
                "covered": True,
                "checks": {**valid_checks, "subject": 1},
            },
            {
                "coverage_group_id": "CGR-1",
                "covered": True,
                "checks": {**valid_checks, "subject": False},
            },
            {
                "coverage_group_id": "CGR-1",
                "covered": False,
                "checks": valid_checks,
            },
        )

        for index, decision in enumerate(malformed):
            with self.subTest(case=index):
                def chat(_system: str, _user: str) -> tuple[dict, dict]:
                    return (
                        {"decisions": [decision]},
                        {"usage": {"total_tokens": 1}, "usage_complete": True},
                    )

                result = claim_ledger.make_semantic_coverage_verifier(chat)(
                    "UNIT-1", [{"coverage_group_id": "CGR-1"}],
                )
                self.assertEqual(result["decisions"], {})
                self.assertEqual(result["operation_failure_count"], 1)

    def test_adapter_accepts_explicit_unknown_with_complete_boolean_checks(self) -> None:
        def chat(_system: str, user: str) -> tuple[dict, dict]:
            payload = __import__("json").loads(user)
            group_ref = payload["groups"][0][0]
            checks = [False] + [True] * (
                len(claim_ledger.SEMANTIC_COVERAGE_CHECKS) - 1
            )
            return (
                {"decisions": [[group_ref, None, checks]]},
                {"usage": {"total_tokens": 1}, "usage_complete": True},
            )

        result = claim_ledger.make_semantic_coverage_verifier(chat)(
            "UNIT-1", [{"coverage_group_id": "CGR-1"}],
        )

        self.assertEqual(result["operation_failure_count"], 0)
        self.assertIsNone(result["decisions"]["CGR-1"]["covered"])

    def test_round_disagreement_is_uncertain_and_costs_each_request(self) -> None:
        calls = 0

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            nonlocal calls
            calls += 1
            payload = __import__("json").loads(user)
            group_ref = payload["groups"][0][0]
            covered = calls == 1
            return ({
                "decisions": [[group_ref, covered, [covered] * len(
                    claim_ledger.SEMANTIC_COVERAGE_CHECKS
                )]],
            }, {"usage": {"total_tokens": 10}, "usage_complete": True})

        result = claim_ledger.make_semantic_coverage_verifier(chat, rounds=2)(
            "UNIT-1", [{"coverage_group_id": "CGR-1"}],
        )
        self.assertEqual(calls, 2)
        self.assertEqual(result["call_count"], 2)
        self.assertEqual(result["tokens"], 20)
        self.assertEqual(result["operation_failure_count"], 0)
        self.assertIsNone(result["decisions"]["CGR-1"]["covered"])

    def test_negative_adapter_is_proposal_blind_and_rejects_round_disagreement(self) -> None:
        calls = 0

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            nonlocal calls
            calls += 1
            payload = __import__("json").loads(user)
            claim = payload["claims"][0]
            self.assertNotIn("unit_context", claim)
            self.assertNotIn("proposal", claim)
            self.assertNotIn("reason", claim)
            self.assertEqual(
                payload["unit_contexts"][claim["unit_ref"]]["prompt_hash"],
                "sha256:context",
            )
            return ({"decisions": [{
                "claim_id": claim["claim_id"],
                "non_normative": True,
                "reason": "informative" if calls == 1 else "example",
                "checks": {
                    name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                },
                "evidence": [{"start": 0, "end": 6, "text": "Source"}],
            }]}, {"usage": {"total_tokens": 5}, "usage_complete": True})

        result = claim_ledger.make_semantic_negative_verifier(chat, rounds=2)(
            "UNIT-1",
            [{
                "claim_id": "CLM-1",
                "claim_hash": "sha256:claim",
                "source_evidence": {"text": "Source"},
                "unit_context": {"prompt": "Source", "prompt_hash": "sha256:context"},
            }],
        )

        self.assertEqual(result["call_count"], 2)
        self.assertEqual(result["tokens"], 10)
        self.assertEqual(result["operation_failure_count"], 0)
        decision = result["decisions"]["CLM-1"]
        self.assertEqual(decision["reason"], "")
        self.assertTrue(decision["disagreement"])

    def test_negative_verifier_counts_missing_decision_as_operation_failure(self) -> None:
        def chat(_system: str, _user: str) -> tuple[dict, dict]:
            return (
                {"decisions": []},
                {"usage": {"total_tokens": 5}, "usage_complete": True},
            )

        result = claim_ledger.make_semantic_negative_verifier(chat)(
            "UNIT-1",
            [{
                "claim_id": "CLM-1",
                "source_evidence": {"text": "Source"},
                "unit_context": {"prompt": "Source", "prompt_hash": "sha256:context"},
            }],
        )
        self.assertEqual(result["decisions"], {})
        self.assertEqual(result["operation_failure_count"], 1)

    def test_negative_verifier_rejects_malformed_or_inconsistent_decisions(self) -> None:
        valid_checks = {
            name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
        }
        valid_evidence = [{"start": 0, "end": 6, "text": "Source"}]
        malformed = (
            {
                "claim_id": "CLM-1",
                "non_normative": 1,
                "reason": "informative",
                "checks": valid_checks,
                "evidence": valid_evidence,
            },
            {
                "claim_id": "CLM-1",
                "reason": "informative",
                "checks": valid_checks,
                "evidence": valid_evidence,
            },
            {
                "claim_id": "CLM-1",
                "non_normative": True,
                "reason": "informative",
                "checks": {**valid_checks, "unexpected": True},
                "evidence": valid_evidence,
            },
            {
                "claim_id": "CLM-1",
                "non_normative": True,
                "reason": "informative",
                "checks": {**valid_checks, "reason_supported": 1},
                "evidence": valid_evidence,
            },
            {
                "claim_id": "CLM-1",
                "non_normative": True,
                "reason": "informative",
                "checks": {**valid_checks, "reason_supported": False},
                "evidence": valid_evidence,
            },
            {
                "claim_id": "CLM-1",
                "non_normative": False,
                "reason": "informative",
                "checks": valid_checks,
                "evidence": valid_evidence,
            },
            {
                "claim_id": "CLM-1",
                "non_normative": True,
                "reason": "informative",
                "checks": valid_checks,
                "evidence": [{"start": 0, "end": 6, "text": "stale!"}],
            },
        )

        for index, decision in enumerate(malformed):
            with self.subTest(case=index):
                def chat(_system: str, _user: str) -> tuple[dict, dict]:
                    return (
                        {"decisions": [decision]},
                        {"usage": {"total_tokens": 5}, "usage_complete": True},
                    )

                result = claim_ledger.make_semantic_negative_verifier(chat)(
                    "UNIT-1",
                    [{
                        "claim_id": "CLM-1",
                        "source_evidence": {"text": "Source"},
                        "unit_context": {
                            "prompt": "Source",
                            "prompt_hash": "sha256:context",
                        },
                    }],
                )
                self.assertEqual(result["decisions"], {})
                self.assertEqual(result["operation_failure_count"], 1)


class VerifierBatchPolicyTests(unittest.TestCase):
    @staticmethod
    def _runtime() -> dict:
        config = LLMClientConfig(
            base_url="https://verifier.invalid/v1",
            model="deepseek-chat",
            temperature=0.0,
            max_tokens=8192,
        )
        return claim_ledger.semantic_verifier_runtime(
            route_mode="llm",
            enabled=True,
            rounds=1,
            config=config,
        )

    @staticmethod
    def _coverage_request(index: int, evidence_text: str) -> dict:
        return {
            "coverage_group_id": f"CGR-{index}",
            "claim_id": f"CLM-{index}",
            "claim_hash": f"sha256:{index:064x}",
            "source_evidence": {"text": f"Source claim {index}"},
            "edges": [{
                "target_requirement_id": f"AIR-{index}",
                "target_fingerprint": f"sha256:{index + 1:064x}",
                "produced_evidence": [{"text": evidence_text}],
            }],
        }

    @staticmethod
    def _coverage_payload(batch: list[dict]) -> dict:
        evidence, groups, _ids = claim_ledger._compact_coverage_transport(batch)
        return {"target_evidence": evidence, "groups": groups}

    @staticmethod
    def _coverage_http_payload(
        batch: list[dict], runtime: dict, batch_index: int = 1,
    ) -> dict:
        user_request = claim_ledger._coverage_verifier_request_payload(
            batch,
            batch_id=f"COVERAGE-BATCH-{batch_index:04d}",
            request_id="CVR-" + "a" * 32,
            round_index=1,
        )
        return claim_ledger._verifier_http_payload(
            runtime,
            claim_ledger._SEMANTIC_VERIFIER_SYSTEM,
            user_request,
        )

    @staticmethod
    def _negative_request(index: int, prompt: str) -> dict:
        return {
            "claim_id": f"CLM-{index}",
            "source_evidence": {
                "text": f"Source claim {index}",
                "claim_start": 0,
                "claim_end": 14,
            },
            "unit_context": {
                "unit_id": f"UNIT-{index}",
                "section_path": ["4 Functions"],
                "prompt": prompt,
                "prompt_hash": f"sha256:{index:064x}",
            },
        }

    def test_cjk_batches_are_bounded_by_wire_serialization_size(self) -> None:
        runtime = self._runtime()
        rows = [
            self._coverage_request(index, "\u914d\u7f6e" * 1500)
            for index in range(1, 5)
        ]

        batches, oversized = claim_ledger._coverage_batches(rows, runtime=runtime)

        self.assertEqual(oversized, [])
        self.assertGreater(len(batches), 1)
        for batch_index, batch in enumerate(batches, start=1):
            payload = self._coverage_http_payload(batch, runtime, batch_index)
            self.assertLessEqual(
                claim_ledger._payload_utf8_size(payload),
                claim_ledger.CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES,
            )
        sample_inner = self._coverage_payload([rows[0]])
        sample_http = self._coverage_http_payload([rows[0]], runtime)
        self.assertGreater(
            claim_ledger._payload_utf8_size(sample_http),
            claim_ledger._payload_utf8_size(sample_inner),
        )
        self.assertEqual(
            json.loads(sample_http["messages"][1]["content"])["schema"],
            "claim-coverage-verifier-request/v2",
        )

    def test_full_http_envelope_rejects_old_compact_payload_boundary(self) -> None:
        runtime = self._runtime()
        low, high = 1, 20_000
        while low < high:
            middle = (low + high + 1) // 2
            row = self._coverage_request(1, "\u914d" * middle)
            if claim_ledger._payload_utf8_size(
                self._coverage_payload([row])
            ) <= claim_ledger.CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES:
                low = middle
            else:
                high = middle - 1
        row = self._coverage_request(1, "\u914d" * low)
        self.assertLessEqual(
            claim_ledger._payload_utf8_size(self._coverage_payload([row])),
            claim_ledger.CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES,
        )
        self.assertGreater(
            claim_ledger._payload_utf8_size(
                self._coverage_http_payload([row], runtime)
            ),
            claim_ledger.CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES,
        )

        batches, oversized = claim_ledger._coverage_batches([row], runtime=runtime)

        self.assertEqual(batches, [])
        self.assertEqual(oversized, [row])

    def test_single_oversized_coverage_request_is_deferred_fail_closed(self) -> None:
        runtime = self._runtime()
        row = self._coverage_request(1, "\u914d\u7f6e" * 5000)

        batches, oversized = claim_ledger._coverage_batches([row], runtime=runtime)

        self.assertEqual(batches, [])
        self.assertEqual(oversized, [row])

    def test_negative_operations_are_bounded_by_their_full_http_bodies(self) -> None:
        runtime = self._runtime()
        rows = [
            self._negative_request(index, "\u8bbe\u5907\u72b6\u6001" * 1000)
            for index in range(1, 4)
        ]
        operations = (
            (
                "proposer",
                claim_ledger._SEMANTIC_NEGATIVE_PROPOSER_SYSTEM,
                lambda batch, index: claim_ledger._negative_proposer_request_payload(
                    batch,
                    batch_id=f"NEGATIVE-PROPOSER-BATCH-{index:04d}",
                    request_id="CNP-" + "b" * 32,
                ),
            ),
            (
                "verifier",
                claim_ledger._SEMANTIC_NEGATIVE_VERIFIER_SYSTEM,
                lambda batch, index: claim_ledger._negative_verifier_request_payload(
                    batch,
                    batch_id=f"NEGATIVE-VERIFIER-BATCH-{index:04d}",
                    request_id="CNV-" + "c" * 32,
                    round_index=1,
                ),
            ),
        )
        for operation, system_prompt, request_payload in operations:
            with self.subTest(operation=operation):
                batches, oversized = claim_ledger._negative_batches(
                    rows,
                    runtime=runtime,
                    operation=operation,
                )
                self.assertEqual(oversized, [])
                self.assertGreater(len(batches), 1)
                for batch_index, batch in enumerate(batches, start=1):
                    http_payload = claim_ledger._verifier_http_payload(
                        runtime,
                        system_prompt,
                        request_payload(batch, batch_index),
                    )
                    self.assertLessEqual(
                        claim_ledger._payload_utf8_size(http_payload),
                        claim_ledger.CLAIM_NEGATIVE_BATCH_MAX_UTF8_BYTES,
                    )


class ShadowCoverageTests(unittest.TestCase):
    @staticmethod
    def _managed_runtime(budget: LLMRequestBudget) -> dict:
        snapshot = budget.snapshot()
        return claim_ledger.semantic_verifier_runtime(
            route_mode="llm",
            enabled=True,
            rounds=1,
            budget_policy_version=LLMRequestBudget.VERSION,
            max_calls=snapshot["max_calls"],
            max_total_tokens=snapshot["max_tokens"],
        )

    def test_coverage_budget_exhaustion_leaves_unprocessed_claim_uncertain(self) -> None:
        labels = [chr(65 + index // 26) + chr(65 + index % 26) for index in range(41)]
        blocks = [
            _block(f"B{index}", f"Output {label} is user-programmable.", order=index)
            for index, label in enumerate(labels, start=1)
        ]
        catalog = claim_catalog.build_claim_catalog(blocks, [], target_chars=1)
        requirements = [
            _requirement(
                f"AIR-{index}",
                description=f"输出 {label} 可由用户编程。",
                source_quote=f"Output {label} is user-programmable.",
                block_ids=[f"B{index}"],
            )
            for index, label in enumerate(labels, start=1)
        ]
        budget = LLMRequestBudget(max_calls=1, max_tokens=100000)

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 7})
            payload = __import__("json").loads(user)
            return ({
                "decisions": [[
                    group[0],
                    True,
                    [True] * len(claim_ledger.SEMANTIC_COVERAGE_CHECKS),
                ] for group in payload["groups"]],
            }, {"usage": {"total_tokens": 7}, "usage_complete": True})

        result = claim_ledger.build_shadow_ledger(
            catalog,
            requirements,
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
            verifier_runtime=self._managed_runtime(budget),
            verifier_budget=budget,
        )

        self.assertEqual(result["meta"]["termination_reason"], "budget_exhausted")
        self.assertEqual(sum(row["resolution"] == "covered" for row in result["ledger"]), 24)
        self.assertEqual(sum(row["resolution"] == "uncertain" for row in result["ledger"]), 17)
        self.assertEqual(result["metrics"]["verifier_call_count"], 1)
        self.assertTrue(result["metrics"]["verifier_budget_denied"])
        self.assertIn("proposed", {group["status"] for group in result["groups"]})

    def test_exactly_consumed_budget_can_still_converge(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )
        budget = LLMRequestBudget(max_calls=1, max_tokens=100000)

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 7})
            group_ref = __import__("json").loads(user)["groups"][0][0]
            return ({"decisions": [[group_ref, True, [True] * len(
                claim_ledger.SEMANTIC_COVERAGE_CHECKS
            )]]}, {
                "usage": {"total_tokens": 7}, "usage_complete": True,
            })

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
            verifier_runtime=self._managed_runtime(budget),
            verifier_budget=budget,
        )
        self.assertEqual(result["ledger"][0]["resolution"], "covered")
        self.assertEqual(result["meta"]["termination_reason"], "converged")
        self.assertFalse(result["meta"]["verifier_budget"]["denied"])

    def test_successful_provider_call_with_invalid_envelope_is_an_operation_failure(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="Auxiliary outputs are programmable.", source_quote=source,
        )
        budget = LLMRequestBudget(max_calls=1, max_tokens=100000)

        def chat(_system: str, _user: str) -> tuple[dict, dict]:
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 7})
            return (
                {"decisions": []},
                {"usage": {"total_tokens": 7}, "usage_complete": True},
            )

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
            verifier_runtime=self._managed_runtime(budget),
            verifier_budget=budget,
            baseline_cost=_verified_baseline_cost(),
        )

        self.assertEqual(result["metrics"]["verifier_call_count"], 1)
        self.assertEqual(result["metrics"]["verifier_failed_calls"], 0)
        self.assertEqual(result["metrics"]["verifier_operation_failure_count"], 1)
        self.assertTrue(result["metrics"]["verifier_usage_complete"])
        self.assertEqual(result["metrics"]["verifier_cost_gate_status"], "insufficient_data")
        self.assertEqual(result["meta"]["termination_reason"], "llm_error")

    def test_negative_proposer_budget_exhaustion_leaves_claims_open(self) -> None:
        labels = [chr(65 + index // 26) + chr(65 + index % 26) for index in range(49)]
        blocks = [
            _block(f"B{index}", f"For guidance only, example {label} is provided.", order=index)
            for index, label in enumerate(labels, start=1)
        ]
        catalog = claim_catalog.build_claim_catalog(blocks, [], target_chars=1)
        budget = LLMRequestBudget(max_calls=1, max_tokens=100000)

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 5})
            return ({"proposals": []}, {
                "usage": {"total_tokens": 5}, "usage_complete": True,
            })

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=claim_ledger.make_semantic_negative_proposer(chat),
            verifier_runtime=self._managed_runtime(budget),
            verifier_budget=budget,
        )
        self.assertEqual(result["meta"]["termination_reason"], "budget_exhausted")
        self.assertTrue(all(row["resolution"] == "uncertain" for row in result["ledger"]))
        self.assertEqual(result["metrics"]["negative_proposer_call_count"], 1)
        self.assertEqual(result["metrics"]["negative_verifier_call_count"], 0)

    def test_negative_verifier_budget_exhaustion_keeps_proposal_nonterminal(self) -> None:
        source = "For guidance only, this example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        budget = LLMRequestBudget(max_calls=1, max_tokens=100000)

        def chat(system: str, user: str) -> tuple[dict, dict]:
            reservation = budget.reserve({"messages": [], "max_tokens": 1})
            budget.commit(reservation, {"total_tokens": 5})
            claim = __import__("json").loads(user)["claims"][0]
            if "propose, but never validate" in system:
                return ({"proposals": [{
                    "claim_id": claim["claim_id"],
                    "non_normative": True,
                    "reason": "informative",
                    "evidence": [{"start": 0, "end": len(source), "text": source}],
                }]}, {"usage": {"total_tokens": 5}, "usage_complete": True})
            self.fail("negative verifier should be denied before returning a response")

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=claim_ledger.make_semantic_negative_proposer(chat),
            semantic_negative_verifier=claim_ledger.make_semantic_negative_verifier(chat),
            verifier_runtime=self._managed_runtime(budget),
            verifier_budget=budget,
        )
        negative = result["ledger"][0]["semantic_negative"]
        self.assertEqual(result["meta"]["termination_reason"], "budget_exhausted")
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")
        self.assertEqual(negative["status"], "proposed")
        self.assertNotEqual(negative["invalid_reason"], "negative_validator_failed")
    def test_full_verbatim_target_validates_without_semantic_verifier(self) -> None:
        source = "The meter shall provide user-programmable auxiliary outputs."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description=source, source_quote=source,
        )
        result = claim_ledger.build_shadow_ledger(catalog, [requirement])
        self.assertEqual(result["ledger"][0]["resolution"], "covered")
        self.assertEqual(result["groups"][0]["validation_method"], "deterministic_verbatim")
        self.assertEqual(result["groups"][0]["status"], "validated")
        self.assertTrue(all(
            result["groups"][0]["validator_checks"].get(name) is True
            for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
        ))

    def test_weak_verbatim_target_requires_seventh_dimension_validation(self) -> None:
        source = "输出可配置为脉冲模式。"
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description=source, source_quote=source,
        )

        result = claim_ledger.build_shadow_ledger(catalog, [requirement])

        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")
        self.assertEqual(result["groups"][0]["validation_method"], "independent_semantic")
        self.assertEqual(result["groups"][0]["status"], "proposed")

    def test_colon_governed_verbatim_target_is_deterministically_formal(self) -> None:
        source = "输出可配置为脉冲模式。"
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1",
            description=f"产品应支持以下能力：{source}",
            source_quote=source,
        )

        result = claim_ledger.build_shadow_ledger(catalog, [requirement])

        self.assertEqual(result["ledger"][0]["resolution"], "covered")
        self.assertEqual(result["groups"][0]["validation_method"], "deterministic_verbatim")

    def test_cross_language_candidate_remains_uncertain_until_independent_verifier(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )
        result = claim_ledger.build_shadow_ledger(catalog, [requirement])
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")
        self.assertEqual(result["groups"][0]["status"], "proposed")
        self.assertEqual(result["groups"][0]["validation_method"], "independent_semantic")
        self.assertEqual(result["metrics"]["semantic_verifier_candidate_count"], 1)

    def test_short_inexact_quote_fragment_is_not_a_semantic_candidate(self) -> None:
        catalog = claim_catalog.build_claim_catalog([_block("B1", "2")], [])
        requirement = _requirement(
            "AIR-1",
            description="The product shall support configuration of profile two.",
            source_quote="The meter shall expose profile 2.",
            block_ids=["B1"],
        )

        result = claim_ledger.build_shadow_ledger(catalog, [requirement])

        self.assertEqual(result["groups"], [])
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")
        self.assertEqual(result["metrics"]["semantic_verifier_candidate_count"], 0)
        self.assertEqual(result["metrics"]["shared_block_only_hint_count"], 1)

    def test_prefilter_rejection_never_calls_semantic_verifier(self) -> None:
        source = "The output uses OBIS 1-0:1.8.0.255 at 230 V."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="输出可配置。", source_quote=source,
        )
        calls: list[list[dict]] = []

        def verifier(unit_id: str, groups: list[dict]) -> dict:
            calls.append(groups)
            return {}

        result = claim_ledger.build_shadow_ledger(catalog, [requirement], semantic_verifier=verifier)
        self.assertEqual(calls, [])
        self.assertEqual(result["groups"][0]["status"], "invalid")
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")

    def test_independent_verifier_runs_once_per_unit_and_can_validate(self) -> None:
        source = "Auxiliary outputs are user-programmable. Another output is selectable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [], target_chars=500)
        requirements = [
            _requirement("AIR-1", description="辅助输出可由用户编程。",
                         source_quote="Auxiliary outputs are user-programmable."),
            _requirement("AIR-2", description="另一个输出可选择。",
                         source_quote="Another output is selectable."),
        ]
        calls: list[tuple[str, list[str]]] = []

        def verifier(unit_id: str, groups: list[dict]) -> dict:
            calls.append((unit_id, [group["coverage_group_id"] for group in groups]))
            return {
                "request_id": "verify-unit-1",
                "tokens": 20,
                "usage_complete": True,
                "decisions": {
                    group["coverage_group_id"]: {
                        "covered": True,
                        "checks": {
                            name: True
                            for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                        },
                    }
                    for group in groups
                }
            }

        result = claim_ledger.build_shadow_ledger(catalog, requirements, semantic_verifier=verifier)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(row["resolution"] == "covered" for row in result["ledger"]))
        self.assertEqual(result["metrics"]["verifier_call_count"], 1)
        self.assertEqual(result["metrics"]["verifier_tokens"], 20)

    def test_semantic_validator_request_is_proposal_blind(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )
        seen: list[dict] = []

        def verifier(_unit_id: str, groups: list[dict]) -> dict:
            seen.extend(groups)
            return {"request_id": "verify-1", "tokens": 0, "usage_complete": False,
                    "decisions": {}}

        claim_ledger.build_shadow_ledger(catalog, [requirement], semantic_verifier=verifier)
        self.assertEqual(len(seen), 1)
        self.assertNotIn("proposal_basis", seen[0])
        self.assertNotIn("prefilter", seen[0])
        self.assertNotIn("status", seen[0])
        self.assertEqual(seen[0]["source_evidence"]["text"], source)
        self.assertEqual(seen[0]["edges"][0]["produced_evidence"][1]["field"], "description")

    def test_incomplete_semantic_checklist_cannot_validate(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )

        def verifier(_unit_id: str, groups: list[dict]) -> dict:
            group_id = groups[0]["coverage_group_id"]
            return {
                "request_id": "verify-1",
                "tokens": 4,
                "usage_complete": True,
                "decisions": {group_id: {"covered": True, "checks": {"subject": True}}},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog, [requirement], semantic_verifier=verifier,
        )
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")
        self.assertEqual(result["groups"][0]["status"], "invalid")
        self.assertEqual(result["groups"][0]["invalid_reason"], "validator_evidence_incomplete")

    def test_shared_block_is_diagnostic_only_and_never_enters_verifier(self) -> None:
        source = (
            "The product shall make Output A programmable. "
            "The product shall make Output B selectable."
        )
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="The product shall make Output A programmable.",
            source_quote="The product shall make Output A programmable.", block_ids=["B1"],
        )
        calls: list[list[dict]] = []

        def verifier(_unit_id: str, groups: list[dict]) -> dict:
            calls.append(groups)
            return {"request_id": "verify-1", "tokens": 0, "decisions": {}}

        result = claim_ledger.build_shadow_ledger(
            catalog, [requirement], semantic_verifier=verifier,
        )
        resolutions = [row["resolution"] for row in result["ledger"]]
        self.assertEqual(resolutions.count("covered"), 1)
        self.assertEqual(resolutions.count("uncertain"), 1)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(calls, [])
        self.assertEqual(result["metrics"]["shared_block_only_hint_count"], 1)

    def test_multi_target_group_uses_declared_evidence_union(self) -> None:
        source = "The device shall retain 12 months and operate at 230 V."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirements = [
            _requirement("AIR-1", description="保留 12 months。", source_quote=source),
            _requirement("AIR-2", description="工作电压为 230 V。", source_quote=source),
        ]
        result = claim_ledger.build_shadow_ledger(catalog, requirements)
        group = result["groups"][0]
        self.assertEqual(len(group["edges"]), 2)
        self.assertEqual(group["prefilter"]["status"], "pass")
        self.assertEqual(group["status"], "proposed")

    def test_coverage_validation_can_be_reused_when_only_reducer_changes(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )

        def verifier(_unit_id: str, groups: list[dict]) -> dict:
            return {
                "request_id": "verify-1",
                "tokens": 7,
                "usage_complete": True,
                "decisions": {
                    groups[0]["coverage_group_id"]: {
                        "covered": True,
                        "checks": {name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS},
                    }
                },
            }

        first = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=verifier,
            validation_generation_run_id="generation-a",
        )
        calls = 0

        def should_not_run(_unit_id: str, _groups: list[dict]) -> dict:
            nonlocal calls
            calls += 1
            return {}

        second = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=should_not_run,
            reusable_groups=first["groups"],
            validation_generation_run_id="generation-b",
        )
        self.assertEqual(calls, 0)
        self.assertEqual(second["ledger"][0]["resolution"], "covered")
        self.assertEqual(second["metrics"]["semantic_validation_reused_group_count"], 1)
        self.assertEqual(
            second["metrics"]["semantic_validation_reused_group_ratio"],
            {"numerator": 1, "denominator": 1, "value": 1.0},
        )
        self.assertTrue(second["groups"][0]["validation_reused"])
        self.assertEqual(second["groups"][0]["validation_source"], {
            "generation_run_id": "generation-a",
            "request_id": "verify-1",
        })
        tampered = copy.deepcopy(second["groups"][0])
        tampered["validation_source"]["request_id"] = "verify-foreign"
        self.assertEqual(
            claim_ledger.coverage_group_record_error(
                tampered,
                catalog["catalog"][0],
                verifier_runtime_fingerprint=str(
                    second["meta"]["verifier_runtime"]["fingerprint"]
                ),
            ),
            "semantic_validation_source_invalid",
        )

    def test_coverage_validation_is_not_reused_across_runtime_fingerprints(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )

        def runtime(model: str) -> dict:
            return claim_ledger.semantic_verifier_runtime(
                route_mode="llm",
                enabled=True,
                rounds=1,
                config=LLMClientConfig(base_url="https://example.test", model=model),
            )

        def covered(_unit_id: str, groups: list[dict]) -> dict:
            return {
                "request_id": "verify-a",
                "tokens": 7,
                "usage_complete": True,
                "decisions": {groups[0]["coverage_group_id"]: {
                    "covered": True,
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                    },
                }},
            }

        first = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=covered,
            verifier_runtime=runtime("model-a"),
        )
        calls = 0

        def reverify(_unit_id: str, groups: list[dict]) -> dict:
            nonlocal calls
            calls += 1
            return covered(_unit_id, groups)

        second = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=reverify,
            reusable_groups=first["groups"],
            verifier_runtime=runtime("model-b"),
        )

        self.assertEqual(calls, 1)
        self.assertEqual(second["metrics"]["semantic_validation_reused_group_count"], 0)

    def test_semantic_not_entailed_reuse_stays_in_candidate_denominator(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1",
            description="The operator can configure auxiliary outputs.",
            source_quote=source,
        )

        def rejected(_unit_id: str, groups: list[dict]) -> dict:
            return {
                "request_id": "verify-rejected-1",
                "tokens": 7,
                "usage_complete": True,
                "decisions": {
                    groups[0]["coverage_group_id"]: {
                        "covered": False,
                        "checks": {
                            name: True
                            for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                        },
                    }
                },
            }

        first = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=rejected,
            validation_generation_run_id="generation-rejected-a",
        )
        calls = 0

        def should_not_run(_unit_id: str, _groups: list[dict]) -> dict:
            nonlocal calls
            calls += 1
            return {}

        second = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=should_not_run,
            reusable_groups=first["groups"],
            validation_generation_run_id="generation-rejected-b",
        )

        self.assertEqual(calls, 0)
        self.assertEqual(second["groups"][0]["status"], "invalid")
        self.assertEqual(
            second["groups"][0]["invalid_reason"],
            "semantic_not_entailed",
        )
        self.assertTrue(second["groups"][0]["validation_reused"])
        self.assertEqual(second["metrics"]["semantic_verifier_candidate_count"], 1)
        self.assertEqual(second["metrics"]["semantic_validation_reused_group_count"], 1)
        self.assertEqual(
            second["metrics"]["semantic_validation_reused_group_ratio"],
            {"numerator": 1, "denominator": 1, "value": 1.0},
        )

    def test_shared_block_candidates_do_not_form_cartesian_edges(self) -> None:
        claims = [f"Output {index} is programmable." for index in range(30)]
        source = " ".join(claims)
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [], target_chars=10000)
        requirements = [
            _requirement(
                f"AIR-{index}",
                description=f"输出 {index} 可编程。",
                source_quote=claim,
                block_ids=["B1"],
            )
            for index, claim in enumerate(claims)
        ]
        result = claim_ledger.build_shadow_ledger(catalog, requirements)
        self.assertEqual(result["metrics"]["coverage_edge_count"], 30)
        self.assertEqual(result["metrics"]["shared_block_only_hint_count"], 870)
        self.assertLess(result["metrics"]["produced_evidence_character_count"], 5000)

    def test_rejected_target_invalidates_otherwise_verbatim_group(self) -> None:
        source = "Output A is programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement("AIR-1", description=source, source_quote=source)
        state = {
            "ai_req_id": "AIR-1",
            "status": "rejected",
            "source_fingerprint": claim_ledger.target_source_fingerprint(requirement),
            "review_subject_fingerprint": claim_ledger.target_fingerprint(requirement),
        }
        result = claim_ledger.build_shadow_ledger(
            catalog, [requirement], review_states={"AIR-1": state},
        )
        self.assertEqual(result["groups"][0]["status"], "invalid")
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")

    def test_rejected_duplicate_does_not_poison_active_verbatim_target(self) -> None:
        source = "The product shall make Output A programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        active = _requirement("AIR-1", description=source, source_quote=source)
        rejected = _requirement("AIR-2", description=source, source_quote=source)
        state = {
            "ai_req_id": "AIR-2",
            "status": "rejected",
            "source_fingerprint": claim_ledger.target_source_fingerprint(rejected),
            "review_subject_fingerprint": claim_ledger.target_fingerprint(rejected),
        }
        result = claim_ledger.build_shadow_ledger(
            catalog,
            [active, rejected],
            review_states={"AIR-2": state},
        )
        self.assertEqual(result["ledger"][0]["resolution"], "covered")
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual({group["status"] for group in result["groups"]}, {"validated", "invalid"})

    def test_duplicate_stable_target_id_is_ambiguous_and_cannot_close(self) -> None:
        source = "Output A is programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirements = [
            _requirement("AIR-1", description=source, source_quote=source),
            _requirement("AIR-1", description=source, source_quote=source, title="Duplicate"),
        ]
        result = claim_ledger.build_shadow_ledger(catalog, requirements)
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")
        self.assertTrue(all(group["invalid_reason"] == "target_review_unknown"
                            for group in result["groups"]))

    def test_legacy_review_row_is_unknown_and_cannot_close(self) -> None:
        source = "Output A is programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement("AIR-1", description=source, source_quote=source)
        result = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            review_states={"AIR-1": {"ai_req_id": "AIR-1", "status": "accepted"}},
        )
        self.assertEqual(result["groups"][0]["status"], "invalid")
        self.assertEqual(result["groups"][0]["invalid_reason"], "target_review_unknown")

    def test_stub_route_does_not_create_semantic_proposals(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )
        result = claim_ledger.build_shadow_ledger(catalog, [requirement], route_mode="stub")
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["ledger"][0]["resolution"], "uncertain")


class SemanticNegativeTests(unittest.TestCase):
    @staticmethod
    def _proposal(_unit_id: str, claims: list[dict]) -> dict:
        claim_id = claims[0]["claim_id"]
        return {
            "request_id": "negative-proposal-1",
            "tokens": 11,
            "usage_complete": True,
            "call_count": 1,
            "failed_call_count": 0,
            "decisions": {claim_id: {
                "non_normative": True,
                "reason": "informative",
                "evidence": [{"start": 0, "end": 12, "text": "For guidance"}],
                "rationale": "The sentence only introduces guidance.",
            }},
        }

    def test_negative_proposal_without_independent_validation_stays_open(self) -> None:
        source = "For guidance only, the following example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=self._proposal,
        )

        row = result["ledger"][0]
        self.assertEqual(row["resolution"], "uncertain")
        self.assertEqual(row["semantic_negative"]["status"], "proposed")
        self.assertEqual(result["metrics"]["semantic_negative_candidate_count"], 1)
        self.assertEqual(result["metrics"]["semantic_negative_validated_count"], 0)

    def test_proposal_blind_negative_verifier_can_validate_semantic_exclusion(self) -> None:
        source = "For guidance only, the following example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        seen: list[dict] = []

        def verifier(_unit_id: str, claims: list[dict]) -> dict:
            seen.extend(claims)
            claim_id = claims[0]["claim_id"]
            self.assertNotIn("proposal", claims[0])
            self.assertNotIn("proposed_reason", claims[0])
            self.assertNotIn("reason", claims[0])
            return {
                "request_id": "negative-verify-1",
                "tokens": 17,
                "usage_complete": True,
                "call_count": 1,
                "failed_call_count": 0,
                "decisions": {claim_id: {
                    "non_normative": True,
                    "reason": "informative",
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                    },
                    "evidence": [{"start": 0, "end": len(source), "text": source}],
                    "rationale": "No implementation or verification obligation is present.",
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=self._proposal,
            semantic_negative_verifier=verifier,
        )

        self.assertEqual(len(seen), 1)
        row = result["ledger"][0]
        self.assertEqual(row["resolution"], "excluded")
        self.assertEqual(row["exclusion_kind"], "semantic")
        self.assertEqual(row["semantic_negative"]["status"], "validated")
        metrics = result["metrics"]
        self.assertEqual(metrics["negative_proposer_call_count"], 1)
        self.assertEqual(metrics["negative_verifier_call_count"], 1)
        self.assertEqual(metrics["verifier_call_count"], 2)
        self.assertEqual(metrics["semantic_negative_validation_pass_rate"]["value"], 1.0)

    def test_negative_reason_disagreement_cannot_close_claim(self) -> None:
        source = "For guidance only, the following example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])

        def verifier(_unit_id: str, claims: list[dict]) -> dict:
            claim_id = claims[0]["claim_id"]
            return {
                "request_id": "negative-verify-1",
                "tokens": 7,
                "usage_complete": True,
                "decisions": {claim_id: {
                    "non_normative": True,
                    "reason": "definition",
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                    },
                    "evidence": [{"start": 0, "end": len(source), "text": source}],
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=self._proposal,
            semantic_negative_verifier=verifier,
        )

        row = result["ledger"][0]
        self.assertEqual(row["resolution"], "uncertain")
        self.assertEqual(row["semantic_negative"]["status"], "invalid")
        self.assertIn("negative_reason_disagreement", row["invalid_reasons"])

    def test_non_independent_negative_request_cannot_close_claim(self) -> None:
        source = "For guidance only, the following example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])

        def verifier(_unit_id: str, claims: list[dict]) -> dict:
            claim_id = claims[0]["claim_id"]
            return {
                "request_id": "negative-proposal-1",
                "usage_complete": True,
                "decisions": {claim_id: {
                    "non_normative": True,
                    "reason": "informative",
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                    },
                    "evidence": [{"start": 0, "end": len(source), "text": source}],
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=self._proposal,
            semantic_negative_verifier=verifier,
        )

        row = result["ledger"][0]
        self.assertEqual(row["resolution"], "uncertain")
        self.assertEqual(row["semantic_negative"]["status"], "invalid")
        self.assertIn(
            "negative_validator_request_not_independent",
            row["invalid_reasons"],
        )

    def test_validated_negative_is_reused_without_new_model_calls(self) -> None:
        source = "For guidance only, the following example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])

        def verifier(_unit_id: str, claims: list[dict]) -> dict:
            claim_id = claims[0]["claim_id"]
            return {
                "request_id": "negative-verify-1",
                "tokens": 17,
                "usage_complete": True,
                "decisions": {claim_id: {
                    "non_normative": True,
                    "reason": "informative",
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                    },
                    "evidence": [{"start": 0, "end": len(source), "text": source}],
                }},
            }

        first = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=self._proposal,
            semantic_negative_verifier=verifier,
            validation_generation_run_id="generation-a",
        )

        def unexpected(*_args, **_kwargs):
            self.fail("validated negative should have been reused")

        second = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=unexpected,
            semantic_negative_verifier=unexpected,
            reusable_negatives=first["negative_decisions"],
            validation_generation_run_id="generation-b",
        )

        self.assertEqual(second["ledger"][0]["resolution"], "excluded")
        self.assertTrue(second["ledger"][0]["semantic_negative"]["validation_reused"])
        self.assertEqual(
            second["ledger"][0]["semantic_negative"]["validation_source"],
            {
                "generation_run_id": "generation-a",
                "request_id": "negative-verify-1",
            },
        )
        self.assertEqual(
            second["metrics"]["semantic_negative_validation_reused_count"],
            1,
        )
        self.assertEqual(second["metrics"]["verifier_call_count"], 0)

    def test_tampered_validated_negative_is_not_reused(self) -> None:
        source = "For guidance only, the following example is provided."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        calls = {"proposal": 0, "verifier": 0}

        def proposer(_unit_id: str, claims: list[dict]) -> dict:
            calls["proposal"] += 1
            return self._proposal(_unit_id, claims)

        def verifier(_unit_id: str, claims: list[dict]) -> dict:
            calls["verifier"] += 1
            claim_id = claims[0]["claim_id"]
            return {
                "request_id": f"negative-verify-{calls['verifier']}",
                "usage_complete": True,
                "decisions": {claim_id: {
                    "non_normative": True,
                    "reason": "informative",
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                    },
                    "evidence": [{"start": 0, "end": len(source), "text": source}],
                }},
            }

        first = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=proposer,
            semantic_negative_verifier=verifier,
        )
        tampered = copy.deepcopy(first["negative_decisions"])
        tampered[0]["validation"]["evidence"][0]["text"] = "stale evidence"

        second = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            semantic_negative_proposer=proposer,
            semantic_negative_verifier=verifier,
            reusable_negatives=tampered,
            verifier_runtime=first["meta"]["verifier_runtime"],
        )

        self.assertEqual(calls, {"proposal": 2, "verifier": 2})
        self.assertEqual(second["ledger"][0]["resolution"], "excluded")
        self.assertFalse(second["ledger"][0]["semantic_negative"]["validation_reused"])

    def test_runtime_fingerprint_is_replayable_from_persisted_fields(self) -> None:
        runtime = claim_ledger.semantic_verifier_runtime(
            route_mode="llm",
            enabled=True,
            rounds=2,
        )
        self.assertTrue(claim_ledger.semantic_verifier_runtime_is_valid(runtime))
        tampered = copy.deepcopy(runtime)
        tampered["rounds"] = 1
        self.assertFalse(claim_ledger.semantic_verifier_runtime_is_valid(tampered))


class ReducerAndMetricsTests(unittest.TestCase):
    def test_positive_and_negative_terminal_facts_conflict(self) -> None:
        claim = {"claim_id": "CLM-1", "claim_hash": "h", "eligibility": "claim"}
        row = claim_ledger.reduce_claim(
            claim,
            validated_groups=[{"coverage_group_id": "G1", "status": "validated"}],
            validated_negative={"reason": "informative", "status": "validated"},
        )
        self.assertEqual(row["resolution"], "uncertain")
        self.assertIn("positive_negative_conflict", row["invalid_reasons"])

    def test_zero_denominator_ratios_are_null(self) -> None:
        catalog = claim_catalog.build_claim_catalog([], [])
        result = claim_ledger.build_shadow_ledger(catalog, [])
        self.assertIsNone(result["metrics"]["verified_coverage_ratio"]["value"])
        self.assertEqual(result["metrics"]["verified_coverage_ratio"]["denominator"], 0)

    def test_failed_extraction_blocks_map_to_unique_owner_units(self) -> None:
        catalog = claim_catalog.build_claim_catalog(
            [
                _block("B1", "The product shall do A. The product shall do B.", order=1),
                _block("B2", "The product shall do C.", order=2),
            ],
            [],
            target_chars=1,
        )

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [],
            failed_section_block_ids=["B1", "B1", "missing"],
        )

        self.assertEqual(result["metrics"]["failed_extraction_units"], 2)
        self.assertEqual(result["meta"]["extraction_status"], "partial")

    def test_unrelated_review_state_does_not_change_claim_revision(self) -> None:
        source = "Output A is programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement("AIR-1", description=source, source_quote=source)
        first = claim_ledger.build_shadow_ledger(catalog, [requirement])
        unrelated = {
            "AIR-X": {"ai_req_id": "AIR-X", "status": "rejected",
                      "source_fingerprint": "x", "review_subject_fingerprint": "y"}
        }
        second = claim_ledger.build_shadow_ledger(catalog, [copy.deepcopy(requirement)],
                                                  review_states=unrelated)
        self.assertEqual(first["ledger"][0]["claim_effective_revision"],
                         second["ledger"][0]["claim_effective_revision"])

    def test_verifier_cost_uses_batch_meta_and_reports_relative_increase(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )

        def verifier(unit_id: str, groups: list[dict]) -> dict:
            del unit_id
            return {
                "request_id": "verify-batch-1",
                "tokens": 100,
                "usage_complete": True,
                "call_count": 1,
                "failed_call_count": 0,
                "decisions": {groups[0]["coverage_group_id"]: {
                    "covered": True,
                    "checks": {name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS},
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=verifier,
            baseline_cost=_verified_baseline_cost(),
        )
        metrics = result["metrics"]
        self.assertEqual(metrics["verifier_call_count"], 1)
        self.assertEqual(metrics["verifier_tokens"], 100)
        self.assertEqual(metrics["verifier_call_increase_ratio"]["value"], 0.1)
        self.assertEqual(metrics["verifier_token_increase_ratio"]["value"], 0.1)
        self.assertTrue(metrics["phase0_cost_gate_met"])
        self.assertEqual(
            metrics["verifier_cost_policy_version"],
            claim_ledger.CLAIM_COST_POLICY_VERSION,
        )
        self.assertEqual(
            metrics["verifier_call_increase_limit"],
            claim_ledger.CLAIM_VERIFIER_CALL_INCREASE_LIMIT,
        )
        self.assertEqual(
            metrics["verifier_token_increase_limit"],
            claim_ledger.CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT,
        )

        unbound = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=verifier,
            baseline_call_count=10,
            baseline_tokens=1000,
            baseline_usage_complete=True,
        )
        self.assertFalse(unbound["metrics"]["no_ledger_baseline_lineage_match"])
        self.assertEqual(
            unbound["metrics"]["verifier_cost_gate_status"],
            "insufficient_data",
        )
        self.assertIsNone(unbound["metrics"]["phase0_cost_gate_met"])

    def test_verifier_token_cost_limit_is_inclusive_at_sixty_five_percent(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )

        def run(tokens: int) -> dict:
            def verifier(_unit_id: str, groups: list[dict]) -> dict:
                return {
                    "request_id": f"verify-{tokens}",
                    "tokens": tokens,
                    "usage_complete": True,
                    "call_count": 1,
                    "failed_call_count": 0,
                    "decisions": {groups[0]["coverage_group_id"]: {
                        "covered": True,
                        "checks": {
                            name: True
                            for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                        },
                    }},
                }

            return claim_ledger.build_shadow_ledger(
                catalog,
                [requirement],
                semantic_verifier=verifier,
                baseline_cost=_verified_baseline_cost(total_tokens=1000),
            )["metrics"]

        at_limit = run(650)
        over_limit = run(651)
        self.assertEqual(at_limit["verifier_token_increase_ratio"]["value"], 0.65)
        self.assertTrue(at_limit["phase0_cost_gate_met"])
        self.assertEqual(over_limit["verifier_token_increase_ratio"]["value"], 0.651)
        self.assertFalse(over_limit["phase0_cost_gate_met"])

    def test_zero_token_envelope_cannot_pass_cost_gate(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="Auxiliary outputs are programmable.",
            source_quote=source,
        )

        def verifier(_unit_id: str, groups: list[dict]) -> dict:
            return {
                "request_id": "verify-zero-usage",
                "tokens": 0,
                "usage_complete": True,
                "call_count": 1,
                "failed_call_count": 0,
                "decisions": {groups[0]["coverage_group_id"]: {
                    "covered": True,
                    "checks": {
                        name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS
                    },
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            semantic_verifier=verifier,
            baseline_cost=_verified_baseline_cost(),
        )
        metrics = result["metrics"]
        self.assertEqual(metrics["verifier_call_count"], 1)
        self.assertEqual(metrics["verifier_tokens"], 0)
        self.assertFalse(metrics["verifier_usage_complete"])
        self.assertTrue(metrics["no_ledger_baseline_lineage_match"])
        self.assertEqual(metrics["verifier_cost_gate_status"], "insufficient_data")
        self.assertIsNone(metrics["phase0_cost_gate_met"])

    def test_missing_cost_baseline_is_reported_as_insufficient_data(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )

        def verifier(unit_id: str, groups: list[dict]) -> dict:
            del unit_id
            return {
                "request_id": "verify-1",
                "tokens": 10,
                "usage_complete": True,
                "decisions": {groups[0]["coverage_group_id"]: {
                    "covered": True,
                    "checks": {name: True for name in claim_ledger.SEMANTIC_COVERAGE_CHECKS},
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog, [requirement], semantic_verifier=verifier,
        )
        self.assertIsNone(result["metrics"]["phase0_cost_gate_met"])

    def test_disabled_verifier_cannot_claim_the_phase0_cost_gate(self) -> None:
        source = "Auxiliary outputs are user-programmable."
        catalog = claim_catalog.build_claim_catalog([_block("B1", source)], [])
        requirement = _requirement(
            "AIR-1", description="辅助输出可由用户编程。", source_quote=source,
        )
        result = claim_ledger.build_shadow_ledger(
            catalog,
            [requirement],
            baseline_call_count=10,
            baseline_tokens=1000,
            baseline_usage_complete=True,
        )
        self.assertFalse(result["meta"]["semantic_verifier_enabled"])
        self.assertIsNone(result["metrics"]["phase0_cost_gate_met"])
        self.assertEqual(result["metrics"]["verifier_cost_gate_status"], "not_run")

    def test_sibling_open_rate_is_scoped_to_multi_claim_quotes(self) -> None:
        quoted = (
            "The product shall make Output A programmable. "
            "The product shall make Output B configurable."
        )
        unrelated = "The enclosure is sealed. The cover is marked."
        catalog = claim_catalog.build_claim_catalog(
            [_block("B1", quoted, order=1), _block("B2", unrelated, order=2)],
            [],
        )
        requirement = _requirement(
            "AIR-1",
            description=quoted,
            source_quote=quoted,
        )

        result = claim_ledger.build_shadow_ledger(catalog, [requirement])

        ratio = result["metrics"]["sibling_claim_open_rate"]
        self.assertEqual(ratio["numerator"], 0)
        self.assertEqual(ratio["denominator"], 2)
        self.assertEqual(ratio["value"], 0.0)


if __name__ == "__main__":
    unittest.main()
