---
id: KB-ABNT-OBIS-1-0-94-55-184-255-TIME-TRIGGER-FOR-MONTHLY-DRP-DRC-CALCULATION
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time trigger for monthly DRP/DRC calculation
aliases:
- OBIS 1-0:94.55.184.255
- Time stamp for the log in DRP It is CKD monthly
keywords:
- 1-0:94.55.184.255
- Time trigger for monthly DRP/DRC calculation
- Time stamp for the log in DRP It is CKD monthly
- TBL-000144
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Time trigger for monthly DRP/DRC calculation

## Definition

Row-level Data object at logical name `1-0:94.55.184.255`. Time trigger for monthly DRP/DRC calculation.

## Aliases

- OBIS 1-0:94.55.184.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.184.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "184 country-specific object (per ABNT)",
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
      "section": "Time trigger for monthly DRP/DRC calculation at 1-0:94.55.184.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about time trigger for monthly drp/drc calculation.",
    "ABNT Appendix 9 (NBR 16968:2022) defines this Brazil-specific object as: Time trigger for monthly DRP/DRC calculation. The Blue Book covers only the value-group structure (utility/country-specific); it does not name this object."
  ]
}
```

## Notes
