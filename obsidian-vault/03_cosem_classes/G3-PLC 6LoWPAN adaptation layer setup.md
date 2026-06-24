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
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC 6LoWPAN adaptation layer setup

## Definition

COSEM interface class for configuring G3-PLC 6LoWPAN adaptation layer setup parameters in DLMS/COSEM devices.

## Aliases

- class 92
- CL 92

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 92,
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
