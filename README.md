# Requirement Atomizer

Requirement Atomizer is the current main engineering module in this repository.

It converts technical standard `.docx`, `.xlsx`, and text-layer `.pdf` documents into structured artifacts that are easier for an LLM-based requirement analysis agent to consume.

It is designed for documents like `ABNT NBR 16968:2022`, where requirements are spread across chapters, protocol descriptions, object definitions, and many tables.

For long-term knowledge maintenance, the recommended source of truth is:

```text
obsidian-vault/
```

The runtime JSON knowledge base is compiled from that vault:

```text
knowledge_bases/compiled_from_obsidian.json
```

## What It Produces

Running the tool creates:

- `blocks.jsonl`: ordered document blocks, including headings, paragraphs, and tables
- `chunks.jsonl`: retrieval chunks for RAG or LLM review
- `table_items.jsonl`: row-level table records, including merged multi-row headers and matrix facts
- `atomic_requirements.jsonl`: rule-based atomic requirement candidates for review
- `llm_tasks.jsonl`: model-ready extraction/classification tasks
- `quality_report.json`: coverage, confidence, ambiguity, and type-distribution report
- `manifest.json`: run metadata and counts
- `summary.md`: human-readable run summary

Supported input formats are `.docx`, `.xlsx`, and PDFs with an extractable text layer. Legacy `.xls` files must be saved as `.xlsx` before running the pipeline. Scanned PDFs without text are rejected; open the PDF in Word and save it as `.docx`, or wait for the OCR milestone.

## Quick Start

```powershell
pip install -r .\requirements.txt

ratomizer run `
  "E:\Canna-29(1)\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\out\abnt_nbr_16968" `
  --kb ".\knowledge_bases\energy_metering.json" `
  --kb ".\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\knowledge_bases\energy_metering_cosem_classes.json" `
  --export md,csv

python .\atomize.py `
  "E:\Canna-29(1)\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\out\abnt_nbr_16968" `
  --kb ".\knowledge_bases\energy_metering.json" `
  --kb ".\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\knowledge_bases\energy_metering_cosem_classes.json"

python -m unittest discover -s tests
```

`ratomizer` is the stable machine-readable CLI for external task managers. It writes one JSON envelope to stdout and sends logs to stderr. See `docs/cli-contract.md` for the command contract, exit codes, and export file rules.

## GUI Workbench

Install the optional GUI dependencies and start the local review workbench:

```powershell
pip install -e ".[gui]"
ratomizer-gui
```

The GUI reads and writes the same output directory files as the CLI, including `atomic_requirements.jsonl`, `llm_review_results.jsonl`, `review_states.jsonl`, and exported Markdown/CSV files.

The GUI uses the configured review pipeline. To enable real LLM review from the GUI, edit `llm_agents/review_pipeline.yaml` and set `model_routes.default` to `openai_compatible`; keep the API key in the environment variable named by `api_key_env`.

## Recommended Pipeline

The intended workflow is:

```text
DOCX, XLSX, or text-layer PDF
-> structural blocks
-> retrieval chunks
-> enhanced table row atoms
-> rule-based atomic candidates
-> LLM review and enrichment tasks
-> domain-specific atomic requirements
```

For this kind of standard/protocol document, avoid sending the whole file to an LLM at once. Use `atomic_requirements.jsonl` as the first reviewable requirement draft, `chunks.jsonl` for contextual review, and `table_items.jsonl` for row-level traceability.

The atomizer now separates two layers:

- deterministic parsing: document blocks, enhanced tables, KB matches, and rule-based candidate requirements
- model review: use `llm_tasks.jsonl` to correct, merge, split, and enrich those candidates

This is useful for DLMS/COSEM documents because many requirements are hidden in tables. For example, an `X` in an xDLMS service matrix is converted into a `matrix_facts` entry and then into a `capability_matrix` candidate requirement.

## External Knowledge Bases

The tool supports external knowledge bases through `--kb`. This is the interface a future Windows application can expose as "attach knowledge base".

```powershell
python .\atomize.py `
  "E:\Canna-29(1)\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\out\abnt_nbr_16968" `
  --kb ".\knowledge_bases\energy_metering.json"
