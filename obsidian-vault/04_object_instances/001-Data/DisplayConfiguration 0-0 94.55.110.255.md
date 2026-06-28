---
id: KB-ABNT-OBIS-0-0-94-55-110-255-DISPLAYCONFIGURATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Common Event Log Filter
aliases:
- OBIS 0-0:94.55.110.255
keywords:
- 0-0:94.55.110.255
- DisplayConfiguration
- TBL-000071
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

# Common Event Log Filter

## Definition

Row-level Data object at logical name `0-0:94.55.110.255`. Common event log filter containing enabling logging and notification of events

## Aliases

- OBIS 0-0:94.55.110.255

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
  "obis_pattern": "0-0:94.55.110.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "110 common event log filter",
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
      "section": "Common Event Log Filter at 0-0:94.55.110.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about common event log filter containing enabling logging and notification of events.",
    "ABNT Appendix 9 describes this object as: common event log filter containing enabling logging and notification of events."
  ]
}
```

## Notes
