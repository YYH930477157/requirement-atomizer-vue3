---
id: KB-ABNT-OBIS-1-0-52-32-0-255-NUMBER-OF-VOLTAGE-SAGS-IN-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Number of voltage sags in phase L2
aliases:
- OBIS 1-0:52.32.0.255
keywords:
- 1-0:52.32.0.255
- Number of voltage sags in phase L2
- TBL-000133
domain_tags:
- cosem_object
- ac_electricity
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-1-DATA
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-19
---

# Number of voltage sags in phase L2

## Definition

Row-level Data object at logical name `1-0:52.32.0.255`. Number of voltage sags in phase L2.

## Aliases

- OBIS 1-0:52.32.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-1-DATA`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-19`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:52.32.0.255",
  "likely_interface_class_id": 1,
  "likely_interface_class_name": "Data",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "52 voltage phase L2",
    "D": "32 number/count",
    "E": "0 no tariff/total value",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 19,
    "title": "Value group E codes - AC electricity - UNIPEDE voltage dips"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 19 Value group E codes - AC electricity - UNIPEDE voltage dips"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Number of voltage sags in phase L2 at 1-0:52.32.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about number of voltage sags in phase l2.",
    "ABNT Appendix 9 describes this object as: Number of voltage sags in phase L2."
  ]
}
```

## Notes
