---
id: KB-L3-IC-95-WI-SUN-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Wi-SUN setup
aliases:
- class 95
- CL 95
keywords:
- wi-sun setup
- class 95
- cl 95
- logical_name
- network_name
- routing_method
- pan_id
- disc_imin
- disc_imax
- data_message_imin
- data_message_imax
- default_dio_interval_min
- default_dio_interval_doublings
- channel_plan
- channel_function
- excluded_channels
- join_state
- reg_channel_exclusions
- reset_join_state
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Wi-SUN setup

## Definition

COSEM interface class (class_id = 95, version = 0). Models the Wi-SUN FAN network setup parameters (network name, routing method, PAN id, DIO/Trickle timers, channel plan).

## Aliases

- class 95
- CL 95

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Models the Wi-SUN FAN network setup parameters (network name, routing method, PAN id, DIO/Trickle timers, channel plan).
- Specific methods: reset_join_state.

## Structured Data

```json metadata
{
  "class_id": 95,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "mode": "static",
      "type": "octet-string"
    },
    {
      "attribute_id": 2,
      "name": "network_name",
      "mode": "static",
      "type": "octet-string",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "routing_method",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "pan_id",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "disc_imin",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "disc_imax",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "data_message_imin",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 8,
      "name": "data_message_imax",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 9,
      "name": "default_dio_interval_min",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 10,
      "name": "default_dio_interval_doublings",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 11,
      "name": "channel_plan",
      "mode": "static",
      "type": "structure",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 12,
      "name": "channel_function",
      "mode": "static",
      "type": "enum",
      "short_name": "x + 0x58"
    },
    {
      "attribute_id": 13,
      "name": "excluded_channels",
      "mode": "static",
      "type": "CHOICE",
      "short_name": "x + 0x60"
    },
    {
      "attribute_id": 14,
      "name": "join_state",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x68"
    },
    {
      "attribute_id": 15,
      "name": "reg_channel_exclusions",
      "mode": "static",
      "type": "structure",
      "short_name": "x + 0x70"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset_join_state",
      "short_name": "x + 0x78"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Models the Wi-SUN FAN network setup parameters (network name, routing method, PAN id, DIO/Trickle timers, channel plan).",
    "Specific methods: reset_join_state."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.18.1; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.18.1.
- 15 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
