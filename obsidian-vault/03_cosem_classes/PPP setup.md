---
id: KB-L3-IC-44-PPP-SETUP
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: PPP setup
aliases:
- class 44
- CL 44
keywords:
- ppp setup
- class 44
- cl 44
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# PPP setup

## Definition

COSEM interface class for configuring PPP setup parameters in DLMS/COSEM devices.

## Aliases

- class 44
- CL 44

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 44,
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
