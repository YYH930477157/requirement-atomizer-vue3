# Blue Book Knowledge Base Coverage

Date: 2026-06-26

This note tracks the current integration state of the local Blue Book knowledge base. The Obsidian vault remains the editable source, and `knowledge_bases/compiled_from_obsidian.json` is the compiled runtime artifact.

## Source Scope

- Blue Book Part 1: `DLMS UA 1000-1 Ed. 16 Part 1`, OBIS Object Identification System.
- Blue Book Part 2: `DLMS UA 1000-1 Ed. 16 Part 2`, COSEM Interface Classes.

The repository does not store the Blue Book PDFs or copy their full text. It stores structured seed knowledge, definitions, aliases, matching keywords, relations, and class metadata needed by the analyzer.

## Current Coverage

- Part 1 OBIS: standard source entry, OBIS value group structure, A-B:C.D.E.F group semantics, common standard-specific code ranges, links to OBIS logical names, and catalogue coverage for all 73 OBIS tables listed in Part 1.
- Part 2 COSEM Interface Classes: current interface class catalogue coverage for all 87 current `class_id` entries extracted from Chapter 4 of Blue Book Part 2.
- Part 2 operational semantics: 45 of 87 current interface classes now carry enriched attributes, methods, behavior notes, access semantics, or implementation-oriented notes. The remaining 42 classes are catalogue seeds tracked in `docs/blue-book-kb-coverage-report.json`.
- Row-level object instances: 52 `cosem_object_instance` entries are available, covering general, AC electricity, and DC electricity object families.
- Runtime loading: `compiled_from_obsidian.json` is now included in the default `requirement_kb` paths and in the Vue/Electron ABNT run preset.
- Corrected seed facts: `TCP-UDP Setup` is class 41 and `IPv4 Setup` is class 42; `Schedule` is class 10 and `Single Action Schedule` is class 22.

## Verification Gates

- `tests/test_blue_book_kb.py` asserts that the compiled Obsidian KB contains Blue Book Part 1/Part 2 entries.
- The same test asserts runtime matching for OBIS value groups and representative COSEM classes.
- The same test asserts 73/73 Part 1 OBIS table catalogue coverage by table number and title.
- The same test asserts 87/87 current Part 2 interface class catalogue coverage by `class_id` and version.
- `tests/test_blue_book_coverage_report.py` asserts the machine-readable coverage snapshot: 73/73 Part 1 tables, 87/87 current Part 2 classes, 45 enriched classes, 42 catalogue-seed classes, and 52 row-level object instances.
- Tests assert that enriched COSEM classes are traceable and contain actionable semantics, including Push Setup v3 attributes, Demand Register `next_period`, Association LN user methods, Compact Data `compact_buffer`, Register Table `capture`, Disconnect Control states, and the enriched communication setup classes.
- Vault validation and JSON schema validation are run against the compiled runtime KB.

## Known Remaining Work

- Part 1 OBIS tables are covered as table-level catalogue seeds, but individual OBIS rows are not yet fully materialized as per-code structured entries.
- 42 Part 2 interface class entries remain catalogue seeds. Their detailed attributes, methods, access semantics, and common instances should be expanded class by class.
- Previous-version interface classes in Blue Book Part 2 Chapter 5 are intentionally not covered by the current-class coverage gate.
- Quality should be measured on additional real DLMS/COSEM documents after each enrichment batch.
