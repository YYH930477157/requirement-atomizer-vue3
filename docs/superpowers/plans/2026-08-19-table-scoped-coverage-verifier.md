# Table-Scoped Coverage Verifier Implementation Plan

> **For agentic workers:** Execute inline with TDD. Tests are `unittest.TestCase` (`python -m unittest …`), not pytest. Do not commit unless the user asks.

**Goal:** Same-table pending `table_row` semantic coverage groups share one LLM call; each row still gets an independent covered/seven-check decision.

**Architecture:** Partition coverage candidates by table key before `_bounded_batches`. Table packs ignore the 24-group cap and split only on the existing 48KB HTTP body. Request envelope becomes `claim-coverage-verifier-request/v3` with `scope.kind=table|independent`. Neighbor rows are structure context only; `target_refs` stay per-row.

**Tech Stack:** Python 3.11+ `claim_ledger.py`, existing `build_shadow_ledger` / `make_semantic_coverage_verifier`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-19-table-scoped-coverage-verifier-design.md`

---

## Files

- Modify: `claim_ledger.py` — versions, table scope index, packing, v3 payload, table prompt addendum, validation hashes
- Modify: `prompt_registry.py` — `claim-coverage-validator` → v7
- Modify: `schemas/claim_shadow_meta.schema.json` — runtime v12, batch-v4 consts
- Modify: `docs/cli-contract.md` — version strings
- Modify: `tests/test_claim_ledger.py` — new table-scope class + existing v2 pins → v3
- Modify: `tests/test_table_structure_e2e.py` — detect v3 request schema
- Do not rewrite historical fixture versions in `tests/test_claim_acceptance.py` unless a test compares them to `current_base_versions()`

## Task 1: Failing packing / envelope tests

Add `TableScopedCoverageVerifierTests` in `tests/test_claim_ledger.py`.

Helpers: `_clause_row_catalog(n)` builds a headerless sequential-clause parameter table via `atomize.build_table_artifacts` + `claim_catalog.build_claim_catalog`; `_row_requirement(claim)` makes a non-verbatim B-track target (`source_quote` is a paraphrase so the group is `independent_semantic`).

- [x] 20 same-table pending rows → `_coverage_batches` returns 1 batch; HTTP body schema v3, `scope.kind=table`, 20 groups
- [x] 24 short same-table rows still 1 batch (24 cap gone for tables)
- [x] One oversized row isolated; other rows still batch
- [x] Two tables never share a batch; `table_cell` groups are `independent`
- [x] 25 prose claims still split at 24
- [x] Sibling target_refs stay disjoint in transport
- [x] Run: `python -m unittest tests.test_table_scoped_coverage`

Expected: FAIL (v2 envelope, 24-cap splits table rows)

## Task 2: Packing + v3 envelope (minimal green)

- [x] Bump `CLAIM_COVERAGE_RUNTIME_VERSION` → `claim-coverage-runtime-v12`
- [x] Bump `CLAIM_COVERAGE_VALIDATOR_VERSION` → `claim-coverage-validator-v7`
- [x] Bump `CLAIM_VERIFIER_BATCH_POLICY_VERSION` → `claim-verifier-batch-v4-table-scoped`
- [x] Add `_table_pack_key`, `_table_scope_index`, `_compact_table_row_text`, `_coverage_scope_for_batch`, `_coverage_system_prompt`
- [x] `_group` / `_semantic_verifier_request` carry `table_scope` + `compact_source_text`
- [x] `_coverage_verifier_request_payload` emits v3 + scope
- [x] `_coverage_batches` partitions table vs independent; table `max_items` = pack size; independent stays 24
- [x] `make_semantic_coverage_verifier` uses matching system prompt for the batch
- [x] Update existing v2 string pins and prompt_registry / shadow schema / cli-contract
- [x] Re-run Task 1 tests + `tests.test_claim_ledger.VerifierBatchPolicyTests` (or current batch class name)

## Task 3: Ledger integration, reuse, negative packing

- [x] `build_shadow_ledger` computes `_table_scope_index(catalog)` once and passes fingerprint into `_group`
- [x] `validation_input_hash` and `coverage_group_record_error` include `table_scope_fingerprint` when present
- [x] `semantic_validation_fingerprint` includes `table_scope_fingerprint`
- [x] Tests: 20-row `build_shadow_ledger` → 1 chat call, 20 decisions; verbatim table rows → 0 calls; changing another row's hash busts reuse; old validator_version group is not reused
- [x] `_negative_claim_request` carries table key; `_negative_batches` does not mix tables
- [x] Test: same-table negatives share a proposer batch; two tables do not
- [x] Test: old `shadow_meta.versions` ≠ `current_base_versions()`

## Task 4: Regression

- [x] `python -m unittest tests.test_claim_ledger tests.test_table_structure_e2e tests.test_claim_acceptance tests.test_prompt_registry -q`
- [x] Fix only failures caused by this change
- [x] Update spec status to approved/implemented