```

You can pass `--kb` multiple times. Each knowledge base is a JSON file with this shape:

```json
{
  "kb_id": "energy_metering",
  "name": "Energy Metering Domain Knowledge Base",
  "version": "0.1.0",
  "entries": [
    {
      "id": "KB-PROTO-DLMS",
      "type": "protocol",
      "layer": "term",
      "name": "DLMS",
      "aliases": ["Device Language Message Specification", "xDLMS"],
      "keywords": ["dlms", "xdlms"],
      "domain_tags": ["dlms_cosem", "communication_protocol"],
      "definition": "Protocol suite used for utility meter data exchange.",
      "relations": [],
      "components": []
    }
  ]
}
```

When a KB is attached, `blocks.jsonl`, `chunks.jsonl`, `table_items.jsonl`, and `llm_tasks.jsonl` include:

```json
{
  "kb_matches": [
    {
      "kb_id": "energy_metering",
      "entry_id": "KB-PROTO-DLMS",
      "type": "protocol",
      "layer": "term",
      "name": "DLMS",
      "matched_terms": ["dlms", "xdlms"],
      "domain_tags": ["dlms_cosem", "communication_protocol"],
      "definition": "Protocol suite used for utility meter data exchange.",
      "relations": [],
      "metadata": {}
    }
  ]
}
```

## Knowledge Base Architecture

The KB is stored as portable JSON files and exposed through a common query interface.

```text
JSON KB files
-> kb_api.py repository
-> CLI / Python API / local HTTP API
-> Windows app, document agent, test agent, or other tools
```

This keeps the storage simple and portable while still giving external tools a stable contract.

## Domain Pack Direction

The project now includes the first seed domain pack:

```text
domain_packs/dlms_cosem/
```

This is the migration target for turning hard-coded DLMS/COSEM behavior into declarative configuration. The current files are intentionally small and conservative:

- `pack.yaml`: domain pack manifest, capability list, KB paths, review policy, and golden set reference
- `requirement_patterns.yaml`: seed requirement pattern DSL entries
- `table_patterns.yaml`: seed table pattern registry for the current table semantics
- `kb_sources.yaml`: KB source declarations

The current `atomize.py` behavior remains the source of truth for runtime output. The domain pack files provide the P0 bridge toward a generic quantization core without regressing the existing DLMS/COSEM output.

## Golden Regression

The current ABNT NBR 16968 output is frozen as a golden baseline:

```text
golden_sets/abnt_nbr_16968_v5/golden_summary.json
```

The golden regression tests verify that future refactors keep the current baseline stable:

```powershell
python -m unittest tests.test_golden_regression
```

The baseline checks:

- manifest counts
- requirement type distribution
- source type distribution
- quality coverage
- representative high-value requirements

## Platform Layer

The project now has an additive platform layer around the current parser. The existing `atomize.py` output remains stable, while the new modules provide interfaces for a generic requirement-analysis agent.

### P1-1 Document IR

`doc_ir.py` defines a normalized intermediate representation:

```text
DocumentIR
-> BlockIR
-> TableIR
-> Provenance
```

The first parser bridge is:

```text
parsers/docx_parser.py
```

Export a DOCX into DocumentIR JSON:

```powershell
python .\doc_ir_export.py `
  "E:\Canna-29(1)\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\out\abnt_nbr_16968_atomizer_v5\document_ir.json"
```

This is the migration target for future PDF, Excel, Markdown, or HTML parsers. The agent should consume DocIR rather than binding directly to DOCX-specific parsing details.

### P1-2 Table Pattern Engine

Declarative table patterns live in:

```text
domain_packs/dlms_cosem/table_patterns.yaml
```

The runtime matcher is:

```text
table_pattern_engine.py
```

Current seed patterns cover:

- xDLMS service marker matrices
- association/security value matrices
- inherited COSEM object/attribute tables
- compact RC/PC/SC/LC access-right codes
- event definition tables
- measurement quantity/unit tables
- security suite tables
- security policy bit/state tables
- event retention tables
- flag/status/code definition tables

This lets the project gradually move table interpretation from hard-coded Python into domain-pack configuration.

### P1-3 KB Schema

The portable KB contract is documented in:

```text
schemas/kb_schema.json
kb_schema.py
```

Validate a knowledge base before attaching it:

```powershell
python .\kb_schema.py `
  ".\knowledge_bases\energy_metering_cosem_classes.json"
