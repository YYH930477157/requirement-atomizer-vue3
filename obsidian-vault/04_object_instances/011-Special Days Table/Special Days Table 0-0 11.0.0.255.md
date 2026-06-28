---
id: KB-ABNT-OBIS-0-0-11-0-0-255-SPECIAL-DAYS-TABLE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Special Days Table
aliases:
- OBIS 0-0:11.0.0.255
keywords:
- 0-0:11.0.0.255
- Special Days Table
- special days table
- TBL-000044
domain_tags:
- cosem_object
- general
- calendar
relations:
- relation: instance_of
  target: KB-L3-IC-11-SPECIAL-DAYS-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Special Days Table

## Definition

Row-level Special Days Table object defining special-day date exceptions at logical name `0-0:11.0.0.255`.

## Aliases

- OBIS 0-0:11.0.0.255

## Domain Tags

- `cosem_object`
- `general`
- `calendar`

## Relations

- `instance_of` -> `KB-L3-IC-11-SPECIAL-DAYS-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:11.0.0.255",
  "likely_interface_class_id": 11,
  "likely_interface_class_name": "Special Days Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "11 special days table",
    "D": "0",
    "E": "0",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Special Days Table at 0-0:11.0.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements that define holiday/special-day date exceptions overriding the activity calendar.",
    "ABNT Appendix 9 registers this object as the Special Days Table (interface class 11) for the meter."
  ]
}
```

## Notes
