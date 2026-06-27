# Blue Book KB Next Steps

Date: 2026-06-27

This checklist continues the active goal: fully integrate the DLMS UA Blue Book into the reusable Obsidian-backed knowledge base and verify it repeatedly against real documents.

## Current Baseline

Refresh these numbers after each KB batch with:

```powershell
python -m requirement_kb.cli coverage knowledge_bases/compiled_from_obsidian.json
```

- Obsidian vault is the editable knowledge source.
- `knowledge_bases/compiled_from_obsidian.json` is the compiled runtime artifact.
- Runtime default KB loading includes `compiled_from_obsidian.json` for CLI, desktop tasks, and Vue/Electron presets.
- Current compiled coverage after the ABNT bulk OBIS import and the 2026-06-27 Part 2 gap fix:
  - 744 total compiled Obsidian entries.
  - 105/105 Blue Book Part 2 COSEM interface classes, all 105 with attributes or methods. The count was corrected from 87 on 2026-06-27 after a PDF re-audit added 18 missing Ed.16 current communication classes (cellular/PRIME/G3/HS-PLC/Wi-SUN/SCHC-LPWAN/LoRaWAN/Function control/CoAP setup); the Push setup (40) catalogue version was also corrected 0→3.
  - Strict Blue Book snapshot: 35 deeply enriched classes and 53 catalogue-seed classes.
  - 73/73 Blue Book Part 1 OBIS table catalogue entries.
  - 495 row-level `cosem_object_instance` entries, distributed across general, AC electricity, DC electricity, HCA, thermal energy, gas, cold-water, and hot-water object families.
  - 255 row-level entries were bulk-generated from `out/abnt_current_kb_smoke/cosem_object_model.json` and tagged `abnt_bulk_import` to provide exact OBIS lookup coverage for the current ABNT smoke. They are intentionally marked for later Blue Book semantic review.
  - Generic coverage now distinguishes true row-level object table gaps from catalogue-only structure/value-group tables. The current `tables_with_catalogue_but_no_rows` list is empty.
  - AC electricity tables 14-20 are materialized for tariff, harmonics, phase angle, loss, voltage dips, and distortion rows.
  - ABNT maximum-demand Extended Register rows for `1-0:1.6.x.255` through `1-0:8.6.x.255` and cumulative-demand rows for `1-0:1.2.x.255` through `1-0:8.2.x.255` are now materialized as class 4 objects.
  - ABNT instantaneous current Register rows `1-0:90.7.0.255`, `1-0:91.7.0.255`, and `1-1:91.7.0.255` are now materialized from `TBL-000112` as class 3 AC electricity objects.
  - Tables 41 HCA examples, 49 thermal cooling examples, 50 gas conversion data-flow, and 72 water examples now include three representative value rows each.
  - High-frequency real-smoke general rows include the COSEM Clock object at `0-0:1.0.0.255`, Device ID rows `0-0:96.1.0.255` / `0-0:96.1.4.255`, the Association LN client rows `0-0:40.0.0.255` / `0-0:40.0.1.255` / `0-0:40.0.2.255` / `0-0:40.0.3.255` / `0-0:40.0.5.255`, Security Setup local/remote rows `0-0:43.0.3.255` / `0-0:43.0.5.255`, Image Transfer `0-0:44.0.0.255`, IEC HDLC setup rows `0-1:22.0.0.255` / `0-2:22.0.0.255`, Disconnect Control rows `0-0:96.3.10.255` / `0-1:96.3.10.255`, Previous Disconnect Control `0-1:94.55.20.255`, Script Table rows `0-0:10.0.0.255` / `0-0:10.0.1.255` / `0-0:10.0.100.255` / `0-0:10.0.107.255`, Image Activation Scheduler `0-0:15.0.2.255`, billing-period schedules `0-0:15.0.0.255` / `0-0:15.1.0.255`, Disconnect Control Scheduler `0-0:15.0.1.255`, Disconnect Script Table `0-0:10.0.106.255`, key-expiration schedule `0-0:15.x.7.255`, key-expiration script table `0-0:10.0.111.255`, security operation logs `0-0:99.98.11.255` / `0-0:99.98.12.255` with event/filter rows, firmware event log triplet `0-0:99.98.4.255` / `0-0:96.11.4.255` / `0-1:94.55.112.255`, standard/common/synchronization event-log triplets at `0-0:99.98.0.255`, `0-0:99.98.7.255`, and `0-0:99.98.8.255`, fraud detection and disconnect-control event-log triplets at `0-0:99.98.1.255` and `0-0:99.98.2.255`, plus the power quality event log group at `0-0:99.98.5.255` and user output configuration `0-1:94.55.118.255`. Recent batches also materialize high-attribute Profile generic rows from the ABNT smoke: current billing values `0-0:21.0.5.255`, instant values `0-0:21.0.6.255`, billing profiles `1-0:98.1.0.255` / `1-0:98.2.0.255`, load profiles `1-0:99.1.0.255` / `1-0:99.2.0.255`, DRP/DRC daily/monthly logs `1-0:94.55.178.255` / `1-0:94.55.183.255` / `1-0:94.55.189.255` / `1-0:94.55.194.255`, and average demand register rows `1-0:1.4.0.255` through `1-0:8.4.0.255`.
  - Tables 9/14/15/16/17/18/19/20/27/28 plus representative HCA/thermal/gas/water list, service, error, profile, and example/data-flow rows are materialized from Blue Book Part 1 Ed.16 source text.
