---
id: KB-L3-IC-122-FUNCTION-CONTROL
kb_id: energy_metering_cosem_classes
kb_name: BB18
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Function control
aliases:
- class 122
- CL 122
keywords:
- function control
- class 122
- cl 122
domain_tags:
- cosem_class
- access_control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Function control

## Definition

COSEM interface class defined by Blue Book Part 2 Ed. 16 (Chapter 4) for Function control objects.

## Aliases

- class 122
- CL 122

## Domain Tags

- `cosem_class`
- `access_control`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-PART-2-IC`

## Structured Data

```json metadata
{
  "class_id": 122,
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
  "coverage_note": "Seeded from the Blue Book Part 2 Ed. 16 current interface class catalogue (Chapter 4); attribute and method details should be expanded during detailed knowledge-base enrichment."
}
```

## Notes

