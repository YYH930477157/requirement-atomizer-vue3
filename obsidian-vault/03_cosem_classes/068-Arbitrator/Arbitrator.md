---
id: KB-L3-IC-68-ARBITRATOR
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Arbitrator
aliases:
- class 68
- CL 68
keywords:
- arbitrator
- class 68
- cl 68
domain_tags:
- cosem_class
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Arbitrator

## Definition

COSEM interface class for monitoring or controlling device behavior through Arbitrator functions.

## Aliases

- class 68
- CL 68

## Domain Tags

- `cosem_class`
- `control`

## Structured Data

```json metadata
{
  "class_id": 68,
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
