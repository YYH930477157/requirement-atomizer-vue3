---
id: KB-L3-IC-127-SCHC-LPWAN-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: SCHC-LPWAN diagnostic
aliases:
- class 127
- CL 127
keywords:
- schc-lpwan diagnostic
- class 127
- cl 127
- logical_name
- schc_packets_tx_counter
- schc_packets_rx_counter
- schc_fragments_tx_counter
- schc_fragments_rx_counter
- schc_ack_tx_counter
- schc_ack_rx_counter
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# SCHC-LPWAN diagnostic

## Definition

COSEM interface class (class_id = 127, version = 0). Provides SCHC-over-LPWAN diagnostic counters (packets, fragments, ACKs transmitted/received).

## Aliases

- class 127
- CL 127

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Provides SCHC-over-LPWAN diagnostic counters (packets, fragments, ACKs transmitted/received).
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 127,
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
      "name": "schc_packets_tx_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "schc_packets_rx_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "schc_fragments_tx_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "schc_fragments_rx_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "schc_ack_tx_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "schc_ack_rx_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x30"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "short_name": "x + 0x40"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Provides SCHC-over-LPWAN diagnostic counters (packets, fragments, ACKs transmitted/received).",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.16.2.2; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.16.2.2.
- 7 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
