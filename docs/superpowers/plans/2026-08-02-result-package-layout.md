# Result Package Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a deterministic `result-package.json`, keep user-facing deliverables in the selected output root, move internal runtime artifacts under `.ratomizer/`, and preserve review progress plus legacy output compatibility.

**Architecture:** Add a focused `result_package.py` contract that owns layout detection, package lifecycle, logical artifact paths, deliverable publication, and integrity checks. Desktop commands receive the user-selected package root but execute against governed internal roots; API and Electron resolve the package contract before reading data. Legacy directories without the marker continue using their existing flat paths.

**Tech Stack:** Python 3.11+, pathlib/json/hashlib, existing Windows atomic replace and cross-process lock patterns, Electron IPC, Vue 3/TypeScript, unittest, Vitest.

---

## File Structure

- Create `result_package.py`: schema/version constants, artifact registry, marker state machine, layout detection, path resolution, deliverable publishing.
- Create `schemas/result_package.schema.json`: machine validation for `ratomizer-result-package/v1`.
- Create `tests/test_result_package.py`: deterministic unit and crash-safety tests.
- Create `tests/test_result_package_e2e.py`: desktop-task/package/API/review persistence E2E.
- Modify `desktop_tasks.py`: package lifecycle commands, internal path resolution, deliverable synchronization, package-root payloads.
- Modify `desktop_backend.py`: API startup resolves package root to internal analysis root.
- Modify `api_server.py`: preserve package root while reading internal artifacts; expose package status.
- Modify `ui/electron/main.cjs`, `ui/electron/main.helpers.cjs`, `ui/electron/preload.cjs`: start/complete/fail package IPC and completed-folder recognition.
- Modify `ui/src/App.vue`, `ui/src/api-client.ts`, `ui/src/env.d.ts`: run lifecycle, package status, open-existing-result behavior.
- Modify review/claim/cache modules listed in Task 6 to use registered category paths.
- Modify `CLAUDE.md`: record result package contract and rollout milestone.

### Task 1: Result Package Contract

**Files:**
- Create: `result_package.py`
- Create: `schemas/result_package.schema.json`
- Create: `tests/test_result_package.py`

- [ ] **Step 1: Write failing lifecycle and validation tests**

Start with this concrete lifecycle test:

```python
class ResultPackageTests(unittest.TestCase):
    def test_initialize_empty_directory_creates_running_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "standard.docx"
            source.write_bytes(b"docx-fixture")
            package = initialize_result_package(
                root,
                input_path=source,
                requested_stages=["atomize", "requirements-analysis"],
            )
            self.assertEqual(package["schema"], RESULT_PACKAGE_SCHEMA)
            self.assertEqual(package["analysis_status"], "running")
            self.assertEqual(package["input"]["display_name"], "standard.docx")
            self.assertTrue((root / "result-package.json").is_file())
            self.assertTrue((root / ".ratomizer" / "pipeline").is_dir())
```

Add separate tests with exact assertions for completion evidence and hashes, review-state independence, failed-rerun preservation, corrupt-marker fail-closed behavior, legacy detection, path-escape rejection, and preservation of unknown user files.

- [ ] **Step 2: Run the new test module and confirm failure**

Run:

```powershell
./.venv/Scripts/python.exe -m unittest tests.test_result_package
```

Expected: import failure because `result_package` does not exist.

- [ ] **Step 3: Implement the schema, registry, state machine, and atomic writer**

Define these public constants and exceptions in `result_package.py`:

```python
RESULT_PACKAGE_SCHEMA = "ratomizer-result-package/v1"
OUTPUT_LAYOUT_VERSION = "result-layout-v1"
RESULT_PACKAGE_FILE = "result-package.json"
INTERNAL_ROOT = ".ratomizer"

class ResultPackageError(RuntimeError):
    pass

class ResultPackageCorrupt(ResultPackageError):
    pass

class ResultPackageVersionUnsupported(ResultPackageError):
    pass
```

Implement the exact public functions `detect_result_layout`, `initialize_result_package`, `package_artifact_path`, `commit_analysis_completion`, `record_analysis_failure`, `load_result_package`, and `publish_registered_deliverables` with the signatures defined in the approved design specification.

