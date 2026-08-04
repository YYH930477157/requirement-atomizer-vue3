# DOCX Table Cell Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved DOCX table-cell extraction design across physical parsing, deterministic dispositions, B-track extraction, review APIs/UI, and package-governed artifacts.

**Architecture:** Keep stable top-level `BLK-*` identities and the existing `table_items`/`table_cell_items` authority. Add a DOCX-only OOXML physical parser, derive versioned cell dispositions from the existing format-neutral table structure layer, and make B-track prompts consume row/cell semantic leaves instead of flattened table blocks. Persist mutable table review decisions separately from immutable source facts and recompute only the affected table.

**Tech Stack:** Python 3.11+, python-docx/lxml OOXML, unittest, Vue 3, TypeScript, Vitest, Electron.

---

### Task 1: DOCX Physical Table Fidelity

**Files:**
- Create: `docx_table_parser.py`
- Modify: `atomize.py`
- Test: `tests/test_docx_table_parser.py`

- [ ] Write failing `unittest.TestCase` coverage for `gridBefore`/`gridAfter`, horizontal/vertical/rectangular merges, nested tables, and paragraph/list/manual-break preservation.
- [ ] Run `python -m unittest tests.test_docx_table_parser` and confirm failures are caused by missing physical parser behavior.
- [ ] Implement a pure OOXML parser returning a physical matrix, merge ranges, covered coordinates, explicit headers, cell content structure, nested table references, style evidence, and honest `parse_incomplete_reason` values.
- [ ] Route `extract_docx` through the new parser without changing top-level block ordering.
- [ ] Re-run the focused tests and existing table structure suites.

### Task 2: Versioned Cell Dispositions and Conservation

**Files:**
- Create: `table_dispositions.py`
- Create: `schemas/table_cell_dispositions.schema.json`
- Modify: `table_structure.py`
- Modify: `atomize.py`
- Modify: `result_package.py`
- Modify: `desktop_tasks.py`
- Test: `tests/test_table_cell_dispositions.py`
- Test: `tests/test_result_package.py`

- [ ] Write failing tests for exactly-one disposition per non-empty canonical cell, covered-cell exclusion from semantic ownership, normative-content fail-closed behavior, and package-v1 addressing.
- [ ] Implement `target/context/composite/excluded/review` classification with evidence, confidence, decision source, linked leaves, and table-level readiness.
- [ ] Persist `table_cell_dispositions.jsonl` through `governed_artifact_path`, register it in the result package, and reject stale structure versions with `base_migration_required`.
- [ ] Bump `TABLE_STRUCTURE_VERSION` and all producer/cache stamps that store post-processed table structure.
- [ ] Re-run focused conservation and package tests.

### Task 3: Structured B-Track Extraction Units

**Files:**
- Modify: `extract_units.py`
- Modify: `ai_extract.py`
- Modify: `clarification_report.py`
- Test: `tests/test_table_row_level.py`
- Test: `tests/test_ai_extract_table_cells.py`

- [ ] Write failing tests proving flattened table text is absent from direct LLM input while paragraph context remains, headers/context accompany every leaf, and source cell IDs survive mapping.
- [ ] Emit row/cell/sentence semantic leaves from authoritative `leaf_plan` and dispositions; keep the flattened block only in source context/audit fields.
- [ ] Update the extraction prompt contract to prohibit invented structured facts and remove the obsolete one-table-one-requirement instruction.
- [ ] Generate deterministic structured facts for parameters, matrices, prose-grid duties, and `Not Applicable`; map every formal requirement to one or more `source_cell_ids`.
- [ ] Merge only exact equivalence keys and aggregate missing-parameter clarifications without suspending explicit requirements.
- [ ] Bump extraction guard/prompt/cache versions and re-run focused tests.

### Task 4: Table-Level Review State, API, and Local Recompute

**Files:**
- Create: `table_review_state.py`
- Modify: `api_server.py`
- Modify: `desktop_tasks.py`
- Modify: `ui/src/api-client.ts`
- Modify: `ui/src/env.d.ts`
- Modify: `ui/src/ReviewWorkspace.vue`
- Test: `tests/test_api_server.py`
- Test: `tests/test_table_review_state.py`
- Test: `ui/src/__tests__/ReviewWorkspace.spec.ts`

- [ ] Write failing tests for table summaries, review decisions, immutable evidence fingerprints, cross-process locking, and one-table recomputation.
- [ ] Add read APIs for table summaries/details and a write API for a single table role-region decision.
- [ ] Persist review history atomically under package state and recompute only the affected table artifacts/requirements.
- [ ] Add a compact table summary and one-shot region/role confirmation UI; high-confidence tables remain action-free and `llm_assisted` is audit-only.
- [ ] Re-run backend API and frontend component tests.

### Task 5: Integration, Migration Gates, and Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: versioned schemas and producer stamps touched above
- Test: relevant backend/frontend suites

- [ ] Add the three synthetic acceptance fixtures: multi-model parameters, multi-duty cells, and partial-model `Not Applicable`.
- [ ] Verify counts, source cells, applicable models, clarifications, exclusions, and zero structural review for the high-confidence fixtures.
- [ ] Verify stable top-level `BLK-*` order, package-v1 paths, cache invalidation, and old-artifact `base_migration_required` behavior.
- [ ] Run `python -m unittest discover -s tests` with the historical sample environment variable.
- [ ] Run `cmd /c "npm test"` and `cmd /c "npm run build"` from `ui/`.
- [ ] Record the milestone and exact verification evidence in `CLAUDE.md`; do not commit or push unless explicitly requested.
