---
id: KB-OBIS-0-1-94-55-110-255-COMMON-EVENT-LOG-FILTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Common Event Log Filter
aliases:
- Common event log filter 0-1:94.55.110.255
keywords:
- 0-1:94.55.110.255
- Common Event Log Filter
- common event log filter
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

# Common Event Log Filter

## Definition

Row-level Data object for the common event log filter at logical name `0-1:94.55.110.255`.

## Aliases

- Common event log filter 0-1:94.55.110.255

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
  "obis_pattern": "0-1:94.55.110.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 utility-specific channel",
    "C": "94 utility-specific data objects",
    "D": "55 event-log filter group",
    "E": "110 common event log filter",
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
      "section": "Common Event Log Filter at 0-1:94.55.110.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching common event log filtering or notification enablement requirements.",
    "ABNT Appendix 9 describes this object as the common event log filter for logging and event notification activation."
  ]
}
```

## Notes
