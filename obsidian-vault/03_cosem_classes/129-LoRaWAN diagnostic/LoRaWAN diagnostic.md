---
id: KB-L3-IC-129-LORAWAN-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: LoRaWAN diagnostic
aliases:
- class 129
- CL 129
keywords:
- lorawan diagnostic
- class 129
- cl 129
- logical_name
- internal_error_code
- out_frames_u_counter
- out_frames_c_counter
- in_frames_u_counter
- in_frames_c_counter
- in_mac_command_counter
- in_mac_ans_error_counter
- in_mac_ignored_counter
- in_per
- in_mean_rssi_rx1
- in_mean_snr_rx1
- in_mean_rssi_rx2
- in_mean_snr_rx2
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# LoRaWAN diagnostic

## Definition

COSEM interface class (class_id = 129, version = 0). Provides LoRaWAN diagnostic information (internal error code, uplink/downlink frame counters, link quality RSSI/SNR).

## Aliases

- class 129
- CL 129

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Provides LoRaWAN diagnostic information (internal error code, uplink/downlink frame counters, link quality RSSI/SNR).
- Specific methods: reset.

## Structured Data

```json metadata
{
  "class_id": 129,
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
      "name": "internal_error_code",
      "mode": "dynamic",
      "type": "enum",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "out_frames_u_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "out_frames_c_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x18"
    },
    {
      "attribute_id": 5,
      "name": "in_frames_u_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x20"
    },
    {
      "attribute_id": 6,
      "name": "in_frames_c_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x28"
    },
    {
      "attribute_id": 7,
      "name": "in_mac_command_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x30"
    },
    {
      "attribute_id": 8,
      "name": "in_mac_ans_error_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x38"
    },
    {
      "attribute_id": 9,
      "name": "in_mac_ignored_counter",
      "mode": "dynamic",
      "type": "double-long-unsigned",
      "short_name": "x + 0x40"
    },
    {
      "attribute_id": 10,
      "name": "in_per",
      "mode": "dynamic",
      "type": "integer",
      "short_name": "x + 0x48"
    },
    {
      "attribute_id": 11,
      "name": "in_mean_rssi_rx1",
      "mode": "dynamic",
      "type": "integer",
      "short_name": "x + 0x50"
    },
    {
      "attribute_id": 12,
      "name": "in_mean_snr_rx1",
      "mode": "dynamic",
      "type": "integer",
      "short_name": "x + 0x58"
    },
    {
      "attribute_id": 13,
      "name": "in_mean_rssi_rx2",
      "mode": "dynamic",
      "type": "integer",
      "short_name": "x + 0x60"
    },
    {
      "attribute_id": 14,
      "name": "in_mean_snr_rx2",
      "mode": "dynamic",
      "type": "integer",
      "short_name": "x + 0x68"
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "reset",
      "short_name": "x + 0x70"
    }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Provides LoRaWAN diagnostic information (internal error code, uplink/downlink frame counters, link quality RSSI/SNR).",
    "Specific methods: reset."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.17.2.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.17.2.3.
- 14 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
