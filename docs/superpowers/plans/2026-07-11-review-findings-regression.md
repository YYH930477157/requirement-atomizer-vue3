# 0711 Review Findings Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the nine confirmed review findings without changing public output contracts, and lock each fix with a regression test.

**Architecture:** Keep fixes local to the existing parsing, enrichment, orchestration, classification, template, and Vue modules. Preserve cache performance by versioning affected stages instead of disabling reuse; preserve current route enum values and expose mixed execution through existing counters.

**Tech Stack:** Python 3.11+, pytest/unittest, Vue 3, TypeScript, Vitest, openpyxl.

---

### Task 1: Recursive trace truncation and cached Blue Book provenance

**Files:**
- Modify: `llm_client.py:71-85`
- Modify: `spec_enrich.py:273-299`
- Test: `tests/test_review_fixes_0711.py`
- Test: `tests/test_spec_enrich.py`

- [ ] **Step 1: Write failing nested trace regression**

Add a test using the real response nesting:

```python
def test_nested_response_content_truncated(self) -> None:
    from llm_client import _truncate_for_trace
    value = {"choices": [{"message": {"content": "x" * 5000,
                                          "reasoning_content": "r" * 5000}}]}
    out = _truncate_for_trace(value)
    message = out["choices"][0]["message"]
    self.assertLess(len(message["content"]), 2200)
    self.assertLess(len(message["reasoning_content"]), 2200)
```

- [ ] **Step 2: Write failing cache provenance regression**

Extend the existing cache-hit test to retain the second requirement and assert:

```python
self.assertEqual(second_req.get("blue_book_origin"), expected_section)
```

Use the existing Blue Book fixture/helpers; the second run must be a cache hit with zero new HTTP calls.

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m pytest tests/test_review_fixes_0711.py::TraceTruncationTests::test_nested_response_content_truncated tests/test_spec_enrich.py -q
```

Expected: nested response remains length 5000 and cached requirement lacks `blue_book_origin`.

- [ ] **Step 4: Implement minimal recursion and cache restoration**

Use recursive container handling:

```python
if isinstance(value, dict):
    return {key: _truncate_for_trace(item) for key, item in value.items()}
```

When recording a cache row, include `blue_book_origin`; on cache hit, restore a non-empty cached origin before applying the description.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_review_fixes_0711.py tests/test_spec_enrich.py tests/test_llm_client.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add llm_client.py spec_enrich.py tests/test_review_fixes_0711.py tests/test_spec_enrich.py
git commit -m "fix: preserve bounded LLM trace provenance"
```

### Task 2: Preserve sparse PDF cell text through validation

**Files:**
- Modify: `parsers/pdf_parser.py:189-200`
- Test: `tests/test_review_fixes_0711.py`
- Test: `tests/test_pdf_parser_defrag.py`

- [ ] **Step 1: Write failing assembly-plus-validation regression**

Build a three-row matrix with stable columns at 100/200/300 and one OBIS cell at 999. Call `_assemble_rows`, then `_validate_text_table`, and assert the final matrix still contains the OBIS value.

```python
matrix = _assemble_rows(region, [100.0, 200.0, 300.0, 999.0])
validated = _validate_text_table(matrix, region_lines=3, page_candidate_lines=3)
self.assertIsNotNone(validated)
self.assertIn("0-0:96.1.0", " ".join(" ".join(row) for row in validated or []))
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_review_fixes_0711.py::PdfCellFallbackTests -q
```

Expected: the OBIS exists before validation but is absent afterward.

- [ ] **Step 3: Merge sparse text before projecting kept columns**

Before dropping sparse columns, append every non-empty dropped cell to the nearest kept column in the same row:

```python
for row in matrix:
    for column in dropped:
        if column < len(row) and row[column]:
            target = min(keep, key=lambda candidate: abs(candidate - column))
            row[target] = " ".join(part for part in (row[target], row[column]) if part)
matrix = [[row[column] if column < len(row) else "" for column in keep] for row in matrix]
```

- [ ] **Step 4: Verify GREEN and parser regressions**

Run:

