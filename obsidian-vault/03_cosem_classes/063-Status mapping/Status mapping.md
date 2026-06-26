---
id: KB-L3-IC-63-STATUS-MAPPING
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Status mapping
aliases:
- class 63
- CL 63
keywords:
- status mapping
- class 63
- cl 63
- status_word
- mapping_table
- ref_table_id
domain_tags:
- cosem_class
- measurement_data
- status
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Status mapping

## Definition

COSEM interface class (class_id = 63, version = 0) for modelling the mapping of bits in a status word to entries in a reference table. Cardinality 0...n.

## Aliases

- class 63
- CL 63

## Domain Tags

- `cosem_class`
- `measurement_data`
- `status`

## Access Semantics

logical_name and mapping_table are static, read-write (RW) via the SET service by an authorised management client; logical_name is read-only for all clients. status_word is **dynamic** (dyn.) — it reflects the current runtime value of the monitored status word and is read-only (R) for operational clients.

## Behavior Notes

- Status mapping models the mapping of bits in a status word to entries in a reference table. Cardinality 0...n.
- **status_word** (attr 2): dynamic, contains the current value of the status word. CHOICE of bit-string/double-long-unsigned/octet-string/visible-string/utf8-string/unsigned/long-unsigned/long64-unsigned. Size = n*8 bits, max 65536 bits. Always interpreted as a bit-string regardless of chosen type.
- **mapping_table** (attr 3): static structure {ref_table_id: unsigned, ref_table_mapping: CHOICE {long-unsigned | array long-unsigned}}. ref_table_id identifies the reference status table. If long-unsigned choice: value points to the leading entry mapped to the leading bit, subsequent bits map to subsequent entries. If array choice: explicit bit-to-entry mapping.
- **No specific methods**: configuration via SET on mapping_table.

## Structured Data

```json metadata
{
  "class_id": 63,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "static": true, "mandatory": true, "access_rights": "R"},
    {"attribute_id": 2, "name": "status_word", "type": "CHOICE", "dynamic": true, "mandatory": true, "access_rights": "R", "short_name": "0x08"},
    {"attribute_id": 3, "name": "mapping_table", "type": "structure", "static": true, "mandatory": true, "access_rights": "RW", "short_name": "0x10"}
  ],
  "methods": [],
  "access_semantics": [
    "logical_name and mapping_table are static RW via SET by management client; logical_name read-only for all.",
    "status_word is dynamic, read-only (R); reflects current runtime value of the monitored status word.",
    "mapping_table.ref_table_id identifies the reference status table for bit-to-entry mapping."
  ],
  "behavior_notes": [
    "Status mapping models the mapping of bits in a status word to entries in a reference table. Cardinality 0...n.",
    "status_word: dynamic, CHOICE of bit-string/integer/octet-string etc.; size n*8 bits, max 65536 bits; always interpreted as bit-string.",
    "mapping_table: {ref_table_id, ref_table_mapping CHOICE}. long-unsigned = sequential bit-to-entry; array = explicit mapping."
  ],
  "source_refs": [
    {"source": "Blue Book Part 2 Ed. 16", "section": "4.3.9 Status mapping (class_id = 63, version = 0)"}
  ],
  "coverage_level": "rich",
  "coverage_note": "Enriched 2026-06-26 from Blue Book Part 2 Ed.16 section 4.3.9. Full attributes with access_rights (status_word dynamic R, mapping_table static RW), access_semantics, and behavior_notes."
}
```

## Notes

- Source: Blue Book Part 2 Ed.16, section 4.3.9 (page 88-89).
