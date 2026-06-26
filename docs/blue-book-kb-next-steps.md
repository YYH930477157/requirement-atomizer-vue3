# Blue Book KB Next Steps

Date: 2026-06-26

This checklist continues the active goal: fully integrate the DLMS UA Blue Book into the reusable Obsidian-backed knowledge base and verify it repeatedly against real documents.

## Current Baseline

Refresh these numbers after each KB batch with:

```powershell
python -m requirement_kb.cli coverage knowledge_bases/compiled_from_obsidian.json
```

- Obsidian vault is the editable knowledge source.
- `knowledge_bases/compiled_from_obsidian.json` is the compiled runtime artifact.
- Runtime default KB loading includes `compiled_from_obsidian.json` for CLI, desktop tasks, and Vue/Electron presets.
- Current compiled coverage before the next batch:
  - 334 total compiled Obsidian entries.
  - 87/87 Blue Book Part 2 COSEM interface classes, all 87 with attributes or methods.
  - 73/73 Blue Book Part 1 OBIS table catalogue entries.
  - 103 row-level `cosem_object_instance` entries, distributed across AC electricity, DC electricity, and general object families.
  - AC electricity tables 14-20 are materialized for tariff, harmonics, phase angle, loss, voltage dips, and distortion rows.
  - Tables 9/14/15/16/17/18/19/20/27/28 were materialized from Blue Book Part 1 Ed.16 source text.
- Engineering composition smoke on ABNT Appendix 9 currently emits 21 requirement functions and 363 DLMS objects.
  - Function/object linking remains conservative: class hints guide semantics but no longer expand to all objects in a class.
  - Structured implementation specs cover deterministic ABNT smoke patterns: event handling, billing period, load profile, capability matrix, and access-control matrix.
  - COSEM attribute orphans are still a real-document follow-up item; class-template projection is covered in unit-level cases but needs more smoke evidence.

The machine-readable Blue Book snapshot is `docs/blue-book-kb-coverage-report.json`. Refresh it with:

```powershell
python -m requirement_kb.cli blue-book-report `
  --kb .\knowledge_bases\compiled_from_obsidian.json `
  --out .\docs\blue-book-kb-coverage-report.json
```

## Real-Document Smoke Results

### ABNT Appendix 9 docx

Input: `C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx`

- `atomic_requirements`: 2337 in the previous smoke comparison.
- ABNT remains focused on access control, so row-level tariff/harmonics additions should increase precise matches without broad noisy expansion.
- Re-run after each KB enrichment and compare `llm_tasks`, `domain_tags`, and `kb_matches`.

### Canna Requirements xlsx

Input: `C:\Users\YYHwudi\Desktop\Canna-29\Canna-29电表软件标准化需求列表 V1.2 - 2026-1-23 (4).xlsx`

- `xlsx_parser` was fixed to use `read_only=False` because conditional formatting made `max_row` unreliable in read-only mode.
- Previous smoke shape: 28 blocks / 2195 table items / 51737 atomic requirements.
- Watch for over-matching after row-level OBIS expansion, especially high-frequency OBIS substrings such as tariff codes.
- Next matching-quality pass should tighten OBIS keyword matching with full-code or boundary-aware evidence instead of reducing coverage.

## Continue In This Order

1. Materialize ABNT/Canna-relevant OBIS rows.
   - Continue beyond current table 9/14-20/27-28 coverage into the remaining electricity, HCA, thermal, gas, water, and other-media tables.
   - Prioritize OBIS objects seen in ABNT Appendix 9 and Canna OBIS spreadsheets.
   - Create row-level `cosem_object_instance` notes with OBIS pattern, object name, likely interface class, medium, value group mapping, and Blue Book table reference.