```powershell
python -m pytest tests/test_review_fixes_0711.py::PdfCellFallbackTests tests/test_pdf_parser_defrag.py tests/test_pdf_text_tables.py -q
```

Expected: all selected tests pass and table veto tests remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add parsers/pdf_parser.py tests/test_review_fixes_0711.py
git commit -m "fix: retain sparse PDF table cells"
```

### Task 3: Correct stage invalidation, clarification fingerprints, and route reporting

**Files:**
- Modify: `desktop_tasks.py:333-386`
- Modify: `requirements_analysis.py:104-190`
- Test: `tests/test_desktop_tasks.py`
- Test: `tests/test_requirements_analysis_pipeline.py`
- Test: `tests/test_review_fixes_0711.py`

- [ ] **Step 1: Write failing stage producer regressions**

Assert every affected stage has a producer value distinct from the pre-fix values and that a manifest using the old producer is not reusable. Cover `atomize`, `ai-extract`, `assemble`, `functional-synthesis`, `requirements-analysis`, `template-write`, and `clarification-report`.

- [ ] **Step 2: Write failing clarification fingerprint regression**

Create all current clarification inputs plus `functional_requirements.json`, fingerprint the stage, change only its conflict flags, and assert the fingerprint changes.

- [ ] **Step 3: Write failing all-degraded route regression**

Extend `test_fabricated_code_rejects_enrichment_and_degrades` or add a focused test:

```python
assert result["enriched"] == 0
assert result["enrich_degraded"] == 1
assert result["route"] == "stub"
assert result["route_requested"] == "openai_compatible"
```

Also add a two-item mixed result test asserting one accepted item keeps `route == "openai_compatible"`.

- [ ] **Step 4: Verify RED**

Run:

```powershell
python -m pytest tests/test_desktop_tasks.py tests/test_requirements_analysis_pipeline.py -q
```

Expected: old producer remains reusable, clarification fingerprint is unchanged, and all-degraded route is still `openai_compatible`.

- [ ] **Step 5: Implement explicit stage implementation revisions**

Add a central revision map in `desktop_tasks.py` and combine it with prompt versions where applicable:

```python
STAGE_IMPLEMENTATION_REVISIONS = {
    "atomize": "v2", "ai-extract": "v2", "assemble": "v2",
    "functional-synthesis": "v2", "requirements-analysis": "v2",
    "template-write": "v2", "clarification-report": "v3",
}
```

`stage_producer()` must return stable strings containing these revisions. Add `FUNCTIONAL_REQUIREMENTS` to `STAGE_INPUTS["clarification-report"]`.

- [ ] **Step 6: Compute executed route after enrichment**

Initialize the route conservatively and finalize after `_run_enrichment`:

```python
executed_route = "openai_compatible" if active_chat is not None and enriched_count > 0 else STUB_ROUTE
```

When active chat existed but no result was accepted, add a truthful degradation note without changing `route_requested`.

- [ ] **Step 7: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_desktop_tasks.py tests/test_requirements_analysis_pipeline.py tests/test_review_fixes_0711.py tests/test_review_findings_regression.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add desktop_tasks.py requirements_analysis.py tests/test_desktop_tasks.py tests/test_requirements_analysis_pipeline.py tests/test_review_fixes_0711.py
git commit -m "fix: invalidate stale analysis stage outputs"
```

### Task 4: Scope CJK false friends and make fallback mappings explicit

**Files:**
- Modify: `requirements_analysis_rules.py:97-156`
- Modify: `template_writer.py:46-79`
- Test: `tests/test_requirements_analysis_rules.py`
- Test: `tests/test_review_fixes_0711.py`
- Test: `tests/test_template_writer.py`

- [ ] **Step 1: Write failing ownership regressions**

Add tests for both cases:

```python
software = classify_ownership({"description": "软件应从计量芯片读取时钟并同步系统时间"})
self.assertEqual(software["ownership"], "software")

hardware_phrase = classify_ownership({"title": "时钟计数器型号"})
self.assertNotIn("时钟", hardware_phrase["ownership_reason"])
```

Add a second occurrence/different-field case so one hardware-local occurrence cannot suppress a legitimate software occurrence elsewhere.

- [ ] **Step 2: Write failing mapping drift assertion**

