---
id: KB-OBIS-0-0-13-0-0-255-ACTIVITY-CALENDAR
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Activity Calendar
aliases:
- Activity Calendar 0-0:13.0.0.255
- tariff activity calendar
keywords:
- 0-0:13.0.0.255
- Activity Calendar
- tariff activity calendar
- calendar_name_active
- activate_passive_calendar_time
domain_tags:
- cosem_object
- tariff_calendar
- billing_profile
relations:
- relation: instance_of
  target: KB-L3-IC-20-ACTIVITY-CALENDAR
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Activity Calendar

## Definition

Row-level COSEM object instance for the tariff Activity Calendar logical name `0-0:13.0.0.255`, used to manage active and passive calendar structures.

## Aliases

- Activity Calendar 0-0:13.0.0.255
- tariff activity calendar

## Domain Tags

- `cosem_object`
- `tariff_calendar`
- `billing_profile`

## Relations

- `instance_of` -> `KB-L3-IC-20-ACTIVITY-CALENDAR`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:13.0.0.255",
  "likely_interface_class_id": 20,
  "likely_interface_class_name": "Activity Calendar",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "13 activity calendar",
    "D": "0 default instance",
    "E": "0 default instance",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "4.5.5 Activity calendar (class_id = 20)"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Activity Calendar row"
    }
  ],
  "applicable_notes": [
    "ABNT Appendix 9 uses this object with class_id 20 and value 0-0:13.0.0.255.",
    "Use this instance for requirements about active/passive tariff calendar tables."
  ]
}
```

## Notes
