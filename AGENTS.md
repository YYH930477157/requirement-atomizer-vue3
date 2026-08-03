# AGENTS.md

Context for agents working in this repo. `CLAUDE.md` is the historical decision log — read it for context before non-trivial work, but it may contain stale claims; where it conflicts with current code/config, the code wins (newest dated entries are most reliable). Update it after milestones.

## What this is

Python pipeline that atomizes technical standards (DOCX/XLSX/PDF) into reviewable atomic requirements, ending in DLMS/COSEM implementation specs. Flat layout: most modules are top-level `*.py` files (registered in `pyproject.toml` `py-modules`); packages are `parsers/`, `requirement_kb/`, `gui/`, plus `ui/` (Vue3+Electron).

Key entrypoints: `cli.py` (`ratomizer`), `atomize.py`, `api_server.py` (local review API), `desktop_tasks.py` (Electron task bridge). Machine-facing CLI contract: `docs/cli-contract.md` (exit codes 0/2/3/4, stdout = UTF-8 JSON envelope).

Agent Phase 0/1/1.5: `agent_eval.py` runs `golden_sets/agent_eval_v1`; `agent_state.py` builds a read-only artifact view; `agent_loop.py` runs the bounded loop (`--decider rule` default, `--decider llm` opt-in with per-iteration rule fallback and decision-only token accounting); `agent_compare.py` runs rule vs llm on copies; `decide_trace.py` validates/appends `decide_trace.jsonl`. The cache lineage anchor is `agent_policy.AGENT_POLICY_VERSION` (`agent-policy-v3`). Agent stages are deliberately outside `CHAIN_ORDER`.

Agent Phase 2: `llm_client.chat_with_tools` runs a bounded tool-loop (`max_rounds=8`, per-requirement token budget default 20000, over-budget/round-cap/4xx → existing stub failure path, never disguised as reviewed); `review_tools.py` exposes five deterministic read-only review tools (`kb_search`/`kb_get`/`blue_book_class`/`source_read`/`coverage_check`) with `REVIEW_TOOLS_VERSION` (`review-tools-v3`) pinned into the review cache fingerprint; `llm_agents/review_pipeline.yaml` operations carry `executor` (`tool_loop` for classify_risk/correct_errors as one fused call per requirement, `deterministic` for merge_duplicates/gap_find, `deferred` for test_point_generate). WP2: unfounded enrichment fields are marked `待澄清` in `requirements_analysis._apply_llm_item` (`UNFOUNDED_RULE_VERSION=analyze-unfounded-v3`, in the analyze cache fingerprint; `ANALYZE_PROMPT_VERSION=analyze-llm-v7`).

Word/Excel facsimile branch + spot extract (2026-07-28, spec `docs/facsimile-spotextract-spec.md`): `doc_facsimile.py` lazily converts docx/xlsx to `out/document_facsimile.pdf` at the `export-annotation-html` stage (Office COM first, LibreOffice `soffice` fallback, `unavailable:<reason>` recorded honestly — page images are never faked); cache key = input sha256 + `DOC_FACSIMILE_VERSION` (`doc-facsimile-v1`), which is pinned into the `export-annotation-html` chain producer stamp. `spot_extract.py` + `POST /spot-extract` (alias `/api/spot-extract`) runs single block/row targeted analysis: deterministic guards-v16 single-row expansion for requirement-shaped parameter rows, single-segment `critique_section` LLM path otherwise; drafts (`source_mapping: "spot_extract"`, suspicion `用户定点解析`) go to clarification only, and an unavailable LLM fails loudly (`ok: false`) — never a fabricated stub.