Replace type-only assertions with:

```python
self.assertEqual(module_mapping_drift(), ([], []))
```

Keep the existing assertion that `安全` routes to `FALLBACK_SHEET` when no dedicated sheet exists.

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m pytest tests/test_requirements_analysis_rules.py tests/test_review_fixes_0711.py::CjkFalseFriendTests tests/test_review_fixes_0711.py::ModuleMappingDriftTests -q
```

Expected: software action case returns hardware and drift reports eight modules.

- [ ] **Step 4: Implement local context matching**

Inspect each CJK term occurrence in a bounded window. Suppress a short software term only when every occurrence has a hardware context term and no software action term such as `读取`, `同步`, `记录`, `配置`, `处理`, `上报`, or `控制`.

- [ ] **Step 5: Make intentional fallback mapping explicit**

Add the currently intentional fallback modules to `MODULE_TO_SHEET` with value `FALLBACK_SHEET`: `CIU`, `其它`, `安全`, `机械结构`, `测试合规`, `环境可靠性`, `节假日`, `附加功能`.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_requirements_analysis_rules.py tests/test_review_fixes_0711.py tests/test_template_writer.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add requirements_analysis_rules.py template_writer.py tests/test_requirements_analysis_rules.py tests/test_review_fixes_0711.py tests/test_template_writer.py
git commit -m "fix: scope ownership and template fallback rules"
```

### Task 5: Disable functional synthesis UI state whenever LLM is off

**Files:**
- Modify: `ui/src/App.vue:741-757`
- Test: `ui/src/__tests__/ReviewWorkspace.spec.ts`

- [ ] **Step 1: Write failing UI regression**

Configure local storage with `aiExtract: true`, `analyze: false`, mount with LLM disabled, start a run, and assert:

```typescript
expect(wrapper.find('[data-testid="run-stage-functional-synthesis"]').text()).toContain("未启用")
expect(wrapper.find('[data-testid="run-stage-functional-synthesis"]').text()).not.toContain("待完成")
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
npm test -- --run src/__tests__/ReviewWorkspace.spec.ts
```

Expected: functional synthesis card remains `待完成`.

- [ ] **Step 3: Implement independent LLM gating**

In `resetRunStageBoard`, after the AI-extract dependency check, disable functional synthesis when `llmMode.value` is false. Keep the dependency-specific message when AI extraction itself is disabled.

- [ ] **Step 4: Verify GREEN and build**

Run:

```powershell
npm test
npm run build
```

Expected: all UI tests and TypeScript/Vite build pass.

- [ ] **Step 5: Commit**

```powershell
git add ui/src/App.vue ui/src/__tests__/ReviewWorkspace.spec.ts
git commit -m "fix: reflect disabled synthesis stage in UI"
```

### Task 6: Integrated regression and final review

**Files:**
- Review all files changed by Tasks 1-5.

- [ ] **Step 1: Run changed-area Python tests**

```powershell
python -m pytest tests/test_review_fixes_0711.py tests/test_audit_fixes.py tests/test_llm_client.py tests/test_spec_enrich.py tests/test_pdf_parser_defrag.py tests/test_pdf_text_tables.py tests/test_desktop_tasks.py tests/test_requirements_analysis_pipeline.py tests/test_requirements_analysis_rules.py tests/test_template_writer.py tests/test_review_findings_regression.py -q
```

- [ ] **Step 2: Run all Python tests in bounded groups**

Run every `tests/test_*.py` file. The monolithic suite exceeds the 240-second command window, so use the same complete, non-overlapping groups established during review and sum passed/skipped counts against collected total.

- [ ] **Step 3: Run complete frontend verification**

```powershell
cd ui
npm test
npm run build
```

- [ ] **Step 4: Inspect repository state**

```powershell
git status --short --branch
git diff main...HEAD --stat
git diff main...HEAD
```

Expected: only intended code, tests, design, and plan changes are present; no template asset, golden baseline, generated `dist`, or local `硬件` file is committed.

- [ ] **Step 5: Request final code review**

Review against `docs/superpowers/specs/2026-07-11-review-findings-regression-design.md`, with findings ordered by severity and exact file/line references.
