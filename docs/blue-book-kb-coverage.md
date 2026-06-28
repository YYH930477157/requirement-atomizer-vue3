# Blue Book Knowledge Base Coverage

Date: 2026-06-27

This note tracks the current integration state of the local Blue Book knowledge base. The Obsidian vault remains the editable source, and `knowledge_bases/compiled_from_obsidian.json` is the compiled runtime artifact.

## Source Scope

- Blue Book Part 1: `DLMS UA 1000-1 Ed. 16 Part 1`, OBIS Object Identification System.
- Blue Book Part 2: `DLMS UA 1000-1 Ed. 16 Part 2`, COSEM Interface Classes.

The repository does not store the Blue Book PDFs or copy their full text. It stores structured seed knowledge, definitions, aliases, matching keywords, relations, and class metadata needed by the analyzer.

## Current Coverage

- Part 1 OBIS: standard source entry, OBIS value group structure, A-B:C.D.E.F group semantics, common standard-specific code ranges, links to OBIS logical names, and catalogue coverage for all 73 OBIS tables listed in Part 1.
- Part 2 COSEM Interface Classes: current interface class catalogue coverage for all 105 current `class_id` entries extracted from Chapter 4 of Blue Book Part 2. This count was corrected from 87 to 105 on 2026-06-27 after a PDF re-audit found 18 Ed.16 current communication classes missing from both the catalogue and the compiled KB (GSM diagnostic 47, LTE monitoring 151, CoAP setup 152, Function control 122, PRIME NB OFDM PLC 81/83/85/86, HS-PLC SSAS 143, G3-PLC Hybrid 162, Wi-SUN 95/96, RPL 97, MPL 98, SCHC-LPWAN 126/127, LoRaWAN 128/129). The Push setup (40) catalogue version was also corrected 0→3 to match the enriched KB note.
- Part 2 operational semantics: all 105 current interface classes are now deeply enriched. The stricter machine-readable Blue Book snapshot classifies all 105 classes as enriched (88 communication/control/payment + the 17 already enriched earlier), with 0 catalogue seeds remaining. The 18 classes added on 2026-06-27 and the remaining 35 catalogue-seed communication classes (50-59, 68, 73, 80, 82, 84, 90-92, 101-105, 116, 123-124, 130-133, 140-142, 153, 160-161) were enriched 2026-06-28 from the Blue Book Part 2 IC attribute/method tables (full attributes with data type + static/dynamic flag + short name, methods, and access semantics; deterministic verbatim extraction, no model guessing). access_rights are described semantically per static/dynamic rather than hard-coded per attribute because the IC tables do not specify concrete R/RW per client.
- Row-level object instances: 495 `cosem_object_instance` entries are available, covering general, AC electricity, DC electricity, HCA, thermal energy, gas, cold-water, and hot-water object families. An earlier batch bulk-generated 255 ABNT Appendix 9 exact OBIS lookup notes from the current `out/abnt_current_kb_smoke/cosem_object_model.json` smoke output. These entries originally carried the `abnt_bulk_import` tag to close ABNT exact-OBIS lookup gaps quickly; they are being progressively curated into Blue Book-traced rows (Blue Book Part 1 table reference + semantic value-group + ABNT-sourced notes, bulk tag removed). Progress: batches B1+B2+B3+B4+B5 curated 197/255 (general/service + event/alarm/filter/status + A=1 energy/reactive/voltage/current/power-factor registers + voltage sag/swell dips + phase angle), 58 still carry `abnt_bulk_import`.
- Generic coverage now separates catalogue-only structure/value-group tables from true row-level gaps. The current `tables_with_catalogue_but_no_rows` list is empty; tables 1-7, 34-36, 43-44, 52-60, 66-67, and 73 are tracked as catalogue/structure tables not expected to have row-level instances.
- Runtime loading: `compiled_from_obsidian.json` is now included in the default `requirement_kb` paths and in the Vue/Electron ABNT run preset.
- Corrected seed facts: `TCP-UDP Setup` is class 41 and `IPv4 Setup` is class 42; `Schedule` is class 10 and `Single Action Schedule` is class 22.

## Verification Gates

- `tests/test_blue_book_kb.py` asserts that the compiled Obsidian KB contains Blue Book Part 1/Part 2 entries.
- The same test asserts runtime matching for OBIS value groups and representative COSEM classes.
- The same test asserts 73/73 Part 1 OBIS table catalogue coverage by table number and title.
- The same test asserts 87/87 current Part 2 interface class catalogue coverage by `class_id` and version.
- `tests/test_blue_book_coverage_report.py` asserts the machine-readable coverage snapshot: 73/73 Part 1 tables, 105/105 current Part 2 classes, 88 strictly enriched classes, 0 catalogue-seed classes, and 495 row-level object instances.
- `tests/test_blue_book_kb.py::BlueBookKnowledgeBaseTests.test_compiled_obsidian_has_exact_obis_for_current_abnt_object_model` asserts that every OBIS pattern emitted by the current ABNT COSEM object-model smoke exists as an exact `cosem_object_instance` pattern in the compiled Obsidian KB.
- Tests assert that enriched COSEM classes are traceable and contain actionable semantics, including Push Setup v3 attributes, Demand Register `next_period`, Association LN user methods, Compact Data `compact_buffer`, Register Table `capture`, Disconnect Control states, and the enriched communication setup classes.
- Vault validation and JSON schema validation are run against the compiled runtime KB.

## Known Remaining Work

- Part 1 OBIS tables are covered as table-level catalogue seeds, and every object/example catalogue table now has at least one row-level representative instance. The ABNT bulk import adds exact lookup entries for all currently extracted ABNT object-model OBIS patterns, including rows that do not yet carry a Blue Book table reference. Those bulk rows should be reviewed and converted to curated Blue Book-backed notes over time.
- All 105 current Part 2 interface classes are now deeply enriched under the stricter Blue Book snapshot (0 catalogue seeds remain). No further class-level attribute/method expansion is pending for the current Part 2 catalogue.
- Previous-version interface classes in Blue Book Part 2 Chapter 5 are intentionally not covered by the current-class coverage gate.
- Quality should be measured on additional real DLMS/COSEM documents after each enrichment batch.
