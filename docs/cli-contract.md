# CLI Contract

Requirement Atomizer exposes a stable command line interface for task managers and future GUI shells.

## Commands

```powershell
ratomizer run <input.docx|input.xlsx|input.pdf> --out DIR [--kb FILE]... [--domain-pack DIR] [--chunk-chars N] [--skip-review] [--llm-route stub|openai_compatible] [--review-scope targeted|all] [--export md,csv] [--quiet | --verbose]
ratomizer atomize <input.docx|input.xlsx|input.pdf> --out DIR [--kb FILE]... [--domain-pack DIR] [--chunk-chars N] [--quiet | --verbose]
ratomizer review --out DIR [--review-pipeline FILE] [--domain-pack FILE] [--kb FILE]... [--limit N] [--llm-route stub|openai_compatible] [--review-scope targeted|all] [--quiet | --verbose]
ratomizer export --out DIR --format md|csv [--status all|accepted|expert_pending|candidate]
ratomizer compose --out DIR [--quiet | --verbose]
ratomizer analyze --out DIR [--template FILE.xlsx] [--llm-route stub|openai_compatible] [--quiet | --verbose]
ratomizer claim-shadow-acceptance --input RUN_SET.json [--output REPORT.json]
ratomizer claim-shadow-review-packet --input RUN_SET.json --output-dir DIR
ratomizer claim-shadow-review-import --input RUN_SET.json --decisions DECISIONS.json --output REVIEWED_RUN_SET.json --golden-manifest GOLDEN_MANIFEST.json
ratomizer --version
python agent_eval.py --eval-dir DIR
python agent_loop.py --out-dir DIR [--max-iterations N]
claim-shadow-acceptance --input RUN_SET.json [--output REPORT.json]
claim-shadow-review-packet --input RUN_SET.json --output-dir DIR
claim-shadow-review-import --input RUN_SET.json --decisions DECISIONS.json --output REVIEWED_RUN_SET.json --golden-manifest GOLDEN_MANIFEST.json
```

`claim-shadow-acceptance` validates immutable Phase 0 claim snapshots and emits a sanitized
transition report. The input manifest assigns safe `run_id`/`document_id` labels to local output
directories and records independent human-curation counts. Source paths are input-only: neither
stdout nor `REPORT.json` contains paths, claim wording, target wording, or verifier exception text.
The report separates hard failures (`source_accounting_incomplete`, mixed/stale versions, corrupt
artifacts, partial/sample runs) from unavailable evidence (stub verifier, missing cost usage,
pending human adjudication). Three ordered runs, current/consistent versions, full accounting,
real semantic verification within the current 25% call / 65% token limits
(`claim-cost-policy-v3-user-approved`), and completed known-omission
adjudication and repository-owned golden held-out adjudication make the report
`eligible_for_user_decision`; they never switch Phase 1 automatically.
An unmet gate returns exit 3 while still writing the report. Invalid input returns exit 2.
`--output` must not name or hard-link to `--input`; report write failures return exit 3.

Real claim verification is fail-closed and requires explicit absolute authorization in addition to
`RATOMIZER_CLAIM_SHADOW_VERIFY=1`: both `RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_CALLS` and
`RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS` must be positive. Their defaults are `0`, meaning
no paid verifier request is authorized. Coverage, semantic-negative proposal, and semantic-negative
verification share one generation-wide budget. Every provider attempt counts, including retries,
JSON repair, response-format fallback, and truncation escalation. Exhaustion leaves unprocessed
claims open and cannot pass acceptance. The real-verifier gate also requires at least one independent
verification attempt, positive token usage for both all verifier operations and the independent
verifier subset, complete provider usage reporting, and zero verifier operation failures. A successful
HTTP response with an empty/missing/duplicate decision is an operation failure, not a successful review.

Verifier batching uses `claim-verifier-batch-v3-full-http-body`. Its 48,000-byte limit is measured
against the complete first-attempt JSON HTTP body produced by `llm_client`, including model options,
JSON mode, system/user messages, request schema and IDs, and the compact domain payload. Coverage,
negative proposal, and negative verification use their own actual prompt/envelope shapes. A single
oversized item is deferred without a network call and its claim remains open.

