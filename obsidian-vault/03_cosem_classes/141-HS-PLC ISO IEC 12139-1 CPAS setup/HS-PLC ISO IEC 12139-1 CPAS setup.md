---
id: KB-L3-IC-141-HS-PLC-ISO-IEC-12139-1-CPAS-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: HS-PLC ISO/IEC 12139-1 CPAS setup
aliases:
- class 141
- CL 141
keywords:
- hs-plc iso/iec 12139-1 cpas setup
- class 141
- cl 141
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# HS-PLC ISO/IEC 12139-1 CPAS setup

## Definition

COSEM interface class for configuring HS-PLC ISO/IEC 12139-1 CPAS setup parameters in DLMS/COSEM devices.

## Aliases

- class 141
- CL 141

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 141,
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
