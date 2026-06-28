---
id: KB-L3-IC-57-ISO-IEC-8802-2-LLC-TYPE-1-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 8802-2 LLC Type 1 setup
aliases:
- class 57
- CL 57
keywords:
- iso/iec 8802-2 llc type 1 setup
- class 57
- cl 57
- logical_name
- max_octets_ui_pdu
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 8802-2 LLC Type 1 setup

## Definition

COSEM interface class (class_id = 57, version = 0). Holds the parameters necessary to set up the ISO/IEC 8802-2 LLC layer in Type 1 operation.

## Aliases

- class 57
- CL 57

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the maximum number of octets in a UI PDU; all MACs shall at least accommodate UI PDU information fields of 128 octets.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 57,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "max_octets_ui_pdu", "mode": "static", "type": "long unsigned", "short_name": "x + 0x08" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the maximum number of octets in a UI PDU; all MACs shall at least accommodate UI PDU information fields of 128 octets.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.11.2; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.11.2.
- 2 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
