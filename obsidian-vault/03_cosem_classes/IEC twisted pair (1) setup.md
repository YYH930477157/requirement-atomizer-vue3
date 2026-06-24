---
id: KB-L3-IC-24-IEC-TWISTED-PAIR-1-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC twisted pair (1) setup
aliases:
- class 24
- CL 24
keywords:
- iec twisted pair (1) setup
- class 24
- cl 24
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC twisted pair (1) setup

## Definition

COSEM interface class for configuring IEC twisted pair (1) setup parameters in DLMS/COSEM devices.

## Aliases

- class 24
- CL 24

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 24,
  "version": 1,
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