Provider usage is strict: `total_tokens` must be a positive non-boolean integer; prompt/completion
components, when present, must be non-negative integers no greater than total and, when both are
present, their sum must equal total. Missing, zero,
negative, boolean, or internally inconsistent usage is incomplete and is conservatively charged from
the request reservation. The cost denominator is accepted only with matching
`no-ledger-baseline-lineage-v2` provenance. It binds the input, route, effective model config, JSON
mode, extraction unit/merge/sample/self-check/verify settings, effective concurrency, and the
versioned provider-attempt policy. Legacy scalar baselines cannot pass this gate.

Verifier accounting is append-only across a cold extraction and all of its ledger-only refreshes.
The immutable chain root binds the cold request, requirements request, document generation, and
requirements hash; each attempt separately binds its target generation, verifier runtime, baseline,
and cost policy. Failed tails remain hash-linked without invalidating an earlier committed prefix.
The full-ledger tail must be the committed attempt and have zero operation failures for the
correctness gate, while calls and tokens from every cold, failed, and recovered attempt are
accumulated for the cost gate. An uncommitted failed/incomplete tail blocks current acceptance without
making the earlier claim snapshot unreadable. A later successful refresh therefore cannot erase paid
work or masquerade as a new cold run. A validated v4 generation may be imported only as an incomplete
legacy root: its observed counters are retained as a lower bound, but its unknown retry history keeps
cumulative cost evidence blocked until a fresh cold chain is produced. A validated v5 generation that
already has a hash-bound attempt ledger may instead expose that lineage read-only and seed a direct
ledger-only v6 refresh; the v5 fixed-name snapshot itself is not accepted as a current v6 artifact.

Before a paid verifier request can leave the process, the attempt scope creates
`.claim_verifier_attempt.checkpoint.json`, and every budget reserve, success commit, or failure update
is synchronously checkpointed. A reserve persists its conservative token ceiling before HTTP starts.
If the process dies before the publication journal becomes durable, the next authoritative reader or
writer converts the dead owner's checkpoint into a hash-linked failed attempt; any in-flight
reservation is charged at its ceiling and usage remains incomplete. Once the publication journal is
durable it contains the same recovery evidence and atomically takes over this responsibility, so the
pre-publication checkpoint can be removed.

Fixed-name claim snapshots use a durable hidden publication journal. Readers and writers take the same
cross-process lock, recover an unfinished journal before use, and treat journal removal after full
generation/effective reload validation as the global commit point. The persistent lock carrier uses an
OS-level exclusive lock (a Windows byte-range lock or POSIX `flock`), which the OS releases when its
process exits. PID, process-creation identity, and nonce metadata are written only after acquisition for
diagnostics and tamper detection; they are not a reason to delete a lock path after a timeout. The
carrier remains in place on release, removing the stale-observation/successor-deletion race. While a
live verifier checkpoint exists, every authoritative snapshot or attempt-ledger read fails closed;
only the publishing path carrying that checkpoint's nonce may proceed. A process kill before the
commit point restores the prior snapshot and records the interrupted verifier attempt as failed; a
corrupt checkpoint, journal, lock owner, or backup fails closed.

This fixed-name WAL contract covers process termination, including `os._exit`/TerminateProcess, and
Windows file-replacement retries. It does not claim directory-metadata transactionality across sudden
host power loss. Covering that failure mode would require immutable generation directories, one atomic
current-generation pointer, and platform-specific write-through/volume-flush evidence.

The current acceptance implementation is `claim-shadow-acceptance-v9`; its sanitized report schema is
`claim-shadow-acceptance-report/v7`. Current claim artifacts use `claim-artifacts-v6`, coverage
validation uses `claim-coverage-validator-v6`, and verifier attempts use the append-only
`claim-verifier-attempt/v2` event ledger.

Input manifests are machine-local and have this shape:

```json
{
  "schema": "claim-shadow-acceptance-input/v3",
  "dataset_id": "representative-shadow-v1",
  "runs": [
    {
      "run_id": "run-1",
      "generation_run_id": "8e9d4f0c1a2b3c4d",
      "document_id": "document-a",
      "sequence": 1,
      "output_dir": "D:/local-output/run-1",
      "attempt_chain_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  ],
  "curation": {
    "human_review_status": "pending",
    "reviewed_by": "",
    "reviewed_at": "",
    "adjudications": [],
    "known_omissions": []
  }
}
```

