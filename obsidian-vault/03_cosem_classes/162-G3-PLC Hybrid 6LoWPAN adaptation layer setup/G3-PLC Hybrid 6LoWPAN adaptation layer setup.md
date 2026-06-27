---
id: KB-L3-IC-162-G3-PLC-HYBRID-6LOWPAN-ADAPTATION-LAYER-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC Hybrid 6LoWPAN adaptation layer setup
aliases:
- class 162
- CL 162
keywords:
- g3-plc hybrid 6lowpan adaptation layer setup
- class 162
- cl 162
- logical_name
- adp_routing_table
- adp_blacklist_table
- adp_low_LQI_value_RF
- adp_high_LQI_value_RF
- adp_routing_configuration_RF
- adp_use_backup_media
- adp_weak_LQI_value_RF
- adp_trickle_LQI_threshold_low_RF
- adp_delay_low_LQI_RF
- adp_delay_high_LQI_RF
- adp_RREQ_jitter_low_LQI_RF
- adp_RREQ_jitter_high_LQI_RF
- adp_cluster_trickle_I_RF
- adp_cluster_trickle_K_RF
- adp_cluster_min_LQI_RF
- adp_last_gasp
- adp_probing_interval
- adp_trickle_LQI_threshold_high_RF
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC Hybrid 6LoWPAN adaptation layer setup

## Definition

COSEM interface class (class_id = 162, version = 1). Holds the G3-Hybrid 6LoWPAN adaptation-layer parameters (routing/blacklist tables, LQI thresholds, RREQ jitter, Trickle/cluster timers).

## Aliases

- class 162
- CL 162

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the G3-Hybrid 6LoWPAN adaptation-layer parameters (routing/blacklist tables, LQI thresholds, RREQ jitter, Trickle/cluster timers).
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 162,
  "version": 1,
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
      "name": "adp_routing_table",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "adp_blacklist_table",
      "mode": "dynamic",
      "type": "array",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "adp_low_LQI_value_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "adp_high_LQI_value_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "adp_routing_configuration_RF",
      "mode": "static",
      "type": "array",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "adp_use_backup_media",
      "mode": "static",
      "type": "boolean",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 8,
      "name": "adp_weak_LQI_value_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 9,
      "name": "adp_trickle_LQI_threshold_low_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 10,
      "name": "adp_delay_low_LQI_RF",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 11,
      "name": "adp_delay_high_LQI_RF",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 12,
      "name": "adp_RREQ_jitter_low_LQI_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x58"
    },
    {
      "attribute_id": 13,
      "name": "adp_RREQ_jitter_high_LQI_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x60"
    },
    {
      "attribute_id": 14,
      "name": "adp_cluster_trickle_I_RF",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x68"
    },
    {
      "attribute_id": 15,
      "name": "adp_cluster_trickle_K_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x70"
    },
    {
      "attribute_id": 16,
      "name": "adp_cluster_min_LQI_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x78"
    },
    {
      "attribute_id": 17,
      "name": "adp_last_gasp",
      "mode": "static",
      "type": "boolean",
      "short_name": "x + 0x80"
    },
    {
      "attribute_id": 18,
      "name": "adp_probing_interval",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x88"
    },
    {
      "attribute_id": 19,
      "name": "adp_trickle_LQI_threshold_high_RF",
      "mode": "static",
      "type": "unsigned",
      "short_name": "x + 0x90"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the G3-Hybrid 6LoWPAN adaptation-layer parameters (routing/blacklist tables, LQI thresholds, RREQ jitter, Trickle/cluster timers).",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.13.8; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.13.8.
- 19 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
