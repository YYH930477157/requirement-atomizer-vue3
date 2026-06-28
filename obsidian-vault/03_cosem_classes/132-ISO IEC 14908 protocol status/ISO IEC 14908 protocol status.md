---
id: KB-L3-IC-132-ISO-IEC-14908-PROTOCOL-STATUS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 protocol status
aliases:
- class 132
- CL 132
keywords:
- iso/iec 14908 protocol status
- class 132
- cl 132
- logical_name
- transmission_errors
- transmit_tx_failure
- transmit_tx_retries
- receive_tx_full
- lost_messages
- missed_messages
- layer2_received
- layer3_received
- messages_received
- messages_validated
- reset
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 protocol status

## Definition

COSEM interface class (class_id = 132, version = 0). Allows the status of the protocol in the ISO/IEC 14908 device to be determined (IEC 62056-8-8:2020 profile).

## Aliases

- class 132
- CL 132

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the protocol status counters (transmission errors, transmit failures/retries, receive-buffer-full, lost/missed messages, layer-2/layer-3 received counts, messages received/validated at the adaptation layer).
- Specific methods: reset (optional). Note: IEC 62056-8-8:2020 specifies version = 0 which does not support the reset method.

## Structured Data

```json metadata
{
  "class_id": 132,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "transmission_errors", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "transmit_tx_failure", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "transmit_tx_retries", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "receive_tx_full", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "lost_messages", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "missed_messages", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "layer2_received", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "layer3_received", "mode": "dynamic", "type": "long-unsigned", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "messages_received", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "messages_validated", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x50" }
  ],
  "methods": [
    { "method_id": 1, "name": "reset", "short_name": "X + 0x70" }
  ],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the protocol status counters (transmission errors, transmit failures/retries, receive-buffer-full, lost/missed messages, layer-2/layer-3 received counts, messages received/validated at the adaptation layer).",
    "Specific methods: reset (optional). Note: IEC 62056-8-8:2020 specifies version = 0 which does not support the reset method."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.19.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.19.4.
- 11 attributes, 1 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
