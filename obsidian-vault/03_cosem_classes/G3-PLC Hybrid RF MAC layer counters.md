---
id: KB-L3-IC-160-G3-PLC-HYBRID-RF-MAC-LAYER-COUNTERS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC Hybrid RF MAC layer counters
aliases:
- class 160
- CL 160
keywords:
- g3-plc hybrid rf mac layer counters
- class 160
- cl 160
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC Hybrid RF MAC layer counters

## Definition

COSEM interface class for exposing G3-PLC Hybrid RF MAC layer counters diagnostic, status, or counter information.

## Aliases

- class 160
- CL 160

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 160,
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
