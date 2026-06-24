---
id: KB-L3-IC-21-REGISTER-MONITOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Register monitor
aliases:
- class 21
- CL 21
keywords:
- register monitor
- class 21
- cl 21
domain_tags:
- cosem_class
- measurement_data
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Register monitor

## Definition

COSEM interface class for monitoring or controlling device behavior through Register monitor functions.

## Aliases

- class 21
- CL 21

## Domain Tags

- `cosem_class`
- `measurement_data`
- `control`

## Structured Data

```json metadata
{
  "class_id": 21,
  "version": 0,
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
