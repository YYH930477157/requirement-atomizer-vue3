# 2026-07-09 Review Handoff

This note supplements the two commits pushed on 2026-07-09 so reviewers do not need to reconstruct the intent from chat history.

## Commit `0cc50d1` - Hardware And Source Annotation Handling

Subject: `Refine hardware and source annotation handling`

### User-visible bug

Some source text was unclear in the generated HTML:

- Hardware-only definitions could be treated like ordinary software requirements.
- Hardware-only items could still show software development or test guidance.
- Unextracted source text could have no clickable marker, so users could not tell whether it was ignored, hardware-only, or terminology.
- Software terminology such as `significant event` could appear without a visible explanation when it was not extracted as a requirement.

### Root cause

The analysis pipeline did not normalize hardware-only outputs separately from software/co-design outputs. The HTML exporter also had incomplete fallback marker coverage and some markers were static rather than interactive.

### Fix

- Normalize hardware-only items so they keep Chinese translation, hardware summary, and ownership reason.
- Clear software requirement text, developer guidance, acceptance criteria, and hardware dependency for hardware-only items.
- Add a lightweight LLM path for hardware translation and ownership reason when `openai_compatible` is enabled.
- Add clickable fallback source markers for hardware, co-design, and software-term cases.
- Add software-term marker coverage for `significant event` style definitions.
- Add regression tests for hardware, co-design, mobile concentrator, and significant-event marker behavior.

### Verification

```powershell
python -m pytest tests/test_requirements_analysis_pipeline.py tests/test_requirements_analysis_rules.py tests/test_doc_annotation_export.py tests/test_annotation_contract.py -q
```

Result recorded before push: `53 passed`.

## Commit `06aa979` - Resumable Desktop Stage Ledger

Subject: `Add resumable stage ledger for desktop runs`

### User-visible bug

If the desktop API failed to reconnect, the app was closed, or a long LLM run was interrupted, users had no reliable way to know which expensive stages had already completed. This could cause unnecessary reruns and wasted LLM token cost.

### Root cause

Desktop tasks only returned coarse run status. They did not persist per-stage completion metadata, required output lists, or route information, and the Vue UI only displayed a single broad progress state.

### Fix

- Add `run_manifest.json` as the output-directory stage ledger.
- Add per-stage manifests under `_stages/<stage>/stage_manifest.json`.
- Track required outputs for atomize, LLM review, AI extraction, assembly, requirements analysis, template writing, clarification report, compose, and annotation HTML export.
- Reuse completed stage outputs when the ledger and files are valid.
- Mark reused stages as skipped instead of rerunning them.
- Add a Vue run-stage board so users can see each stage as pending, running, completed, skipped, or failed.
- Keep generated-output guidance visible when API session refresh times out, instead of turning a completed run into a failed user experience.
- Update Electron bridge typing and package smoke handling for progress events and JSON output.

### Verification

```powershell
python -m pytest tests/test_desktop_tasks.py -q
npm test
```

Results recorded before push:

- Python desktop task tests: `37 passed`
- Vue/Electron tests: `60 passed`

## Notes For Reviewers

- The two commits were intentionally separated:
  - `0cc50d1` changes requirement interpretation and HTML annotation semantics.
  - `06aa979` changes desktop execution reliability, resumability, and run progress UI.
- The untracked zero-byte file named `硬件` was not included in either commit.
- No force push or history rewrite was used after the commits reached `origin/main`.
