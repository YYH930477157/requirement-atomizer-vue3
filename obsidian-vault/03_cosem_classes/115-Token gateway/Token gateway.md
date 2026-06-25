---
id: KB-L3-IC-115-TOKEN-GATEWAY
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Token gateway
aliases:
- class 115
- CL 115
keywords:
- token gateway
- class 115
- cl 115
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Token gateway

## Definition

COSEM interface class for payment metering functions related to Token gateway.

## Aliases

- class 115
- CL 115

## Domain Tags

- `cosem_class`
- `payment_metering`

## Structured Data

```json metadata
{
  "class_id": 115,
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
