# Engineering Requirement Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-atomization composer that turns atomic requirements into two developer-facing outputs: requirement functions and DLMS objects.

**Architecture:** Keep the existing atomizer, review, and knowledge base layers unchanged. Add a focused `engineering_composer.py` module that reads existing JSONL artifacts and writes an `engineering_requirements/` folder under the output directory. The composer is deterministic first, with traceability to atomic requirement IDs and source references preserved.

**Tech Stack:** Python stdlib JSON/Path, existing JSONL artifacts, `unittest`, existing CLI envelope pattern.

---

### Task 1: Composer Model And Deterministic Grouping

**Files:**
- Create: `engineering_composer.py`
- Test: `tests/test_engineering_composer.py`

- [ ] Write tests for function grouping, DLMS object grouping, and traceability.
- [ ] Run `python -m unittest tests.test_engineering_composer -v` and verify it fails because `engineering_composer` does not exist.
- [ ] Implement `compose_engineering_requirements(out_dir)` and `write_engineering_requirements(out_dir, model)`.
- [ ] Run `python -m unittest tests.test_engineering_composer -v` and verify it passes.

### Task 2: Human-Readable Markdown Output

**Files:**
- Modify: `engineering_composer.py`
- Test: `tests/test_engineering_composer.py`

- [ ] Add test assertions for `requirement_functions.md` and `dlms_objects.md`.
- [ ] Run the composer tests and verify the Markdown assertions fail.
- [ ] Implement compact Markdown renderers for the two sections.
- [ ] Run the composer tests and verify they pass.

### Task 3: CLI Entry Point

**Files:**
- Modify: `cli.py`
- Test: `tests/test_engineering_composer.py` or a new CLI-focused test if existing CLI helpers are convenient.

- [ ] Add a test for `ratomizer compose --out <dir>` returning the standard JSON envelope and written file list.
- [ ] Run the test and verify it fails because the command is not implemented.
- [ ] Add `compose` subcommand and route it to the composer.
- [ ] Run the new test and the existing CLI contract tests.

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/cli-contract.md`

- [ ] Document the new composer outputs and CLI command.
- [ ] Keep docs concise and focused on developer-facing requirement output.

### Task 5: Verification

**Files:**
- No code changes unless failures require fixes.

- [ ] Run `python -m unittest tests.test_engineering_composer tests.test_assemble_spec tests.test_spec_export tests.test_requirement_schema`.
- [ ] Run full Python tests if targeted verification is clean.
- [ ] Inspect `git diff --check`.
