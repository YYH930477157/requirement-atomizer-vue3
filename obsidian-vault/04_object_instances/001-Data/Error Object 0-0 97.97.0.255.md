---
id: KB-ABNT-OBIS-0-0-97-97-0-255-ERROR-OBJECT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Error Object
aliases:
- OBIS 0-0:97.97.0.255
- Register of error
keywords:
- 0-0:97.97.0.255
- Error Object
- Register of error
- TBL-000051
domain_tags:
- cosem_object
- general
- general
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Error Object

## Definition

Row-level Data object at logical name `0-0:97.97.0.255`. Register of error

## Aliases

- OBIS 0-0:97.97.0.255

## Domain Tags

- `cosem_object`
- `general`
- `general`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:97.97.0.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "97 error/alarm registers",
    "D": "97 error register",
    "E": "0 error object",
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
      "section": "Error Object at 0-0:97.97.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about register of error.",
    "ABNT Appendix 9 describes this object as: register of error."
  ]
}
```

## Notes