Use a frozen artifact registry with explicit IDs and roles. Reject absolute paths, `..`, unknown IDs, and unsupported schemas. Write markers through a sibling temporary file plus `os.replace`, using the existing Windows `PermissionError` retry pattern.

- [ ] **Step 4: Run lifecycle tests**

Expected: all tests in `tests.test_result_package` pass.

- [ ] **Step 5: Commit the contract**

```powershell
git add result_package.py schemas/result_package.schema.json tests/test_result_package.py
git commit -m "feat(result-package): add completion marker contract"
```

### Task 2: Desktop Task Lifecycle and Internal Roots

**Files:**
- Modify: `desktop_tasks.py`
- Modify: `tests/test_desktop_tasks.py`

- [ ] **Step 1: Add failing desktop lifecycle tests**

Add five named tests: `test_package_start_routes_new_desktop_output_under_dot_ratomizer`, `test_package_complete_publishes_root_deliverables_and_keeps_internal_jsonl_hidden`, `test_package_failure_does_not_claim_completion`, `test_summary_accepts_package_root_and_reads_internal_analysis_root`, and `test_legacy_nonempty_output_keeps_flat_layout`. Each test must assert the exact returned `out_dir`, physical internal path, marker status, and root file set.

- [ ] **Step 2: Run targeted tests and verify failure**

```powershell
./.venv/Scripts/python.exe -m unittest tests.test_desktop_tasks
```

- [ ] **Step 3: Add package lifecycle commands**

Extend `desktop_tasks.parse_args` and `main` with:

```text
result-package-start --out ROOT --input FILE --stages CSV
result-package-complete --out ROOT --run-id ID --completed-stages CSV
result-package-fail --out ROOT --run-id ID --error TEXT
result-package-status --out ROOT
```

For every existing desktop command with `--out`, resolve:

```python
package_root = Path(args.out).expanduser().resolve()
analysis_root = resolve_analysis_root(package_root)
```

Pass `analysis_root` to existing pipeline functions, but normalize returned `out_dir` to `package_root`. New package runs use `.ratomizer/pipeline/`; legacy directories continue using the root.

- [ ] **Step 4: Route logs and stage manifests**

For package layout only:

```text
run.log / llm_trace.jsonl -> .ratomizer/logs/
run_manifest.json / run_manifest.lock / _stages -> .ratomizer/stages/
```

Keep stage fingerprints semantically unchanged; bump only `OUTPUT_LAYOUT_VERSION` and result-package schema.

- [ ] **Step 5: Publish registered deliverables after successful tasks**

Call `publish_registered_deliverables(package_root)` after commands that can create a final deliverable. Rewrite `payload.path`, `payload.written`, and `payload.out_dir` to root-facing paths when a published copy exists.

- [ ] **Step 6: Run desktop task tests and commit**

```powershell
./.venv/Scripts/python.exe -m unittest tests.test_result_package tests.test_desktop_tasks
git add desktop_tasks.py tests/test_desktop_tasks.py
git commit -m "feat(desktop): manage result package lifecycle"
```

### Task 3: API and Electron Folder Recognition

**Files:**
- Modify: `desktop_backend.py`
- Modify: `api_server.py`
- Modify: `ui/electron/main.cjs`
- Modify: `ui/electron/main.helpers.cjs`
- Modify: `ui/electron/preload.cjs`
- Modify: `tests/test_api_server.py`
- Modify: `ui/electron/__tests__/main.helpers.spec.ts`

- [ ] **Step 1: Write failing recognition tests**

Test valid completed, incomplete, interrupted, corrupt, legacy, empty, and missing directories. A corrupt marker must not fall back to marker-file heuristics.

- [ ] **Step 2: Add package-aware API startup**

`api_server.main` receives the user package root, stores both:

```python
server.package_root
server.output_dir  # resolved internal analysis root for package_v1, root for legacy
```

Add `GET /result-package` returning package status plus derived review counts. Existing API endpoints continue reading `server.output_dir`.

- [ ] **Step 3: Replace Electron output heuristics**

Update `isLikelyOutputDir`/recent-session helpers to return a structured classification:

