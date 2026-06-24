---
id: KB-L3-IC-30-COSEM-DATA-PROTECTION
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: COSEM data protection
aliases:
- class 30
- CL 30
keywords:
- cosem data protection
- class 30
- cl 30
domain_tags:
- cosem_class
- measurement_data
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# COSEM data protection

## Definition

COSEM interface class defined by Blue Book Part 2 for COSEM data protection objects.

## Aliases

- class 30
- CL 30

## Domain Tags

- `cosem_class`
- `measurement_data`
- `access_control`

## Structured Data

```json metadata
{
  "class_id": 30,
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