Only an actual independent review may change `human_review_status` to `reviewed`; test generation and
the acceptance runner never promote it. Reviewed entries bind the exact `run_id`, `claim_id`,
`claim_hash`, current ledger resolution, category, reviewer verdict, rationale, and a
`claim-review-evidence-v1` fingerprint. That fingerprint hashes the source claim, effective ledger
row, coverage groups, target generation/review authority, and bound requirements metadata; changing
the produced target or evidence therefore makes the old decision stale even when the source claim ID
and final resolution happen to stay the same. Disagree/follow-up decisions require a non-empty
rationale. Known-omission entries bind
the same immutable claim identity. All summary counts are recomputed from committed snapshots rather
than accepted from caller-provided counters.

Acceptance also loads `golden_sets/claim_ledger_v1` from the installed repository/package location;
the caller cannot supply a replacement path or held-out count. The golden manifest uses
`claim-ledger-golden-manifest/v3`, current dataset `claim-ledger-golden-v4`, and review contract
`claim-golden-heldout-review-v2`. Each current
held-out adjudication binds the rebuilt claim ID/hash and a
`claim-golden-heldout-fixture-hash-v1` digest over the dataset/version, case declaration, complete
synthetic input, and expected projection. It records exact verdicts for claim boundary,
eligibility, resolution, coverage, target obligation subject, target modality, and role/object
preservation; the overall disposition is derived rather than caller supplied. Missing/stale/duplicate
evidence, a non-independent reviewer, a timestamp without timezone, any unreviewed dimension, or
any disagree/follow-up dimension fails closed. Superseded held-out fixtures and their human decisions
are immutable, hash-bound baseline revisions under `history/`; a rejected fixture is removed from the
active held-out partition (and is development data only when explicitly retained there), never
silently rewritten into an approved held-out case. Raw-hashed history JSON is repository-pinned to
LF line endings so checkout conversion cannot invalidate its digest. The
sanitized report contains only statuses and counts, never reviewer identity, hashes, selectors,
wording, paths, or exception text.

`claim-shadow-review-packet` loads the same committed snapshots and frozen held-out corpus, then
writes `claim-shadow-review-packet.json` and a self-contained offline
`claim-shadow-review-packet.html`. The current generator is v7, packet wire schema is v5,
and exported decisions remain v3 with the golden dataset binding fixed to
`claim-ledger-golden-v4`. The packet contains customer wording and is therefore marked
`machine_local_do_not_commit`; only its generator belongs in the repository. The HTML shows source
claims, target-side produced evidence, validation method, ledger resolution, and the synthetic
held-out expected projection and target-formulation expectations. It renders each
held-out review dimension separately and exports decisions schema v3. Shadow disagree/follow-up
decisions and every held-out review require a rationale. Generation never changes either
human-review status. The generator refuses stale component/target versions and verifies every
manifest `generation_run_id` and `attempt_chain_id`, so review must follow the exact current run.
The fixed JSON/HTML packet outputs must not name or hard-link to the acceptance input. Packet write
failures return exit 3; exit 4 remains reserved for LLM service unavailability.

`claim-shadow-review-import` is the supported path from the exported decisions JSON to the two gate
inputs. It validates `claim-shadow-review-decisions/v3` with
`schemas/claim_shadow_review_decisions.schema.json`, rebuilds the current review packet, and requires
the shadow and held-out identity sets to match exactly. Missing, duplicate, extra, or stale items;
timestamps without timezone; non-independent held-out reviewers; and missing required rationales are
rejected before any write. It writes a new reviewed acceptance input and atomically replaces the
explicit repository-owned golden manifest only after both candidates validate. Imports acquire
stable locks for both the golden manifest and reviewed output in deterministic order, so operations
sharing either resource serialize. A completed review is idempotent but cannot be overwritten by
different reviewer metadata or decisions. The pending input and exported decisions remain immutable:
`--output` may equal neither one, must stay outside the golden corpus, and an existing different
output fails closed.

The explicit `--golden-manifest` is a write target, not an acceptance override. Acceptance continues
to read only its repository/package-owned corpus. When the importer is run from a previously built
portable executable, point it at the source repository manifest and rebuild the binaries before using
that binary as final held-out evidence; an old executable keeps its original embedded pending corpus.
After a successful import, run `claim-shadow-acceptance` against `REVIEWED_RUN_SET.json`. Valid
disagreement decisions are preserved rather than coerced to approval, so the final report may
correctly remain failed or blocked.

This command evaluates Phase 0-to-Phase 1 shadow evidence. It does not satisfy the separate Phase 2
production-cutover held-out gate (150/150/150 category samples, Wilson bounds, and disagreement
bounds).

