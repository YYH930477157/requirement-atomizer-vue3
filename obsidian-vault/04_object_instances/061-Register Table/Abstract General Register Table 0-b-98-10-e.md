---
id: KB-OBIS-0-B-98-10-E-ABSTRACT-REGISTER-TABLE-GENERAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Abstract general register table
aliases:
- Abstract register table 0-b:98.10.e
- General use abstract register table
keywords:
- 0-b:98.10.e
- Abstract general register table
- general use abstract register table
- abstract register table
domain_tags:
- cosem_object
- register_table
relations:
- relation: instance_of
  target: KB-L3-IC-61-REGISTER-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-11
---

# Abstract general register table

## Definition

Pattern-level row entry for abstract general-use Register table objects, represented by OBIS pattern `0-b:98.10.e`.

## Aliases

- Abstract register table 0-b:98.10.e
- General use abstract register table

## Domain Tags

- `cosem_object`
- `register_table`

## Relations

- `instance_of` -> `KB-L3-IC-61-REGISTER-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-11`

## Structured Data

```json metadata
{
  "obis_pattern": "0-b:98.10.e",
  "likely_interface_class_id": 61,
  "likely_interface_class_name": "Register Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "b channel or logical-device selector",
    "C": "98 register-table object family",
    "D": "10 general use",
    "E": "e register-table selector",
    "F": "not used in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 11,
    "title": "OBIS codes for Register table objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 11 register table objects - Abstract"
    }
  ],
  "applicable_notes": [
    "Register tables hold a number of values of the same type.",
    "Use this abstract pattern when the register table is not tied to a specific medium."
  ]
}
```

## Notes

