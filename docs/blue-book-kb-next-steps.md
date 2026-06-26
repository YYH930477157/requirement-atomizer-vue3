# Blue Book KB Next Steps

Date: 2026-06-26

This checklist continues the active goal: fully integrate the DLMS UA Blue Book into the reusable Obsidian-backed knowledge base and verify it repeatedly against real documents.

## Current Baseline

- Obsidian vault is the editable knowledge source.
- `knowledge_bases/compiled_from_obsidian.json` is the compiled runtime artifact.
- Runtime default KB loading includes `compiled_from_obsidian.json` for CLI, desktop tasks, and Vue/Electron presets.
- Current compiled coverage:
  - 283 total compiled Obsidian entries.
  - 87/87 current Blue Book Part 2 COSEM interface classes.
  - 73/73 Blue Book Part 1 OBIS table catalogue entries.
  - 45 enriched COSEM classes with attributes, methods, behavior notes, or access semantics.
  - 42 catalogue-seed COSEM classes still need detailed semantics.
  - 52 row-level `cosem_object_instance` entries.
  - Object instance split: general 9, AC electricity 33, DC electricity 10.
  - Object instance class split: class 1 = 5, class 3 = 37, class 6 = 1, class 7 = 3, class 15 = 1, class 17 = 1, class 20 = 1, class 61 = 3.
- Engineering composition smoke on ABNT Appendix 9 currently emits 21 requirement functions and 363 DLMS objects.
  - Function/object linking is now conservative: class hints remain semantic guidance and no longer expand to all objects in a class; explicit name/OBIS/source-table/object-use evidence currently links 7 functions to 21 objects.
  - Structured implementation specs now cover the main deterministic patterns seen in the ABNT smoke: event handling (1), billing period (4), load profile (1), capability matrix (4), and access-control matrix (1).
  - COSEM attribute orphans are still 256 in the current smoke; verified class-template projection is implemented in unit-level cases but has not yet reduced the real ABNT orphan count.
  - The object-model count now separates source attribute requirements from projected class-template attributes; current `projected_class_attributes` is 0.

The machine-readable snapshot is `docs/blue-book-kb-coverage-report.json`. Refresh it with:

```powershell
python -m requirement_kb.cli blue-book-report `
  --kb .\knowledge_bases\compiled_from_obsidian.json `
  --out .\docs\blue-book-kb-coverage-report.json
```

## Continue In This Order

1. Materialize ABNT/Canna-relevant OBIS rows.
   - Start with electricity tables 13-25 and 26-33.
   - Prioritize OBIS objects seen in `Appendix 9-ABNT NBR 16968-2022 EN.docx` and Canna OBIS spreadsheets.
   - Create row-level `cosem_object_instance` notes with OBIS pattern, object name, likely interface class, medium, value group mapping, and Blue Book table reference.

2. Expand high-value Part 2 class semantics.
   - Newly enriched in this batch: Association SN, M-Bus slave port setup, IEC local port setup, IEC twisted pair setup, Modem configuration, Auto answer, Auto connect, MAC address setup, PPP setup, NTP setup, Utility tables, COSEM data protection, GPRS modem setup, SMTP setup, M-Bus client, M-Bus master port setup, DLMS server M-Bus port setup, M-Bus diagnostic.
   - Next seed classes first: Status mapping, Measurement data monitoring objects, Sensor manager, Arbitrator, Wireless Mode Q channel, Communication port protection, Array manager, and the remaining PLC / ZigBee / payment-domain classes.
   - Keep already-enriched classes such as Register Activation, Schedule, Single Action Schedule, Activity Calendar, Register Monitor, Parameter Monitor, SAP Assignment, IEC HDLC Setup, TCP-UDP Setup, IPv4 Setup, and the newly enriched communication setup classes under regression tests.
   - For each class, add `source_refs`, complete attributes, methods, behavior notes, access semantics, state model if applicable, and common instances when available.

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
   - Compare `llm_tasks`, `domain_tags`, and `kb_matches` before/after each enrichment batch.
   - Watch for noisy broad matches from generic terms such as `interface class`, `blue book`, and `object`.

## Known Remaining Gaps

- Part 1 currently has table-level catalogue coverage, not full row-level OBIS materialization.
- 42 of 87 Part 2 interface classes still need detailed method behavior and access semantics.
- Previous-version classes in Blue Book Part 2 Chapter 5 are intentionally not covered yet.
- Matching quality must be tuned after row-level OBIS entries are added, because more entries can increase false positives.
- Engineering requirement wording is still deterministic and partly template-like, but key families now have structured fields. Actor labels from the current ABNT capability matrix are normalized, access-control matrix output exists, and the known ABNT translation residues `must to be used`, `O object`, `Data of billing period`, `O record`, `must)`, `he must`, `all you days`, and `It is The capacity` are cleaned in engineering output. Next quality pass should sample for new residues after adding more source documents.
- Function-to-object linking is intentionally conservative. Add more source/table-aware, object-use, and OBIS-pattern evidence before increasing linked object counts.
- Remaining orphan attributes are concentrated around class templates and extracted pseudo-parents such as Data, Compact Data, Extended Register, sort_object, Register Table, and Disconnect Control variants. Review these before treating the DLMS object spec as complete.

## Verification Snapshot From This Batch

- `python -m requirement_kb.cli validate-vault --vault .\obsidian-vault`
- `python -m requirement_kb.cli validate .\knowledge_bases\compiled_from_obsidian.json --strict`
- `python -m requirement_kb.cli blue-book-report --kb .\knowledge_bases\compiled_from_obsidian.json --out .\docs\blue-book-kb-coverage-report.json`
- `python -m unittest tests.test_blue_book_coverage_report -v`
- `python -m unittest discover -s tests`
- `npm test -- --run`
- `npm run build`
- Real ABNT smoke run confirmed the compiled Obsidian KB is loaded by default.
