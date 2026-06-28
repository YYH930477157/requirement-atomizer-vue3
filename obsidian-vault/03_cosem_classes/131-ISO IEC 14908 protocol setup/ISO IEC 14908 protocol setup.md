---
id: KB-L3-IC-131-ISO-IEC-14908-PROTOCOL-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 protocol setup
aliases:
- class 131
- CL 131
keywords:
- iso/iec 14908 protocol setup
- class 131
- cl 131
- logical_name
- inactivity_timeout
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 protocol setup

## Definition

COSEM interface class (class_id = 131, version = 0). Allows the configuration of the ISO/IEC 14908 device (IEC 62056-8-8:2020 profile).

## Aliases

- class 131
- CL 131

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the inactivity_timeout: minutes of absence of adaptation layer messages from the NNAP before the LNAP is considered to be out of communication.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 131,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "inactivity_timeout", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x08" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the inactivity_timeout: minutes of absence of adaptation layer messages from the NNAP before the LNAP is considered to be out of communication.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.19.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.19.3.
- 2 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
