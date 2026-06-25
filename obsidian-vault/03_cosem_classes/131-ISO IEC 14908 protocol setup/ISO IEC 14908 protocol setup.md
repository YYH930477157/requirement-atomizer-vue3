---
id: KB-L3-IC-131-ISO-IEC-14908-PROTOCOL-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 protocol setup
aliases:
- class 131
- CL 131
keywords:
- iso/iec 14908 protocol setup
- class 131
- cl 131
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 protocol setup

## Definition

COSEM interface class for configuring ISO/IEC 14908 protocol setup parameters in DLMS/COSEM devices.

## Aliases

- class 131
- CL 131

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 131,
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
