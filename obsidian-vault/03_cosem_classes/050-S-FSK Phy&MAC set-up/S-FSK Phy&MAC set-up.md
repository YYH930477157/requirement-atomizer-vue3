---
id: KB-L3-IC-50-S-FSK-PHY-MAC-SET-UP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: S-FSK Phy&MAC set-up
aliases:
- class 50
- CL 50
keywords:
- s-fsk phy&mac set-up
- class 50
- cl 50
- logical_name
- initiator_electrical_phase
- delta_electrical_phase
- max_receiving_gain
- max_transmitting_gain
- search_initiator_threshold
- frequencies
- mac_address
- mac_group_addresses
- repeater
- repeater_status
- min_delta_credit
- initiator_mac_address
- synchronization_locked
- transmission_speed
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# S-FSK Phy&MAC set-up

## Definition

COSEM interface class (class_id = 50, version = 1). Stores the data necessary to set up and manage the physical and the MAC layer of the PLC S-FSK lower layer profile. (The use of version 0 of this interface class is deprecated.)

## Aliases

- class 50
- CL 50

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- An instance stores the data necessary to set up and manage the physical and the MAC layer of the PLC S-FSK lower layer profile (physical-layer management and MAC-layer management variables).
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 50,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "initiator_electrical_phase", "mode": "static", "type": "enum", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "delta_electrical_phase", "mode": "dynamic", "type": "enum", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "max_receiving_gain", "mode": "static", "type": "unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "max_transmitting_gain", "mode": "static", "type": "unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "search_initiator_threshold", "mode": "static", "type": "unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "frequencies", "mode": "static", "type": "frequencies_type", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "mac_address", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "mac_group_addresses", "mode": "static", "type": "array", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "repeater", "mode": "static", "type": "enum", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "repeater_status", "mode": "dynamic", "type": "boolean", "short_name": "x + 0x50" },
    { "attribute_id": 12, "name": "min_delta_credit", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x58" },
    { "attribute_id": 13, "name": "initiator_mac_address", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x60" },
    { "attribute_id": 14, "name": "synchronization_locked", "mode": "dynamic", "type": "boolean", "short_name": "x + 0x68" },
    { "attribute_id": 15, "name": "transmission_speed", "mode": "static", "type": "enum", "short_name": "x + 0x70" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "An instance stores the data necessary to set up and manage the physical and the MAC layer of the PLC S-FSK lower layer profile (physical-layer management and MAC-layer management variables).",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.10.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.10.3.
- 15 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
