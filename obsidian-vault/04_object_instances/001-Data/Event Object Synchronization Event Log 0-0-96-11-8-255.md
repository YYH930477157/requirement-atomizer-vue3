---
id: KB-OBIS-0-0-96-11-8-255-EVENT-OBJECT-SYNCHRONIZATION-EVENT-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Event Object - Synchronization Event Log
aliases:
- Event Object - Synchronization Event Log 0-0:96.11.8.255
- Synchronization event object
keywords:
- 0-0:96.11.8.255
- Event Object - Synchronization Event Log
- synchronization event object
- time synchronization event value
domain_tags:
- cosem_object
- event
- data_model
- timekeeping
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Event Object - Synchronization Event Log

## Definition

Row-level Data object for the event value captured by the synchronization event log, specialized to logical name `0-0:96.11.8.255`.

## Aliases

- Event Object - Synchronization Event Log 0-0:96.11.8.255
- Synchronization event object

## Domain Tags

- `cosem_object`
- `event`
- `data_model`
- `timekeeping`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.11.8.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device", 
    "C": "96 data and identification objects",
    "D": "11 event object group",
    "E": "8 synchronization events",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for data objects - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 data objects - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Event Object - Synchronization Event Log at 0-0:96.11.8.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching synchronization event values captured by the synchronization Profile generic.",
    "ABNT Appendix 9 captures this Data object together with Clock and the synchronization event-log filter."
  ]
}
```

## Notes
