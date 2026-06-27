---
id: KB-L3-IC-81-PRIME-NB-OFDM-PLC-PHYSICAL-LAYER-COUNTERS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC Physical layer counters
aliases:
- class 81
- CL 81
keywords:
- prime nb ofdm plc physical layer counters
- class 81
- cl 81
- logical_name
- phy_stats_crc_incorrect_count
- phy_stats_crc_fail_count
- phy_stats_tx_drop_count
- phy_stats_rx_drop_count
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC Physical layer counters

## Definition

COSEM interface class (class_id = 81, version = 0). Holds PRIME NB OFDM PLC physical-layer statistics counters (CRC errors, dropped frames).

## Aliases

- class 81
- CL 81

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds PRIME NB OFDM PLC physical-layer statistics counters (CRC errors, dropped frames).
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 81,
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
      "name": "phy_stats_crc_incorrect_count",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "phy_stats_crc_fail_count",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "phy_stats_tx_drop_count",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "phy_stats_rx_drop_count",
      "mode": "dynamic",
      "type": "long-unsigned",
      "short_name": "x + 0x20"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "short_name": "x + 0x28"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds PRIME NB OFDM PLC physical-layer statistics counters (CRC errors, dropped frames).",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.5; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.5.
- 5 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
