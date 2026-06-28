---
id: KB-L3-IC-84-PRIME-NB-OFDM-PLC-MAC-COUNTERS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC MAC counters
aliases:
- class 84
- CL 84
keywords:
- prime nb ofdm plc mac counters
- class 84
- cl 84
- logical_name
- mac_tx_data_pkt_count
- mac_rx_data_pkt_count
- mac_tx_ctrl_pkt_count
- mac_rx_ctrl_pkt_count
- mac_csma_fail_count
- mac_csma_ch_busy_count
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC MAC counters

## Definition

COSEM interface class (class_id = 84, version = 0). Stores statistical information on the operation of the MAC layer for management purposes.

## Aliases

- class 84
- CL 84

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the read-only MAC statistic counters (transmitted/received data and control packets, CSMA failures and channel-busy counts); counters wrap to 0 at the maximum value and can be reset via the reset method.
- Specific methods: reset (optional).

## Structured Data

```json metadata
{
  "class_id": 84,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "mac_tx_data_pkt_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "mac_rx_data_pkt_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "mac_tx_ctrl_pkt_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "mac_rx_ctrl_pkt_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "mac_csma_fail_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "mac_csma_ch_busy_count", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x30" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "x + 0x40" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the read-only MAC statistic counters (transmitted/received data and control packets, CSMA failures and channel-busy counts); counters wrap to 0 at the maximum value and can be reset via the reset method.",
    "Specific methods: reset (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.8; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.8.
- 7 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
