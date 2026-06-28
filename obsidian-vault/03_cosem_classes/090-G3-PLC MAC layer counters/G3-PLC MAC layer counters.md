---
id: KB-L3-IC-90-G3-PLC-MAC-LAYER-COUNTERS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC MAC layer counters
aliases:
- class 90
- CL 90
keywords:
- g3-plc mac layer counters
- class 90
- cl 90
- logical_name
- mac_tx_data_packet_count
- mac_rx_data_packet_count
- mac_tx_cmd_packet_count
- mac_rx_cmd_packet_count
- mac_csma_fail_count
- mac_csma_no_ack_count
- mac_bad_crc_count
- mac_tx_data_broadcast_count
- mac_rx_data_broadcast_count
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC MAC layer counters

## Definition

COSEM interface class (class_id = 90, version = 1). Stores counters related to the G3-PLC MAC layer exchanges to provide statistical information for management purposes.

## Aliases

- class 90
- CL 90

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the read-only MAC statistic counters (data/command packets transmitted/received, CSMA failures, no-ACK and bad-CRC counts, and broadcast counts); counters wrap to 0 at the maximum value and can be reset via the reset method.
- Specific methods: reset (optional).

## Structured Data

```json metadata
{
  "class_id": 90,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "mac_Tx_data_packet_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "mac_Rx_data_packet_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "mac_Tx_cmd_packet_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "mac_Rx_cmd_packet_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "mac_CSMA_fail_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "mac_CSMA_no_ACK_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "mac_bad_CRC_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "mac_Tx_data_broadcast_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "mac_Rx_data_broadcast_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x48" }
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
    "Holds the read-only MAC statistic counters (data/command packets transmitted/received, CSMA failures, no-ACK and bad-CRC counts, and broadcast counts); counters wrap to 0 at the maximum value and can be reset via the reset method.",
    "Specific methods: reset (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.13.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.13.3.
- 10 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
