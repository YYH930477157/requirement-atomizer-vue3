---
id: KB-L3-IC-161-G3-PLC-HYBRID-RF-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: G3-PLC Hybrid RF MAC setup
aliases:
- class 161
- CL 161
keywords:
- g3-plc hybrid rf mac setup
- class 161
- cl 161
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# G3-PLC Hybrid RF MAC setup

## Definition

COSEM interface class for configuring G3-PLC Hybrid RF MAC setup parameters in DLMS/COSEM devices.

## Aliases

- class 161
- CL 161

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 161,
  "version": 1,
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
