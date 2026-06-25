---
id: KB-L3-IC-140-HS-PLC-ISO-IEC-12139-1-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: HS-PLC ISO/IEC 12139-1 MAC setup
aliases:
- class 140
- CL 140
keywords:
- hs-plc iso/iec 12139-1 mac setup
- class 140
- cl 140
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# HS-PLC ISO/IEC 12139-1 MAC setup

## Definition

COSEM interface class for configuring HS-PLC ISO/IEC 12139-1 MAC setup parameters in DLMS/COSEM devices.

## Aliases

- class 140
- CL 140

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 140,
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
