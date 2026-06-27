---
id: KB-L3-IC-129-LORAWAN-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
kb_name: BB18
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: LoRaWAN diagnostic
aliases:
- class 129
- CL 129
keywords:
- lorawan diagnostic
- class 129
- cl 129
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# LoRaWAN diagnostic

## Definition

COSEM interface class defined by Blue Book Part 2 Ed. 16 (Chapter 4) for LoRaWAN diagnostic objects.

## Aliases

- class 129
- CL 129

## Domain Tags

- `cosem_class`
- `communication_profile`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-PART-2-IC`

## Structured Data

```json metadata
{
  "class_id": 129,
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

