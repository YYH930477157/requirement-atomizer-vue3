---
id: KB-L3-IC-53-S-FSK-MAC-COUNTERS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: S-FSK MAC counters
aliases:
- class 53
- CL 53
keywords:
- s-fsk mac counters
- class 53
- cl 53
- logical_name
- synchronization_register
- desynchronization_listing
- broadcast_frames_counter
- repetitions_counter
- transmissions_counter
- crc_ok_frames_counter
- crc_nok_frames_counter
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# S-FSK MAC counters

## Definition

COSEM interface class (class_id = 53, version = 0). Stores counters related to the S-FSK frame exchange, transmission and repetition phases.

## Aliases

- class 53
- CL 53

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds synchronization and desynchronization statistics plus per-cause counters for broadcast frames, repetitions, transmissions and CRC-OK/CRC-NOK frames; all counters wrap to 0 at the maximum value.
- The reset method clears all counters.
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 53,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "synchronization_register", "mode": "dynamic", "type": "array", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "desynchronization_listing", "mode": "dynamic", "type": "structure", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "broadcast_frames_counter", "mode": "dynamic", "type": "array", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "repetitions_counter", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "transmissions_counter", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "CRC_OK_frames_counter", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "CRC_NOK_frames_counter", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x38" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "x + 0x50" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds synchronization and desynchronization statistics plus per-cause counters for broadcast frames, repetitions, transmissions and CRC-OK/CRC-NOK frames; all counters wrap to 0 at the maximum value.",
    "The reset method clears all counters.",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.10.6; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.10.6.
- 8 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
