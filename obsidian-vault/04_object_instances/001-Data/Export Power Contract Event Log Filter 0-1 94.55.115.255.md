---
id: KB-ABNT-OBIS-0-1-94-55-115-255-EXPORT-POWER-CONTRACT-EVENT-LOG-FILTER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Export Power Contract Event Log Filter
aliases:
- OBIS 0-1:94.55.115.255
- Contract Event Log Filter export of energy it contains enabling logging and enabling
keywords:
- 0-1:94.55.115.255
- Export Power Contract Event Log Filter
- Contract Event Log Filter export of energy it contains enabling logging and enabling
domain_tags:
- cosem_object
- general
- event
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# Export Power Contract Event Log Filter

## Definition

Row-level Data object at logical name `0-1:94.55.115.255`. Export power contract event log filter

## Aliases

- OBIS 0-1:94.55.115.255

## Domain Tags

- `cosem_object`
- `general`
- `event`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "0-1:94.55.115.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "general",
  "value_group_mapping": {
    "A": "0 abstract/general",
    "B": "1 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "115 export power contract event log filter",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for error registers, alarm registers and alarm filters - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 OBIS codes for error registers, alarm registers and alarm filters - Abstract"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Export Power Contract Event Log Filter at 0-1:94.55.115.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about export power contract event log filter.",
    "ABNT Appendix 9 describes this object as: export power contract event log filter."
  ]
}
```

## Notes
