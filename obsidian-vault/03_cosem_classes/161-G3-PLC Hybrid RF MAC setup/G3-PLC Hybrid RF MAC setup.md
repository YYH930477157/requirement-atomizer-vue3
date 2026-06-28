---
id: KB-L3-IC-161-G3-PLC-HYBRID-RF-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC Hybrid RF MAC setup
aliases:
- class 161
- CL 161
keywords:
- g3-plc hybrid rf mac setup
- class 161
- cl 161
- logical_name
- mac_max_be_rf
- mac_max_csma_backoffs_rf
- mac_max_frame_retries_rf
- mac_min_be_rf
- mac_frame_counter_rf
- mac_duplicate_detection_ttl_rf
- mac_pos_table_rf
- mac_operating_mode_rf
- mac_channel_number_rf
- mac_duty_cycle_usage_rf
- mac_duty_cycle_period_rf
- mac_duty_cycle_limit_rf
- mac_duty_cycle_threshold_rf
- mac_disable_phy_rf
- mac_frequency_band_rf
- mac_transmit_atten_rf
- mac_adaptive_power_step_rf
- mac_adaptive_power_high_bound_rf
- mac_adaptive_power_low_bound_rf
- mac_pos_recent_entries_rf
- mac_hopping_enabled_rf
- mac_broadcast_interval_duration_rf
- mac_broadcast_slot_duration_rf
- mac_unicast_slot_duration_rf
- mac_extended_bitmap_rf
- mac_beacon_randomization_window_length_rf
- mac_additional_channel_scan_time_rf
- mac_max_cca_attempts_retries_rf
- mac_min_inter_tx_interval_rf
- mac_initial_retry_time_rf
- mac_maximum_retry_time_rf
- mac_max_clock_drift_rf
- mac_fh_unicast_schedule_address_rf
- mac_fh_unicast_slot_number_rf
- mac_fh_unicast_offset_rf
- mac_min_guard_time_rf
- mac_max_bcast_resync_wait_unit_rf
- mac_get_pos_table_entry_rf
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC Hybrid RF MAC setup

## Definition

COSEM interface class (class_id = 161, version = 1). Holds the necessary additional parameters to set up and manage the G3-Hybrid IEEE 802.15.4:2015 RF MAC sub-layer.

## Aliases

- class 161
- CL 161

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the G3-PLC Hybrid RF MAC sub-layer parameters (CSMA/backoff/retry tuning, frame counter, POS table, RF operating mode, channel, duty-cycle management, frequency band/transmit attenuation, adaptive power, frequency hopping, broadcast/unicast slot timing and frequency-hopping scheduling); values may be changed during normal running.
- mac_get_POS_table_entry_RF retrieves the POS table entry for a given MAC short address.
- Specific methods: mac_get_POS_table_entry_RF (optional).

## Structured Data

```json metadata
{
  "class_id": 161,
  "version": 1,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "mac_max_BE_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "mac_max_CSMA_backoffs_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "mac_max_frame_retries_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "mac_min_BE_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "mac_frame_counter_RF", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "mac_duplicate_detection_TTL_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "mac_POS_table_RF", "mode": "dynamic", "type": "array", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "mac_operating_mode_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "mac_channel_number_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "mac_duty_cycle_usage_RF", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x50" },
    { "attribute_id": 12, "name": "mac_duty_cycle_period_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x58" },
    { "attribute_id": 13, "name": "mac_duty_cycle_limit_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x60" },
    { "attribute_id": 14, "name": "mac_duty_cycle_threshold_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x68" },
    { "attribute_id": 15, "name": "mac_disable_PHY_RF", "mode": "static", "type": "boolean", "short_name": "x + 0x70" },
    { "attribute_id": 16, "name": "mac_frequency_band_RF", "mode": "static", "type": "enum", "short_name": "x + 0x78" },
    { "attribute_id": 17, "name": "mac_transmit_atten_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x80" },
    { "attribute_id": 18, "name": "mac_adaptive_power_step_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x88" },
    { "attribute_id": 19, "name": "mac_adaptive_power_high_bound_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x90" },
    { "attribute_id": 20, "name": "mac_adaptive_power_low_bound_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x98" },
    { "attribute_id": 21, "name": "mac_POS_recent_entries_RF", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0xA0" },
    { "attribute_id": 22, "name": "mac_hopping_enabled_RF", "mode": "static", "type": "boolean", "short_name": "x + 0xA8" },
    { "attribute_id": 23, "name": "mac_broadcast_interval_duration_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xB0" },
    { "attribute_id": 24, "name": "mac_broadcast_slot_duration_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0xB8" },
    { "attribute_id": 25, "name": "mac_unicast_slot_duration_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0xC0" },
    { "attribute_id": 26, "name": "mac_extended_bitmap_RF", "mode": "static", "type": "bit-string", "short_name": "x + 0xC8" },
    { "attribute_id": 27, "name": "mac_beacon_randomization_window_length_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xD0" },
    { "attribute_id": 28, "name": "mac_additional_channel_scan_time_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0xD8" },
    { "attribute_id": 29, "name": "mac_max_cca_attempts_retries_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0xE0" },
    { "attribute_id": 30, "name": "mac_min_inter_Tx_interval_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xE8" },
    { "attribute_id": 31, "name": "mac_initial_retry_time_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xF0" },
    { "attribute_id": 32, "name": "mac_maximum_retry_time_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xF8" },
    { "attribute_id": 33, "name": "mac_max_clock_drift_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x100" },
    { "attribute_id": 34, "name": "mac_FH_unicast_schedule_address_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x108" },
    { "attribute_id": 35, "name": "mac_FH_unicast_slot_number_RF", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x110" },
    { "attribute_id": 36, "name": "mac_FH_unicast_offset_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x118" },
    { "attribute_id": 37, "name": "mac_min_guard_time_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x120" },
    { "attribute_id": 38, "name": "mac_max_bcast_resync_wait_unit_RF", "mode": "static", "type": "unsigned", "short_name": "x + 0x128" }
  ],
  "methods": [
    { "method_id": 1, "name": "mac_get_POS_table_entry_RF", "short_name": "x + 0x130" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the G3-PLC Hybrid RF MAC sub-layer parameters (CSMA/backoff/retry tuning, frame counter, POS table, RF operating mode, channel, duty-cycle management, frequency band/transmit attenuation, adaptive power, frequency hopping, broadcast/unicast slot timing and frequency-hopping scheduling); values may be changed during normal running.",
    "mac_get_POS_table_entry_RF retrieves the POS table entry for a given MAC short address.",
    "Specific methods: mac_get_POS_table_entry_RF (optional)."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.13.7; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.13.7.
- 38 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
