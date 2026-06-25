---
id: KB-OBIS-2-B-98-1-E-255-DC-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC billing period list 1
aliases:
- DC billing list 2-b:98.1.e.255
- DC electricity billing period data list 1
keywords:
- 2-b:98.1.e.255
- DC billing period list 1
- DC electricity billing period data list
- billing period scheme 1 DC list
domain_tags:
- cosem_object
- dc_electricity
- billing_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-31
---

# DC billing period list 1

## Definition

Pattern-level row entry for DC electricity billing period data list objects using OBIS pattern `2-b:98.1.e.255`.

## Aliases

- DC billing list 2-b:98.1.e.255
- DC electricity billing period data list 1

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `billing_profile`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-31`

## Structured Data

```json metadata
{
  "obis_pattern": "2-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "b channel selector",
    "C": "98 list objects",
    "D": "1 billing period scheme 1",
    "E": "e list selector",
    "F": "255 wildcard in this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 31,
    "title": "OBIS codes for list objects - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 31 list objects - DC electricity"
    }
  ],
  "applicable_notes": [
    "F=255 is explicitly used as a wildcard for this list-object row.",
    "The concrete interface class can be companion-specific; this KB row uses Data as the conservative fallback."
  ]
}
```

## Notes

