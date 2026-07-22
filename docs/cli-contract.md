# CLI Contract

Requirement Atomizer exposes a stable command line interface for task managers and future GUI shells.

## Commands

```powershell
ratomizer run <input.docx|input.xlsx|input.pdf> --out DIR [--kb FILE]... [--domain-pack DIR] [--chunk-chars N] [--skip-review] [--llm-route stub|openai_compatible] [--review-scope targeted|all] [--export md,csv] [--quiet | --verbose]
ratomizer atomize <input.docx|input.xlsx|input.pdf> --out DIR [--kb FILE]... [--domain-pack DIR] [--chunk-chars N] [--quiet | --verbose]
ratomizer review --out DIR [--review-pipeline FILE] [--domain-pack FILE] [--limit N] [--llm-route stub|openai_compatible] [--review-scope targeted|all] [--quiet | --verbose]
ratomizer export --out DIR --format md|csv [--status all|accepted|expert_pending|candidate]
ratomizer compose --out DIR [--quiet | --verbose]
ratomizer analyze --out DIR [--template FILE.xlsx] [--llm-route stub|openai_compatible] [--quiet | --verbose]
ratomizer --version
python agent_eval.py --eval-dir DIR
python agent_loop.py --out-dir DIR [--max-iterations N]
```

`agent_eval.py` is the Phase 0 deterministic evaluation runner. It validates every case against
`schemas/agent_eval_case.schema.json`, scores only the current rule-based classification cases,
and reports grouping, must-ask, and hallucination cases as schema-only until later agent phases.
It never calls an LLM. Missing/empty datasets return exit 2; malformed cases return exit 3.

`agent_loop.py` is the Phase 1 bounded rule-decider (`agent-policy-v2`). It reloads a read-only
aggregate view of an existing extraction directory before each decision, appends every decision
to `decide_trace.jsonl`, and writes `agent_loop_summary.json`. The default iteration budget is
10 and the accepted range is 1 through 50; `tokens_max` and `tokens_used` are always zero. The
frozen priority is READY -> stop, unqueued gaps -> `queue_all_gaps`, unresolved hard question ->
`ask_clarification`, otherwise stop. Phase 1 never calls an LLM or the network.

`queue_all_gaps` registers every currently uncovered, not-yet-queued block as
`needs_extraction` in one locked batch (per-block queueing exhausted the iteration budget on
real documents). Blocks already carrying a current `needs_extraction` or `issue_confirmed`
omission state are excluded from candidates, so re-running the loop over the same directory
never appends duplicate omission rows; a repeated per-block `resample_section` call is likewise
idempotent and returns `skipped` without appending.

The existing targeted omission extractor is LLM-only. Therefore a Phase 1
`resample_section:<block_id>` decision records the current block as `needs_extraction` and
truthfully returns `result.status: "skipped"`; it never claims that semantic extraction
completed. The thin tool wrapper can delegate to the existing targeted extractor only when an
external caller explicitly enables LLM execution. `recheck:<req_id>` is exposed as a tool
contract but is not selected by the rule priority and is skipped in zero-LLM mode because the
existing semantic recheck has no standalone deterministic publisher.

`analyze` runs the requirements analysis agent over a reviewed output directory (requires `ai_requirements.jsonl` produced by AI extraction; missing input is an input error, exit 2 semantics via error envelope). It writes `software_requirements.xlsx`, `engineering_analysis.json`, `hardware_items.md`, and `co_design_items.md`. An explicit `--template` path must exist.

Ownership classification, module mapping, review decisions, and all structural fields are deterministic. `--llm-route openai_compatible` additionally enables an **LLM enrichment layer** that fills the narrative fields only — `software_requirement_text`, `developer_guidance`, `design_options`, `acceptance_criteria`, `hardware_dependency`, `open_questions`. Structural and routing fields (ownership, module, OBIS/class/access, ids) are never overwritten by the model. Each enrichment is drift-checked: if the model fabricates a code or number not in the source, that item's enrichment is rejected and it stays deterministic (recorded as an issue). When the endpoint is unusable (no `RATOMIZER_LLM_API_KEY` set), the run degrades to the deterministic path and records `route: "stub"` plus `route_requested` (provenance is never falsified). Output adds `enriched` / `enrich_degraded` counts. Enrichment results are cached per source-content fingerprint in `analyze_enrich_cache.json` (idempotent re-runs).

Existing entry points remain compatible:

```powershell
python .\atomize.py <input.docx|input.xlsx|input.pdf> --out DIR
python .\llm_pipeline.py --out DIR
```

Supported input formats are `.docx`, `.xlsx`, and text-layer `.pdf`. Legacy `.xls` workbooks are rejected with an input error and should be saved as `.xlsx`. PDFs without an extractable text layer are rejected with exit code 2; OCR/scanned PDF handling is out of scope for this version, and callers should convert the PDF to `.docx` first.

## Stdout Envelope

All non-version commands write exactly one JSON object to stdout.
The stdout byte stream is UTF-8 encoded; consumers must decode it as UTF-8. Windows callers that decode pipes with the default GBK code page may fail on non-ASCII paths or messages.

