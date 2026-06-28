---
id: KB-ABNT-OBIS-1-0-32-49-0-255-AVERAGE-VOLTAGE-PHASE-R-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Average voltage PHASE R - period 1
aliases:
- OBIS 1-0:32.49.0.255
keywords:
- 1-0:32.49.0.255
- Average voltage PHASE R - period 1
- TBL-000148
domain_tags:
- cosem_object
- ac_electricity
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Average voltage PHASE R - period 1

## Definition

Row-level Register object at logical name `1-0:32.49.0.255`. Average voltage PHASE R - period 1.

## Aliases

- OBIS 1-0:32.49.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:32.49.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "32 voltage phase L1",
    "D": "49 average - period 1",
    "E": "0 no tariff/total value",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 14,
    "title": "Value group D codes - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 Value group D codes - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Average voltage PHASE R - period 1 at 1-0:32.49.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about average voltage phase r - period 1.",
    "ABNT Appendix 9 describes this object as: Average voltage PHASE R - period 1."
  ]
}
```

## Notes
