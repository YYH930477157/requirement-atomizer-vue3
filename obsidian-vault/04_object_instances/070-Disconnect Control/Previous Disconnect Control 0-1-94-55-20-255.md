---
id: KB-OBIS-0-1-94-55-20-255-PREVIOUS-DISCONNECT-CONTROL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Previous Disconnect Control
aliases:
- Previous Disconnect Control 0-1:94.55.20.255
- Previous disconnect control status
keywords:
- 0-1:94.55.20.255
- Previous Disconnect Control
- previous disconnect status
- previous connection status
domain_tags:
- cosem_object
- disconnect_control
- status
- switching
relations:
- relation: instance_of
  target: KB-L3-IC-70-DISCONNECT-CONTROL
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Previous Disconnect Control

## Definition

Row-level Disconnect Control object for previous consumer-premises connection/disconnection status at logical name `0-1:94.55.20.255`.

## Aliases

- Previous Disconnect Control 0-1:94.55.20.255
- Previous disconnect control status

## Domain Tags

- `cosem_object`
- `disconnect_control`
- `status`
- `switching`

## Relations

- `instance_of` -> `KB-L3-IC-70-DISCONNECT-CONTROL`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:94.55.20.255",
  "likely_interface_class_id": 70,
  "likely_interface_class_name": "Disconnect Control",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 previous/status channel",
    "C": "94 utility-specific status objects",
    "D": "55 disconnect-control status group",
    "E": "20 previous disconnect control status",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 8,
    "title": "OBIS codes for general and service entry objects"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 8 general and service entry objects"
    },
    {
      "source": "Blue Book Part 2 Ed. 16",
      "section": "Disconnect Control interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Previous Disconnect Control at 0-1:94.55.20.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching previous disconnection status or historical connection-state requirements.",
    "ABNT Appendix 9 describes this instance as previous status for consumer-premises connection and disconnection."
  ]
}
```

## Notes
