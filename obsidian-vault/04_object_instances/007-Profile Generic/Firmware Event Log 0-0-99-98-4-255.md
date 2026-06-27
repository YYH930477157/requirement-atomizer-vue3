---
id: KB-OBIS-0-0-99-98-4-255-FIRMWARE-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Firmware Event Log
aliases:
- Firmware event log 0-0:99.98.4.255
- Firmware upgrade event log
keywords:
- 0-0:99.98.4.255
- Firmware Event Log
- firmware event log
- firmware upgrade event profile
domain_tags:
- cosem_object
- event
- firmware
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Firmware Event Log

## Definition

Row-level COSEM object instance for the Profile generic event log `0-0:99.98.4.255`, used to retain firmware-related events.

## Aliases

- Firmware event log 0-0:99.98.4.255
- Firmware upgrade event log

## Domain Tags

- `cosem_object`
- `event`
- `firmware`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:99.98.4.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "99 data profile objects",
    "D": "98 event log",
    "E": "4 firmware events",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 12,
    "title": "OBIS codes for data profile objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 12 data profile objects - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Firmware Event Log at 0-0:99.98.4.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements for firmware event history or firmware activation logging.",
    "ABNT Appendix 9 configures this Profile generic with a firmware event object and a firmware event-log filter."
  ]
}
```

## Notes

