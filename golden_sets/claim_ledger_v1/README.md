# Claim Ledger Golden Set v1

This directory freezes a small, fully synthetic Phase 0A/0B contract corpus. It contains no
customer wording, proprietary document excerpts, external evaluation assets, or machine-local
paths.

## Files

- `manifest.json` records dataset lineage, partitions, and runtime schema paths.
- `inputs.json` contains parser-like blocks, table items, and final B-track requirements.
- `expected.json` records claim-level catalog, resolution, and coverage-group expectations.
- `history/*.json` preserves superseded held-out fixtures and their adjudications. Each history
  file is referenced by repository-relative path and a digest of its raw bytes. The synthetic
  fixture, exact dimension verdicts, reviewer attribution, timestamp, and rationale are retained
  as an immutable audit record; customer wording and machine-local paths remain prohibited.

The runtime rows are validated by the JSON Schemas in `../../schemas/`. The regression test also
rebuilds every case through `claim_catalog.build_claim_catalog` and
`claim_ledger.build_shadow_ledger`, so the expected claim partition is executable rather than a
decorative fixture.

## Scenarios

The corpus covers a generic programmable-channel equivalent, a capability-only configurable
interface held-out, partial coverage between sibling claims in one block, repeated page markers
and watermarks, a list with no introductory sentence, normal table rows, and bounded table
fallback groups.
It also freezes a semantic-negative proposal that closes only after an independent,
proposal-blind verifier returns matching reason-specific evidence and all policy checks.

The independently rejected v2 form of `programmable-equivalent-001` and rejected v3
`status-indication-mapping-001` are retained as replayable, hash-bound baseline revisions. The
active `configurable-interface-capability-001` case is `held_out`, `tuning_eligible=false`, and
approved on all seven review dimensions. It checks only that interface configurability is expressed
as a product capability; no operator, maintainer, user, or usage scenario appears in the fixture.
This is a reviewer-scoped acceptance fixture frozen before any further behavior or threshold
change. It does not by itself provide statistical evidence of generalized recall.

Review contract v2 records an exact verdict for each of seven dimensions: claim boundary,
eligibility, resolution, coverage, target obligation subject, target modality, and role/object
preservation. Overall disposition is derived from those values; only seven `agree` values complete
the current held-out review. For a fixture with no human role, the seventh dimension requires that
absence to remain intact while preserving the interface object and configuration capability.

## Maintenance

1. Keep all wording synthetic and domain-generic.
2. Do not refresh expected outcomes merely to make a behavior change green; explain every baseline
   change in `CLAUDE.md`.
3. Schema behavior changes require the corresponding producer/version decision before updating the
   frozen files.
4. Run `python -m unittest tests.test_claim_ledger_schema_golden -v` from the repository root.
5. Generate the machine-local packet with `claim-shadow-review-packet`; never place its JSON/HTML
   output in this directory because it also contains customer-run evidence.
6. Never edit a history file without adding a new baseline revision and updating its raw SHA-256
   reference deliberately; the loader verifies the digest before replay.
