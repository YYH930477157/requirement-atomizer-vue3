---
id: KB-OBIS-0-1-96-3-10-255-DISCONNECT-CONTROL-AUX-RELAY
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Disconnect Control for Aux. relay
aliases:
- Disconnect Control for Aux. relay 0-1:96.3.10.255
- Auxiliary relay disconnect control
keywords:
- 0-1:96.3.10.255
- Disconnect Control for Aux. relay
- auxiliary relay disconnect control
- aux relay disconnect control
domain_tags:
- cosem_object
- disconnect_control
- auxiliary_relay
- switching
relations:
- relation: instance_of
  target: KB-L3-IC-70-DISCONNECT-CONTROL
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Disconnect Control for Aux. relay

## Definition

Row-level Disconnect Control object for auxiliary relay connection and disconnection at logical name `0-1:96.3.10.255`.

## Aliases

- Disconnect Control for Aux. relay 0-1:96.3.10.255
- Auxiliary relay disconnect control

## Domain Tags

- `cosem_object`
- `disconnect_control`
- `auxiliary_relay`
- `switching`

## Relations

- `instance_of` -> `KB-L3-IC-70-DISCONNECT-CONTROL`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:96.3.10.255",
  "likely_interface_class_id": 70,
  "likely_interface_class_name": "Disconnect Control",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 auxiliary relay channel",
    "C": "96 internal control and status objects",
    "D": "3 disconnect control group",
    "E": "10 auxiliary relay disconnect control",
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
      "section": "Disconnect Control for Aux. relay at 0-1:96.3.10.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching auxiliary relay output_state, control_state, control_mode, or relay switching requirements.",
    "ABNT Appendix 9 describes this instance as controlling connection and disconnection of auxiliary relays."
  ]
}
```

## Notes
