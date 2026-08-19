from __future__ import annotations

import copy
import json
import unittest

import claim_catalog
import claim_ledger
from llm_client import LLMClientConfig

from tests.test_claim_ledger import VerifierBatchPolicyTests, _requirement


class TableScopedCoverageVerifierTests(unittest.TestCase):
    """表级综合覆盖：同行 claim 仍登记，同表语义覆盖一次调用、逐行结论。"""

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
    def _table_scope(
        table_id: str = "TBL-000215",
        block_id: str = "BLK-000215",
        *,
        title: str = "Operating conditions",
        headers: list[str] | None = None,
    ) -> dict:
        return {
            "kind": "table",
            "table_id": table_id,
            "block_id": block_id,
            "title": title,
            "headers": headers or ["Clause", "Specification", "Value"],
            "fingerprint": "sha256:" + "c" * 64,
        }

    def _table_row_request(
        self,
        index: int,
        *,
        table_id: str = "TBL-000215",
        evidence_text: str = "product shall implement the named parameter",
        compact: str | None = None,
    ) -> dict:
        row = VerifierBatchPolicyTests._coverage_request(index, evidence_text)
        row["table_scope"] = self._table_scope(table_id)
        row["compact_source_text"] = compact or (
            f"Clause={chr(64 + index)} | Specification=Parameter {index:02d} "
            f"operating limit | Value={100 + index} V"
        )
        return row

    def _http_payload(self, batch: list[dict], runtime: dict) -> dict:
        return VerifierBatchPolicyTests._coverage_http_payload(batch, runtime)

    def test_twenty_same_table_rows_are_one_v3_table_batch(self) -> None:
        runtime = self._runtime()
        rows = [self._table_row_request(index) for index in range(1, 21)]

        batches, oversized = claim_ledger._coverage_batches(rows, runtime=runtime)

        self.assertEqual(oversized, [])
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 20)
        payload = self._http_payload(batches[0], runtime)
        body = json.loads(payload["messages"][1]["content"])
        self.assertEqual(body["schema"], "claim-coverage-verifier-request/v3")
        self.assertEqual(body["scope"]["kind"], "table")
        self.assertEqual(body["scope"]["table_id"], "TBL-000215")
        self.assertEqual(len(body["groups"]), 20)
        self.assertIn("sibling", " ".join(payload["messages"][0]["content"].split()).lower())

    def test_twenty_four_short_table_rows_ignore_independent_group_cap(self) -> None:
        runtime = self._runtime()
        rows = [self._table_row_request(index) for index in range(1, 25)]

        batches, oversized = claim_ledger._coverage_batches(rows, runtime=runtime)

        self.assertEqual(oversized, [])
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 24)

    def test_single_oversized_table_row_is_isolated(self) -> None:
        runtime = self._runtime()
        huge = self._table_row_request(1, evidence_text="\u914d\u7f6e" * 5000)
        small = [self._table_row_request(index) for index in range(2, 5)]

        batches, oversized = claim_ledger._coverage_batches(
            [huge, *small], runtime=runtime,
        )

        self.assertEqual(oversized, [huge])
        self.assertEqual(len(batches), 1)
        self.assertEqual([row["claim_id"] for row in batches[0]], ["CLM-2", "CLM-3", "CLM-4"])

    def test_two_tables_and_table_cells_never_share_a_table_batch(self) -> None:
        runtime = self._runtime()
        table_a = [self._table_row_request(index, table_id="TBL-A") for index in range(1, 3)]
        table_b = [self._table_row_request(index, table_id="TBL-B") for index in range(3, 5)]
        cell = VerifierBatchPolicyTests._coverage_request(9, "cell evidence")

        batches, oversized = claim_ledger._coverage_batches(
            [*table_a, cell, *table_b], runtime=runtime,
        )

        self.assertEqual(oversized, [])
        scopes = [
            json.loads(self._http_payload(batch, runtime)["messages"][1]["content"])["scope"]
            for batch in batches
        ]
        table_ids = {
            scope.get("table_id")
            for scope in scopes
            if scope.get("kind") == "table"
        }
        self.assertEqual(table_ids, {"TBL-A", "TBL-B"})
        independent = [scope for scope in scopes if scope.get("kind") == "independent"]
        self.assertEqual(len(independent), 1)
        self.assertTrue(all(not scope.get("table_id") for scope in independent))

    def test_prose_claims_still_split_at_twenty_four(self) -> None:
        runtime = self._runtime()
        rows = [
            VerifierBatchPolicyTests._coverage_request(index, "short evidence")
            for index in range(1, 26)
        ]

        batches, oversized = claim_ledger._coverage_batches(rows, runtime=runtime)

        self.assertEqual(oversized, [])
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 24)
        self.assertEqual(len(batches[1]), 1)
        body = json.loads(self._http_payload(batches[0], runtime)["messages"][1]["content"])
        self.assertEqual(body["schema"], "claim-coverage-verifier-request/v3")
        self.assertEqual(body["scope"]["kind"], "independent")

    def test_sibling_target_refs_stay_disjoint_in_table_transport(self) -> None:
        runtime = self._runtime()
        row_a = self._table_row_request(1, evidence_text="only target one")
        row_b = self._table_row_request(2, evidence_text="only target two")

        batches, oversized = claim_ledger._coverage_batches(
            [row_a, row_b], runtime=runtime,
        )

        self.assertEqual(oversized, [])
        self.assertEqual(len(batches), 1)
        body = json.loads(self._http_payload(batches[0], runtime)["messages"][1]["content"])
        refs_a = body["groups"][0][2]
        refs_b = body["groups"][1][2]
        self.assertEqual(len(refs_a), 1)
        self.assertEqual(len(refs_b), 1)
        self.assertNotEqual(refs_a, refs_b)
        self.assertEqual(len(body["target_evidence"]), 2)

    def _parameter_table_catalog(
        self,
        row_count: int,
        *,
        table_id: str = "TBL-000215",
        obligation_rows: bool = False,
    ):
        block_id = "BLK-000215"
        headers = ["Clause", "Specification", "Value"]
        data_rows = []
        items = []
        row_leaves = []
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for index in range(row_count):
            row_index = index + 2
            clause = letters[index % 26] + ("" if index < 26 else str(index // 26))
            if obligation_rows:
                spec = f"The product shall keep {clause} operating voltage at 230 V"
            else:
                spec = f"{clause} operating voltage"
            value = "230 V"
            data_rows.append([clause, spec, value])
            row_leaves.append(row_index)
            items.append({
                "item_id": f"{table_id}-R{row_index:06d}",
                "table_block_id": block_id,
                "row_index": row_index,
                "fields": {
                    "Clause": clause,
                    "Specification": spec,
                    "Value": value,
                },
                "text": f"{clause} | {spec} | {value}",
                "section_path": ["6"],
            })
        block = {
            "block_id": block_id,
            "order": 1,
            "type": "table",
            "text": "Operating conditions",
            "raw_text": "Operating conditions",
            "text_repair_checked": True,
            "text_repair_version": "identity-v1",
            "raw_to_repaired_spans": [{
                "raw_start": 0,
                "raw_end": 21,
                "repaired_start": 0,
                "repaired_end": 21,
                "operation": "equal",
            }],
            "section_path": ["6"],
            "noise": False,
            "table_id": table_id,
            "table_title": "Operating conditions",
            "headers": headers,
            "data_rows": data_rows,
            "leaf_plan": {
                "row_leaves": row_leaves,
                "cell_leaves": [],
                "context_cells": [],
            },
        }
        return claim_catalog.build_claim_catalog([block], items)

    @staticmethod
    def _row_requirements(catalog: dict) -> list[dict]:
        requirements = []
        for index, claim in enumerate(catalog["catalog"], start=1):
            fields = {
                str(field.get("name") or ""): str(field.get("value") or "")
                for field in (claim.get("table_context") or {}).get("fields") or []
            }
            spec = fields.get("Specification") or claim["text"]
            value = fields.get("Value") or ""
            requirements.append(_requirement(
                f"AIR-{index}",
                description=(
                    f"The product shall implement {spec}"
                    + (f" at {value}." if value else ".")
                ),
                source_quote=spec,
                block_ids=["BLK-000215"],
            ))
        return requirements

    def test_shadow_ledger_sends_one_call_for_twenty_table_rows(self) -> None:
        catalog = self._parameter_table_catalog(20)
        row_claims = [
            row for row in catalog["catalog"] if row["source_kind"] == "table_row"
        ]
        self.assertEqual(len(row_claims), 20)
        seen: list[dict] = []

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            payload = json.loads(user)
            seen.append(payload)
            return ({
                "decisions": [
                    [group[0], True, [True] * len(claim_ledger.SEMANTIC_COVERAGE_CHECKS)]
                    for group in payload["groups"]
                ],
            }, {"usage": {"total_tokens": 40}, "usage_complete": True})

        result = claim_ledger.build_shadow_ledger(
            catalog,
            self._row_requirements(catalog),
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
        )

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["schema"], "claim-coverage-verifier-request/v3")
        self.assertEqual(seen[0]["scope"]["kind"], "table")
        self.assertEqual(len(seen[0]["groups"]), 20)
        self.assertEqual(
            sum(row["resolution"] == "covered" for row in result["ledger"]),
            20,
        )

    def test_verbatim_table_rows_make_zero_coverage_calls(self) -> None:
        catalog = self._parameter_table_catalog(3, obligation_rows=True)
        requirements = []
        for index, claim in enumerate(catalog["catalog"], start=1):
            requirements.append(_requirement(
                f"AIR-{index}",
                description=claim["text"],
                source_quote=claim["text"],
                block_ids=["BLK-000215"],
            ))
        seen: list[dict] = []

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            seen.append(json.loads(user))
            return ({"decisions": []}, {"usage": {"total_tokens": 1}, "usage_complete": True})

        result = claim_ledger.build_shadow_ledger(
            catalog,
            requirements,
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
        )

        self.assertEqual(seen, [])
        self.assertTrue(all(row["resolution"] == "covered" for row in result["ledger"]))

    def test_changing_sibling_claim_hash_invalidates_semantic_reuse(self) -> None:
        catalog = self._parameter_table_catalog(2)
        requirements = self._row_requirements(catalog)

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            payload = json.loads(user)
            return ({
                "decisions": [
                    [group[0], True, [True] * len(claim_ledger.SEMANTIC_COVERAGE_CHECKS)]
                    for group in payload["groups"]
                ],
            }, {"usage": {"total_tokens": 11}, "usage_complete": True})

        first = claim_ledger.build_shadow_ledger(
            catalog,
            requirements,
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
            validation_generation_run_id="gen-1",
        )
        reused_calls: list[int] = []

        def should_run(_system: str, user: str) -> tuple[dict, dict]:
            reused_calls.append(1)
            payload = json.loads(user)
            return ({
                "decisions": [
                    [group[0], True, [True] * len(claim_ledger.SEMANTIC_COVERAGE_CHECKS)]
                    for group in payload["groups"]
                ],
            }, {"usage": {"total_tokens": 11}, "usage_complete": True})

        mutated = copy.deepcopy(catalog)
        mutated["catalog"][1]["claim_hash"] = "sha256:" + "f" * 64
        second = claim_ledger.build_shadow_ledger(
            mutated,
            requirements,
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(should_run),
            reusable_groups=first["groups"],
            validation_generation_run_id="gen-2",
        )

        self.assertGreaterEqual(sum(reused_calls), 1)
        self.assertFalse(any(group.get("validation_reused") for group in second["groups"]))

    def test_old_validator_version_is_not_reused(self) -> None:
        catalog = self._parameter_table_catalog(1)
        requirements = self._row_requirements(catalog)

        def chat(_system: str, user: str) -> tuple[dict, dict]:
            payload = json.loads(user)
            return ({
                "decisions": [
                    [group[0], True, [True] * len(claim_ledger.SEMANTIC_COVERAGE_CHECKS)]
                    for group in payload["groups"]
                ],
            }, {"usage": {"total_tokens": 9}, "usage_complete": True})

        first = claim_ledger.build_shadow_ledger(
            catalog,
            requirements,
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(chat),
            validation_generation_run_id="gen-old",
        )
        stale = copy.deepcopy(first["groups"])
        for group in stale:
            group["validator_version"] = "claim-coverage-validator-v6"
            group["validation_input_hash"] = "sha256:" + "0" * 64
        calls = []

        def again(_system: str, user: str) -> tuple[dict, dict]:
            calls.append(1)
            payload = json.loads(user)
            return ({
                "decisions": [
                    [group[0], True, [True] * len(claim_ledger.SEMANTIC_COVERAGE_CHECKS)]
                    for group in payload["groups"]
                ],
            }, {"usage": {"total_tokens": 9}, "usage_complete": True})

        second = claim_ledger.build_shadow_ledger(
            catalog,
            requirements,
            semantic_verifier=claim_ledger.make_semantic_coverage_verifier(again),
            reusable_groups=stale,
            validation_generation_run_id="gen-new",
        )
        self.assertEqual(len(calls), 1)
        self.assertFalse(second["groups"][0].get("validation_reused"))

    def test_negative_batches_do_not_mix_tables(self) -> None:
        runtime = self._runtime()
        rows = []
        for index, table_id in enumerate(("TBL-A", "TBL-A", "TBL-B"), start=1):
            row = VerifierBatchPolicyTests._negative_request(index, "unit prompt")
            row["table_pack_key"] = ["table_id", table_id]
            rows.append(row)

        batches, oversized = claim_ledger._negative_batches(
            rows, runtime=runtime, operation="proposer",
        )

        self.assertEqual(oversized, [])
        keys = [
            {tuple(request.get("table_pack_key") or ()) for request in batch}
            for batch in batches
        ]
        self.assertTrue(all(len(key_set) == 1 for key_set in keys))
        self.assertEqual(
            {next(iter(key_set)) for key_set in keys},
            {("table_id", "TBL-A"), ("table_id", "TBL-B")},
        )

    def test_stale_base_versions_are_not_current(self) -> None:
        current = claim_ledger.current_base_versions()
        stale = dict(current)
        stale["coverage_validator"] = "claim-coverage-validator-v6"
        stale["batch_policy"] = "claim-verifier-batch-v3-full-http-body"
        self.assertNotEqual(stale, current)
        self.assertEqual(
            current["coverage_validator"],
            "claim-coverage-validator-v7",
        )
        self.assertEqual(
            current["batch_policy"],
            "claim-verifier-batch-v4-table-scoped",
        )


if __name__ == "__main__":
    unittest.main()