Table structure & cell-level closure (2026-08-01, branch `codex/table-structure-cell-closure`): `table_structure.py` owns deterministic table roles and row/cell/mixed leaf planning (`TABLE_STRUCTURE_VERSION="table-structure-v6"`; catalog `claim-catalog-v10`). `table_cell_items.jsonl` (schema `table-cell-item/v1`) records each non-empty physical cell/merge anchor and is hash-bound into publication. Table-cell claims use exact `table_cell_text` locators, per-sentence spans, deterministic row/header context, and a real catalog→publish→fold→queue→execute→annotation E2E. Ambiguous, weak-signal, unsignaled, rejected-marker, and untyped-colon cells are materialized as reviewable excluded candidates rather than silently dropped or promoted. Experts can promote them or confirm exclusion; confirmations append to `claim_structural_candidate_decisions.jsonl` (`v2` writer with frozen `v1` replay), and pending candidates block Ledger Ready. Old table artifacts are never fake-migrated: version/status gates return `base_migration_required`.

Claim paid-work recovery (2026-08-01): queue and verifier accounting fan out through `.claim_budget_checkpoint.outbox.json`. The same cumulative budget transition is durably projected to `claim_reextract_attempts.jsonl` and the verifier WAL before the outbox is removed. GET paths fail closed and never recover it; queue execution, startup maintenance, or `POST /claim-maintenance` recover under write locks. `CLAIM_REEXTRACT_ATTEMPT_VERSION="claim-reextract-attempt-log-v3"`.

Result package layout (2026-08-02/03): new desktop runs write a `result-package.json` marker (`ratomizer-result-package/v1`, layout `result-layout-v1`) plus `.ratomizer/{pipeline,state,cache,logs,stages}`; the root holds only registry-published human deliverables. **Addressing rule: all state/cache/log/stage paths MUST go through `result_package.governed_artifact_path` (or `package_artifact_path` for registry artifacts) — never hardcode filename joins against the output root.** Under `package_v1` those files live in `.ratomizer/state|cache|logs|stages`, so bare `root / "review_states.jsonl"`-style joins silently mis-address (this caused the 2026-08-03 B1 startup-maintenance skip). `governed_artifact_path(..., for_write=False)` is the pure-resolution read form; only `for_write=True` may create directories. Marker loading validates against `schemas/result_package.schema.json` (top-level whitelist, `package_id`/`tool`/`warnings`); `load_result_package(root, verify=True)` recomputes deliverable/completion-evidence SHA and is wired to 「打开已有结果」(`/result-package?verify=1`, `result-package-status --verify`) — mismatch surfaces `result_package_modified` ("结果文件已被修改"). The frozen PySide6 `gui/` (`gui/requirements_model.py`) reads legacy flat paths only and is compatible with legacy outputs, not `package_v1`.

Facsimile geometry + table-row/cell zones (2026-08-01, same branch): `_resolve_pdf_geometry` backfills block geometry for page-less docx/xlsx blocks and carries row/canonical-cell geometry without inventing coordinates. Row zones remain mutually exclusive; merged cells render only at their canonical anchor. The app and standalone HTML expose row and cell context plus table-cell claim chips, including title/header cells. Current annotation contract is `claim-annotation-v16`, with producer stamp `doc_annotation_export/v16-cell-claim-projection`.

## Test & verify commands

Backend (run from repo root):

```powershell
python -m unittest discover -s tests   # NOT pytest — pytest is not installed; module-level def test_* is silently skipped. Tests MUST be unittest.TestCase.
```

Frontend (run from `ui/`):

```powershell
npm test         # vitest
npm run build    # vue-tsc --noEmit + vite build (typecheck lives here)
```

On this machine PowerShell blocks `npm.ps1` (execution policy) — use `cmd /c "npm test"` or fix the policy; this also affects `npm run desktop:pack`.

README's `python -m pytest -q` is stale; trust the unittest command above.

- In the main checkout (where `out/` exists): 0-skip run requires env `RATOMIZER_HISTORICAL_SAMPLE="C:/Users/YYHwudi/Desktop/Canna-29/eval_assets/test18_functional_synthesis_sample.json"` (machine-local path, else 1 honest skip). In isolated worktrees, `out/` is git-ignored so the 5 golden tests also skip — a green run there does NOT cover golden regression.
- Golden regression (`golden_sets/abnt_nbr_16968_v5/golden_summary.json`) is a frozen baseline — never change it without itemized justification. Baseline output in `out/abnt_nbr_16968_atomizer_v5/` was generated with **three seed `--kb` files + domain-pack**, NOT the single compiled KB; regenerating with the wrong KB causes fake drift.
- GUI tests skip if PySide6 is absent.

