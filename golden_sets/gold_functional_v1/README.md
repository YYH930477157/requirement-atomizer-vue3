# Functional Truth Set v1 (`gold_functional_v1`)

This is the WS0 micro truth set for **functional-requirement-level** evaluation: the yardstick that
turns the direct-extract (`functional_extract`) and drilldown (`functional_drilldown`) gates from
"mechanism delivered, no ruler" into "recall/precision measured". Per restructure plan §2.2, the first
drop is a single-document micro set (100–200 entries); the full 2+1-document set is deferred.

Entry schema: [`schema/gold_functional_entry.schema.json`](schema/gold_functional_entry.schema.json).
Agreement algorithm: [`tools/agreement.py`](tools/agreement.py) (WS0 spec §5, byte-faithful).
Recall/precision + threshold sweep: `python tools/functional_truth_eval.py` (repo root).

## Status: `pending_annotation` (pending-human)

**There are currently ZERO real annotations.** `truth.jsonl` is empty by design. Every committed entry
lives under `fixtures/` and carries `"annotation_status": "fixture"` — these are synthetic self-proof
inputs that exercise the consumption chain (`parse_ab_gate --truth-set`, `functional_truth_eval`); they
must never be counted as annotations or quoted as quality numbers. The tools detect this and report
`truth_status: pending_annotation` rather than fabricating recall/precision.

