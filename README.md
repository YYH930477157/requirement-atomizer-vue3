# Requirement Atomizer

Requirement Atomizer is the current main engineering module in this repository.

It converts technical standard `.docx` documents into structured artifacts that are easier for an LLM-based requirement analysis agent to consume.

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
- `table_items.jsonl`: row-level atomic table records
- `llm_tasks.jsonl`: model-ready extraction/classification tasks
- `manifest.json`: run metadata and counts
- `summary.md`: human-readable run summary

## Quick Start

```powershell
pip install -r .\requirement-atomizer\requirements.txt

python .\requirement-atomizer\atomize.py `
  "E:\Canna-29(1)\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\requirement-atomizer\out\abnt_nbr_16968" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering.json" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering_cosem_classes.json"
```

## Recommended Pipeline

The intended workflow is:

```text
DOCX
-> structural blocks
-> retrieval chunks
-> table row atoms
-> LLM tasks
-> domain-specific atomic requirements
```

For this kind of standard/protocol document, avoid sending the whole file to an LLM at once. Use `chunks.jsonl` for contextual review and `table_items.jsonl` for row-level extraction.

## External Knowledge Bases

The tool supports external knowledge bases through `--kb`. This is the interface a future Windows application can expose as "attach knowledge base".

```powershell
python .\requirement-atomizer\atomize.py `
  "E:\Canna-29(1)\Appendix 9-ABNT NBR 16968-2022 EN.docx" `
  --out ".\requirement-atomizer\out\abnt_nbr_16968" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering.json"
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
python .\requirement-atomizer\kb_query.py info

python .\requirement-atomizer\kb_query.py search "class 8"

python .\requirement-atomizer\kb_query.py get "KB-L3-IC-8-CLOCK"

python .\requirement-atomizer\kb_query.py match "Image Transfer uses image_transfer_status"

python .\requirement-atomizer\kb_query.py context "Association LN object_list shall be readable"
```

All commands print JSON.

### Local HTTP API

Start the local KB service:

```powershell
python .\requirement-atomizer\kb_server.py --host 127.0.0.1 --port 8765
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
python .\requirement-atomizer\obsidian_kb.py export `
  --vault ".\requirement-atomizer\obsidian-vault" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering.json" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering_protocol_layer.json" `
  --kb ".\requirement-atomizer\knowledge_bases\energy_metering_cosem_classes.json"
```

Open `requirement-atomizer/obsidian-vault` in Obsidian and edit the Markdown notes.

Compile the Obsidian vault back to a runtime JSON KB:

```powershell
python .\requirement-atomizer\obsidian_kb.py compile `
  --vault ".\requirement-atomizer\obsidian-vault" `
  --out ".\requirement-atomizer\knowledge_bases\compiled_from_obsidian.json" `
  --kb-id "obsidian_energy_metering"
```

Then use the compiled KB with any existing interface:

```powershell
python .\requirement-atomizer\kb_query.py `
  --kb ".\requirement-atomizer\knowledge_bases\compiled_from_obsidian.json" `
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
python .\requirement-atomizer\extract_terms.py `
  ".\requirement-atomizer\out\abnt_nbr_16968" `
  --out ".\requirement-atomizer\out\abnt_nbr_16968\candidate_terms.json"
```

Review `candidate_terms.json`, then add useful terms to a knowledge base JSON file.

## COSEM Object Instance Extraction

After running the atomizer, extract object instances from the document's COSEM tables:

```powershell
python .\requirement-atomizer\extract_cosem_instances.py `
  ".\requirement-atomizer\out\abnt_nbr_16968" `
  --out ".\requirement-atomizer\out\abnt_nbr_16968\cosem_object_instances.json" `
  --kb-out ".\requirement-atomizer\out\abnt_nbr_16968\document_cosem_object_instances.kb.json"
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
  "domain_tags": ["event"]
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
  "parameters": {},
  "verification_method": "configuration_check",
  "ambiguity": false,
  "review_questions": [],
  "confidence": 0.85
}
```
