---
id: KB-L3-IC-101-ZIGBEE-SAS-STARTUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee SAS startup
aliases:
- class 101
- CL 101
keywords:
- zigbee sas startup
- class 101
- cl 101
- logical_name
- short_address
- extended_pan_id
- pan_id
- channel_mask
- protocol_version
- stack_profile
- start_up_control
- trust_center_address
- link_key
- network_key
- use_insecure_join
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee SAS startup

## Definition

COSEM interface class (class_id = 101, version = 0). Used to configure a ZigBee® Pro device with the information necessary to create or join the network.

## Aliases

- class 101
- CL 101

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the ZigBee® network start-up parameters (short/extended-PAN/PAN addressing, channel mask, protocol/stack profile, commissioning state, trust center address, link/network keys and the insecure-join flag); the driven functionality depends on whether the object is in a coordinator or another ZigBee® device.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 101,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "short_address", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "extended_pan_id", "mode": "dynamic", "type": "octet-string", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "pan_id", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "channel_mask", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "protocol_version", "mode": "static", "type": "unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "stack_profile", "mode": "static", "type": "enum", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "start_up_control", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "trust_center_address", "mode": "dynamic", "type": "octet-string", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "link_key", "mode": "dynamic", "type": "octet-string", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "network_key", "mode": "dynamic", "type": "octet-string", "short_name": "x + 0x50" },
    { "attribute_id": 12, "name": "use_insecure_join", "mode": "static", "type": "boolean", "short_name": "x + 0x58" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the ZigBee® network start-up parameters (short/extended-PAN/PAN addressing, channel mask, protocol/stack profile, commissioning state, trust center address, link/network keys and the insecure-join flag); the driven functionality depends on whether the object is in a coordinator or another ZigBee® device.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.15.2; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.15.2.
- 12 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