```javascript
{
  kind: "package_v1" | "legacy" | "invalid" | "not_output",
  analysisStatus: "completed" | "incomplete" | "running" | "legacy",
  reason: ""
}
```

`dialog:open-output` rejects ordinary folders and corrupt markers before starting the API.

- [ ] **Step 4: Run API/Electron tests and commit**

```powershell
./.venv/Scripts/python.exe -m unittest tests.test_api_server tests.test_result_package
cd ui
cmd /c npx vitest run electron/__tests__/main.helpers.spec.ts
cd ..
git add desktop_backend.py api_server.py ui/electron/main.cjs ui/electron/main.helpers.cjs ui/electron/preload.cjs tests/test_api_server.py ui/electron/__tests__/main.helpers.spec.ts
git commit -m "feat(result-package): recognize completed output folders"
```

### Task 4: Vue Run Lifecycle and Status UI

**Files:**
- Modify: `ui/src/App.vue`
- Modify: `ui/src/api-client.ts`
- Modify: `ui/src/env.d.ts`
- Modify: `ui/src/__tests__/ReviewWorkspace.spec.ts`
- Modify: `ui/src/__tests__/api-client.spec.ts`

- [ ] **Step 1: Extend the existing open-result test first**

Assert:

```text
run start -> result-package-start once
base pipeline + optional chain success -> result-package-complete once
any thrown pipeline/chain error -> result-package-fail once
review actions never call package-complete/fail
open completed folder -> review workspace + completed badge
open legacy folder -> legacy badge
```

- [ ] **Step 2: Add typed bridge/API contracts**

Expose lifecycle methods in preload/type declarations and add `RequirementApiClient.loadResultPackage()` for `/result-package`.

- [ ] **Step 3: Integrate lifecycle with `handleRunPipeline`**

Start the package before the first paid or mutating backend task. Complete only after base parsing and all UI-selected automatic stages finish. On error, record failure before surfacing the existing error message. Review and export-only actions do not change analysis completion.

- [ ] **Step 4: Render status without adding a new marketing panel**

Use compact badges in the run path panel/recent rows:

```text
自动分析：已完成
人工审核：36/120
旧版结果
上次运行中断
```

- [ ] **Step 5: Run frontend tests and commit**

```powershell
cd ui
cmd /c npm test
cmd /c npm run build
cd ..
git add ui/src/App.vue ui/src/api-client.ts ui/src/env.d.ts ui/src/__tests__/ReviewWorkspace.spec.ts ui/src/__tests__/api-client.spec.ts
git commit -m "feat(ui): show result package completion status"
```

### Task 5: Deliverable Publisher and Root Cleanliness

**Files:**
- Modify: `result_package.py`
- Modify: `desktop_tasks.py`
- Modify: `tests/test_result_package.py`
- Modify: `tests/test_desktop_tasks.py`

- [ ] **Step 1: Add failing root allowlist tests**

Generate representative internal and final files, publish, and assert the root contains only registered deliverables, `summary.md`, `result-package.json`, unknown user files, and `.ratomizer/`.

- [ ] **Step 2: Implement atomic file and directory publication**

Files use same-directory temp plus replace. Directories use a publication journal and backup swap so `engineering_requirements/` cannot be left half-updated.

- [ ] **Step 3: Register the initial deliverable set**

Register the exact logical outputs from the approved spec. Do not publish internal JSON merely because it is machine-readable.

- [ ] **Step 4: Verify hashes and stable marker bytes**

Unchanged deliverables must not rewrite `result-package.json`; changed exports update only their entry and package revision.

- [ ] **Step 5: Run tests and commit**

```powershell
./.venv/Scripts/python.exe -m unittest tests.test_result_package tests.test_desktop_tasks
git add result_package.py desktop_tasks.py tests/test_result_package.py tests/test_desktop_tasks.py
git commit -m "feat(result-package): publish clean root deliverables"
```

### Task 6: Review, Claim, Cache, and Lock Category Migration

**Files:**
- Modify: `review_state.py`, `ai_review_actions.py`, `llm_pipeline.py`
- Modify: `claim_artifacts.py`, `claim_review_actions.py`, `claim_queue_execution.py`
- Modify: `claim_reextract_attempts.py`, `claim_structural_overrides.py`, `claim_structural_operations.py`
- Modify: `ai_extract.py`, `requirements_analysis.py`, `doc_annotation_export.py`
- Modify affected tests under `tests/test_review_state.py`, `tests/test_claim_*.py`, `tests/test_ai_extract.py`

