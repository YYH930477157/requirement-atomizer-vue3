# CLI Contract

Requirement Atomizer exposes a stable command line interface for task managers and future GUI shells.

## Commands

```powershell
ratomizer run <input.docx|input.xlsx|input.pdf> --out DIR [--kb FILE]... [--domain-pack DIR] [--chunk-chars N] [--skip-review] [--llm-route stub|openai_compatible] [--review-scope targeted|all] [--export md,csv] [--quiet | --verbose]
ratomizer atomize <input.docx|input.xlsx|input.pdf> --out DIR [--kb FILE]... [--domain-pack DIR] [--chunk-chars N] [--quiet | --verbose]
ratomizer review --out DIR [--review-pipeline FILE] [--domain-pack FILE] [--limit N] [--llm-route stub|openai_compatible] [--review-scope targeted|all] [--quiet | --verbose]
ratomizer export --out DIR --format md|csv [--status all|accepted|expert_pending|candidate]
ratomizer compose --out DIR [--quiet | --verbose]
ratomizer --version
```

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
  --kb ".\knowledge_bases\energy_metering.json" `
  --kb ".\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\knowledge_bases\energy_metering_cosem_classes.json" `
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
