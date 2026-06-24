---
id: KB-L3-IC-55-IEC-61334-4-32-LLC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: IEC 61334-4-32 LLC setup
aliases:
- class 55
- CL 55
keywords:
- iec 61334-4-32 llc setup
- class 55
- cl 55
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# IEC 61334-4-32 LLC setup

## Definition

COSEM interface class for configuring IEC 61334-4-32 LLC setup parameters in DLMS/COSEM devices.

## Aliases

- class 55
- CL 55

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 55,
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
