# Requirement Atomizer

Requirement Atomizer is a local tool for extracting, reviewing, and exporting atomic requirements from technical standards.

It is built for DLMS/COSEM-style documents where requirements are scattered across chapters, protocol descriptions, object definitions, and tables. The current desktop product uses a Vue3 + Electron UI with a Python backend.

## What It Supports

- Inputs: `.docx`, `.xlsx`, and text-layer `.pdf`
- Outputs: structured blocks, table rows, atomic requirement candidates, LLM review results, review states, Markdown/CSV exports, assembled specification files, and engineering requirement summaries
- Knowledge base: reusable `requirement_kb` Python package, with Obsidian as the human-editing source
- Review flow: deterministic extraction first, then optional OpenAI-compatible LLM review and expert review

Scanned PDFs without text are not supported yet. Save them as `.docx` first or handle OCR separately.

## Quick Start

```powershell
pip install -r .\requirements.txt

python -m pytest -q
```

Run the full pipeline:

```powershell
ratomizer run `
  ".\samples\your-standard.docx" `
  --out ".\out\run-001" `
  --kb ".\knowledge_bases\energy_metering.json" `
  --kb ".\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\knowledge_bases\energy_metering_cosem_classes.json" `
  --export md,csv
```

The main output files are written under the selected `out` directory:

```text
blocks.jsonl
table_items.jsonl
atomic_requirements.jsonl
llm_review_results.jsonl
review_states.jsonl
quality_report.json
manifest.json
summary.md
```

Compose developer-facing requirements from an existing output directory:

```powershell
ratomizer compose --out ".\out\run-001"
```

This writes `engineering_requirements/` with two sections:

- `requirement_functions.md`: implementable requirement functions grouped by domain
- `dlms_objects.md`: DLMS/COSEM objects with OBIS, interface class, attributes, access rights, and traceability

## Desktop App

Install and run the Vue3/Electron UI:

```powershell
cd .\ui
npm install
npm run desktop:dev
```

Build the renderer:

```powershell
npm test
npm run build
```

Package the portable Electron app:

```powershell
npm run desktop:pack
```

The Electron package includes the Python source files and runtime assets such as `requirement_kb/`, `parsers/`, `domain_packs/`, `knowledge_bases/`, and `llm_agents/`. Until the backend is bundled as executables, the target machine still needs a compatible Python runtime.

## Knowledge Base

The knowledge base is maintained as an Obsidian vault and compiled to runtime JSON:

```text
obsidian-vault/             # human-maintained Markdown source
knowledge_bases/*.json      # runtime KB files
requirement_kb/             # reusable Python package
```

Compile the vault:

```powershell
python -m requirement_kb.obsidian compile `
  --vault ".\obsidian-vault" `
  --out ".\knowledge_bases\compiled_from_obsidian.json" `
  --kb-id "obsidian_energy_metering"
```

Use the KB package directly:

```powershell
python -m requirement_kb.cli info
python -m requirement_kb.cli search "class 8"
python -m requirement_kb.server --host 127.0.0.1 --port 8765
```

External tools should depend on `requirement_kb` instead of old root-level KB scripts.

## LLM Review

The default route is local stub review, so no external API is called by default.

To enable an OpenAI-compatible service, edit:

```text
llm_agents/review_pipeline.yaml
```

Set:

```yaml
model_routes:
  default: openai_compatible
```

Keep API keys in environment variables only. The config stores the variable name, not the key.

## Useful Commands

```powershell
# Python tests
python -m pytest -q

# Frontend tests and build
cd .\ui
npm test
npm run build

# Validate a runtime KB
python -m requirement_kb.schema ".\knowledge_bases\energy_metering.json"

# Run local review API for an output directory
python .\api_server.py --out ".\out\run-001" --port 8770
```

## Main Directories

```text
atomize.py                  # extraction pipeline
cli.py                      # stable machine-readable CLI
desktop_tasks.py            # Electron task bridge
ui/                         # Vue3 + Electron desktop UI
requirement_kb/             # reusable knowledge-base package
knowledge_bases/            # runtime JSON knowledge bases
obsidian-vault/             # editable KB source
domain_packs/dlms_cosem/    # DLMS/COSEM patterns and policy
llm_agents/                 # review pipeline config
parsers/                    # DOCX/XLSX/PDF parser bridges
tests/                      # backend tests
docs/                       # design notes and detailed contracts
```

## References

- CLI contract: `docs/cli-contract.md`
- Platform design: `docs/requirement-atomizer-platform-overview-design.md`
- KB schema: `schemas/kb_schema.json`
- Atomic requirement schema: `schemas/atomic_requirement.schema.json`