2. Expand high-value Part 2 class semantics.
   - Completed target classes in the current semantic-depth pass: communication classes 19/23/41/42/44/45/46/48/100, event/monitor classes 63/65/66/67, and payment classes 111/112/113/115.
   - Keep enriched classes under regression tests, especially Register Activation, Schedule, Single Action Schedule, Activity Calendar, Register Monitor, Parameter Monitor, SAP Assignment, IEC HDLC Setup, TCP-UDP Setup, IPv4 Setup, PPP setup, GPRS modem setup, SMTP setup, and NTP setup.
   - For remaining classes, add `source_refs`, complete attributes, methods, behavior notes, access semantics, state model if applicable, and common instances when available.

3. Keep coverage gates current as knowledge grows.
   - Keep tests in `tests/test_blue_book_kb.py` focused on facts that matter to downstream requirement composition.
   - Run `python -m unittest tests.test_blue_book_coverage_report -v` after each KB batch.
   - Add row-level OBIS tests for representative electricity, DC, general, profile, list, and register-table objects.
   - Add matching tests that use realistic requirement sentences, not only isolated keywords.

4. Recompile and validate after every batch.
   - `python -m requirement_kb.obsidian compile --vault .\obsidian-vault --out .\knowledge_bases\compiled_from_obsidian.json --kb-id obsidian_energy_metering`
   - `python -m requirement_kb.cli validate-vault --vault .\obsidian-vault`
   - `python -m requirement_kb.cli validate .\knowledge_bases\compiled_from_obsidian.json --strict`

5. Run real-document smoke checks.
   - Use ABNT Appendix 9 and Canna OBIS spreadsheets.
   - Confirm `manifest.knowledge_bases` lists the compiled Obsidian KB.
   - Compare before/after `llm_tasks`, `domain_tags`, and `kb_matches`.
   - Watch for noisy broad matches from generic terms such as `interface class`, `blue book`, and `object`.

## Known Remaining Gaps

- Part 1 row-level OBIS materialization is still incomplete outside the current priority electricity tables.
- Previous-version classes in Blue Book Part 2 Chapter 5 are intentionally not covered yet.
- Matching quality must be tuned after row-level OBIS entries are added, because more entries can increase false positives.
- Remaining orphan attributes are concentrated around class templates and extracted pseudo-parents such as Data, Compact Data, Extended Register, sort_object, Register Table, and Disconnect Control variants.
- Engineering requirement wording is still deterministic and partly template-like; keep sampling real outputs for translation residue and over-specific template language.
- Function-to-object linking is intentionally conservative. Add more source/table-aware, object-use, and OBIS-pattern evidence before increasing linked object counts.

## Part 2 Interface Class Semantic Depth

The named 17 target classes have attribute/method enrichment, access semantics, and behavior notes:

- Communication: IEC local port (19), IEC HDLC (23), TCP-UDP (41), IPv4 (42), PPP (44), GPRS modem (45), SMTP (46), IPv6 (48), NTP (100).
- Event/monitoring: Status mapping (63), Parameter monitor (65), Measurement data monitoring objects (66), Sensor manager (67).
- Payment: Account (111), Credit (112), Charge (113), Token gateway (115).

## Verification Snapshot From This Batch

Run after every KB batch and paste the tail output into the PR/commit:

```powershell
# 1. Coverage reports
python -m requirement_kb.cli coverage knowledge_bases/compiled_from_obsidian.json
python -m requirement_kb.cli blue-book-report --kb .\knowledge_bases\compiled_from_obsidian.json --out .\docs\blue-book-kb-coverage-report.json

# 2. Vault + JSON schema validation
python -m requirement_kb.cli validate-vault --vault .\obsidian-vault
python -m requirement_kb.cli validate .\knowledge_bases\compiled_from_obsidian.json --strict

# 3. Full test suites
python -m unittest discover -s tests
npm test -- --run electron/__tests__/main.helpers.spec.ts electron/__tests__/package-config.spec.ts src/__tests__/ReviewWorkspace.spec.ts
npm run build
```

Real ABNT smoke run confirmed the compiled Obsidian KB is loaded by default.
