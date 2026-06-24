---
id: KB-L3-IC-65-PARAMETER-MONITOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Parameter monitor
aliases:
- class 65
- CL 65
keywords:
- parameter monitor
- class 65
- cl 65
domain_tags:
- cosem_class
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Parameter monitor

## Definition

COSEM interface class for monitoring or controlling device behavior through Parameter monitor functions.

## Aliases

- class 65
- CL 65

## Domain Tags

- `cosem_class`
- `control`

## Structured Data

```json metadata
{
  "class_id": 65,
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
