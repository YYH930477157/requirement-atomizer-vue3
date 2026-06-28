---
id: KB-ABNT-OBIS-0-0-96-11-10-255-EVENT-OBJECT-EXPORT-POWER-CONTRACT-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Export Power Contract Event Log
aliases:
- OBIS 0-0:96.11.10.255
keywords:
- 0-0:96.11.10.255
- Event Object - Export Power Contract Event Log
- TBL-000055
domain_tags:
- cosem_object
- general
- event
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Export Power Contract Event Log

## Definition

Row-level Data object at logical name `0-0:96.11.10.255`. Event object - export power contract event log

## Aliases

- OBIS 0-0:96.11.10.255

## Domain Tags

- `cosem_object`
- `general`
- `event`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.11.10.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "96 abstract general data objects",
    "D": "11 event log",
    "E": "10 export power contract event log",
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
      "section": "Export Power Contract Event Log at 0-0:96.11.10.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about event object - export power contract event log.",
    "ABNT Appendix 9 describes this object as: event object - export power contract event log."
  ]
}
```

## Notes
