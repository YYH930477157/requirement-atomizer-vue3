---
id: KB-L3-IC-59-ISO-IEC-8802-2-LLC-TYPE-3-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 8802-2 LLC Type 3 setup
aliases:
- class 59
- CL 59
keywords:
- iso/iec 8802-2 llc type 3 setup
- class 59
- cl 59
- logical_name
- max_octets_acn_pdu_n3
- max_number_transmissions_n4
- acknowledgement_time_t1
- receive_lifetime_var_t2
- transmit_lifetime_var_t3
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 8802-2 LLC Type 3 setup

## Definition

COSEM interface class (class_id = 59, version = 0). Holds the parameters necessary to set up the ISO/IEC 8802-2 LLC layer in Type 3 operation.

## Aliases

- class 59
- CL 59

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the Type 3 logical link parameters: max ACn PDU octets (N3), max transmissions (N4), and the acknowledgement time T1, receive lifetime T2 and transmit lifetime T3 timers (in seconds; infinity is all bits set to 1).
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 59,
  "version": 0,
  "cardinality": "0...n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "max_octets_acn_pdu_n3", "mode": "static", "type": "long unsigned", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "max_number_transmissions_n4", "mode": "static", "type": "unsigned", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "acknowledgement_time_t1", "mode": "static", "type": "long unsigned", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "receive_lifetime_var_t2", "mode": "static", "type": "long unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "transmit_lifetime_var_t3", "mode": "static", "type": "long unsigned", "short_name": "x + 0x28" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the Type 3 logical link parameters: max ACn PDU octets (N3), max transmissions (N4), and the acknowledgement time T1, receive lifetime T2 and transmit lifetime T3 timers (in seconds; infinity is all bits set to 1).",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.11.4; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.11.4.
- 6 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
