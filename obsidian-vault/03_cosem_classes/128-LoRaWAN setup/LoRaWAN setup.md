---
id: KB-L3-IC-128-LORAWAN-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: LoRaWAN setup
aliases:
- class 128
- CL 128
keywords:
- lorawan setup
- class 128
- cl 128
- logical_name
- class
- state
- max_transmit_EIRP_setting
- ADR_mode
- regional_parameters
- device_operation
- modem_versions
- devAddr
- join_strategy
- multicasts_parameters
- disconnect_from_network
- change_class
- change_region
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# LoRaWAN setup

## Definition

COSEM interface class (class_id = 128, version = 0). Holds the parameters to set up a LoRaWAN 1.0.3 device (class, state, EIRP, ADR, regional parameters, device operation).

## Aliases

- class 128
- CL 128

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the parameters to set up a LoRaWAN 1.0.3 device (class, state, EIRP, ADR, regional parameters, device operation).
- Specific methods: disconnect_from_network, change_class, change_region.

## Structured Data

```json metadata
{
  "class_id": 128,
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
      "name": "class",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "state",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "max_transmit_EIRP_setting",
      "mode": "static",
      "type": "integer",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "ADR_mode",
      "mode": "dynamic",
      "type": "boolean",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "regional_parameters",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "device_operation",
      "mode": "dynamic",
      "type": "structure",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 8,
      "name": "modem_versions",
      "mode": "static",
      "type": "structure",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 9,
      "name": "devAddr",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 10,
      "name": "join_strategy",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 11,
      "name": "multicasts_parameters",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x58"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "disconnect_from_network",
      "short_name": "x + 0x60"
    },
    {
      "method_id": 2,
      "name": "change_class",
      "short_name": "x + 0x68"
    },
    {
      "method_id": 3,
      "name": "change_region",
      "short_name": "x + 0x70"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the parameters to set up a LoRaWAN 1.0.3 device (class, state, EIRP, ADR, regional parameters, device operation).",
    "Specific methods: disconnect_from_network, change_class, change_region."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.17.2.2; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.17.2.2.
- 11 attributes, 3 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
