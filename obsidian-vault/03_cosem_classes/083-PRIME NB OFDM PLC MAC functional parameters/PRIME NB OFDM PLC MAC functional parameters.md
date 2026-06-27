---
id: KB-L3-IC-83-PRIME-NB-OFDM-PLC-MAC-FUNCTIONAL-PARAMETERS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC MAC functional parameters
aliases:
- class 83
- CL 83
keywords:
- prime nb ofdm plc mac functional parameters
- class 83
- cl 83
- logical_name
- mac_LNID
- mac_LSID
- mac_SID
- mac_SNA
- mac_state
- mac_scp_length
- mac_node_hierarchy_level
- mac_beacon_slot_count
- mac_beacon_rx_slot
- mac_beacon_tx_slot
- mac_beacon_rx_frequency
- mac_beacon_tx_frequency
- mac_capabilities
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC MAC functional parameters

## Definition

COSEM interface class (class_id = 83, version = 0). Holds PRIME NB OFDM PLC MAC functional parameters (LNID/LSID/SID, MAC state, beacon slots/frequencies, capabilities).

## Aliases

- class 83
- CL 83

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds PRIME NB OFDM PLC MAC functional parameters (LNID/LSID/SID, MAC state, beacon slots/frequencies, capabilities).
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 83,
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
      "name": "mac_LNID",
      "mode": "static",
      "type": "long",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "mac_LSID",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "mac_SID",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "mac_SNA",
      "mode": "static",
      "type": "octet-string",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "mac_state",
      "mode": "static",
      "type": "enum",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "mac_scp_length",
      "mode": "static",
      "type": "long",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 8,
      "name": "mac_node_hierarchy_level",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 9,
      "name": "mac_beacon_slot_count",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 10,
      "name": "mac_beacon_rx_slot",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 11,
      "name": "mac_beacon_tx_slot",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 12,
      "name": "mac_beacon_rx_frequency",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x58"
    },
    {
      "attribute_id": 13,
      "name": "mac_beacon_tx_frequency",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x60"
    },
    {
      "attribute_id": 14,
      "name": "mac_capabilities",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x68"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds PRIME NB OFDM PLC MAC functional parameters (LNID/LSID/SID, MAC state, beacon slots/frequencies, capabilities).",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.7; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.7.
- 14 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
