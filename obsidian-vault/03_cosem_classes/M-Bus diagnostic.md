---
id: KB-L3-IC-77-M-BUS-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus diagnostic
aliases:
- class 77
- CL 77
keywords:
- m-bus diagnostic
- class 77
- cl 77
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus diagnostic

## Definition

COSEM interface class for exposing M-Bus diagnostic diagnostic, status, or counter information.

## Aliases

- class 77
- CL 77

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 77,
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
