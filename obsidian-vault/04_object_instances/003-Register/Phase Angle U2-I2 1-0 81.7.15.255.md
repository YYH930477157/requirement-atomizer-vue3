---
id: KB-ABNT-OBIS-1-0-81-7-15-255-PHASE-ANGLE-U2-I2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Phase Angle U2-I2
aliases:
- OBIS 1-0:81.7.15.255
keywords:
- 1-0:81.7.15.255
- Phase Angle U2-I2
- TBL-000129
domain_tags:
- cosem_object
- ac_electricity
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-17
---

# Phase Angle U2-I2

## Definition

Row-level Register object at logical name `1-0:81.7.15.255`. Phase Angle U2-I2.

## Aliases

- OBIS 1-0:81.7.15.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-17`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:81.7.15.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "81 phase angle",
    "D": "7 instantaneous value",
    "E": "0 no tariff/total value",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 17,
    "title": "Value group E codes - AC electricity - Extended phase angle measurement"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 17 Value group E codes - AC electricity - Extended phase angle measurement"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Phase Angle U2-I2 at 1-0:81.7.15.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about phase angle u2-i2.",
    "ABNT Appendix 9 describes this object as: Phase Angle U2-I2."
  ]
}
```

## Notes
