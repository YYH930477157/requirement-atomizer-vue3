---
id: KB-L3-IC-12-ASSOCIATION-SN
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Association SN
aliases:
- class 12
- CL 12
keywords:
- association sn
- class 12
- cl 12
domain_tags:
- cosem_class
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Association SN

## Definition

COSEM interface class defined by Blue Book Part 2 for Association SN objects.

## Aliases

- class 12
- CL 12

## Domain Tags

- `cosem_class`
- `access_control`

## Structured Data

```json metadata
{
  "class_id": 12,
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