```

Use strict mode when preparing a polished external KB:

```powershell
python .\kb_schema.py `
  ".\knowledge_bases\compiled_from_obsidian.json" `
  --strict
```

The validator treats `id`, `type`, `name`, and `definition` as required entry fields. `layer` is recommended and will be inferred from the KB-level layer or `term` by the runtime if omitted, preserving compatibility with the earlier seed KB.

## Review Agent Layer

The review layer is the bridge from deterministic extraction to AI/expert collaboration.

### P2-1 LLM Agent Pipeline

Pipeline configuration:

```text
llm_agents/review_pipeline.yaml
llm_pipeline.py
schemas/llm_review_result.schema.json
schemas/test_point.schema.json
```

Run the current local rule/stub review pipeline over atomizer output:

```powershell
python .\llm_pipeline.py `
  --out ".\out\abnt_nbr_16968_atomizer_v5"
```

By default, the review route is still `stub`, so the pipeline does not call any external service. To use an OpenAI-compatible local model such as Ollama:

```yaml
model_routes:
  default: "openai_compatible"
  openai_compatible:
    base_url: "http://127.0.0.1:11434/v1"
    model: "qwen2.5:14b"
    api_key_env: "RATOMIZER_LLM_API_KEY"
    temperature: 0.0
    concurrency: 4
    connection_failure_abort: 10
```

For Zhipu GLM cloud, keep the API key in the environment and change only the endpoint and model:

```powershell
$env:RATOMIZER_LLM_API_KEY = "<your-api-key>"
```

```yaml
model_routes:
  default: "openai_compatible"
  openai_compatible:
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    model: "glm-4-flash"
    api_key_env: "RATOMIZER_LLM_API_KEY"
    temperature: 0.0
    concurrency: 4
    connection_failure_abort: 10
```

You can override the configured route for one run:

```powershell
ratomizer review `
  --out ".\out\abnt_nbr_16968_atomizer_v5" `
  --llm-route openai_compatible `
  --review-scope targeted
```

`targeted` scope sends ambiguous, low-confidence, mandatory-review, and selected source candidates to the LLM. Non-targeted candidates keep the local stub result. LLM review results are cached in `llm_review_cache.jsonl` by stable requirement id, model, and prompt version.

It writes:

```text
llm_review_results.jsonl
review_states.jsonl
llm_review_cache.jsonl
```

The current pipeline has operations for risk classification, correction, duplicate merging, gap finding, and test-point generation. The OpenAI-compatible route writes the same review and state files as the stub route, so downstream CLI export and GUI review flows do not change.

### P2-2 Expert Review State Machine

Expert review state logic is in:

```text
review_state.py
```

Current statuses:

```text
candidate
llm_reviewed
expert_pending
needs_discussion
needs_rework
flagged
accepted
rejected
frozen
```

High-risk or low-confidence requirements are routed to `expert_pending`; low-risk requirements are routed to `accepted`. The state history keeps actor, reason, and timestamp for audit.

### P2-3 API, UI, And Windows App Shell

Local API:

```powershell
python .\api_server.py `
  --out ".\out\abnt_nbr_16968_atomizer_v5" `
  --port 8770
```

Endpoints:

```text
GET /health
GET /manifest
GET /quality
GET /requirements?limit=100&type=cosem_attribute_access
GET /reviews?limit=100
GET /review-states?status=expert_pending
GET /review-summary
```

Static review UI:

```text
ui/index.html
```

Windows starter script:

```powershell
.\desktop\start-review-app.ps1 -RunReview
```

This runs the local review pipeline, starts the API in the background, and opens the review UI. It is intentionally simple so it can later be wrapped by Electron, Tauri, PyInstaller, or another Windows packaging layer.

### Storage Model

Each KB file has:

```json
{
  "kb_id": "energy_metering_cosem_classes",
  "name": "COSEM Interface Classes Seed Knowledge Base",
  "version": "0.1.0",
  "layer": "cosem_class_attribute_method",
  "entries": []
}
```

Each entry has the common fields:

```json
{
  "id": "KB-L3-IC-8-CLOCK",
  "type": "cosem_interface_class",
  "layer": "cosem_class",
  "name": "Clock",
  "aliases": ["COSEM Clock", "class 8", "CL 8"],
  "keywords": ["class 8", "clock", "time_zone"],
  "domain_tags": ["cosem_class", "clock"],
  "definition": "COSEM interface class for date, time, timezone, daylight saving, and clock status.",
  "relations": [],
  "class_id": 8,
  "attributes": [],
  "methods": []
}
```

Fields outside the common set are preserved as `metadata` by the interface. This is how class definitions, attributes, methods, OBIS examples, security suites, and rules stay available without changing the API schema every time.

### Python API

```python
from pathlib import Path
from kb_api import KnowledgeRepository

