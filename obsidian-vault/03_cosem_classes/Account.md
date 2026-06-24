---
id: KB-L3-IC-111-ACCOUNT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Account
aliases:
- class 111
- CL 111
keywords:
- account
- class 111
- cl 111
domain_tags:
- cosem_class
- payment_metering
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Account

## Definition

COSEM interface class for payment metering functions related to Account.

## Aliases

- class 111
- CL 111

## Domain Tags

- `cosem_class`
- `payment_metering`

## Structured Data

```json metadata
{
  "class_id": 111,
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
