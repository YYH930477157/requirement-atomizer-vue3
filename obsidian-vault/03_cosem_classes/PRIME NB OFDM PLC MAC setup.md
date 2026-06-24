---
id: KB-L3-IC-82-PRIME-NB-OFDM-PLC-MAC-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PRIME NB OFDM PLC MAC setup
aliases:
- class 82
- CL 82
keywords:
- prime nb ofdm plc mac setup
- class 82
- cl 82
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PRIME NB OFDM PLC MAC setup

## Definition

COSEM interface class for configuring PRIME NB OFDM PLC MAC setup parameters in DLMS/COSEM devices.

## Aliases

- class 82
- CL 82

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 82,
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
