---
id: KB-L3-IC-101-ZIGBEE-SAS-STARTUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee SAS startup
aliases:
- class 101
- CL 101
keywords:
- zigbee sas startup
- class 101
- cl 101
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee SAS startup

## Definition

COSEM interface class defined by Blue Book Part 2 for ZigBee SAS startup objects.

## Aliases

- class 101
- CL 101

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 101,
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
