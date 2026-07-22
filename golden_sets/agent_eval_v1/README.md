# Agent Evaluation Dataset v1

This dataset freezes evidence and output contracts for the agent evaluation runner.
The runner (`agent_eval.py`, runner version `agent-eval-v2`) scores all four categories
with deterministic zero-LLM judges per `docs/agent-eval-v2-spec.md`.

## Scope

- `classify`: judged against the deterministic rule layer
  (`looks_like_compliance` / `is_requirement_like` / `classify_ownership`).
- `grouping`: judged pair-wise through the production merge path
  `functional_catalog.build_function_catalog(chat=None)` — cases sharing `group_key`
  must merge; every cross-key pair (auto-derived) must not.
- `must_ask`: three tiers. Tier 1 (all cases): `expected.forbidden` default values must
  never leak into deterministic derivations. Tier 2 (cases declaring `expected.detector`):
  the named production detector (`vague_acceptance` / `values_left_behind`) must fire and
  its suspicion policy must route to customer/blocking. Tier 3 (no detector): semantic
  traps, honestly marked `manual`, excluded from the automatic pass-rate denominator.
- `hallucination`: every `expected.forbidden` token must be caught by the production
  guard family named in `expected.detector` — drift guards (default, `code_drift` ∪
  `int_drift`, forbidden tokens matched by code/int atoms), `foreign_standard_refs`,
  or `opposed_qualifiers` (merge prevention).

The canonical case schema is [`../../schemas/agent_eval_case.schema.json`](../../schemas/agent_eval_case.schema.json).
It is referenced directly and is not copied into this directory. `expected.detector`
is an optional per-category field (allowed values are scoped per category in the schema).

## Sources And Anonymization

Cases are derived from existing repository regressions and remediation evidence:

- `ABNT-NBR-16968-ANON`: short semantic rewrites of the frozen public-standard regression family.
- `TEST2-TENDER-ANON`: anonymized rewrites of the test2 remediation findings documented in
  `docs/remediation-plan-2026-07-20.md` and of test2 suspicion records (2026-07-22 expansion).
- `TEST3-FAILURE-ANON`: anonymized rewrites of fabricated-code, numeric-drift, and
  source-truncation regressions, plus test3 suspicion records (2026-07-22 expansion).
- `TEST18-ANON`: anonymized rewrites of grouping and clarification regressions; no customer
  wording or external evaluation asset is stored here.

`source.origin` is `anonymized_rewrite` whenever wording was changed. Block identifiers are
stable anonymized coordinates (`T2/T3-ANON-ROW-n` references the source row index in the
machine-local run artifacts, which are not checked in).

must_ask cases additionally follow the **full-text absence principle**: a "missing
information" gold is valid only if the answer is absent from the entire source document
(including clauses reachable via cross-section references); `input.context` records the
full-text absence claim, and human review re-checks it.

## Review Status

The project reviewer manually checked the five case IDs recorded in `manifest.json` against
their anonymized inputs and repository evidence on 2026-07-22. The runner never changes
`curation`, `human_review_status`, or `reviewed_case_ids`; changing review status remains a
human action. Cases not yet in `reviewed_case_ids` are flagged `unreviewed` in the runner
report (`summary.unreviewed_count`, `unreviewed_case_ids` in the full report); baselines
cover all auto-judged cases and converge to fully reviewed as curation is registered.

## Maintenance Rules

1. Never add customer wording, proprietary documents, credentials, or external evaluation assets.
2. Model-generated expected answers cannot enter the dataset without recorded human review.
3. Numeric values, standard identifiers, and forbidden tokens use exact matching; drift
   families match forbidden tokens by their code/int atoms.
4. New fields require a schema version change. Decision behavior changes require an
   `AGENT_POLICY_VERSION` bump (judge-only changes do not — they bump
   `EVAL_RUNNER_VERSION`).
5. The runner may refresh deterministic counts and the four baseline fields
   (`classification_baseline`, `grouping_baseline`, `must_ask_baseline`,
   `hallucination_baseline`), but never review metadata.

Run the baseline from the repository root:

```powershell
python agent_eval.py --eval-dir golden_sets/agent_eval_v1
```
