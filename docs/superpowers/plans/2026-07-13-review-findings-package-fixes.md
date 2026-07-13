# 0713 Review Findings and Packaging Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the six confirmed review findings and produce a verified Windows portable application.

**Architecture:** Keep changes local to stage fingerprinting, analysis validation, annotation export, and the Vue document review component. Preserve all public contracts and lock each corrected boundary with a regression test before packaging.

**Tech Stack:** Python 3.11, pytest/unittest, Vue 3, TypeScript, Vitest, Electron, PyInstaller, electron-builder.

---

### Task 1: Invalidate stale stages and track terminology input

**Files:**
- Modify: `desktop_tasks.py:337-380`
- Test: `tests/test_desktop_tasks.py`

- [ ] **Step 1: Write failing producer and fingerprint tests**

Update the expected producer map to `atomize+impl-v3` and `ai-extract-v15+impl-v3`. Add a test that fingerprints requirements analysis, changes only `term_map.json`, and asserts the fingerprint changes.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_desktop_tasks.py::ChainAndManifestTests -q`

Expected: producer expectations fail and the term map fingerprint remains unchanged.

- [ ] **Step 3: Implement minimal invalidation**

Set:

```python
STAGE_IMPLEMENTATION_REVISIONS = {
    "atomize": "v3",
    "ai-extract": "v3",
    # existing stages unchanged
}
```

Add `"term_map.json"` to `STAGE_INPUTS["requirements-analysis"]`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_desktop_tasks.py tests/test_review_findings_regression.py -q`

- [ ] **Step 5: Commit**

```powershell
git add desktop_tasks.py tests/test_desktop_tasks.py
git commit -m "fix: invalidate stale parsing and analysis stages"
```

### Task 2: Keep sibling numbers out of the evidence baseline

**Files:**
- Modify: `requirements_analysis.py:479-481`
- Test: `tests/test_enrich_depth_0712.py`

- [ ] **Step 1: Write failing sibling-number regression**

Call `validate_llm_item` with source number `12`, generated number `60`, and a sibling title containing `60`. Assert `fabricated number not in source: 60` is present.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_enrich_depth_0712.py::W1BaselineTests::test_sibling_number_is_not_grounded -q`

Expected: issues is empty.

- [ ] **Step 3: Implement minimal context split**

Pass only `ctx["doc_context"]` as `context_text`; keep siblings in `build_analysis_prompt` and cache basis.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_enrich_depth_0712.py tests/test_requirements_analysis_pipeline.py -q`

- [ ] **Step 5: Commit**

```powershell
git add requirements_analysis.py tests/test_enrich_depth_0712.py
git commit -m "fix: preserve sibling numeric drift warnings"
```

### Task 3: Embed rejection notes on the first annotation export

**Files:**
- Modify: `doc_annotation_export.py:830-840`
- Test: `tests/test_doc_annotation_export.py`

- [ ] **Step 1: Write failing all-rejected export regression**

Seed one omission block, mock translation generation to write a rejected sidecar entry, run `export_annotation_bundle`, and assert the resulting HTML contains the rejection note on that first call.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_doc_annotation_export.py::MarkerTranslationTests::test_first_export_embeds_all_rejected_notes -q`

Expected: generated HTML lacks the new rejection note.

- [ ] **Step 3: Implement minimal rerender condition**

```python
if summary.get("translated") or summary.get("rejected"):
    rendered = render_annotation_html(out_dir)
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_doc_annotation_export.py -q`

- [ ] **Step 5: Commit**

```powershell
git add doc_annotation_export.py tests/test_doc_annotation_export.py
git commit -m "fix: surface rejected translations on first export"
```

### Task 4: Hide software guidance from hardware cards

**Files:**
- Modify: `ui/src/DocumentReview.vue:185-203`
- Test: `ui/src/__tests__/DocumentReview.spec.ts`

- [ ] **Step 1: Write failing hardware-card regression**

Seed a hardware requirement with extraction `dev_guidance` and `acceptance_criteria`, select it, and assert neither string appears in the detail card.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/__tests__/DocumentReview.spec.ts`

Expected: hardware card contains both extraction strings.

- [ ] **Step 3: Implement hardware guard**

Return empty arrays from `devGuidanceOf` and `acceptanceOf` when `ownershipOf(r) === "hardware"`.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run src/__tests__/DocumentReview.spec.ts src/__tests__/AnnotationContract.spec.ts`

- [ ] **Step 5: Commit**

```powershell
git add ui/src/DocumentReview.vue ui/src/__tests__/DocumentReview.spec.ts
git commit -m "fix: keep hardware review cards implementation-neutral"
```

### Task 5: Formatting and integrated regression

**Files:**
- Modify: `text_normalize.py:79`

- [ ] **Step 1: Remove the extra EOF blank line**

Keep exactly one newline after `strip_enum_markers`.

- [ ] **Step 2: Run changed-area tests**

```powershell
python -m pytest tests/test_desktop_tasks.py tests/test_enrich_depth_0712.py tests/test_doc_annotation_export.py tests/test_requirements_analysis_pipeline.py -q
```

- [ ] **Step 3: Run all backend tests in complete non-overlapping groups**

Enumerate every `tests/test_*.py`, run all files, and reconcile passed/skipped totals.

- [ ] **Step 4: Run frontend verification**

```powershell
cd ui
npm test
npm run build
```

- [ ] **Step 5: Run repository checks**

```powershell
git diff --check main...HEAD
git status --short --branch
```

### Task 6: Build and inspect the portable application

**Files:**
- Generated: `dist-backend/ratomizer-desktop.exe`
- Generated: `ui/release/*.exe`

- [ ] **Step 1: Build portable package**

Run from `ui`: `npm run desktop:pack`

- [ ] **Step 2: Verify artifacts**

Confirm the backend executable and newest portable executable both exist and have non-zero size. Record absolute paths, sizes, and SHA-256 hashes.

- [ ] **Step 3: Smoke-test packaged backend**

Run `dist-backend/ratomizer-desktop.exe --help` and require exit code 0.

- [ ] **Step 4: Report trial artifact**

Provide the absolute portable `.exe` path to the user and note that the generated release directory is intentionally not committed.
