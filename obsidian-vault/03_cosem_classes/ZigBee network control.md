---
id: KB-L3-IC-104-ZIGBEE-NETWORK-CONTROL
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee network control
aliases:
- class 104
- CL 104
keywords:
- zigbee network control
- class 104
- cl 104
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee network control

## Definition

COSEM interface class defined by Blue Book Part 2 for ZigBee network control objects.

## Aliases

- class 104
- CL 104

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 104,
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
