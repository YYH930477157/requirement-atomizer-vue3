---
id: KB-L3-IC-19-IEC-LOCAL-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC local port setup
aliases:
- class 19
- CL 19
keywords:
- iec local port setup
- class 19
- cl 19
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC local port setup

## Definition

COSEM interface class for configuring IEC local port setup parameters in DLMS/COSEM devices.

## Aliases

- class 19
- CL 19

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 19,
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
