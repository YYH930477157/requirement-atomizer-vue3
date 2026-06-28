---
id: KB-ABNT-OBIS-1-0-7-9-X-255-REACTIVE-ENERGY-QIII-RI-INCREMENTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reactive energy QIII (-Ri) incremental
aliases:
- OBIS 1-0:7.9.x.255
- Incremental value
keywords:
- 1-0:7.9.x.255
- Reactive energy QIII (-Ri) incremental
- Incremental value
- TBL-000083
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Reactive energy QIII (-Ri) incremental

## Definition

Row-level Register object at logical name `1-0:7.9.x.255`. Reactive energy QIII (-Ri) incremental.

## Aliases

- OBIS 1-0:7.9.x.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:7.9.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "7 reactive energy (Q3/-Ri)",
    "D": "9 incremental",
    "E": "x tariff/rate index (templated)",
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
      "section": "Reactive energy QIII (-Ri) incremental at 1-0:7.9.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about reactive energy qiii (-ri) incremental.",
    "ABNT Appendix 9 describes this object as: Reactive energy QIII (-Ri) incremental."
  ]
}
```

## Notes
