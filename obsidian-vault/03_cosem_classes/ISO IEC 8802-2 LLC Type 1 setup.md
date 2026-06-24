---
id: KB-L3-IC-57-ISO-IEC-8802-2-LLC-TYPE-1-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 8802-2 LLC Type 1 setup
aliases:
- class 57
- CL 57
keywords:
- iso/iec 8802-2 llc type 1 setup
- class 57
- cl 57
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 8802-2 LLC Type 1 setup

## Definition

COSEM interface class for configuring ISO/IEC 8802-2 LLC Type 1 setup parameters in DLMS/COSEM devices.

## Aliases

- class 57
- CL 57

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 57,
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
