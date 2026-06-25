---
id: KB-L3-IC-76-DLMS-SERVER-M-BUS-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: DLMS server M-Bus port setup
aliases:
- class 76
- CL 76
keywords:
- dlms server m-bus port setup
- class 76
- cl 76
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# DLMS server M-Bus port setup

## Definition

COSEM interface class for configuring DLMS server M-Bus port setup parameters in DLMS/COSEM devices.

## Aliases

- class 76
- CL 76

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 76,
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
