---
id: KB-L3-IC-52-S-FSK-MAC-SYNCHRONIZATION-TIMEOUTS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: S-FSK MAC synchronization timeouts
aliases:
- class 52
- CL 52
keywords:
- s-fsk mac synchronization timeouts
- class 52
- cl 52
- logical_name
- search_initiator_timeout
- synchronization_confirmation_timeout
- time_out_not_addressed
- time_out_frame_not_ok
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# S-FSK MAC synchronization timeouts

## Definition

COSEM interface class (class_id = 52, version = 0). Stores the timeouts related to the S-FSK MAC synchronization process.

## Aliases

- class 52
- CL 52

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the four timeouts of the synchronization process: search-initiator, synchronization-confirmation, time-out-not-addressed and time-out-frame-not-OK. A value of 0 cancels the use of the related counter.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 52,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "search_initiator_timeout", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "synchronization_confirmation_timeout", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "time_out_not_addressed", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "time_out_frame_not_OK", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x20" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the four timeouts of the synchronization process: search-initiator, synchronization-confirmation, time-out-not-addressed and time-out-frame-not-OK. A value of 0 cancels the use of the related counter.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.10.5; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.10.5.
- 5 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
