---
id: KB-OBIS-1-B-98-10-E-AC-REGISTER-TABLE-GENERAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AC general register table
aliases:
- AC register table 1-b:98.10.e
- General use AC register table
keywords:
- 1-b:98.10.e
- AC general register table
- general use AC register table
- AC register table objects
domain_tags:
- cosem_object
- ac_electricity
- register_table
relations:
- relation: instance_of
  target: KB-L3-IC-61-REGISTER-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-25
---

# AC general register table

## Definition

Pattern-level row entry for general-use AC electricity Register table objects, represented by OBIS pattern `1-b:98.10.e`.

## Aliases

- AC register table 1-b:98.10.e
- General use AC register table

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `register_table`

## Relations

- `instance_of` -> `KB-L3-IC-61-REGISTER-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-25`

## Structured Data

```json metadata
{
  "obis_pattern": "1-b:98.10.e",
  "likely_interface_class_id": 61,
  "likely_interface_class_name": "Register Table",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "b channel selector",
    "C": "98 list/register-table object family",
    "D": "10 general-use register table",
    "E": "e register-table selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 25,
    "title": "OBIS codes for register table objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 25 register table objects - AC electricity"
    }
  ],
  "applicable_notes": [
    "Register table objects hold a number of values of the same type.",
    "Use this pattern for AC general-use register table rows that do not use the specialized voltage dip or angle-measurement patterns."
  ]
}
```

## Notes

