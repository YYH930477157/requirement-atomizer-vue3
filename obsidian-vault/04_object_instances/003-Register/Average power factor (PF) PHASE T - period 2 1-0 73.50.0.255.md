---
id: KB-ABNT-OBIS-1-0-73-50-0-255-AVERAGE-POWER-FACTOR-PF-PHASE-T-PERIOD-2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Average power factor (PF) PHASE T - period 2
aliases:
- OBIS 1-0:73.50.0.255
keywords:
- 1-0:73.50.0.255
- Average power factor (PF) PHASE T - period 2
- TBL-000154
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Average power factor (PF) PHASE T - period 2

## Definition

Row-level Register object at logical name `1-0:73.50.0.255`. Average of power factor (PF) phase L3, period 2

## Aliases

- OBIS 1-0:73.50.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:73.50.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "73 power factor (PF) phase L3",
    "D": "50 average - period 2",
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
      "section": "Average power factor (PF) PHASE T - period 2 at 1-0:73.50.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about average of power factor (PF) phase L3.",
    "ABNT Appendix 9 describes this object as: average of power factor (PF) phase L3, period 2."
  ]
}
```

## Notes
