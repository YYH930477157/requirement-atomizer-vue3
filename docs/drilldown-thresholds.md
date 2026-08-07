# Drilldown Threshold Calibration Procedure

`functional_drilldown` decides deterministically (zero LLM) which functional-requirement entries are
drilled into atom-level sub-evidence. Three thresholds govern it (all are config items in
`config.ENV_REGISTRY`, env-overridable):

| Threshold | Env var | Current default | Signal |
|---|---|---|---|
| `multi_behavior` | `RATOMIZER_FUNCTIONAL_DRILLDOWN_MULTI_BEHAVIOR` | 2 | one subject with ≥N obligation-modal-governed distinct actions |
| `multi_condition` | `RATOMIZER_FUNCTIONAL_DRILLDOWN_MULTI_CONDITION` | 1 | ≥N distinct condition connectors / mutually-exclusive branches |
| `matrix_rows` | `RATOMIZER_FUNCTIONAL_DRILLDOWN_MATRIX_ROWS` | 2 | a clause's source table block carries ≥N parameter rows |

The current defaults are **initial guesses** ("pending WS0 gold-standard regression" per the module
docstring). This document is the procedure that replaces them with calibrated values once the S2 truth
set (`golden_sets/gold_functional_v1`) is frozen.

## Why calibrate

Drilldown error is asymmetric but not free: under-drilling delays evidence to review-time; over-drilling
spends atomization cost on entries that did not need it. The truth set's optional `expects_drilldown`
field (or, in its absence, a deterministic field-richness proxy) gives a ground-truth signal for which
entries *should* be drilled, so the thresholds can be tuned to maximize agreement with that signal
instead of guessed.

## Prerequisites

1. `golden_sets/gold_functional_v1/truth.jsonl` is frozen at `GOLD_FUNCTIONAL_VERSION = 1.0.0` with real
   annotations (status `annotated`, not `pending_annotation`).
2. A direct-extract run over the truth document exists: `out/<doc>/functional_requirements.json`.
3. Truth entries that warrant drilling carry `expects_drilldown: true/false`. (If absent on most
   entries, the sweep falls back to the richness proxy and reports `truth_no_signal` — calibrate only
   when the signal coverage is adequate; otherwise annotate more entries first.)

## Procedure

1. **Run the sweep** over the truth document's direct-extract product and the frozen truth set:

   ```powershell
   python tools/functional_truth_eval.py ^
     --products out/<truth-doc>/functional_requirements.json ^
     --truth-set golden_sets/gold_functional_v1 ^
     --sweep-thresholds ^
     --report drilldown_sweep_<doc>.json
   ```

   The report's `sweep.matrix` is a grid over `multi_behavior × multi_condition × matrix_rows`, each
   cell carrying `drill_recall` and `drill_precision` computed against the truth's `expects_drilldown`
   signal on product↔truth matched pairs.

2. **Read off the calibration diagnostics.** `truth_needs_drill_pos` / `truth_needs_drill_neg` must be
   non-zero and `truth_no_signal` small; otherwise the signal is too sparse to calibrate — stop and
   annotate more `expects_drilldown` values. `uncalibrated_products` (products with no truth match) are
   excluded from the matrix denominator; a large value means the truth set does not yet cover this
   document's clauses.

3. **Select the optimal cell.** Prefer the cell that maximizes `drill_recall` subject to
   `drill_precision ≥ 0.80` (recall-first: a missed drill is recoverable at review, a systematic
   over-drill is pure cost). Tie-break toward the **higher** threshold (less drilling = less cost) and
   toward the current default if within tolerance.

4. **Sanity-check against the fixture baseline.** The synthetic fixture sweep (run it the same way with
   `--products golden_sets/gold_functional_v1/fixtures/products_cover.json --truth-set …/fixtures/synthetic_truth.jsonl`)
   is the regression anchor: it must still report the same optimal cell shape (the fixture is engineered
   so the optimum is `multi_behavior=2, multi_condition=1`, matching the current default). If the
   fixture optimum moves, the sweep logic regressed — fix before trusting the real-document sweep.

5. **Backfill the defaults.** Update `functional_drilldown.default_thresholds()` and the matching
   `config.ENV_REGISTRY` defaults together, and record the calibration in `CLAUDE.md` (document, raw
   recall/precision at the chosen cell, signal coverage, date). A default change is behavior-facing and
   does **not** require a version bump of `FUNCTIONAL_DRILLDOWN_VERSION` (the thresholds are inputs, not
   the decision logic) — but it must be recorded and re-validated on the next truth-document.

## Multi-document policy

Calibrate per document family (same family_id as the role audit), then adopt the **most conservative**
(least drilling) cell that keeps recall ≥ target on **every** family. Never average across families
(restructure §2.2: cross-family averaging masks per-family defects). If no single cell satisfies all
families, keep the higher-recall cell and accept the over-drill cost on the cheaper family.

## Current state

No real-document sweep has been run (truth set `pending_annotation`). The defaults above stand as
guesses until the first S2 truth document is frozen; the fixture sweep self-proves the mechanism.