The first real numbers arrive only after the S2 annotation campaign (expert 2–3 days): two experts
independently annotate one document → `agreement.py` → human adjudication → freeze. See
[Freeze gate checklist](#freeze-gate-checklist-t1-5) below.

## Maintenance rules

1. **Never commit customer wording, proprietary documents, credentials, or external evaluation assets.**
   Annotations are anonymized rewrites; `source_anchor.coordinates` reference the parser's block-id
   coordinate space, never verbatim client text. Same discipline as `agent_eval_v1`.
2. **Model-generated content cannot enter without recorded human review.** `functional_extract` /
   `functional_catalog` output is a *candidate* for an annotation, never an annotation itself. Every
   entry must be traceable to a human decision (annotator + annotated_at).
3. **Numeric values, OBIS codes, units are transcribed verbatim.** No unit conversion, no rounding, no
   normalization in the annotation — `data_constraints` is scored by exact set equality
   (`agreement.py`); a transcribed `15 min` ≠ `900 s`. A disagreement here is a transcription error,
   not an "understanding difference" (triggers a spec review per WS0 §3).
4. **Any change to fields, matching, or normalization bumps `GOLD_FUNCTIONAL_VERSION`.** Pre-freeze the
   version is `0.x.0` and may move freely; once frozen it becomes `1.0.0` and only moves on a schema
   or matching-rule change (judge-only tool changes do not bump it).

## Annotation norms

- **Granularity rule (是否成条).** One entry = one independently testable system-behavior goal. Multiple
  behaviors under one goal go into the `behaviors` list (not split into entries); mechanical table facts
  (single parameter value / single OBIS value) fold into the owning entry's `data_constraints`. This
  mirrors `functional_catalog` / `functional_extract` granularity so the yardstick and the product share
  one unit.
- **Anchor granularity must be frozen before agreement runs.** `source_anchor.coordinates` granularity
  (paragraph-level block ids vs sentence-level) decides the matching rule itself — divergent granularity
  between experts becomes a spurious disagreement source (WS0 §6). Freeze it in this README before D3.
  **Current frozen choice: paragraph-level block ids** (matches `functional_extract.source_block_ids`).
- **Conflict pairs: "mark, do not resolve" (标记不消解).** When two clauses genuinely conflict in the
  source, annotate both, cross-reference via `source_anchor.conflict_with`, and do **not** reconcile
  them. `agreement.py` exempts `conflict_with` entries from the entry-agreement Dice in both files —
  otherwise conflict clauses systematically depress agreement. The referenced peer `entry_id` must exist
  in the same file or the entry fails protocol compliance.
- **Disputes: "prefer over-annotation" (宁多勿少).** If two annotators disagree on whether to split a
  clause into two entries, both keep their split; the disagreement is recorded, not silently merged.
  This biases recall upward (acceptable) over silent merging (which hides misses).
- **`expects_drilldown` is optional.** Set it only when an entry genuinely warrants atom-level evidence
  (multi-behavior / multi-condition / parameter matrix). It feeds `functional_truth_eval --sweep-thresholds`
  calibration; leave it absent otherwise (the sweep falls back to a deterministic field-richness proxy).

## Recall / precision definitions (the yardstick)

Matching reuses `agreement.py`'s anchor-overlap criterion: a product item and a truth entry match iff
**same `section` AND ≥1 shared coordinate**.

- **Recall (查全)** = covered truth entries / total truth entries. A truth entry is covered iff some
  product item shares its section + a coordinate.
- **Precision (查准)** = product items whose anchor validly back-references / total product items. A
  product item validly back-references iff some truth entry shares its section + a coordinate (its
  source anchor lands on a truth-recognized normative location). A floating product (empty section /
  empty block_ids / coordinate with no truth correspondence) counts against precision.

Reported **per document, never averaged across documents** (restructure §2.2). Against a complete truth
set this is classical IR precision; against this micro/pending set precision is a lower bound — the
report flags `truth_completeness`.

## Freeze gate checklist (T1-5)

Execute in order. The set is not frozen (and no quality number is quotable) until every step passes.

1. **Two expert JSONL files** (`expert_a.jsonl`, `expert_b.jsonl`), each schema-valid against
   `schema/gold_functional_entry.schema.json`, same document, independent annotation:
   ```powershell
   python -c "import json,schema_check"   # or jsonschema validation per entry
   ```
   (Validation is enforced by `tests/test_gold_agreement.py::ProtocolComplianceTests` shape; a frozen
   run additionally validates every entry against the JSON Schema.)
2. **Run agreement:**
   ```powershell
   python golden_sets/gold_functional_v1/tools/agreement.py expert_a.jsonl expert_b.jsonl --report agreement_report.json
   ```
3. **Entry-agreement Dice ≥ 0.80** (`freeze_pass: true`). If below, do **not** lower the threshold —
   reconcile anchors/granularity and re-annotate. Field agreement (especially `data_constraints` < 100%)
   triggers a transcription spec review, not a threshold relaxation.
4. **Human full-volume adjudication.** Every mismatched/unmatched entry is reviewed by a third party;
   adjudications cite a clause or spec line and are logged to `arbitration_log` (entry id, both values,
   verdict, basis). Adjudicated entries count as agreed in the frozen metric, but the frozen report must
   carry **raw** entry-agreement, adjudication count + ratio, and per-field raw agreement — never the
   post-adjudication number alone (WS0 §4).
5. **Full human review of every entry** (analogous to `agent_eval_v1` reviewed_case_ids; the runner
   never self-certifies review status).
6. **Bump `GOLD_FUNCTIONAL_VERSION` to `1.0.0`** and write the adjudicated single truth set to
   `truth.jsonl`. From this point `truth_status` becomes `annotated` and `functional_truth_eval` /
   `parse_ab_gate --truth-set` emit real numbers. Re-freezing after any change requires re-running from
   step 1.

## Wiring to the gates

| Gate | Command (repo root) | What it does with the truth set |
|---|---|---|
| Direct-extract recall/precision | `python tools/functional_truth_eval.py --products <out> --truth-set golden_sets/gold_functional_v1` | per-doc recall/precision; `pending_annotation` while empty |
| Drilldown threshold calibration | add `--sweep-thresholds` to the above | recall/precision matrix over the `functional_drilldown` threshold grid (procedure: `docs/drilldown-thresholds.md`) |
| Table A/B role-audit sampling frame | `python tools/parse_ab_gate.py --corpus <…> --truth-set golden_sets/gold_functional_v1` | sampling-frame status + truth consumption; `pending_annotation` while empty |
| Inter-annotator agreement | `python golden_sets/gold_functional_v1/tools/agreement.py a.jsonl b.jsonl` | Dice + per-field; freeze gate |
