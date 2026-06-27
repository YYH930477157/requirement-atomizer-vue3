---
id: KB-OBIS-0-0-15-0-1-255-DISCONNECT-CONTROL-SCHEDULER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Disconnect control Scheduler
aliases:
- Disconnect control Scheduler 0-0:15.0.1.255
- Disconnect control single action schedule
keywords:
- 0-0:15.0.1.255
- Disconnect control Scheduler
- disconnect control scheduler
- disconnect single action schedule
domain_tags:
- cosem_object
- schedule
- disconnect_control
- switching
relations:
- relation: instance_of
  target: KB-L3-IC-22-SINGLE-ACTION-SCHEDULE
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-8
---

# Disconnect control Scheduler

## Definition

Row-level Single Action Schedule object for scheduled disconnect-control actions at logical name `0-0:15.0.1.255`.

## Aliases

- Disconnect control Scheduler 0-0:15.0.1.255
- Disconnect control single action schedule

## Domain Tags

- `cosem_object`
- `schedule`
- `disconnect_control`
- `switching`

## Relations

- `instance_of` -> `KB-L3-IC-22-SINGLE-ACTION-SCHEDULE`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-8`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:15.0.1.255",
  "likely_interface_class_id": 22,
  "likely_interface_class_name": "Single Action Schedule",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "15 Single Action Schedule",
    "D": "0 predefined schedule group",
    "E": "1 disconnect control scheduler",
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
      "section": "Single Action Schedule interface class"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Disconnect control Scheduler at 0-0:15.0.1.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching scheduled disconnect or reconnect actions.",
    "This scheduler typically references a Disconnect Script Table entry through executed_script."
  ]
}
```

## Notes
