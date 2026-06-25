---
id: KB-OBIS-1-B-98-1-E-255-AC-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AC billing period list 1
aliases:
- AC billing list 1-b:98.1.e.255
- AC electricity billing period data list 1
keywords:
- 1-b:98.1.e.255
- AC billing period list 1
- AC electricity billing period data list
- billing period scheme 1 AC list
domain_tags:
- cosem_object
- ac_electricity
- billing_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-23
---

# AC billing period list 1

## Definition

Pattern-level row entry for AC electricity billing period data list objects using OBIS pattern `1-b:98.1.e.255`.

## Aliases

- AC billing list 1-b:98.1.e.255
- AC electricity billing period data list 1

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `billing_profile`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-23`

## Structured Data

```json metadata
{
  "obis_pattern": "1-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "b channel selector",
    "C": "98 list objects",
    "D": "1 billing period scheme 1",
    "E": "e list selector",
    "F": "255 wildcard for this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 23,
    "title": "OBIS codes for list objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 23 list objects - AC electricity"
    }
  ],
  "applicable_notes": [
    "F=255 is explicitly a wildcard for this AC list-object row.",
    "Use this pattern for AC billing period scheme 1 data list references."
  ]
}
```

## Notes

