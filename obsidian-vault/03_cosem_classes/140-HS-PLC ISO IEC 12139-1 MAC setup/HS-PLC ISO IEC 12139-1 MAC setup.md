---
id: KB-L3-IC-140-HS-PLC-ISO-IEC-12139-1-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: HS-PLC ISO/IEC 12139-1 MAC setup
aliases:
- class 140
- CL 140
keywords:
- hs-plc iso/iec 12139-1 mac setup
- class 140
- cl 140
- logical_name
- group_id
- secondary_group_id
- station_id
- parent_station_id
- repeater_status
- encryption_mode
- initial_encryption_key
- rts/cts
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# HS-PLC ISO/IEC 12139-1 MAC setup

## Definition

COSEM interface class (class_id = 140, version = 0). Holds the parameters necessary to set up and manage the MAC layer of the HS-PLC ISO/IEC 12139-1 profile.

## Aliases

- class 140
- CL 140

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the HS-PLC ISO/IEC 12139-1 MAC parameters (group/station identifiers, repeater status, encryption mode and initial key, and the RTS/CTS collision-avoidance flag).
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 140,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "group_id", "mode": "static", "type": "long64-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "secondary_group_id", "mode": "static", "type": "long64-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "station_id", "mode": "static", "type": "long64-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "parent_station_id", "mode": "static", "type": "long64-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "repeater_status", "mode": "static", "type": "boolean", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "encryption_mode", "mode": "static", "type": "enum", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "initial_encryption_key", "mode": "static", "type": "octet-string", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "rts/cts", "mode": "static", "type": "boolean", "short_name": "x + 0x40" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the HS-PLC ISO/IEC 12139-1 MAC parameters (group/station identifiers, repeater status, encryption mode and initial key, and the RTS/CTS collision-avoidance flag).",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.14.2; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.14.2.
- 9 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
