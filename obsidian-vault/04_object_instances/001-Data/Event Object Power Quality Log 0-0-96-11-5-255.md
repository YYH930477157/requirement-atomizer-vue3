---
id: KB-OBIS-0-0-96-11-5-255-EVENT-OBJECT-POWER-QUALITY-LOG
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Event Object - Power Quality Log
aliases:
- Event Object - Power Quality Log 0-0:96.11.5.255
- Power quality event object
keywords:
- 0-0:96.11.5.255
- Event Object - Power Quality Log
- power quality event object
- power quality event value
domain_tags:
- cosem_object
- event
- power_quality
- data_model
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Event Object - Power Quality Log

## Definition

Row-level Data object for the event value captured by the power quality event log, specialized to logical name `0-0:96.11.5.255`.

## Aliases

- Event Object - Power Quality Log 0-0:96.11.5.255
- Power quality event object

## Domain Tags

- `cosem_object`
- `event`
- `power_quality`
- `data_model`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-0:96.11.5.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "0 management logical device",
    "C": "96 data and identification objects",
    "D": "11 event object group",
    "E": "5 power quality events",
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
      "section": "Event Object - Power Quality Log at 0-0:96.11.5.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching power-quality event values captured by a power quality Profile generic.",
    "ABNT Appendix 9 captures this Data object together with the power quality event log filters."
  ]
}
```

## Notes

