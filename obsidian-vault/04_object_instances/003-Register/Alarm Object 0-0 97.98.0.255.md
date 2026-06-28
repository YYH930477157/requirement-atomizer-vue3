---
id: KB-ABNT-OBIS-0-0-97-98-0-255-ALARM-OBJECT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Alarm Object
aliases:
- OBIS 0-0:97.98.0.255
- Alarm log
keywords:
- 0-0:97.98.0.255
- Alarm Object
- Alarm log
- TBL-000051
domain_tags:
- cosem_object
- general
- general
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Alarm Object

## Definition

Row-level Register object at logical name `0-0:97.98.0.255`. Alarm log

## Aliases

- OBIS 0-0:97.98.0.255

## Domain Tags

- `cosem_object`
- `general`
- `general`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:97.98.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "97 error/alarm registers",
    "D": "98 alarm register",
    "E": "0 alarm object",
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
      "section": "Alarm Object at 0-0:97.98.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about alarm log.",
    "ABNT Appendix 9 describes this object as: alarm log."
  ]
}
```

## Notes
