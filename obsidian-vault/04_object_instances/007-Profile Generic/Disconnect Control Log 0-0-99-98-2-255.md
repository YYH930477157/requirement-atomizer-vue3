---
id: KB-OBIS-0-0-99-98-2-255-DISCONNECT-CONTROL-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Disconnect Control log
aliases:
- Disconnect control log 0-0:99.98.2.255
- Disconnection control event log
keywords:
- 0-0:99.98.2.255
- Disconnect Control log
- disconnect control log
- disconnection control event log
domain_tags:
- cosem_object
- event
- profile_generic
- control
relations:
- relation: instance_of
  target: KB-L3-IC-7-PROFILE-GENERIC
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-12
---

# Disconnect Control log

## Definition

Row-level COSEM object instance for the Profile generic event log `0-0:99.98.2.255`, used to retain disconnect-control state and threshold-change events.

## Aliases

- Disconnect control log 0-0:99.98.2.255
- Disconnection control event log

## Domain Tags

- `cosem_object`
- `event`
- `profile_generic`
- `control`

## Relations

- `instance_of` -> `KB-L3-IC-7-PROFILE-GENERIC`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-12`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:99.98.2.255",
  "likely_interface_class_id": 7,
  "likely_interface_class_name": "Profile generic",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "99 data profile objects",
    "D": "98 event log",
    "E": "2 disconnect control events",
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
      "section": "Disconnect Control log at 0-0:99.98.2.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching disconnection, reconnection, or disconnect-control event history requirements.",
    "ABNT Appendix 9 describes this log as containing state changes related to disconnection control, including threshold, connection, and disconnection events."
  ]
}
```

## Notes
