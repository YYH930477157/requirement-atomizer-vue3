# AGENTS.md

Context for agents working in this repo. `CLAUDE.md` is the historical decision log — read it for context before non-trivial work, but it may contain stale claims; where it conflicts with current code/config, the code wins (newest dated entries are most reliable). Update it after milestones.

## What this is

Python pipeline that atomizes technical standards (DOCX/XLSX/PDF) into reviewable atomic requirements, ending in DLMS/COSEM implementation specs. Flat layout: most modules are top-level `*.py` files (registered in `pyproject.toml` `py-modules`); packages are `parsers/`, `requirement_kb/`, `gui/`, plus `ui/` (Vue3+Electron).

Key entrypoints: `cli.py` (`ratomizer`), `atomize.py`, `api_server.py` (local review API), `desktop_tasks.py` (Electron task bridge). Machine-facing CLI contract: `docs/cli-contract.md` (exit codes 0/2/3/4, stdout = UTF-8 JSON envelope).

Agent Phase 0: `agent_eval.py` runs `golden_sets/agent_eval_v1`; `decide_trace.py` validates/appends the future `decide_trace.jsonl`; the cache lineage anchor is `agent_policy.AGENT_POLICY_VERSION`.

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
- **Shared state files** (`review_states.jsonl`, `ai_review_states.jsonl`, `run_manifest.json`, append-only caches) require cross-process lock + atomic replace with `PermissionError` retry (Windows readers block `os.replace`). Copy the existing pattern in `review_state.py` / `ai_review_actions.py` / `desktop_tasks.py`; never bare-append without a lock.

## Environment gotchas

- **Node 24 breaks `extract-zip`** (electron install silently writes nothing; `npm install` won't fix). Fix: `Expand-Archive` the cached electron zip from `%LOCALAPPDATA%\electron\Cache\<hash>\` into `ui/node_modules/electron/dist`, then write `ui/node_modules/electron/path.txt` containing `electron.exe`. Packaging via electron-builder is unaffected. Root fix: use Node LTS 22.
- Dev machine runs Python 3.14, but `pyproject.toml` only requires >=3.11 — don't hard-require 3.14 features. `requirements.txt` is runtime deps only; desktop packaging additionally needs PyInstaller (`pip install -e .[package]`, used by `cd ui; npm run desktop:pack`, which builds the backend first).

## Workflow conventions

- Implementation happens on `codex/*` branches in isolated git worktrees; user decides merge to main. Never push without user approval. Never commit unless asked.
- Golden six-item tests run only in a checkout where the `out/` baseline exists (main; they compare against the pre-generated directory, they do not regenerate it). After bumping any behavior version (`EXTRACT_GUARDS_VERSION`, `*_PROMPT_VERSION`, `ENRICH_GUARDS_VERSION`, `LLM_REVIEW_CACHE_VERSION`): merge to main, regenerate `out/abnt_nbr_16968_atomizer_v5/` with the three seed KBs + domain-pack, then run the golden tests — the merge is not final until drift is zero or itemized in `CLAUDE.md`.
- B-track (`merged_spec`/`analyze`, AI extraction) is the primary deliverable for prose-style/tender docs (no COSEM tables; rule layer is blind to noun-phrase specs). A-track (`assemble`, atoms+llm_review) is primary for DLMS profile docs.
