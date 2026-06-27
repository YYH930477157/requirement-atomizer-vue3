---
id: KB-OBIS-0-0-99-98-5-255-POWER-QUALITY-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Power Quality Event Log
aliases:
- Power quality event log 0-0:99.98.5.255
- Power quality log profile
keywords:
- 0-0:99.98.5.255
- Power Quality Event Log
- power quality event log
- power quality log profile
domain_tags:
- cosem_object
- event
- power_quality
- profile_generic
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Power Quality Event Log

## Definition

Row-level COSEM object instance for the Profile generic event log `0-0:99.98.5.255`, used to retain power-quality events.

## Aliases

- Power quality event log 0-0:99.98.5.255
- Power quality log profile

## Domain Tags

- `cosem_object`
- `event`
- `power_quality`
- `profile_generic`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:99.98.5.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "99 data profile objects",
    "D": "98 event log",
    "E": "5 power quality events",
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
      "section": "Power Quality Event Log at 0-0:99.98.5.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching power-quality event history requirements.",
    "ABNT Appendix 9 describes this object as the non-finalized power quality event log and pairs it with finished and non-finished event-log filters."
  ]
}
```

## Notes

