---
id: KB-OBIS-2-B-98-10-E-DC-REGISTER-TABLE-GENERAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC general register table
aliases:
- DC register table 2-b:98.10.e
- General use DC register table
keywords:
- 2-b:98.10.e
- DC general register table
- general use DC register table
- DC register table objects
domain_tags:
- cosem_object
- dc_electricity
- register_table
relations:
- relation: instance_of
  target: KB-L3-IC-61-REGISTER-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-33
---

# DC general register table

## Definition

Pattern-level row entry for general-use DC electricity Register table objects, represented by OBIS pattern `2-b:98.10.e`.

## Aliases

- DC register table 2-b:98.10.e
- General use DC register table

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `register_table`

## Relations

- `instance_of` -> `KB-L3-IC-61-REGISTER-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-33`

## Structured Data

```json metadata
{
  "obis_pattern": "2-b:98.10.e",
  "likely_interface_class_id": 61,
  "likely_interface_class_name": "Register Table",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "b channel selector",
    "C": "98 list/register-table object family",
    "D": "10 general-use register table",
    "E": "e register-table selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 33,
    "title": "OBIS codes for Register table objects - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 33 register table objects - DC electricity"
    }
  ],
  "applicable_notes": [
    "Register table objects hold a number of values of the same type.",
    "Use this pattern for general-use DC register table rows."
  ]
}
```

## Notes

