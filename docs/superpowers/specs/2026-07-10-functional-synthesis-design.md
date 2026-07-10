# Document-Level Functional Synthesis Design

Date: 2026-07-10
Status: approved by the active review-remediation goal

## Purpose

Turn chapter-local atomic AI requirements into implementable document-level functional requirements without losing source constraints, expert decisions, or meaningful variants. The stage must improve legacy outputs that do not contain `functional_key`, and it must remain useful without a live LLM.

## Pipeline

1. Read `ai_requirements.jsonl` and latest `ai_review_states.jsonl`.
2. Exclude rejected items and project expert module/ownership overrides.
3. Build a document-level function catalog per module.
4. Assign every eligible atom to exactly one catalog function.
5. Synthesize each function into a structured development requirement.
6. Emit merge evidence, confidence, variants, conflicts, and complete provenance.
7. Let `requirements-analysis` enrich the structured result without replacing deterministic evidence.

## Catalog Strategy

### Explicit keys

When atoms contain `functional_key`, normalize spelling and punctuation and merge equal keys across compatible source modules. Explicit keys are high-confidence evidence, but opposed qualifiers, generic event keys with different subjects, conflicting ownership, and incompatible object identities cannot be silently combined.

### Deterministic legacy fallback

Legacy atoms without a key are clustered conservatively inside a module. Similarity uses title, description, source quote, source-section family, domain concepts, protected identifiers, and numeric constraints.

The fallback may merge closely related variants such as PM1/PM2 profiles or 15-minute/1-hour archives only when each original atom is retained as a named variant. It must not merge unrelated items merely because both mention a generic word such as device, event, or interface class.

Protected identifiers (OBIS codes, interface-class IDs, event IDs, protocol profile IDs) and discriminating numbers are never erased. They become variant constraints or conflict evidence.

### Optional document-level LLM catalog

For `openai_compatible`, the stage may send one bounded module batch at a time to a catalog prompt. The model returns only an atom-ID to catalog-key mapping plus catalog titles. Every returned ID and grouping is validated. Invalid or unavailable responses fall back to deterministic clustering for that module. API failure must not destroy reusable extraction results.

## Structured Functional Requirement

Each synthesized item contains:

- `functional_requirement_id`
- `functional_key` and `title`
- `objective`
- `behaviors[]`
- `preconditions[]`
- `data_constraints[]`
- `variants[]`, each retaining source atom IDs and constraints
- `exceptions[]`
- `related_dlms_objects[]`
- `developer_guidance[]`
- `design_options[]`
- `acceptance_criteria[]`
- `assumptions[]`
- `source_ai_requirement_ids[]`, block IDs, quotes, sections, and evidence records
- `synthesis_reason`, `merge_confidence`, `merge_method`
- `conflict_flags[]`

The compatibility `description` is generated from objective, behaviors, and constraints. It is not a raw newline concatenation.

## Merge Safety

- Every eligible source atom appears in exactly one synthesized item.
- No source block, quote, protected identifier, numeric constraint, or expert override may disappear.
- A low-confidence candidate remains a singleton.
- Conflicting values under the same unqualified requirement produce `conflict_flags`; they are not silently selected.
- Variant-specific values remain attached to their variant.
- Mixed expert ownership overrides produce an explicit conflict and do not auto-select an ownership.

## Quality Baseline

The semantic baseline contains at least 30 real-domain cases covering definitions, events, communication profiles, clock synchronization, billing, archives, security, access control, hardware/co-design, DLMS objects, tables, variants, and unsupported design choices.

Measured gates:

- all expected source atoms assigned exactly once
- zero protected-identifier loss
- zero rejected-item resurrection
- all expert overrides preserved or explicitly conflicted
- expected merge/split decisions pass
- legacy corpus has non-zero useful reduction
- no known false-merge fixtures

## Compatibility

- `functional_requirements.json` remains the stage output.
- `requirements-analysis` continues to fall back to `ai_requirements.jsonl` if synthesis output is absent or invalid.
- Stage fingerprints include prompt/algorithm version, route, environment, input files, and synthesis configuration.
- Stub runs may reuse validated OpenAI extraction and run deterministic synthesis. Fresh stub runs cannot claim AI behavioral extraction succeeded.
