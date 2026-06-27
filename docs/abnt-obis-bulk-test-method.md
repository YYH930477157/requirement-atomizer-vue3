# ABNT OBIS Bulk Import Test Method

Date: 2026-06-27

This file is the handoff checklist for testing the one-shot ABNT OBIS import. The goal is to avoid slow, one-by-one knowledge-base work: generate all missing ABNT smoke OBIS notes first, compile the Obsidian vault, then run coverage and real-document checks in one batch.

## What Was Generated

- Source smoke model: `out/abnt_current_kb_smoke/cosem_object_model.json`
- Generator: `tools/generate_abnt_obis_notes.py`
- Generated notes: 255 Markdown files under `obsidian-vault/04_object_instances/`
- Marker tag: `abnt_bulk_import`
- Compiled runtime KB: `knowledge_bases/compiled_from_obsidian.json`
- Current compiled totals after import: 726 entries, including 495 `cosem_object_instance` entries.

The generated notes are exact OBIS lookup coverage for the current ABNT object-model smoke. They are not a claim that every row has been manually reviewed against Blue Book semantics.

## One-Shot Retest Commands

Run these from `E:\Codex\requirement-atomizer-vue3`.

```powershell
# 1. Recreate missing ABNT OBIS notes if the smoke model or compiled KB changed.
python tools\generate_abnt_obis_notes.py

# 2. Compile the editable Obsidian vault into the runtime KB artifact.
python -m requirement_kb.obsidian compile --vault .\obsidian-vault --out .\knowledge_bases\compiled_from_obsidian.json --kb-id obsidian_energy_metering

# 3. Validate vault frontmatter, relations, and compiled JSON schema.
python -m requirement_kb.cli validate-vault --vault .\obsidian-vault
python -m requirement_kb.cli validate .\knowledge_bases\compiled_from_obsidian.json --strict

# 4. Refresh coverage snapshots.
python -m requirement_kb.cli blue-book-report --kb .\knowledge_bases\compiled_from_obsidian.json --out .\docs\blue-book-kb-coverage-report.json
python -m requirement_kb.cli coverage .\knowledge_bases\compiled_from_obsidian.json

# 5. Run the exact ABNT OBIS coverage guard and Blue Book coverage tests.
python -m unittest tests.test_blue_book_kb.BlueBookKnowledgeBaseTests.test_compiled_obsidian_has_exact_obis_for_current_abnt_object_model -v
python -m unittest tests.test_blue_book_kb -v
python -m unittest tests.test_blue_book_coverage_report -v

# 6. Rebuild ABNT smoke outputs for downstream manual review.
python -m cosem_object_model --out .\out\abnt_current_kb_smoke
python -m cli compose --out .\out\abnt_current_kb_smoke --quiet
```

## Pass Criteria

- `generate_abnt_obis_notes.py` should write `0` new paths when all current ABNT OBIS gaps are already closed.
- `validate-vault` should report `errors: 0` and `warnings: 0`.
- Strict JSON validation should print `[]`.
- The exact ABNT coverage guard should pass with no missing OBIS patterns.
- `tests.test_blue_book_coverage_report` should expect 726 total compiled entries and 495 object instances.

## Manual Review Notes

- Use the `abnt_bulk_import` tag to filter generated notes for semantic review.
- Prioritize rows that are high-impact in real ABNT/Canna outputs, especially class 1 Data, class 3 Register, class 4 Extended Register, class 7 Profile Generic, and security/control rows.
- During semantic review, keep the exact `obis_pattern` stable. Enrich aliases, keywords, Blue Book table references, source references, notes, and relations only when the source evidence is clear.
- Do not hand-edit `knowledge_bases/compiled_from_obsidian.json`; always edit Obsidian notes and recompile.
