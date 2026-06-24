---
id: KB-L3-IC-58-ISO-IEC-8802-2-LLC-TYPE-2-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 8802-2 LLC Type 2 setup
aliases:
- class 58
- CL 58
keywords:
- iso/iec 8802-2 llc type 2 setup
- class 58
- cl 58
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 8802-2 LLC Type 2 setup

## Definition

COSEM interface class for configuring ISO/IEC 8802-2 LLC Type 2 setup parameters in DLMS/COSEM devices.

## Aliases

- class 58
- CL 58

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 58,
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
