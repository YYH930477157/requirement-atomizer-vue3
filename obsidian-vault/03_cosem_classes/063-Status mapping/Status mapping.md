---
id: KB-L3-IC-63-STATUS-MAPPING
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Status mapping
aliases:
- class 63
- CL 63
keywords:
- status mapping
- class 63
- cl 63
domain_tags:
- cosem_class
- measurement_data
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Status mapping

## Definition

COSEM interface class for exposing Status mapping diagnostic, status, or counter information.

## Aliases

- class 63
- CL 63

## Domain Tags

- `cosem_class`
- `measurement_data`

## Structured Data

```json metadata
{
  "class_id": 63,
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