## Hard constraints (violations have caused real bugs)

- **GUI = `ui/` (Vue3+Electron). `gui/` (PySide6) is FROZEN** — kept runnable but never extended. `review_actions.py` lives at repo root, not under `gui/`.
- **Cache fingerprints must include deterministic post-processing versions.** Cached results store post-guard output, so if you change guard/verify behavior, bump `EXTRACT_GUARDS_VERSION` (and equivalents) — otherwise old caches silently bypass new behavior.
- **KB dual-track is deliberate:** runtime (CLI default + GUI preset) uses single `knowledge_bases/compiled_from_obsidian.json`; golden baseline uses the three seed KBs. Don't "unify" them.
- **Never commit:** Blue Book PDFs, company template xlsx, customer documents, eval assets with client wording, API keys. Keys are env-vars only; the mimo endpoint requires `x-api-key` header (`llm_client` sends both).
- Machine-local test assets (this machine only; parameterize if tests ever run elsewhere): `C:\Users\YYHwudi\Desktop\Canna-29\` (ABNT docx/pdf, Blue Book part 1/2 PDFs, company template).
- Anti-hallucination discipline: structured fields (OBIS, class_id, access) are deterministic-join only; LLM enrichment fills narrative fields only, fabricated codes/numbers are rejected. "Better to miss than to guess" (宁漏勿错).
- **Provenance is never falsified:** route degradation must record `route_requested` truthfully; stub output must never be labeled as LLM output; cached/merged results keep their true origin.
- **Phase 1 is zero-LLM:** the rule loop has `tokens_max=0`. Its resample action queues the current omission as `needs_extraction` and records `skipped`; only an explicit external `allow_llm=True` tool call may delegate to `targeted_reextract`. A queued action must never be reported as completed extraction.
- **Shared state files** (`review_states.jsonl`, `ai_review_states.jsonl`, `run_manifest.json`, append-only caches) require cross-process lock + atomic replace with `PermissionError` retry (Windows readers block `os.replace`). Copy the existing pattern in `review_state.py` / `ai_review_actions.py` / `desktop_tasks.py`; never bare-append without a lock.

## Environment gotchas

- **Node 24 breaks `extract-zip`** (electron install silently writes nothing; `npm install` won't fix). Fix: `Expand-Archive` the cached electron zip from `%LOCALAPPDATA%\electron\Cache\<hash>\` into `ui/node_modules/electron/dist`, then write `ui/node_modules/electron/path.txt` containing `electron.exe`. Packaging via electron-builder is unaffected. Root fix: use Node LTS 22.
- Dev machine runs Python 3.14, but `pyproject.toml` only requires >=3.11 — don't hard-require 3.14 features. `requirements.txt` is runtime deps only; desktop packaging additionally needs PyInstaller (`pip install -e .[package]`, used by `cd ui; npm run desktop:pack`, which builds the backend first).

## Workflow conventions

- Implementation happens on `codex/*` branches in isolated git worktrees; user decides merge to main. Never push without user approval. Never commit unless asked.
- Golden six-item tests run only in a checkout where the `out/` baseline exists (main; they compare against the pre-generated directory, they do not regenerate it). After bumping any behavior version (`EXTRACT_GUARDS_VERSION`, `*_PROMPT_VERSION`, `ENRICH_GUARDS_VERSION`, `LLM_REVIEW_CACHE_VERSION`): merge to main, regenerate `out/abnt_nbr_16968_atomizer_v5/` with the three seed KBs + domain-pack, then run the golden tests — the merge is not final until drift is zero or itemized in `CLAUDE.md`.
- B-track (`merged_spec`/`analyze`, AI extraction) is the primary deliverable for prose-style/tender docs (no COSEM tables; rule layer is blind to noun-phrase specs). A-track (`assemble`, atoms+llm_review) is primary for DLMS profile docs.
