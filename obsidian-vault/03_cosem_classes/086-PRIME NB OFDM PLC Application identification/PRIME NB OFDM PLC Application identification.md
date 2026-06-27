---
id: KB-L3-IC-86-PRIME-NB-OFDM-PLC-APPLICATION-IDENTIFICATION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC Application identification
aliases:
- class 86
- CL 86
keywords:
- prime nb ofdm plc application identification
- class 86
- cl 86
- logical_name
- firmware_version
- vendor_Id
- product_Id
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC Application identification

## Definition

COSEM interface class (class_id = 86, version = 0). Holds PRIME NB OFDM PLC application identification (firmware version, vendor and product IDs).

## Aliases

- class 86
- CL 86

## Domain Tags

- `cosem_class`
- `communication_profile`

## Access Semantics

- Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.
- logical_name (attribute 1) is read-only for all clients.
- Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client.

## Behavior Notes

- Holds PRIME NB OFDM PLC application identification (firmware version, vendor and product IDs).
- No specific methods defined.

## Structured Data

```json metadata
{
  "class_id": 86,
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
      "name": "firmware_version",
      "mode": "static",
      "type": "octet-string",
      "short_name": "x + 0x08"
    },
    {
      "attribute_id": 3,
      "name": "vendor_Id",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x10"
    },
    {
      "attribute_id": 4,
      "name": "product_Id",
      "mode": "static",
      "type": "long-unsigned",
      "short_name": "x + 0x18"
    }
  ],
  "methods": [],
  "access_semantics": [
    "Static attributes are configuration parameters set via SET by an authorised management client; dynamic attributes are read (GET) status/diagnostic values.",
    "logical_name (attribute 1) is read-only for all clients.",
    "Per-attribute access rights follow the COSEM access model and the association's access_rights_list; the Blue Book IC table specifies static/dynamic only, not concrete R/RW per client."
  ],
  "behavior_notes": [
    "Holds PRIME NB OFDM PLC application identification (firmware version, vendor and product IDs).",
    "No specific methods defined."
  ],
  "common_instances": [],
  "coverage_note": "Enriched 2026-06-28 from Blue Book Part 2 Ed.16 section 4.12.11; attributes (id/name/static-or-dynamic/data-type/short-name) and methods taken verbatim from the IC table. access_rights are described semantically, not hard-coded per attribute, because the IC table does not specify concrete R/RW per client."
}
```

## Notes

- Source: Blue Book Part 2 (DLMS UA 1000-1 Ed.16) section 4.12.11.
- 4 attributes, 0 method(s); enriched from the IC attribute/method table (deterministic, no model guessing).
