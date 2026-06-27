---
id: KB-L3-IC-95-WI-SUN-SETUP
kb_id: energy_metering_cosem_classes
kb_name: BB18
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Wi-SUN setup
aliases:
- class 95
- CL 95
keywords:
- wi-sun setup
- class 95
- cl 95
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Wi-SUN setup

## Definition

COSEM interface class defined by Blue Book Part 2 Ed. 16 (Chapter 4) for Wi-SUN setup objects.

## Aliases

- class 95
- CL 95

## Domain Tags

- `cosem_class`
- `communication_profile`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-PART-2-IC`

## Structured Data

```json metadata
{
  "class_id": 95,
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

