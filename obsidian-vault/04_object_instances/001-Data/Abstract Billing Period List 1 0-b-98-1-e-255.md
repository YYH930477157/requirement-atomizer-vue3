---
id: KB-OBIS-0-B-98-1-E-255-ABSTRACT-BILLING-LIST-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Abstract billing period list 1
aliases:
- Data of billing period scheme 1
- Abstract billing list 0-b:98.1.e.255
keywords:
- 0-b:98.1.e.255
- Abstract billing period list 1
- data of billing period scheme 1
- abstract billing list
domain_tags:
- cosem_object
- billing_profile
relations:
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-10
---

# Abstract billing period list 1

## Definition

Pattern-level row entry for abstract billing period data list objects using OBIS pattern `0-b:98.1.e.255`.

## Aliases

- Data of billing period scheme 1
- Abstract billing list 0-b:98.1.e.255

## Domain Tags

- `cosem_object`
- `billing_profile`

## Relations

- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-10`

## Structured Data

```json metadata
{
  "obis_pattern": "0-b:98.1.e.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "b channel or logical-device selector",
    "C": "98 list objects",
    "D": "1 billing period scheme 1",
    "E": "e list selector",
    "F": "255 wildcard for this table row"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 10,
    "title": "OBIS codes for list objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 10 list objects - Abstract"
    }
  ],
  "applicable_notes": [
    "F=255 means wildcard for this billing-period list row.",
    "Use this abstract pattern when a billing-period list is not specific to a media type."
  ]
}
```

## Notes

