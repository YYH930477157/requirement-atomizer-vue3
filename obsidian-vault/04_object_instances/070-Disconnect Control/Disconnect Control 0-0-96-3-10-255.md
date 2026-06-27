---
id: KB-OBIS-0-0-96-3-10-255-DISCONNECT-CONTROL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Disconnect Control
aliases:
- Disconnect Control 0-0:96.3.10.255
- Consumer premises disconnect control
keywords:
- 0-0:96.3.10.255
- Disconnect Control
- consumer premises disconnect control
- remote disconnect control
domain_tags:
- cosem_object
- disconnect_control
- load_control
- switching
relations:
- relation: instance_of
  target: KB-L3-IC-70-DISCONNECT-CONTROL
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Disconnect Control

## Definition

Row-level Disconnect Control object for consumer premises connection and disconnection at logical name `0-0:96.3.10.255`.

## Aliases

- Disconnect Control 0-0:96.3.10.255
- Consumer premises disconnect control

## Domain Tags

- `cosem_object`
- `disconnect_control`
- `load_control`
- `switching`

## Relations

- `instance_of` -> `KB-L3-IC-70-DISCONNECT-CONTROL`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.3.10.255",
  "likely_interface_class_id": 70,
  "likely_interface_class_name": "Disconnect Control",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "96 internal control and status objects",
    "D": "3 disconnect control group",
    "E": "10 consumer premises disconnect control",
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
      "section": "Disconnect Control at 0-0:96.3.10.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching connect/disconnect state, output_state, control_state, control_mode, remote_disconnect, or remote_reconnect requirements.",
    "ABNT Appendix 9 describes this instance as controlling connection and disconnection of consumer facilities."
  ]
}
```

## Notes