```json
{
  "tool": "requirement-atomizer",
  "schema_version": "1.0",
  "command": "run",
  "ok": true,
  "output_dir": "D:/path/to/out",
  "manifest": {
    "input_format": "docx"
  },
  "review": {
    "reviews": 2337,
    "llm_reviewed": 340,
    "rule_stub": 1997,
    "llm_failed": 0
  },
  "quality_summary": {
    "atomic_requirements": 2337,
    "ambiguous": 6,
    "low_confidence": 83,
    "body_table_candidate_ratio": 0.9928
  },
  "exports": ["requirements_export.csv"],
  "timing_ms": {"atomize": 41200, "review": 1800, "total": 43000}
}
```

On failure stdout still contains one JSON envelope:

```json
{
  "tool": "requirement-atomizer",
  "schema_version": "1.0",
  "command": "run",
  "ok": false,
  "error": {"type": "input_error", "message": "Input file does not exist: D:/missing.docx"}
}
```

Argument parser errors raised before command dispatch, such as an invalid `ratomizer export --format` choice, are the only exception: argparse writes usage details to stderr and may not emit a JSON envelope. Runtime validation errors, such as an unsupported `ratomizer run --export` format, still emit the failure envelope above.

`schema_version` follows semantic compatibility: breaking envelope changes require a major schema version bump.

## Exit Codes

| Code | Meaning | Trigger |
| --- | --- | --- |
| 0 | Success | Command completed and stdout contains `ok: true`. |
| 2 | Input error | Missing input, unsupported input format, missing domain pack file, or invalid arguments detected by the runtime. |
| 3 | Pipeline or validation error | Atomic requirement schema validation failure or output write/validation errors. |
| 4 | LLM service unavailable | OpenAI-compatible review route fails the initial LLM connection probe or reaches the configured consecutive connection failure abort threshold. |
| 1 | Unexpected exception | Any unclassified crash. Traceback is written to stderr. |

## Stderr Logging

The core logger name is `requirement_atomizer`.

- stdout is reserved for the JSON envelope.
- stderr receives human-readable logs in `[seconds] message` format.
- `--quiet` emits only `WARNING` and above.
- default emits `INFO` and above.
- `--verbose` emits `DEBUG` and above.

## Functional Synthesis Contract

The desktop bridge command `python -m desktop_tasks functional-synthesis --out DIR [--llm-route stub|openai_compatible]` writes `functional_requirements.json`. Every eligible AI requirement ID must appear exactly once. Items contain structured objective, behavior, lifecycle-role, condition, constraint, variant, exception, DLMS-object, source-module, provenance, and merge-diagnostic fields. Safe event/profile/period families may span modules; opposed qualifiers, different event subjects, low-confidence LLM mappings, and unqualified parameter conflicts cannot be auto-merged. The optional LLM catalog is assignment-only: malformed, incomplete, duplicate, or unknown atom mappings fall back to deterministic grouping. `route_requested` records intent; `route` records the route actually executed after any credential/config degradation.

## Output Files

Atomizer output files:

- `blocks.jsonl`
- `chunks.jsonl`
- `table_items.jsonl`
- `atomic_requirements.jsonl`
- `llm_tasks.jsonl`
- `quality_report.json`
- `manifest.json`
- `summary.md`

Review output files:

- `llm_review_results.jsonl`
- `review_states.jsonl`
- `review_state_events.jsonl`
- `llm_review_cache.jsonl` when `openai_compatible` route is used

Agent Phase 0 contracts:

- `golden_sets/agent_eval_v1/manifest.json` stores the deterministic classification baseline.
- `schemas/decide_trace.schema.json` freezes the future decision trace row format.
- `decide_trace.jsonl` is produced by Phase 1 as an append-only, schema-validated decision log.

Agent Phase 1 output files:

- `decide_trace.jsonl`
- `agent_loop_summary.json`
- `omission_states.jsonl` when a zero-LLM resample target is queued as `needs_extraction`
- clarification report files when `ask_clarification` is selected

Export output files:

- `requirements_export.csv`
- `requirements_export.md`

CSV exports use `utf-8-sig` intentionally so Excel can recognize UTF-8 when opened directly.

Engineering composer output files:

- `engineering_requirements/engineering_requirements.json`
- `engineering_requirements/requirement_functions.md`
- `engineering_requirements/dlms_objects.md`

The composer is a post-processing stage. It keeps atomic requirements unchanged and reorganizes them into two developer-facing sections: requirement functions and DLMS/COSEM objects. Function entries include deterministic acceptance criteria derived from atom metadata; DLMS object entries include implementation and access summaries.

## Examples

End-to-end run:

```powershell
ratomizer run `
  "D:\standards\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\out\abnt_nbr_16968_atomizer_v5" `
  --kb ".\knowledge_bases\compiled_from_obsidian.json" `
  --export md,csv
```

Review with an OpenAI-compatible local or cloud endpoint configured in `llm_agents/review_pipeline.yaml`:

```powershell
ratomizer review `
  --out ".\out\abnt_nbr_16968_atomizer_v5" `
  --llm-route openai_compatible `
  --review-scope targeted
```

Export accepted requirements only:

```powershell
ratomizer export `
  --out ".\out\abnt_nbr_16968_atomizer_v5" `
  --format csv `
  --status accepted
```

Compose engineering requirements:

```powershell
ratomizer compose `
  --out ".\out\abnt_nbr_16968_atomizer_v5"
```
