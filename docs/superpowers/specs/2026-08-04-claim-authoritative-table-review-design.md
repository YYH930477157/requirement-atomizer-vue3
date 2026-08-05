# Claim-Authoritative Table Review Design

## Goal

Make Claim Ledger structural authority the only source of truth for terminal
table-cell review decisions. The B-track table review view and disposition
artifact become deterministic projections of that authority.

## Authority Boundary

Claim authority remains the existing protocol bundle:

- `claim_structural_candidate_decisions.jsonl` confirms that a structural
  candidate stays excluded.
- `claim_structural_overrides.jsonl` plus the resumable structural operation
  protocol promotes a candidate into the claim catalog.
- Claim catalog/effective publication and fold determine Ledger Ready.

`table_review_states.jsonl`, `table_review_events.jsonl`, and
`table_cell_dispositions.jsonl` are not terminal-decision authorities. They may
store projection/audit information, but a stale or missing projection must be
reconstructible from current claim artifacts.

## Candidate Coverage

Every B-track `review` cell must have exactly one current claim structural
candidate bound by `table_cell_id`. Existing candidate reasons remain unchanged.
Two B-track-only cases are added to the claim catalog:

- `parse_incomplete_table_cell`
- `normative_context_conflict`

Changing candidate materialization bumps `CLAIM_CATALOG_VERSION`. Old claim
bases fail closed with `base_migration_required`; table review never fabricates
a candidate against an old base.

## Projection

A focused projection helper reads the committed claim snapshot, current
candidate decisions, structural overrides, and pending structural operations.
It returns one state per `table_cell_id`:

- `pending_review`
- `promotion_pending`
- `promoted`
- `confirmed_excluded`

Projection rules are deterministic:

- promoted cell: `target` for a cell leaf, `composite` for a row leaf;
- confirmed exclusion: `excluded`;
- pending states: `review`.

Canonical role, coordinates, text, headers, and merge evidence remain sourced
from `table_cell_items.jsonl`. User-selected role labels do not rewrite physical
or structural source facts.

`GET /table-reviews` and B-track extraction apply this projection at read time.
After a table action, the projected disposition file may be atomically refreshed
as a materialized view, but correctness never depends on that refresh succeeding.

## Write Flow

`POST /table-review-actions` keeps its table-level UI contract but delegates each
pending cell to claim authority in stable cell-ID order:

- `target|composite` requests use the existing structural override coordinator;
- `context|excluded` requests use the existing exclusion-confirmation append;
- each cell uses a deterministic idempotency key derived from table, cell,
  evidence fingerprint, actor, and requested terminal class;
- claim identity and effective revision are refreshed before each cell so a
  preceding promotion may safely advance the catalog generation;
- completed cells remain committed if a later cell fails; retries resume from
  claim authority and do not duplicate decisions.

The initial table adapter uses the deterministic structural route. Existing
claim workflows may still explicitly authorize LLM verification; this design
does not impose a product-wide zero-LLM rule.

## Failure Semantics

- Missing current claim candidate: fail closed with
  `base_migration_required`/authority refresh guidance.
- Stale table evidence or claim revision: return conflict and require refresh.
- Partial batch completion: return completed and remaining cell IDs; claim
  authority is already durable and retryable.
- Claim publication journal or recovery requirement: propagate the existing
  retryable claim error; table GET stays read-only.
- Projection write failure: report it, but rebuild the response from claim
  authority so terminal state is not rolled back or contradicted.

## Tests

- B review cell and claim candidate coverage is exactly one-to-one.
- Table confirmation promotes a cell through claim authority and makes both the
  table view and Ledger Ready state non-pending.
- A claim-side exclusion confirmation is visible in the table view without a
  table-state write.
- A claim-side promotion is visible in the table view after catalog rebuild.
- Table batch retry is idempotent after partial completion.
- Structured-leaf fake-chat extraction plus parameter-row fallback publishes no
  duplicate row requirement.
- `table-cell-item/v1` receives a formal JSON Schema and validation fixtures.

## Documentation

The design document is corrected to state that the current version has no LLM
table-structure classifier, that prompts also receive terms/references, and that
unreadable DOCX files fail honestly. `AGENTS.md` records claim catalog v11 for
the already-published baseline and the new authoritative projection milestone
after implementation.
