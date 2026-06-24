---
id: KB-L3-IC-112-CREDIT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Credit
aliases:
- class 112
- CL 112
keywords:
- credit
- class 112
- cl 112
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Credit

## Definition

COSEM interface class for payment metering functions related to Credit.

## Aliases

- class 112
- CL 112

## Domain Tags

- `cosem_class`
- `payment_metering`

## Structured Data

```json metadata
{
  "class_id": 112,
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
