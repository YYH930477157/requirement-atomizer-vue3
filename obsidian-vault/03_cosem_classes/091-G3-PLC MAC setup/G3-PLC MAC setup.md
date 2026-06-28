---
id: KB-L3-IC-91-G3-PLC-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC MAC setup
aliases:
- class 91
- CL 91
keywords:
- g3-plc mac setup
- class 91
- cl 91
- logical_name
- mac_short_address
- mac_rc_coord
- mac_pan_id
- mac_key_table
- mac_frame_counter
- mac_tone_mask
- mac_tmr_ttl
- mac_max_frame_retries
- mac_pos_table_entry_ttl
- mac_neighbour_table
- mac_high_priority_window_size
- mac_csma_fairness_limit
- mac_beacon_randomization_window_length
- mac_a
- mac_k
- mac_min_cw_attempts
- mac_cenelec_legacy_mode
- mac_fcc_legacy_mode
- mac_max_be
- mac_max_csma_backoffs
- mac_min_be
- mac_broadcast_max_cw_enabled
- mac_transmit_atten
- mac_pos_table
- mac_duplicate_detection_ttl
- mac_pos_recent_entry_threshold
- mac_pos_recent_entries
- mac_preamble_length
- mac_get_neighbour_table_entry
- mac_get_pos_table_entry
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC MAC setup

## Definition

COSEM interface class (class_id = 91, version = 4). Holds the necessary parameters to set up and manage the G3-PLC IEEE 802.15.4:2006 MAC sub-layer.

## Aliases

- class 91
- CL 91

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the G3-PLC MAC sub-layer parameters (addressing, security key table and frame counter, tone mask, CSMA/tone-map/legacy-mode tuning, neighbour and POS tables); the attributes influence functional behaviour and may be changed during normal running.
- mac_get_neighbour_table_entry / mac_get_POS_table_entry retrieve the table entry for a given MAC short address, usable for topology monitoring.
- Specific methods: mac_get_neighbour_table_entry (optional), mac_get_POS_table_entry (optional).

## Structured Data

```json metadata
{
  "class_id": 91,
  "version": 4,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "mac_short_address", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "mac_RC_coord", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "mac_PAN_id", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "mac_key_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "mac_frame_counter", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "mac_tone_mask", "mode": "static", "type": "bit-string", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "mac_TMR_TTL", "mode": "static", "type": "unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "mac_max_frame_retries", "mode": "static", "type": "unsigned", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "mac_POS_table_entry_TTL", "mode": "static", "type": "unsigned", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "mac_neighbour_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x50" },
    { "attribute_id": 12, "name": "mac_high_priority_window_size", "mode": "static", "type": "unsigned", "short_name": "x + 0x58" },
    { "attribute_id": 13, "name": "mac_CSMA_fairness_limit", "mode": "static", "type": "unsigned", "short_name": "x + 0x60" },
    { "attribute_id": 14, "name": "mac_beacon_randomization_window_length", "mode": "static", "type": "unsigned", "short_name": "x + 0x68" },
    { "attribute_id": 15, "name": "mac_A", "mode": "static", "type": "unsigned", "short_name": "x + 0x70" },
    { "attribute_id": 16, "name": "mac_K", "mode": "static", "type": "unsigned", "short_name": "x + 0x78" },
    { "attribute_id": 17, "name": "mac_min_CW_attempts", "mode": "static", "type": "unsigned", "short_name": "x + 0x80" },
    { "attribute_id": 18, "name": "mac_cenelec_legacy_mode", "mode": "static", "type": "unsigned", "short_name": "x + 0x88" },
    { "attribute_id": 19, "name": "mac_FCC_legacy_mode", "mode": "static", "type": "unsigned", "short_name": "x + 0x90" },
    { "attribute_id": 20, "name": "mac_max_BE", "mode": "static", "type": "unsigned", "short_name": "x + 0x98" },
    { "attribute_id": 21, "name": "mac_max_CSMA_backoffs", "mode": "static", "type": "unsigned", "short_name": "x + 0xA0" },
    { "attribute_id": 22, "name": "mac_min_BE", "mode": "static", "type": "unsigned", "short_name": "x + 0xA8" },
    { "attribute_id": 23, "name": "mac_broadcast_max_CW_enabled", "mode": "static", "type": "boolean", "short_name": "x + 0xB0" },
    { "attribute_id": 24, "name": "mac_transmit_atten", "mode": "static", "type": "unsigned", "short_name": "x + 0xB8" },
    { "attribute_id": 25, "name": "mac_POS_table", "mode": "dynamic", "type": "array", "short_name": "x + 0xC0" },
    { "attribute_id": 26, "name": "mac_duplicate_detection_TTL", "mode": "static", "type": "unsigned", "short_name": "x + 0xC8" },
    { "attribute_id": 27, "name": "mac_POS_recent_entry_threshold", "mode": "static", "type": "unsigned", "short_name": "x + 0xD0" },
    { "attribute_id": 28, "name": "mac_POS_recent_entries", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xD8" },
    { "attribute_id": 29, "name": "mac_preamble_length", "mode": "static", "type": "unsigned", "short_name": "x + 0xE0" }
  ],
  "methods": [
    { "method_id": 1, "name": "mac_get_neighbour_table_entry", "short_name": "x + 0xE8" },
    { "method_id": 2, "name": "mac_get_POS_table_entry", "short_name": "x + 0xF0" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the G3-PLC MAC sub-layer parameters (addressing, security key table and frame counter, tone mask, CSMA/tone-map/legacy-mode tuning, neighbour and POS tables); the attributes influence functional behaviour and may be changed during normal running.",
    "mac_get_neighbour_table_entry / mac_get_POS_table_entry retrieve the table entry for a given MAC short address, usable for topology monitoring.",
    "Specific methods: mac_get_neighbour_table_entry (optional), mac_get_POS_table_entry (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.13.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.13.4.
- 29 attributes, 2 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
