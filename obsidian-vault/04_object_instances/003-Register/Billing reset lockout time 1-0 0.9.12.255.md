---
id: KB-ABNT-OBIS-1-0-0-9-12-255-BILLING-RESET-LOCKOUT-TIME
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Billing reset lockout time
aliases:
- OBIS 1-0:0.9.12.255
keywords:
- 1-0:0.9.12.255
- Billing reset lockout time
- TBL-000172
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-21
---

# Billing reset lockout time

## Definition

Row-level Register object at logical name `1-0:0.9.12.255`. Period from lock to reset after any reset

## Aliases

- OBIS 1-0:0.9.12.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-21`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.9.12.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "0 general and service-entry object",
    "D": "9 instantaneous/status",
    "E": "12",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 21,
    "title": "OBIS codes for general and service entry objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 21 OBIS codes for general and service entry objects - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Billing reset lockout time at 1-0:0.9.12.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about period from lock to reset after any reset.",
    "ABNT Appendix 9 describes this object as: period from lock to reset after any reset."
  ]
}
```

## Notes
