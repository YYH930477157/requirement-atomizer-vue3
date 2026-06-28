---
id: KB-ABNT-OBIS-1-1-94-55-100-255-ACTIVE-QUADRANT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active Quadrant
aliases:
- OBIS 1-1:94.55.100.255
keywords:
- 1-1:94.55.100.255
- Active Quadrant
- TBL-000169
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Active Quadrant

## Definition

Row-level Data object at logical name `1-1:94.55.100.255`. Active Quadrant.

## Aliases

- OBIS 1-1:94.55.100.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`
## Structured Data

```json metadata
{
  "obis_pattern": "1-1:94.55.100.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "1 channel 1",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "100 country-specific object (per ABNT)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 24,
    "title": "OBIS codes for data profile objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 24 OBIS codes for data profile objects - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Active Quadrant at 1-1:94.55.100.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about active quadrant.",
    "ABNT Appendix 9 (NBR 16968:2022) defines this Brazil-specific object as: Active Quadrant. The Blue Book covers only the value-group structure (utility/country-specific); it does not name this object."
  ]
}
```

## Notes