repo = KnowledgeRepository.from_paths([
    Path("knowledge_bases/energy_metering.json"),
    Path("knowledge_bases/energy_metering_protocol_layer.json"),
    Path("knowledge_bases/energy_metering_cosem_classes.json"),
])

print(repo.search("class 8"))
print(repo.get("KB-L3-IC-8-CLOCK"))
print(repo.match_text("The meter shall expose Clock 0-0:1.0.0.255"))
print(repo.export_context("Image Transfer shall support image_activate"))
```

### CLI API

```powershell
python .\kb_query.py info

python .\kb_query.py search "class 8"

python .\kb_query.py get "KB-L3-IC-8-CLOCK"

python .\kb_query.py match "Image Transfer uses image_transfer_status"

python .\kb_query.py context "Association LN object_list shall be readable"
```

All commands print JSON.

### Local HTTP API

Start the local KB service:

```powershell
python .\kb_server.py --host 127.0.0.1 --port 8765
```

Endpoints:

```text
GET  /health
GET  /info
GET  /search?q=class%208&limit=5
GET  /get?entry_id=KB-L3-IC-8-CLOCK
POST /match   {"text": "Image Transfer uses image_transfer_status", "limit": 5}
POST /context {"text": "Association LN object_list shall be readable", "limit": 5}
```

This is the recommended interface for external agents that do not run inside the same Python process.

## Obsidian-As-Source Workflow

The recommended long-term workflow is:

```text
Obsidian Markdown vault
-> compiled JSON KB
-> kb_api.py / kb_server.py
-> Windows app and agents
```

Export the current JSON KBs to an Obsidian vault:

```powershell
python .\obsidian_kb.py export `
  --vault ".\obsidian-vault" `
  --kb ".\knowledge_bases\energy_metering.json" `
  --kb ".\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\knowledge_bases\energy_metering_cosem_classes.json"
```

Open `obsidian-vault` in Obsidian and edit the Markdown notes.

Compile the Obsidian vault back to a runtime JSON KB:

```powershell
python .\obsidian_kb.py compile `
  --vault ".\obsidian-vault" `
  --out ".\knowledge_bases\compiled_from_obsidian.json" `
  --kb-id "obsidian_energy_metering"
```

Then use the compiled KB with any existing interface:

```powershell
python .\kb_query.py `
  --kb ".\knowledge_bases\compiled_from_obsidian.json" `
  search "class 8"
