---
id: KB-ABNT-OBIS-1-0-32-37-0-255-DURATION-OF-VOLTAGE-SWELLS-IN-PHASE-L1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Duration of voltage swells in phase L1
aliases:
- OBIS 1-0:32.37.0.255
keywords:
- 1-0:32.37.0.255
- Duration of voltage swells in phase L1
- TBL-000137
domain_tags:
- cosem_object
- ac_electricity
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-19
---

# Duration of voltage swells in phase L1

## Definition

Row-level Register object at logical name `1-0:32.37.0.255`. Duration of voltage swells in phase L1.

## Aliases

- OBIS 1-0:32.37.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-19`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:32.37.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "32 voltage phase L1",
    "D": "37 duration (swell)",
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
      "section": "Duration of voltage swells in phase L1 at 1-0:32.37.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about duration of voltage swells in phase l1.",
    "ABNT Appendix 9 describes this object as: Duration of voltage swells in phase L1."
  ]
}
```

## Notes
