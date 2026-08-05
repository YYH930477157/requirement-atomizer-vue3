# Claim-Authoritative Table Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Claim Ledger structural decisions the sole terminal authority for B-track table review and project them consistently into table review, extraction, and Ledger Ready views.

**Architecture:** Extend claim candidate coverage to every B-track review cell, add a read-only table-cell authority projection, and make the table action endpoint delegate terminal decisions to existing claim exclusion/override protocols. Keep table dispositions as a rebuildable projection rather than a second authority.

**Tech Stack:** Python 3.11+, `unittest`, JSONL/hash-chain claim artifacts, Vue 3/Vitest, result-package governed paths.

---

### Task 1: Candidate Coverage Contract

**Files:**
- Modify: `claim_catalog.py`
- Modify: `claim_structural_overrides.py`
- Modify: `claim_views.py`
- Modify: `schemas/claim_catalog.schema.json`
- Modify: `schemas/claim_structural_candidate_decision_v2.schema.json` or add the next version
- Test: `tests/test_claim_structural_overrides.py`
- Test: `tests/test_table_structure_e2e.py`

- [x] Write failing tests proving every disposition `review` cell has one claim candidate, including parse-incomplete and normative-context cases.
- [x] Run the focused tests and confirm they fail because those candidate reasons are absent.
- [x] Add the two candidate reasons, disposition input loading, catalog version bump, and schema support.
- [x] Run the focused tests and confirm candidate coverage and migration behavior pass.

### Task 2: Read-Only Claim Projection

**Files:**
- Create: `table_claim_authority.py`
- Modify: `table_review_state.py`
- Modify: `ai_extract.py`
- Test: `tests/test_table_claim_authority.py`
- Test: `tests/test_table_review_state.py`

- [x] Write failing tests for pending, confirmed-excluded, promoted, and promotion-pending projection by exact `table_cell_id`.
- [x] Run the tests and confirm the projection API is missing.
- [x] Implement the read-only authority loader and disposition overlay.
- [x] Apply the overlay in table GET and B-track extraction input loading.
- [x] Run the focused tests and confirm reverse synchronization works without table-state writes.

### Task 3: Table Action Delegation

**Files:**
- Modify: `table_review_state.py`
- Modify: `api_server.py`
- Modify: `ui/src/api-client.ts`
- Modify: `ui/src/App.vue`
- Test: `tests/test_table_review_state.py`
- Test: `ui/src/__tests__/ReviewWorkspace.spec.ts`

- [x] Write failing tests showing table actions append claim exclusion decisions or execute structural promotion, not independent human terminal state.
- [x] Run backend/frontend focused tests and confirm the old independent state behavior fails the assertions.
- [x] Implement stable per-cell delegation, idempotency, partial completion reporting, and projection refresh.
- [x] Update the UI to present promote/confirm-exclusion actions while retaining table-level confirmation.
- [x] Run focused backend/frontend tests and confirm claim and table status converge.

### Task 4: Full-Chain Duplicate Guard

**Files:**
- Modify: `tests/test_ai_extract_table_cells.py`
- Modify: `ai_extract.py` only if the failing test exposes a real duplicate

- [x] Add a fake-chat E2E covering structured table leaves, parameter-row fallback, and row merge.
- [x] Run it and confirm whether the current implementation duplicates a row.
- [x] If red, make the smallest provenance-based merge correction.
- [x] Re-run and confirm one published requirement with all source IDs retained.

### Task 5: Schemas and Documentation

**Files:**
- Create: `schemas/table_cell_item.schema.json`
- Modify: `tests/test_table_cell_dispositions.py`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `C:/Users/YYHwudi/Downloads/2026-08-04-docx-table-cell-extraction-design.md` only if the external design file is intended to remain the maintained copy

- [x] Add a failing schema-validation test for representative table-cell items.
- [x] Add the formal schema and package it through `pyproject.toml` if required.
- [x] Correct catalog version, prompt context, LLM-structure scope, unreadable-DOCX behavior, and quality-target wording in repository documentation.
- [x] Run schema and packaging smoke tests.

### Task 6: Verification

**Files:**
- Modify: `CLAUDE.md` with final versions and evidence

- [x] Run all claim/table focused backend tests.
- [x] Run `python -m unittest discover -s tests` with the historical sample environment variable.
- [x] Run `cmd /c "npm test"` and `cmd /c "npm run build"` from `ui/`.
- [x] Run Python compileall and `git diff --check`.
- [x] Confirm golden baseline files are unchanged.
