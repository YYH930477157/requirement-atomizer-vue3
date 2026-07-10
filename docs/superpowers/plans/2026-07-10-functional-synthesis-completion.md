# Functional Synthesis Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert chapter-local atomic requirements into auditable, structured document-level development requirements and prove quality with a broad semantic baseline.

**Architecture:** Split catalog construction from requirement rendering. `functional_catalog.py` owns deterministic clustering, protected constraints, variants, merge evidence, and optional validated LLM mappings; `functional_synthesis.py` handles review-state projection, I/O, and compatibility output. Quality evaluation is a standalone deterministic runner over a 30+ case baseline.

**Tech Stack:** Python standard library, existing OpenAI-compatible `llm_client`, JSON/JSONL contracts, unittest/pytest, Vue3 progress UI.

---

### Task 1: Catalog Contracts and Conservative Clustering

**Files:**
- Create: `functional_catalog.py`
- Modify: `functional_synthesis.py`
- Test: `tests/test_functional_catalog.py`

- [ ] Write failing tests for explicit-key normalization, legacy cross-section event merge, PM1/PM2 variant grouping, and low-battery/abnormal-flow split.
- [ ] Run `python -m pytest tests/test_functional_catalog.py -q` and confirm the new API is missing.
- [ ] Implement `CatalogAssignment`, protected token extraction, concept signatures, conservative pair compatibility, union-find clustering, and catalog assignment output.
- [ ] Re-run the catalog tests and confirm all pass.

### Task 2: Structured Development Requirement Synthesis

**Files:**
- Modify: `functional_catalog.py`
- Modify: `functional_synthesis.py`
- Test: `tests/test_functional_catalog.py`
- Test: `tests/test_review_findings_regression.py`

- [ ] Write failing tests for objective, behaviors, data constraints, variants, conflicts, related DLMS objects, and generated compatibility description.
- [ ] Verify failures show the current newline concatenation behavior.
- [ ] Implement structured synthesis with complete provenance and exactly-once atom assignment.
- [ ] Preserve rejected filtering and expert module/ownership projections.
- [ ] Verify tests pass.

### Task 3: Auditable Merge Evidence and Optional LLM Catalog

**Files:**
- Modify: `functional_catalog.py`
- Modify: `functional_synthesis.py`
- Modify: `desktop_tasks.py`
- Test: `tests/test_functional_catalog.py`
- Test: `tests/test_desktop_tasks.py`

- [ ] Write failing tests for `merge_method`, `merge_confidence`, `synthesis_reason`, `conflict_flags`, invalid LLM mapping fallback, and stage route/config fingerprinting.
- [ ] Add a bounded module-level catalog prompt that returns only catalog IDs/titles and atom assignments.
- [ ] Validate complete exactly-once ID coverage; fall back per module on any malformed response.
- [ ] Expose `route` through `functional_synthesis_task` and chain routing.
- [ ] Verify deterministic and injected-chat tests pass without network.

### Task 4: Executable 30-Case Semantic Quality Baseline

**Files:**
- Replace: `golden_sets/requirements_analysis_semantic_v1.json`
- Create: `semantic_quality.py`
- Create: `tests/test_semantic_quality.py`
- Modify: `tests/test_review_findings_regression.py`

- [ ] Expand to at least 30 cases covering merge, split, ownership, protected values, provenance, and delivery-field separation.
- [ ] Write evaluator tests for completeness, expected grouping, protected-token retention, rejected exclusion, and override preservation.
- [ ] Implement deterministic evaluator and JSON report.
- [ ] Set gates: zero critical violations, all named cases pass, and non-zero reduction on legacy fixture.
- [ ] Run evaluator tests.

### Task 5: Legacy Corpus and End-to-End Regression

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Test: existing Python and Vue suites

- [ ] Replay `test18/ai_requirements.jsonl` into a fresh output directory.
- [ ] Assert useful non-zero reduction, no atom loss, no rejected resurrection, and no protected-token loss.
- [ ] Generate `functional_requirements.json`, analysis workbook, and annotation HTML.
- [ ] Run `python -m pytest -q`, `npm test`, and `npm run build`.
- [ ] Run `git diff --check` and review all changed files.
