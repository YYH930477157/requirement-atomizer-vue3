---
id: KB-L3-IC-74-M-BUS-MASTER-PORT-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus master port setup
aliases:
- class 74
- CL 74
keywords:
- m-bus master port setup
- class 74
- cl 74
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus master port setup

## Definition

COSEM interface class for configuring M-Bus master port setup parameters in DLMS/COSEM devices.

## Aliases

- class 74
- CL 74

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 74,
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
