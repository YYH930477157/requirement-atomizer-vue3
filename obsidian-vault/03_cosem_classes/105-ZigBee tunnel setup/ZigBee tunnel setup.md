---
id: KB-L3-IC-105-ZIGBEE-TUNNEL-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ZigBee tunnel setup
aliases:
- class 105
- CL 105
keywords:
- zigbee tunnel setup
- class 105
- cl 105
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ZigBee tunnel setup

## Definition

COSEM interface class for configuring ZigBee tunnel setup parameters in DLMS/COSEM devices.

## Aliases

- class 105
- CL 105

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 105,
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
