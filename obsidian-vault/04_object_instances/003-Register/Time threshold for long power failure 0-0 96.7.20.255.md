---
id: KB-ABNT-OBIS-0-0-96-7-20-255-TIME-THRESHOLD-FOR-LONG-POWER-FAILURE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time threshold for long power failure
aliases:
- OBIS 0-0:96.7.20.255
keywords:
- 0-0:96.7.20.255
- Time threshold for long power failure
- TBL-000047
domain_tags:
- cosem_object
- general
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Time threshold for long power failure

## Definition

Row-level Register object at logical name `0-0:96.7.20.255`. Time threshold for long power failure

## Aliases

- OBIS 0-0:96.7.20.255

## Domain Tags

- `cosem_object`
- `general`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.7.20.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "7 power failure counters",
    "E": "20 long power-failure time threshold",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for error registers, alarm registers and alarm filters - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 OBIS codes for error registers, alarm registers and alarm filters - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Time threshold for long power failure at 0-0:96.7.20.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about time threshold for long power failure.",
    "ABNT Appendix 9 describes this object as: time threshold for long power failure."
  ]
}
```

## Notes