`agent_eval.py` is the deterministic evaluation runner (`agent-eval-v2`). It validates every case
against `schemas/agent_eval_case.schema.json` and scores all four categories with zero-LLM
production-path judges (`docs/agent-eval-v2-spec.md`): `classify` via the rule layer, `grouping`
via pair-wise `build_function_catalog(chat=None)` merge checks, `must_ask` via forbidden-default
leak checks plus declared suspicion detectors (`expected.detector`; cases without one are marked
`manual` and excluded from the automatic pass rate), and `hallucination` via the declared guard
family (drift guards, `foreign_standard_refs`, or `opposed_qualifiers`). It never calls an LLM.
Missing/empty datasets return exit 2; malformed cases return exit 3.

`agent_loop.py` is the bounded agent decision loop (`agent-policy-v3`). It reloads a read-only
aggregate view of an existing extraction directory before each decision, appends every decision
to `decide_trace.jsonl`, and writes `agent_loop_summary.json`. The default iteration budget is
10 and the accepted range is 1 through 50. The frozen priority is READY -> stop, unqueued gaps
-> `queue_all_gaps`, unresolved hard question -> `ask_clarification`, otherwise stop.

`--decider rule` (default) is the Phase 1 zero-LLM behavior: `tokens_max`/`tokens_used` stay
zero and no network calls happen. `--decider llm` (Phase 1.5, opt-in, never the default) asks
the model to pick one candidate per iteration; any LLM failure, invalid pick, or exhausted
`--max-tokens` budget (default 20000) falls back to the rule decider for that iteration, and
each trace row truthfully records which mechanism decided (`decider: rule|llm`). `tokens_used`
counts decision calls only (initial + JSON-repair + truncation-escalation), taken from endpoint
`usage`; endpoints without usage report 0 and mark `token_accounting: "partial"` — never an
estimate. `--decider llm` without a configured endpoint or API key exits 2.

`agent_compare.py --out-dir DIR` (Phase 1.5) copies the directory twice and runs both deciders
side by side without touching the source, reporting iterations, termination, readiness, action
sequences, `decider_usage`, tokens, and sequence agreement. Without an API key the rule side
still runs and the report marks `llm_ran: false` — a rule-only result is never presented as a
comparison.

`queue_all_gaps` registers the decision-time snapshot candidates
(`state.unqueued_gap_block_ids` = coverage gaps ∪ failed-section blocks, minus already
queued) as `needs_extraction` in one locked batch (per-block queueing exhausted the
iteration budget on real documents). Each candidate is revalidated inside the lock
(exists in `blocks.jsonl`, not currently pending, source fingerprint matches the current
text); candidates that fail revalidation are reported in `skipped_block_ids` with reasons
instead of aborting the batch. Blocks already carrying a current `needs_extraction` or
`issue_confirmed` omission state are excluded, so re-running the loop over the same
directory never appends duplicate omission rows; a repeated per-block `resample_section`
call is likewise idempotent and returns `skipped` without appending. External callers that
invoke `queue_all_gaps` without snapshot candidates keep the legacy behavior of
recomputing the currently uncovered set.

The existing targeted omission extractor is LLM-only. Therefore a Phase 1
`resample_section:<block_id>` decision records the current block as `needs_extraction` and
truthfully returns `result.status: "skipped"`; it never claims that semantic extraction
completed. The thin tool wrapper can delegate to the existing targeted extractor only when an
external caller explicitly enables LLM execution. `recheck:<req_id>` is exposed as a tool
contract but is not selected by the rule priority and is skipped in zero-LLM mode because the
existing semantic recheck has no standalone deterministic publisher.

`analyze` runs the requirements analysis agent over a reviewed output directory (requires `ai_requirements.jsonl` produced by AI extraction; missing input is an input error, exit 2 semantics via error envelope). It writes `software_requirements.xlsx`, `engineering_analysis.json`, `hardware_items.md`, and `co_design_items.md`. An explicit `--template` path must exist.

Ownership classification, module mapping, review decisions, and all structural fields are deterministic. `--llm-route openai_compatible` additionally enables an **LLM enrichment layer** that fills the narrative fields only — `software_requirement_text`, `developer_guidance`, `design_options`, `acceptance_criteria`, `hardware_dependency`, `open_questions`. Structural and routing fields (ownership, module, OBIS/class/access, ids) are never overwritten by the model. Each enrichment is drift-checked: if the model fabricates a code or number not in the source, that item's enrichment is rejected and it stays deterministic (recorded as an issue). When the endpoint is unusable (no `RATOMIZER_LLM_API_KEY` set), the run degrades to the deterministic path and records `route: "stub"` plus `route_requested` (provenance is never falsified). Output adds `enriched` / `enrich_degraded` counts. Enrichment results are cached per source-content fingerprint in `analyze_enrich_cache.json` (idempotent re-runs).

