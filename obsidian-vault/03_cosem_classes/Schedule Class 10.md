---
id: KB-L3-IC-10-SCHEDULE
kb_id: energy_metering_cosem_classes
type: cosem_interface_class
layer: cosem_class
name: Schedule
aliases:
- COSEM Schedule
- class 10
- CL 10
keywords:
- schedule
- class 10
- cl 10
- entries
- script logical name
- script selector
domain_tags:
- cosem_class
- schedule
- control
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-PART-2-IC
---

# Schedule

## Definition

COSEM interface class for schedule tables that define scripts to be executed according to configured times or calendar conditions.

## Aliases

- COSEM Schedule
- class 10
- CL 10

## Domain Tags

- `cosem_class`
- `schedule`
- `control`

## Structured Data

```json metadata
{
  "class_id": 10,
  "version": 0,
  "attributes": [
    {"attribute_id": 1, "name": "logical_name", "type": "octet-string[6]", "mandatory": true},
    {"attribute_id": 2, "name": "entries", "type": "array", "mandatory": true}
  ],
  "methods": [
    {"method_id": 1, "name": "enable_disable"}
  ]
}
```

## Notes

