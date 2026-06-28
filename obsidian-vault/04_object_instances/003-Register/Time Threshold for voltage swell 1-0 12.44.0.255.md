---
id: KB-ABNT-OBIS-1-0-12-44-0-255-TIME-THRESHOLD-FOR-VOLTAGE-SWELL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Time Threshold for voltage swell
aliases:
- OBIS 1-0:12.44.0.255
keywords:
- 1-0:12.44.0.255
- Time Threshold for voltage swell
- TBL-000136
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

# Time Threshold for voltage swell

## Definition

Row-level Register object at logical name `1-0:12.44.0.255`. Time Threshold for voltage swell.

## Aliases

- OBIS 1-0:12.44.0.255

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
  "obis_pattern": "1-0:12.44.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "12 voltage sag/swell (any phase)",
    "D": "44 time threshold (swell)",
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
      "section": "Time Threshold for voltage swell at 1-0:12.44.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about time threshold for voltage swell.",
    "ABNT Appendix 9 describes this object as: Time Threshold for voltage swell."
  ]
}
```

## Notes
