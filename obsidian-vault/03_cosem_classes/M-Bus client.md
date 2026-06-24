---
id: KB-L3-IC-72-M-BUS-CLIENT
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: M-Bus client
aliases:
- class 72
- CL 72
keywords:
- m-bus client
- class 72
- cl 72
domain_tags:
- cosem_class
- communication_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# M-Bus client

## Definition

COSEM interface class defined by Blue Book Part 2 for M-Bus client objects.

## Aliases

- class 72
- CL 72

## Domain Tags

- `cosem_class`
- `communication_profile`

## Structured Data

```json metadata
{
  "class_id": 72,
  "version": 2,
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