- Engineering composition smoke on ABNT Appendix 9 currently emits 13 requirement functions and 363 DLMS objects; capture-period/capture-list load-profile requirements are folded into the structured load-profile function, meter/profile status bit rows, including the `Bit 3 MP` wording variant, are folded into a structured status-bit function, and accumulator all-9s rollover is emitted as a structured measurement rollover requirement.
  - Function/object linking remains conservative: class hints guide semantics but no longer expand to all objects in a class.
  - Structured implementation specs cover deterministic ABNT smoke patterns: event handling, billing period, load profile, capability matrix, and access-control matrix.
  - COSEM object model smoke currently reports 0 orphan attributes and 257 projected class-template attributes.

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

1. Review and curate the ABNT bulk OBIS rows.
   - `tools/generate_abnt_obis_notes.py` now fills all exact OBIS gaps found in the current ABNT COSEM object-model smoke in one run.
   - The first verification gate is exact coverage, not manual semantic quality: `tests.test_blue_book_kb.BlueBookKnowledgeBaseTests.test_compiled_obsidian_has_exact_obis_for_current_abnt_object_model`.
   - After coverage is closed, review `abnt_bulk_import` notes against Blue Book source text and replace generic bulk metadata with curated table references, richer aliases, and behavior notes where needed.

2. Materialize ABNT/Canna-relevant OBIS rows not present in the current smoke.
   - There are no longer any table-catalogue entries with zero row-level object coverage in the generic coverage report. Tables 41, 49, 50, and 72 now each have three representative value rows; continue deepening table 50 gas conversion data-flow objects and table 72 water examples when source text or real document evidence identifies additional concrete rows.
   - Treat structure/value-group catalogue tables as supporting classification data rather than row-level object gaps: tables 1-7, 34-36, 43-44, 52-60, 66-67, and 73 are currently separated by the coverage report.
   - Prioritize OBIS objects seen in ABNT Appendix 9 and Canna OBIS spreadsheets; the common Association LN client rows, Security Setup local/remote rows, correct/failed security operation logs, and their event/filter Data rows are now materialized from class common-instance sets and real ABNT smoke evidence.
   - Create row-level `cosem_object_instance` notes with OBIS pattern, object name, likely interface class, medium, value group mapping, and Blue Book table reference.

3. Expand high-value Part 2 class semantics.
   - Completed target classes in the current semantic-depth pass: communication classes 19/23/41/42/44/45/46/48/100, event/monitor classes 63/65/66/67, and payment classes 111/112/113/115.
   - Keep enriched classes under regression tests, especially Register Activation, Schedule, Single Action Schedule, Activity Calendar, Register Monitor, Parameter Monitor, SAP Assignment, IEC HDLC Setup, TCP-UDP Setup, IPv4 Setup, PPP setup, GPRS modem setup, SMTP setup, and NTP setup.
   - For remaining classes, add `source_refs`, complete attributes, methods, behavior notes, access semantics, state model if applicable, and common instances when available.

4. Keep coverage gates current as knowledge grows.
   - Keep tests in `tests/test_blue_book_kb.py` focused on facts that matter to downstream requirement composition.
   - Run `python -m unittest tests.test_blue_book_coverage_report -v` after each KB batch.
   - Add row-level OBIS tests for representative electricity, DC, general, profile, list, and register-table objects.
   - Add matching tests that use realistic requirement sentences, not only isolated keywords.

5. Recompile and validate after every batch.
   - `python -m requirement_kb.obsidian compile --vault .\obsidian-vault --out .\knowledge_bases\compiled_from_obsidian.json --kb-id obsidian_energy_metering`
   - `python -m requirement_kb.cli validate-vault --vault .\obsidian-vault`
   - `python -m requirement_kb.cli validate .\knowledge_bases\compiled_from_obsidian.json --strict`

6. Run real-document smoke checks.
   - Use ABNT Appendix 9 and Canna OBIS spreadsheets.
   - Confirm `manifest.knowledge_bases` lists the compiled Obsidian KB.
   - Compare before/after `llm_tasks`, `domain_tags`, and `kb_matches`.
   - Watch for noisy broad matches from generic terms such as `interface class`, `blue book`, and `object`.

## Known Remaining Gaps

- Part 1 row-level OBIS materialization has no zero-row object table gaps in the current coverage report. Example/data-flow tables 50 and 72 now cover three representative value rows each, but can still be deepened when source text or real document evidence identifies additional concrete rows.
- Previous-version classes in Blue Book Part 2 Chapter 5 are intentionally not covered yet.
- Matching quality must be tuned after row-level OBIS entries are added, because more entries can increase false positives.
- Class-template projection should remain under smoke regression because it is responsible for keeping real ABNT COSEM attribute orphans at zero.
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
