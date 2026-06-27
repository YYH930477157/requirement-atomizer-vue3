---
id: KB-OBIS-0-1-94-55-113-255-SYNCHRONIZATION-EVENT-LOG-FILTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Synchronization Event Log Filter
aliases:
- Synchronization event log filter 0-1:94.55.113.255
- Sync event log filter
keywords:
- 0-1:94.55.113.255
- Synchronization Event Log Filter
- synchronization event log filter
- sync event log filter
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

# Synchronization Event Log Filter

## Definition

Row-level Data object for the synchronization event log filter at logical name `0-1:94.55.113.255`.

## Aliases

- Synchronization event log filter 0-1:94.55.113.255
- Sync event log filter

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
  "obis_pattern": "0-1:94.55.113.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 utility-specific channel",
    "C": "94 utility-specific data objects",
    "D": "55 event-log filter group",
    "E": "113 synchronization event log filter",
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
      "section": "Synchronization Event Log Filter at 0-1:94.55.113.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching synchronization event log filtering or notification enablement requirements.",
    "ABNT Appendix 9 describes this object as the synchronization event log filter for logging and event notification activation."
  ]
}
```

## Notes
