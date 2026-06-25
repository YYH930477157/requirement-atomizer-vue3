---
id: KB-L3-IC-91-G3-PLC-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC MAC setup
aliases:
- class 91
- CL 91
keywords:
- g3-plc mac setup
- class 91
- cl 91
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC MAC setup

## Definition

COSEM interface class for configuring G3-PLC MAC setup parameters in DLMS/COSEM devices.

## Aliases

- class 91
- CL 91

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 91,
  "version": 4,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    }
  ],
  "methods": [],
  "coverage_level": "catalogue_seed",
  "coverage_note": "Seeded from the Blue Book Part 2 current interface class catalogue; attribute and method details should be expanded during detailed knowledge-base enrichment."
}
```

## Notes
