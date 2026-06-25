---
id: KB-L3-IC-45-GPRS-MODEM-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: GPRS modem setup
aliases:
- class 45
- CL 45
keywords:
- gprs modem setup
- class 45
- cl 45
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# GPRS modem setup

## Definition

COSEM interface class for configuring GPRS modem setup parameters in DLMS/COSEM devices.

## Aliases

- class 45
- CL 45

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 45,
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
