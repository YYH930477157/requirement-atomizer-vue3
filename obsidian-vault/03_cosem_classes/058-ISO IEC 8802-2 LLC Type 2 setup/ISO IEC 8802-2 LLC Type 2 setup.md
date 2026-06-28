---
id: KB-L3-IC-58-ISO-IEC-8802-2-LLC-TYPE-2-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 8802-2 LLC Type 2 setup
aliases:
- class 58
- CL 58
keywords:
- iso/iec 8802-2 llc type 2 setup
- class 58
- cl 58
- logical_name
- transmit_window_size_k
- receive_window_size_rw
- max_octets_i_pdu_n1
- max_number_transmissions_n2
- acknowledgement_timer
- p_bit_timer
- reject_timer
- busy_state_timer
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 8802-2 LLC Type 2 setup

## Definition

COSEM interface class (class_id = 58, version = 0). Holds the parameters necessary to set up the ISO/IEC 8802-2 LLC layer in Type 2 operation.

## Aliases

- class 58
- CL 58

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the Type 2 data link connection parameters: transmit/receive window sizes, max I-PDU octets, max retransmissions and the acknowledgement / P-bit / reject / busy-state timers (the latter in seconds).
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 58,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "transmit_window_size_k", "mode": "static", "type": "unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "receive_window_size_rw", "mode": "static", "type": "unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "max_octets_i_pdu_n1", "mode": "static", "type": "long unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "max_number_transmissions_n2", "mode": "static", "type": "unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "acknowledgement_timer", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "p_bit_timer", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "reject_timer", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "busy_state_timer", "mode": "static", "type": "long-unsigned", "short_name": "x + 0x40" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the Type 2 data link connection parameters: transmit/receive window sizes, max I-PDU octets, max retransmissions and the acknowledgement / P-bit / reject / busy-state timers (the latter in seconds).",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.11.3; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.11.3.
- 9 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
