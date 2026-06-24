---
id: KB-L3-IC-80-61334-4-32-LLC-SSCS-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: 61334-4-32 LLC SSCS setup
aliases:
- class 80
- CL 80
keywords:
- 61334-4-32 llc sscs setup
- class 80
- cl 80
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# 61334-4-32 LLC SSCS setup

## Definition

COSEM interface class for configuring 61334-4-32 LLC SSCS setup parameters in DLMS/COSEM devices.

## Aliases

- class 80
- CL 80

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 80,
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
