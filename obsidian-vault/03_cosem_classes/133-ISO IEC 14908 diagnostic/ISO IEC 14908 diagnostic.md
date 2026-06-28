---
id: KB-L3-IC-133-ISO-IEC-14908-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 diagnostic
aliases:
- class 133
- CL 133
keywords:
- iso/iec 14908 diagnostic
- class 133
- cl 133
- logical_name
- plc_signal_quality_status
- com_module_state
- received_message_status
- no_receive_buffer
- transmit_no_data
- backlog_overflows
- late_ack
- frequency_invalid
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 diagnostic

## Definition

COSEM interface class (class_id = 133, version = 0). Provides information about the device status inside the PLC network (IEC 62056-8-8:2020 profile).

## Aliases

- class 133
- CL 133

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds PLC signal quality status, communication module state, received message status and per-cause counters (no receive buffer, transmit no data, backlog overflows, late ACK, invalid frequency).
- Specific methods: reset (optional). Note: IEC 62056-8-8:2020 specifies version = 0 which does not support the reset method.

## Structured Data

```json metadata
{
  "class_id": 133,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "plc_signal_quality_status", "mode": "dynamic", "type": "enum", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "com_module_state", "mode": "dynamic", "type": "enum", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "received_message_status", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "no_receive_buffer", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "transmit_no_data", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "backlog_overflows", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "late_ack", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "frequency_invalid", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x40" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "X + 0x60" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds PLC signal quality status, communication module state, received message status and per-cause counters (no receive buffer, transmit no data, backlog overflows, late ACK, invalid frequency).",
    "Specific methods: reset (optional). Note: IEC 62056-8-8:2020 specifies version = 0 which does not support the reset method."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.19.5; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.19.5.
- 9 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
