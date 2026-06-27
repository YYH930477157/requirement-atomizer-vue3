---
id: KB-OBIS-0-1-94-55-105-255-STANDARD-EVENT-LOG-FILTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Standard Event Log Filter
aliases:
- Standard event log filter 0-1:94.55.105.255
- Default event log filter
keywords:
- 0-1:94.55.105.255
- Standard Event Log Filter
- standard event log filter
- default event log filter
domain_tags:
- cosem_object
- event
- data_model
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Standard Event Log Filter

## Definition

Row-level Data object for the standard event log filter at logical name `0-1:94.55.105.255`.

## Aliases

- Standard event log filter 0-1:94.55.105.255
- Default event log filter

## Domain Tags

- `cosem_object`
- `event`
- `data_model`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:94.55.105.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 utility-specific channel",
    "C": "94 utility-specific data objects",
    "D": "55 event-log filter group",
    "E": "105 standard event log filter",
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
      "section": "Standard Event Log Filter at 0-1:94.55.105.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching standard log filtering or event notification enablement requirements.",
    "ABNT Appendix 9 describes this object as the default event log filter for logging and notification activation."
  ]
}
```

## Notes
