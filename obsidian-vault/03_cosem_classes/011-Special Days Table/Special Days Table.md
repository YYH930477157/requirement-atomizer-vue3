---
id: KB-L3-IC-11-SPECIAL-DAYS-TABLE
kb_id: energy_metering_cosem_classes
kb_name: COSEM Interface Classes Seed Knowledge Base
kb_version: 0.1.0
type: cosem_interface_class
layer: cosem_class
name: Special Days Table
aliases:
- class 11
- CL 11
keywords:
- class 11
- cl 11
- special days table
- entries
domain_tags:
- cosem_class
- tariff_calendar
- billing_profile
---

# Special Days Table

## Definition

COSEM class containing special day definitions for tariff/calendar behavior.

## Aliases

- class 11
- CL 11

## Domain Tags

- `cosem_class`
- `tariff_calendar`
- `billing_profile`

## Structured Data

```json metadata
{
  "class_id": 11,
  "attributes": [
    {
      "attribute_id": 1,
      "name": "logical_name",
      "type": "octet-string[6]",
      "mandatory": true
    },
    {
      "attribute_id": 2,
      "name": "entries",
      "type": "array",
      "mandatory": true
    }
  ],
  "methods": [
    {
      "method_id": 1,
      "name": "insert"
    },
    {
      "method_id": 2,
      "name": "delete"
    }
  ]
}
```

## Notes

