---
id: KB-L3-IC-85-PRIME-NB-OFDM-PLC-MAC-NETWORK-ADMINISTRATION-DATA
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC MAC network administration data
aliases:
- class 85
- CL 85
keywords:
- prime nb ofdm plc mac network administration data
- class 85
- cl 85
- logical_name
- mac_list_multicast_entries
- mac_list_switch_table
- mac_list_direct_table
- mac_list_available_switches
- mac_list_phy_comm
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC MAC network administration data

## Definition

COSEM interface class (class_id = 85, version = 0). Holds PRIME NB OFDM PLC MAC network administration data (multicast/switch/direct/available-switch/phy-comm lists).

## Aliases

- class 85
- CL 85

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds PRIME NB OFDM PLC MAC network administration data (multicast/switch/direct/available-switch/phy-comm lists).
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 85,
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
      "name": "mac_list_multicast_entries",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "mac_list_switch_table",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "mac_list_direct_table",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "mac_list_available_switches",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "mac_list_phy_comm",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x28"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "short_name": "x + 0x30"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds PRIME NB OFDM PLC MAC network administration data (multicast/switch/direct/available-switch/phy-comm lists).",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.9; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.9.
- 6 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
