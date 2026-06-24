---
id: KB-L3-IC-66-MEASUREMENT-DATA-MONITORING-OBJECTS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Measurement data monitoring objects
aliases:
- class 66
- CL 66
keywords:
- measurement data monitoring objects
- class 66
- cl 66
domain_tags:
- cosem_class
- measurement_data
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Measurement data monitoring objects

## Definition

COSEM interface class for monitoring or controlling device behavior through Measurement data monitoring objects functions.

## Aliases

- class 66
- CL 66

## Domain Tags

- `cosem_class`
- `measurement_data`
- `control`

## Structured Data

```json metadata
{
  "class_id": 66,
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
