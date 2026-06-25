---
id: KB-L3-IC-133-ISO-IEC-14908-DIAGNOSTIC
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 diagnostic
aliases:
- class 133
- CL 133
keywords:
- iso/iec 14908 diagnostic
- class 133
- cl 133
domain_tags:
- cosem_class
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 diagnostic

## Definition

COSEM interface class for exposing ISO/IEC 14908 diagnostic diagnostic, status, or counter information.

## Aliases

- class 133
- CL 133

## Domain Tags

- `cosem_class`

## Structured Data

```json metadata
{
  "class_id": 133,
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
