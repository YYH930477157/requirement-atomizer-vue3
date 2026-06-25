---
id: KB-L3-IC-132-ISO-IEC-14908-PROTOCOL-STATUS
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: ISO/IEC 14908 protocol status
aliases:
- class 132
- CL 132
keywords:
- iso/iec 14908 protocol status
- class 132
- cl 132
domain_tags:
- cosem_class
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# ISO/IEC 14908 protocol status

## Definition

COSEM interface class for exposing ISO/IEC 14908 protocol status diagnostic, status, or counter information.

## Aliases

- class 132
- CL 132

## Domain Tags

- `cosem_class`

## Structured Data

```json metadata
{
  "class_id": 132,
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
