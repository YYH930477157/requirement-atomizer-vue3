---
id: KB-ABNT-OBIS-1-0-94-55-145-255-LAST-UFER-TOTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Last UFER - total
aliases:
- OBIS 1-0:94.55.145.255
- Value absolute
keywords:
- 1-0:94.55.145.255
- Last UFER - total
- Value absolute
- TBL-000086
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Last UFER - total

## Definition

Row-level Register object at logical name `1-0:94.55.145.255`. Last UFER - total.

## Aliases

- OBIS 1-0:94.55.145.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.145.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "145 country-specific object (per ABNT)",
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
      "section": "Last UFER - total at 1-0:94.55.145.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about last ufer - total.",
    "ABNT Appendix 9 (NBR 16968:2022) defines this Brazil-specific object as: Last UFER - total. The Blue Book covers only the value-group structure (utility/country-specific); it does not name this object."
  ]
}
```

## Notes
