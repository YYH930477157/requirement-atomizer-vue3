---
id: KB-L3-IC-92-G3-PLC-6LOWPAN-ADAPTATION-LAYER-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC 6LoWPAN adaptation layer setup
aliases:
- class 92
- CL 92
keywords:
- g3-plc 6lowpan adaptation layer setup
- class 92
- cl 92
- logical_name
- adp_max_hops
- adp_weak_lqi_value
- adp_security_level
- adp_prefix_table
- adp_routing_configuration
- adp_broadcast_log_table
- adp_routing_table
- adp_context_information_table
- adp_blacklist_table
- adp_group_table
- adp_max_join_wait_time
- adp_path_discovery_time
- adp_active_key_index
- adp_metric_type
- adp_coord_short_address
- adp_disable_default_routing
- adp_device_type
- adp_default_coord_route_enabled
- adp_destination_address_set
- adp_low_lqi_value
- adp_high_lqi_value
- adp_delay_low_lqi
- adp_delay_high_lqi
- adp_rreq_jitter_low_lqi
- adp_rreq_jitter_high_lqi
- adp_trickle_data_enabled
- adp_trickle_lqi_threshold_low
- adp_trickle_step
- adp_trickle_imin
- adp_trickle_max_ki
- adp_trickle_adaptive_imin
- adp_trickle_adaptive_ki
- adp_cluster_trickle_enabled
- adp_cluster_min_lqi
- adp_cluster_trickle_k
- adp_cluster_rreq_route_cost_deviation
- adp_cluster_trickle_i
- adp_trickle_lqi_threshold_high
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC 6LoWPAN adaptation layer setup

## Definition

COSEM interface class (class_id = 92, version = 4). Holds the necessary parameters to set up and manage the G3-PLC 6LoWPAN Adaptation layer.

## Aliases

- class 92
- CL 92

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the G3-PLC 6LoWPAN adaptation layer parameters (routing, security, prefix/blacklist/group tables, LQI thresholds, trickle and cluster-trickle tuning) that influence functional behaviour; values may be changed during normal running.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 92,
  "version": 4,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "adp_max_hops", "mode": "static", "type": "unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "adp_weak_LQI_value", "mode": "static", "type": "unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "adp_security_level", "mode": "static", "type": "unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "adp_prefix_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "adp_routing_configuration", "mode": "static", "type": "array", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "adp_broadcast_log_table_entry_TTL", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "adp_routing_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "adp_context_information_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "adp_blacklist_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "adp_broadcast_log_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x50" },
    { "attribute_id": 12, "name": "adp_group_table", "mode": "dynamic", "type": "array", "short_name": "x + 0x58" },
    { "attribute_id": 13, "name": "adp_max_join_wait_time", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x60" },
    { "attribute_id": 14, "name": "adp_path_discovery_time", "mode": "static", "type": "unsigned", "short_name": "x + 0x68" },
    { "attribute_id": 15, "name": "adp_active_key_index", "mode": "static", "type": "unsigned", "short_name": "x + 0x70" },
    { "attribute_id": 16, "name": "adp_metric_type", "mode": "static", "type": "unsigned", "short_name": "x + 0x78" },
    { "attribute_id": 17, "name": "adp_coord_short_address", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x80" },
    { "attribute_id": 18, "name": "adp_disable_default_routing", "mode": "static", "type": "boolean", "short_name": "x + 0x88" },
    { "attribute_id": 19, "name": "adp_device_type", "mode": "static", "type": "enum", "short_name": "x + 0x90" },
    { "attribute_id": 20, "name": "adp_default_coord_route_enabled", "mode": "static", "type": "boolean", "short_name": "x + 0x98" },
    { "attribute_id": 21, "name": "adp_destination_address_set", "mode": "dynamic", "type": "array", "short_name": "x + 0xA0" },
    { "attribute_id": 22, "name": "adp_low_LQI_value", "mode": "static", "type": "unsigned", "short_name": "x + 0xA8" },
    { "attribute_id": 23, "name": "adp_high_LQI_value", "mode": "static", "type": "unsigned", "short_name": "x + 0xB0" },
    { "attribute_id": 24, "name": "adp_delay_low_LQI", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xB8" },
    { "attribute_id": 25, "name": "adp_delay_high_LQI", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xC0" },
    { "attribute_id": 26, "name": "adp_RREQ_jitter_low_LQI", "mode": "static", "type": "unsigned", "short_name": "x + 0xC8" },
    { "attribute_id": 27, "name": "adp_RREQ_jitter_high_LQI", "mode": "static", "type": "unsigned", "short_name": "x + 0xD0" },
    { "attribute_id": 28, "name": "adp_trickle_data_enabled", "mode": "static", "type": "boolean", "short_name": "x + 0xD8" },
    { "attribute_id": 29, "name": "adp_trickle_LQI_threshold_low", "mode": "static", "type": "unsigned", "short_name": "x + 0xE0" },
    { "attribute_id": 30, "name": "adp_trickle_step", "mode": "static", "type": "unsigned", "short_name": "x + 0xE8" },
    { "attribute_id": 31, "name": "adp_trickle_Imin", "mode": "static", "type": "long-unsigned", "short_name": "x + 0xF0" },
    { "attribute_id": 32, "name": "adp_trickle_max_Ki", "mode": "static", "type": "unsigned", "short_name": "x + 0xF8" },
    { "attribute_id": 33, "name": "adp_trickle_adaptive_Imin", "mode": "static", "type": "boolean", "short_name": "x + 0x100" },
    { "attribute_id": 34, "name": "adp_trickle_adaptive_Ki", "mode": "static", "type": "boolean", "short_name": "x + 0x108" },
    { "attribute_id": 35, "name": "adp_cluster_trickle_enabled", "mode": "static", "type": "boolean", "short_name": "x + 0x110" },
    { "attribute_id": 36, "name": "adp_cluster_min_LQI", "mode": "static", "type": "unsigned", "short_name": "x + 0x118" },
    { "attribute_id": 37, "name": "adp_cluster_trickle_K", "mode": "static", "type": "unsigned", "short_name": "x + 0x120" },
    { "attribute_id": 38, "name": "adp_cluster_RREQ_route_cost_deviation", "mode": "static", "type": "unsigned", "short_name": "x + 0x128" },
    { "attribute_id": 39, "name": "adp_cluster_trickle_I", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x130" },
    { "attribute_id": 40, "name": "adp_trickle_LQI_threshold_high", "mode": "static", "type": "unsigned", "short_name": "x + 0x138" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the G3-PLC 6LoWPAN adaptation layer parameters (routing, security, prefix/blacklist/group tables, LQI thresholds, trickle and cluster-trickle tuning) that influence functional behaviour; values may be changed during normal running.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.13.5; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.13.5.
- 40 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
