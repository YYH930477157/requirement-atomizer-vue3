---
id: KB-OBIS-0-0-10-0-106-255-DISCONNECT-SCRIPT-TABLE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Disconnect Script Table
aliases:
- Disconnect Script Table 0-0:10.0.106.255
- Disconnect control script table
keywords:
- 0-0:10.0.106.255
- Disconnect Script Table
- disconnect control script
- disconnect script table
domain_tags:
- cosem_object
- script
- disconnect_control
- switching
relations:
- relation: instance_of
  target: KB-L3-IC-9-SCRIPT-TABLE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Disconnect Script Table

## Definition

Row-level Script Table object for disconnect-control script actions at logical name `0-0:10.0.106.255`.

## Aliases

- Disconnect Script Table 0-0:10.0.106.255
- Disconnect control script table

## Domain Tags

- `cosem_object`
- `script`
- `disconnect_control`
- `switching`

## Relations

- `instance_of` -> `KB-L3-IC-9-SCRIPT-TABLE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:10.0.106.255",
  "likely_interface_class_id": 9,
  "likely_interface_class_name": "Script Table",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "10 Script Table",
    "D": "0 predefined script group",
    "E": "106 disconnect control script table",
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
      "section": "Script Table interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Disconnect Script Table at 0-0:10.0.106.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching script-driven disconnect or reconnect behavior.",
    "Disconnect control Scheduler entries can execute scripts from this table."
  ]
}
```

## Notes