- [ ] **Step 1: Add category-path tests**

For package layout, assert review/claim authority files and locks use `.ratomizer/state/`, caches use `.ratomizer/cache/`, and trace/log files use `.ratomizer/logs/`. For legacy layout, assert byte-for-byte historical paths remain unchanged.

- [ ] **Step 2: Replace filename ownership with registered artifact IDs**

At each module boundary, resolve governed paths through `package_artifact_path`. Keep lock files colocated with their owning authority file and preserve existing lock order.

- [ ] **Step 3: Preserve cross-domain reads**

Claim and review code that needs pipeline evidence must resolve the pipeline artifact ID independently instead of assuming state and evidence share a directory.

- [ ] **Step 4: Run focused authority/recovery suites**

```powershell
./.venv/Scripts/python.exe -m unittest tests.test_review_state tests.test_authority_write_cas tests.test_claim_artifacts tests.test_claim_review_actions tests.test_claim_queue_execution tests.test_ai_extract
```

- [ ] **Step 5: Commit category migration**

```powershell
git add review_state.py ai_review_actions.py llm_pipeline.py claim_artifacts.py claim_review_actions.py claim_queue_execution.py claim_reextract_attempts.py claim_structural_overrides.py claim_structural_operations.py ai_extract.py requirements_analysis.py doc_annotation_export.py tests
git commit -m "refactor(artifacts): move internal state under dot ratomizer"
```

### Task 7: End-to-End, Legacy, and Crash Recovery Gates

**Files:**
- Create: `tests/test_result_package_e2e.py`
- Modify: `tests/test_golden_regression.py` only to add assertions, never baseline files
- Modify: `ui/src/__tests__/ReviewWorkspace.spec.ts`

- [ ] **Step 1: Build package E2E fixture**

Use a real minimal DOCX and real desktop task/API stack with network disabled. Verify analysis, package completion, API reload, one review decision, process restart, and persisted review progress.

- [ ] **Step 2: Add crash probes**

Inject failures before deliverable replace, after deliverable replace but before marker commit, during marker replace, and during a failed rerun over a previously completed package.

- [ ] **Step 3: Assert legacy and golden stability**

Legacy temp directories and frozen golden output continue using flat paths and retain exact expected bytes.

- [ ] **Step 4: Run complete verification**

```powershell
$env:RATOMIZER_HISTORICAL_SAMPLE='C:/Users/YYHwudi/Desktop/Canna-29/eval_assets/test18_functional_synthesis_sample.json'
./.venv/Scripts/python.exe -m unittest discover -s tests
./.venv/Scripts/python.exe -m unittest tests.test_golden_regression
./.venv/Scripts/python.exe agent_eval.py --eval-dir golden_sets/agent_eval_v1
cd ui
cmd /c npm test
cmd /c npm run build
cd ..
git diff --check
```

- [ ] **Step 5: Commit E2E gates**

```powershell
git add tests/test_result_package_e2e.py tests/test_golden_regression.py ui/src/__tests__/ReviewWorkspace.spec.ts
git commit -m "test(result-package): lock clean output and recovery"
```

### Task 8: Documentation and Desktop Packaging

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/cli-contract.md` if the opt-in CLI flag is exposed

- [ ] **Step 1: Record the shipped contract**

Document schema/version constants, desktop default behavior, legacy compatibility, review independence, and the exact verification results.

- [ ] **Step 2: Build the portable desktop tool**

Close any running portable executable that locks `ui/dist`, then run:

```powershell
cd ui
cmd /c npm run desktop:pack
```

- [ ] **Step 3: Smoke test the packaged executable**

Run a minimal document into a new output directory, confirm the clean root and completed badge, close the app, reopen the package using “打开已有结果”, and verify review progress persists.

- [ ] **Step 4: Commit documentation**

```powershell
git add CLAUDE.md docs/cli-contract.md
git commit -m "docs: record result package layout rollout"
```
