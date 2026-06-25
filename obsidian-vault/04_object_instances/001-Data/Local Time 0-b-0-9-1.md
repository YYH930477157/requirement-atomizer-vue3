---
id: KB-OBIS-0-B-0-9-1-LOCAL-TIME
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Local time
aliases:
- Local time 0-b:0.9.1
- Device local time
keywords:
- 0-b:0.9.1
- Local time
- device local time
- local time data
domain_tags:
- cosem_object
- timekeeping
- clock
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Local time

## Definition

Row-level OBIS object for the device local time data value, represented by logical name pattern `0-b:0.9.1`.

## Aliases

- Local time 0-b:0.9.1
- Device local time

## Domain Tags

- `cosem_object`
- `timekeeping`
- `clock`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-b:0.9.1",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "b logical-device or channel selector",
    "C": "0 time/date related general object",
    "D": "9 time object group",
    "E": "1 local time"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects: local time 0-b:0.9.1"
    }
  ],
  "applicable_notes": [
    "Use this row as the specific Data-class anchor for requirements that mention local device time.",
    "The B group remains a selector in the table pattern and may be specialized by a concrete device profile."
  ]
}
```

## Notes