```

In this mode, Obsidian is the human-maintained source of truth. JSON is the compiled runtime format for agents.

The bundled knowledge bases are:

```text
knowledge_bases/energy_metering.json
knowledge_bases/energy_metering_protocol_layer.json
knowledge_bases/energy_metering_cosem_classes.json
```

`energy_metering.json` is the first layer. It covers terminology such as DLMS, COSEM, OBIS, IEC 62056, ABNT NBR 14519/14522, RTM 587/2012, HDLC, PLC-PRIME, Wi-SUN, LoRaWAN, SAP, logical device, association, HLS, LLS, AES-GCM, ECDSA, ECDH, smart meter, load profile, billing profile, event, alarm, error, QEE, firmware update, and disconnect control.

`energy_metering_protocol_layer.json` is the second layer. It adds structured protocol and object-model knowledge, including:

- DLMS/COSEM smart meter profile components and relations
- client roles: public, remote management, local management, read client
- SAP values and typical security levels
- xDLMS service set: GET, SET, ACTION, selective access, EventNotification, DataNotification
- association matrix for logical devices and security levels
- COSEM access-right model for RC/PC/SC/LC columns
- DLMS/COSEM security suites and security policy maps
- communication profile set: HDLC, PLC-PRIME, RF-Wi-SUN, RF-LoRaWAN
- OBIS logical name structure and examples
- COSEM object model fields
- key COSEM objects: SAP Assignment, Association LN, COSEM Logical Device Name, Device ID 1, Image Transfer, Disconnect Control Scheduler
- data profile groups: billing profile, load profile, power quality profile
- event group/subgroup model

`energy_metering_cosem_classes.json` is the third layer. It adds COSEM interface class, attribute, method, and common instance definitions, including:

- class 1 Data
- class 3 Register
- class 4 Extended Register
- class 5 Demand Register
- class 6 Register Activation
- class 7 Profile Generic
- class 8 Clock
- class 9 Script Table
- class 11 Special Days Table
- class 15 Association LN
- class 17 SAP Assignment
- class 18 Image Transfer
- class 20 Activity Calendar
- class 22 Schedule
- class 23 IEC HDLC Setup
- class 64 Security Setup
- class 70 Disconnect Control
- class 122 TCP-UDP Setup
- class 128 IPv4 Setup

The third layer is still a seed library, not a complete replacement for the official DLMS UA Blue Book / Green Book. It is intended to help the agent recognize classes, attributes, and methods in customer documents.

## Candidate Term Extraction

After running the atomizer, extract candidate industry terms for KB expansion:

```powershell
python .\extract_terms.py `
  ".\out\abnt_nbr_16968" `
  --out ".\out\abnt_nbr_16968\candidate_terms.json"
```

Review `candidate_terms.json`, then add useful terms to a knowledge base JSON file.

## COSEM Object Instance Extraction

After running the atomizer, extract object instances from the document's COSEM tables:

```powershell
python .\extract_cosem_instances.py `
  ".\out\abnt_nbr_16968" `
  --out ".\out\abnt_nbr_16968\cosem_object_instances.json" `
  --kb-out ".\out\abnt_nbr_16968\document_cosem_object_instances.kb.json"
```

This produces:

- `cosem_object_instances.json`: extracted instances for review
- `document_cosem_object_instances.kb.json`: optional generated KB that can be attached with `--kb` after review

Each instance has:

```json
{
  "name": "Image Transfer",
  "class_id": 18,
  "obis": "0-0:44.0.0.255",
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "access_rights": "--/--/R-/R-"
    }
  ]
}
```

## Core Fields

### Block

```json
{
  "block_id": "BLK-000123",
  "order": 123,
  "type": "paragraph",
  "style": "Body Text",
  "text": "The smart electricity meter acts as a DLMS/COSEM server...",
  "section_path": ["Scope"],
  "domain_tags": ["dlms_cosem", "meter_function"],
  "kb_matches": []
}
```

### Table Item

```json
{
  "item_id": "TBL-000007-R000003",
  "type": "table_row",
  "table_id": "TBL-000007",
  "table_title": "Table 7 - Events",
  "row_index": 3,
  "fields": {
    "Group number": "1",
    "Subgroup number": "10",
    "Number of event": "1",
    "Description of the event": "Reboot with data loss"
  },
  "matrix_facts": [],
  "domain_tags": ["event"]
}
```

For matrix tables, `matrix_facts` preserves the meaning of positive markers such as `X`:

```json
{
  "subject": "Public customer",
  "predicate_header": "xDLMS Service / GET",
  "marker": "X",
  "relation": "allowed"
}
```

For COSEM object tables, attribute rows also keep their parent object context:

```json
{
  "fields": {
    "#": "1",
    "Object/attribute name": "logical_name",
    "Access rights RC/PC/SC/LC": "R-/R-/R-/R-"
  },
  "cosem_object_context": {
    "object_name": "SAP Assignment",
    "class_id": 17,
    "obis": "0-0:41.0.0.255"
  }
}
```

### Atomic Requirement Candidate

```json
{
  "req_id": "AREQ-000043",
  "source_type": "table_matrix_fact",
  "source_refs": ["BLK-000219", "TBL-000001-R000003"],
  "domain": "association",
  "object": "Public customer",
  "requirement_type": "capability_matrix",
  "requirement": "Public customer shall support xDLMS Service: GET.",
  "verification_method": "configuration_check",
  "confidence": 0.82,
  "generated_by": "rule_based_atomizer_v1"
}
```

These candidates are intentionally conservative. They are meant to give the agent a structured draft, not to replace expert/model review.

