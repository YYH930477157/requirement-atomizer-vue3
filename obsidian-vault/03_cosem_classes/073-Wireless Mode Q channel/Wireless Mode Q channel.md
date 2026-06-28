---
id: KB-L3-IC-73-WIRELESS-MODE-Q-CHANNEL
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Wireless Mode Q channel
aliases:
- class 73
- CL 73
keywords:
- wireless mode q channel
- class 73
- cl 73
- logical_name
- addr_state
- device_address
- address_mask
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Wireless Mode Q channel

## Definition

COSEM interface class (class_id = 73, version = 1). Defines the operational parameters for communication using the wireless Mode Q interfaces. See also EN 13757-5:2015.

## Aliases

- class 73
- CL 73

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the address state (whether an address has been assigned since last power up), the currently assigned device address and the group address (address mask) the device responds to when short form addressing is used.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 73,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "addr_state", "mode": "static", "type": "enum", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "device_address", "mode": "static", "type": "octet-string", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "address_mask", "mode": "static", "type": "octet-string", "short_name": "x + 0x18" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the address state (whether an address has been assigned since last power up), the currently assigned device address and the group address (address mask) the device responds to when short form addressing is used.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.8.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.8.4.
- 4 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
