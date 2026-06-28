---
id: KB-L3-IC-116-IEC-62055-41-ATTRIBUTES
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC 62055-41 attributes
aliases:
- class 116
- CL 116
keywords:
- iec 62055-41 attributes
- class 116
- cl 116
- logical_name
- meter_pan
- commodity
- token_carrier_types
- encryption_algorithm
- supply_group_code
- tariff_index
- key_revision_number
- key_type
- key_expiry_number
- no_of_kct_supported
- sts_certificate_no
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC 62055-41 attributes

## Definition

COSEM interface class (class_id = 116, version = 0). Presents a selection of IEC 62055-41 data elements necessary to manage STS functions implemented within a DLMS server.

## Aliases

- class 116
- CL 116

## Domain Tags

- `cosem_class`
- `payment_metering`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds the STS meter attributes (meter PAN, commodity, token carrier types, encryption algorithm, supply group code, tariff/key parameters and STS certificate number); several are set at manufacture and read-only, while the key-related attributes are updated only via key change tokens.
- Specific methods: none defined.

## Structured Data

```json metadata
{
  "class_id": 116,
  "version": 0,
  "cardinality": "0..n",
  "attributes": [
    { "attribute_id": 1, "name": "logical_name", "mode": "static", "type": "octet-string" },
    { "attribute_id": 2, "name": "meter_pan", "mode": "static", "type": "structure", "short_name": "x + 0x08" },
    { "attribute_id": 3, "name": "commodity", "mode": "static", "type": "visible-string", "short_name": "x + 0x10" },
    { "attribute_id": 4, "name": "token_carrier_types", "mode": "static", "type": "array", "short_name": "x + 0x18" },
    { "attribute_id": 5, "name": "encryption_algorithm", "mode": "static", "type": "unsigned", "short_name": "x + 0x20" },
    { "attribute_id": 6, "name": "supply_group_code", "mode": "dynamic", "type": "double-long-unsigned", "short_name": "x + 0x28" },
    { "attribute_id": 7, "name": "tariff_index", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x30" },
    { "attribute_id": 8, "name": "key_revision_number", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x38" },
    { "attribute_id": 9, "name": "key_type", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x40" },
    { "attribute_id": 10, "name": "key_expiry_number", "mode": "dynamic", "type": "unsigned", "short_name": "x + 0x48" },
    { "attribute_id": 11, "name": "no_of_kct_supported", "mode": "static", "type": "unsigned", "short_name": "x + 0x50" },
    { "attribute_id": 12, "name": "sts_certificate_no", "mode": "static", "type": "visible-string", "short_name": "x + 0x58" }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds the STS meter attributes (meter PAN, commodity, token carrier types, encryption algorithm, supply group code, tariff/key parameters and STS certificate number); several are set at manufacture and read-only, while the key-related attributes are updated only via key change tokens.",
    "Specific methods: none defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.6.6; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.6.6.
- 12 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