COSEM attribute candidates include the parent object and parsed RC/PC/SC/LC rights:

```json
{
  "object": "SAP Assignment.logical_name",
  "requirement_type": "cosem_attribute_access",
  "requirement": "COSEM attribute SAP Assignment.logical_name for SAP Assignment / CL 17 / OBIS 0-0:41.0.0.255 shall use access rights R-/R-/R-/R-.",
  "parameters": {
    "access_rights_by_client": {
      "clients": [
        {"client": "RC", "code": "R-", "read": true, "write": false, "allowed": true},
        {"client": "PC", "code": "R-", "read": true, "write": false, "allowed": true},
        {"client": "SC", "code": "R-", "read": true, "write": false, "allowed": true},
        {"client": "LC", "code": "R-", "read": true, "write": false, "allowed": true}
      ]
    }
  }
}
```

COSEM object header rows are also converted into object-instance candidates:

```json
{
  "object": "Association LN",
  "requirement_type": "cosem_object_instance",
  "requirement": "COSEM object Association LN / CL 15 / OBIS 0-0:40.0.0.255 shall be defined by the profile."
}
```

Event tables are converted into event-definition candidates:

```json
{
  "object": "Event G1-SG10-E1",
  "requirement_type": "event_definition",
  "requirement": "Event G1-SG10-E1 shall be defined as: Reboot with data loss.",
  "parameters": {
    "group_number": "1",
    "subgroup_number": "10",
    "event_number": 1
  }
}
```

Additional table patterns are converted into candidates where possible:

- `association_security_matrix`: association/security matrix cells such as HLS, LLS, or without security
- `security_suite_definition`: DLMS/COSEM security suite rows
- `security_policy_bit`: security policy bit definitions
- `security_policy_state`: security policy state definitions
- `event_group_retention`: group/subgroup minimum record requirements
- `measurement_quantity_unit`: measurement quantity and unit rows
- `flag_definition`: profile status, flag, or code definition rows

The quality report summarizes rule coverage and review queues:

```json
{
  "counts": {
    "atomic_requirements": 2337,
    "ambiguous_atomic_requirements": 6,
    "low_confidence_atomic_requirements": 83
  },
  "coverage": {
    "body_table_candidate_ratio": 0.9928,
    "domain_table_candidate_ratio": 0.9966
  }
}
```

### LLM Task

```json
{
  "task_id": "TASK-000001",
  "task_type": "extract_atomic_requirements",
  "source_type": "chunk",
  "source_id": "CH-000001",
  "domain_tags": ["security_policy"],
  "instruction": "Extract atomic requirements from this source..."
}
```

## Output Schema For The Next LLM Step

Use the following schema when converting each task to atomic requirements:

```json
{
  "req_id": "REQ-SEC-0001",
  "source_id": "CH-000001",
  "source_refs": ["BLK-000120"],
  "domain": "security_policy",
  "object": "Security Policy",
  "requirement_type": "security_requirement",
  "requirement": "Remote management associations shall use High Level Security.",
  "condition": "When a remote management client accesses a metering logical device",
  "source_context": {
    "paragraph_text": "When a remote management client accesses a metering logical device. Remote management associations shall use High Level Security.",
    "prev_sentence": "When a remote management client accesses a metering logical device."
  },
  "parameters": {},
  "verification_method": "configuration_check",
  "ambiguity": false,
  "review_questions": [],
  "confidence": 0.85
}
```

## Windows Packaging

Install packaging dependencies and build the onedir distribution:

```powershell
pip install -e ".[gui,package]"
.\packaging\build.ps1
```

The build writes `dist\RequirementAtomizer\` with two entry points:

```text
ratomizer.exe              # console CLI for task systems
RequirementAtomizer.exe    # GUI workbench for reviewers
llm_agents\review_pipeline.yaml
domain_packs\
knowledge_bases\
schemas\
gui\theme.qss.template
```

This project intentionally uses PyInstaller onedir packaging, not onefile. The startup is faster, and `dist\RequirementAtomizer\llm_agents\review_pipeline.yaml` remains editable after distribution. To switch a packaged copy between Ollama, vLLM, or GLM, edit `base_url`, `model`, and `model_routes.default` in that file and set the environment variable named by `api_key_env`.
