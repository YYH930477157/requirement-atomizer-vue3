# Agent Evaluation Dataset v1

This Phase 0 dataset freezes evidence and output contracts before any agent decision loop is added.

## Scope

- `classify`: evaluated with the current deterministic rule layer.
- `grouping`, `must_ask`, and `hallucination`: schema and count validation only in Phase 0.
- Automated scoring for the three schema-only categories belongs to Phase 1 or later.

The canonical case schema is [`../../schemas/agent_eval_case.schema.json`](../../schemas/agent_eval_case.schema.json).
It is referenced directly and is not copied into this directory.

## Sources And Anonymization

Cases are derived from existing repository regressions and remediation evidence:

- `ABNT-NBR-16968-ANON`: short semantic rewrites of the frozen public-standard regression family.
- `TEST2-TENDER-ANON`: anonymized rewrites of the test2 remediation findings documented in
  `docs/remediation-plan-2026-07-20.md`.
- `TEST3-FAILURE-ANON`: anonymized rewrites of fabricated-code, numeric-drift, and source-truncation
  regressions already represented in repository tests.
- `TEST18-ANON`: anonymized rewrites of grouping and clarification regressions; no customer wording
  or external evaluation asset is stored here.

`source.origin` is `anonymized_rewrite` whenever wording was changed. Block identifiers in those
cases are stable anonymized coordinates, not claims that customer source files are checked in.

## Review Status

The project reviewer manually checked the five case IDs recorded in `manifest.json` against their
anonymized inputs and repository evidence on 2026-07-22. The runner never changes `curation`,
`human_review_status`, or `reviewed_case_ids`; changing review status remains a human action.

## Maintenance Rules

1. Never add customer wording, proprietary documents, credentials, or external evaluation assets.
2. Model-generated expected answers cannot enter the dataset without recorded human review.
3. Numeric values, standard identifiers, and forbidden tokens use exact matching.
4. New fields require a schema version change. Decision behavior changes require an
   `AGENT_POLICY_VERSION` bump.
5. The runner may refresh deterministic counts and classification metrics, but never review metadata.

Run the baseline from the repository root:

```powershell
python agent_eval.py --eval-dir golden_sets/agent_eval_v1
```
