---
id: KB-L3-IC-130-ISO-IEC-14908-IDENTIFICATION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 identification
aliases:
- class 130
- CL 130
keywords:
- iso/iec 14908 identification
- class 130
- cl 130
- logical_name
- node_id
- subnet_id
- domain_id
- program_id
- unique_node_id
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 identification

## Definition

COSEM interface class (class_id = 130, version = 0). Allows the identification of the device and the network to which the device is connected (ISO/IEC 14908 series / IEC 62056-8-8:2020 profile).

## Aliases

- class 130
- CL 130

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the node, subnet, domain and program identifiers plus the worldwide-unique Unique_Node_ID assigned to the physical connection module at manufacture.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 130,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "node_ID", "mode": "static", "type": "unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "subnet_ID", "mode": "static", "type": "unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "domain_ID", "mode": "static", "type": "octet-string", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "program_ID", "mode": "static", "type": "octet-string", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "unique_node_ID", "mode": "static", "type": "octet-string", "short_name": "x + 0x28" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the node, subnet, domain and program identifiers plus the worldwide-unique Unique_Node_ID assigned to the physical connection module at manufacture.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.19.2; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.19.2.
- 6 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
