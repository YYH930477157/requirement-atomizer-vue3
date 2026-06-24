# Blue Book Knowledge Base Coverage

Date: 2026-06-24

This note tracks the current integration state of the local Blue Book knowledge base. The Obsidian vault remains the editable source, and `knowledge_bases/compiled_from_obsidian.json` is the compiled runtime artifact.

## Source Scope

- Blue Book Part 1: `DLMS UA 1000-1 Ed. 16 Part 1`, OBIS Object Identification System.
- Blue Book Part 2: `DLMS UA 1000-1 Ed. 16 Part 2`, COSEM Interface Classes.

The repository does not store the Blue Book PDFs or copy their full text. It stores structured seed knowledge, definitions, aliases, matching keywords, relations, and class metadata needed by the analyzer.

## Current Coverage

- Part 1 OBIS: standard source entry, OBIS value group structure, A-B:C.D.E.F group semantics, common standard-specific code ranges, links to OBIS logical names, and catalogue coverage for all 73 OBIS tables listed in Part 1.
- Part 2 COSEM Interface Classes: current interface class catalogue coverage for all 87 current `class_id` entries extracted from Chapter 4 of Blue Book Part 2.
- Part 2 high-value operational semantics: the primary engineering classes now carry source references plus structured attributes, methods, and behavior notes for Data, Register, Extended Register, Demand Register, Profile Generic, Association LN, Image Transfer, Push Setup, IPv6 Setup, Register Table, Compact Data, Security Setup, Disconnect Control, and Limiter.
- Runtime loading: `compiled_from_obsidian.json` is now included in the default `requirement_kb` paths and in the Vue/Electron ABNT run preset.
- Corrected seed facts: `TCP-UDP Setup` is class 41 and `IPv4 Setup` is class 42; `Schedule` is class 10 and `Single Action Schedule` is class 22.

## Verification Gates

- `tests/test_blue_book_kb.py` asserts that the compiled Obsidian KB contains Blue Book Part 1/Part 2 entries.
- The same test asserts runtime matching for OBIS value groups and representative COSEM classes.
- The same test asserts 73/73 Part 1 OBIS table catalogue coverage by table number and title.
- The same test asserts 87/87 current Part 2 interface class catalogue coverage by `class_id` and version.
- The same test asserts that high-value COSEM classes are traceable to Blue Book sections and contain actionable operational semantics, including Push Setup v3 attributes, Demand Register `next_period`, Association LN user methods, Compact Data `compact_buffer`, Register Table `capture`, and Disconnect Control states.
- Vault validation and JSON schema validation are run against the compiled runtime KB.

## Known Remaining Work

- Part 1 OBIS tables are covered as table-level catalogue seeds, but individual OBIS rows are not yet fully materialized as per-code structured entries.
- Most generated Part 2 interface class entries are catalogue seeds. Their detailed attributes, methods, access semantics, and common instances should be expanded class by class.
- Previous-version interface classes in Blue Book Part 2 Chapter 5 are intentionally not covered by the current-class coverage gate.
- Quality should be measured on additional real DLMS/COSEM documents after each enrichment batch.
