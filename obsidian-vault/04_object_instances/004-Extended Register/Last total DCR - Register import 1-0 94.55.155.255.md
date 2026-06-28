---
id: KB-ABNT-OBIS-1-0-94-55-155-255-LAST-TOTAL-DCR-REGISTER-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Last total DCR - Register import
aliases:
- OBIS 1-0:94.55.155.255
- Last registered corrected demand
keywords:
- 1-0:94.55.155.255
- Last total DCR - Register import
- Last registered corrected demand
- TBL-000100
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-4-EXTENDED-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-24
---

# Last total DCR - Register import

## Definition

Row-level Extended Register object at logical name `1-0:94.55.155.255`. Last total DCR - Register import.

## Aliases

- OBIS 1-0:94.55.155.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-4-EXTENDED-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-24`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:94.55.155.255",
  "likely_interface_class_id": 4,
  "likely_interface_class_name": "Extended Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "94 utility/country-specific data objects",
    "D": "55 country-specific (Brazil)",
    "E": "155 country-specific object (per ABNT)",
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
      "section": "Last total DCR - Register import at 1-0:94.55.155.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about last total dcr - register import.",
    "ABNT Appendix 9 (NBR 16968:2022) defines this Brazil-specific object as: Last total DCR - Register import. The Blue Book covers only the value-group structure (utility/country-specific); it does not name this object."
  ]
}
```

## Notes
