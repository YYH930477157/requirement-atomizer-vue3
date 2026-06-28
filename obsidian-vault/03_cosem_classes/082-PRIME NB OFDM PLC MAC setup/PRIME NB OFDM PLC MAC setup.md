---
id: KB-L3-IC-82-PRIME-NB-OFDM-PLC-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC MAC setup
aliases:
- class 82
- CL 82
keywords:
- prime nb ofdm plc mac setup
- class 82
- cl 82
- logical_name
- mac_min_switch_search_time
- mac_max_promotion_pdu
- mac_promotion_pdu_tx_period
- mac_beacons_per_frame
- mac_scp_max_tx_attempts
- mac_ctl_re_tx_timer
- mac_max_ctl_re_tx
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC MAC setup

## Definition

COSEM interface class (class_id = 82, version = 0). Holds the necessary parameters to set up and manage the PRIME NB OFDM PLC MAC layer.

## Aliases

- class 82
- CL 82

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the read-write MAC management variables (switch search, promotion PDU count/period, beacons per frame, SCP retransmit attempts, control retransmit timer and count) that influence functional behaviour; values may be changed during normal running.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 82,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "mac_min_switch_search_time", "mode": "static", "type": "unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "mac_max_promotion_pdu", "mode": "static", "type": "unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "mac_promotion_pdu_tx_period", "mode": "static", "type": "unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "mac_beacons_per_frame", "mode": "static", "type": "unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "mac_scp_max_tx_attempts", "mode": "static", "type": "unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "mac_ctl_re_tx_timer", "mode": "static", "type": "unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "mac_max_ctl_re_tx", "mode": "static", "type": "unsigned", "short_name": "x + 0x38" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the read-write MAC management variables (switch search, promotion PDU count/period, beacons per frame, SCP retransmit attempts, control retransmit timer and count) that influence functional behaviour; values may be changed during normal running.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.6; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.6.
- 8 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