Since Agent Phase 2 (WP2, `ANALYZE_PROMPT_VERSION=analyze-llm-v7`, rule version `analyze-unfounded-v1` in the cache fingerprint), an enrichment rejected wholesale by the guards no longer falls back to base text silently: the unfounded narrative fields are marked `待澄清`, and an accepted field whose numbers have no basis in the source, template references, or document context is likewise downgraded to `待澄清`. Each mark appends an internal-review `open_questions` entry that flows through the existing clarification report channel. Rendering follows the 2026-07-23 fallback ruling (`analyze-unfounded-v2`): the pre-mark original value is stashed in `clarify_fallback`, and the `software_requirements.xlsx` requirement/notes columns render `待澄清` together with the labelled original candidate (`原始候选（未经依据校验，仅供参考，不得作为实现依据）`) — the data layer keeps the honest `待澄清` mark while the reader still sees the fallback content, clearly labelled. Grounded fields stay byte-identical (step-numbering and template-sourced values are not unfounded), and deterministic join fields (ids, ownership, quotes, module) are never marked.

`review` runs the M2 review pipeline. Since Agent Phase 2 the five `operations` in `llm_agents/review_pipeline.yaml` carry an `executor` disposition: `classify_risk` and `correct_errors` run as one fused **tool-loop** call per requirement (`executor: "tool_loop"`); `merge_duplicates` and `gap_find` stay `deterministic` (already covered by `merged_consistency`); `test_point_generate` is `deferred` (schema exists but has no consumer). In tool-loop mode the model may call the deterministic read-only tools from `review_tools.py` — `kb_search`, `kb_get`, `blue_book_class`, `source_read`, `coverage_check` — to gather evidence before deciding. The output contract (`decision`/`risk`/`confidence`/`revised_requirement`/`review_notes`/`expert_questions`), `llm_review_schema` validation, and the deterministic policy layer are unchanged; the loop only changes how those fields are produced. The loop is bounded (`max_rounds=8`; per-requirement token budget defaults to 20000, adjustable via the yaml route key `tool_loop_token_budget`). An endpoint that rejects tools (4xx) fails loudly; a requirement whose loop exhausts the round cap or budget, or whose call fails, falls back to the stub review with an honest `llm_unavailable` note and is counted in `llm_failed` — it is never disguised as a completed tool-using review. Each LLM review row carries a `tool_calls` summary (tool name + round) so its producing process is explainable from `llm_trace.jsonl`. Review cache fingerprints include `REVIEW_TOOLS_VERSION` and the executor mode (`PROMPT_VERSION=m2-review-v2`, `LLM_REVIEW_CACHE_VERSION=llm-review-cache-v5`); pipelines without an `executor` declaration keep the legacy single-shot behavior, and the stub path is byte-identical.

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

- `golden_sets/agent_eval_v1/manifest.json` stores the deterministic baselines for all four
  categories (classification / grouping / must_ask / hallucination, `agent-eval-v2`).
- `schemas/decide_trace.schema.json` freezes the future decision trace row format.
- `decide_trace.jsonl` is produced by Phase 1 as an append-only, schema-validated decision log.

Agent Phase 1 output files:

- `decide_trace.jsonl`
- `agent_loop_summary.json`
- `omission_states.jsonl` when a zero-LLM resample target is queued as `needs_extraction`
- clarification report files when `ask_clarification` is selected

Claim-ledger Phase 0 acceptance files:

- caller-owned `claim-shadow-acceptance-input/v3` manifest (machine-local; paths never enter repo)
- append-only `claim_verifier_attempts.jsonl` with hash-linked cold/ledger-only evidence
- optional sanitized `claim-shadow-acceptance-report/v7` JSON report
- machine-local sensitive `claim-shadow-review-packet.json` and
  `claim-shadow-review-packet.html` (never commit)
- machine-local `claim-shadow-review-decisions/v3` export and reviewed acceptance input
- repository-owned `golden_sets/claim_ledger_v1/manifest.json` updated only through the validated
  review importer

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
