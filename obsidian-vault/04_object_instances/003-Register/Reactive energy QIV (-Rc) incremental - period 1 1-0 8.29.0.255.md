---
id: KB-ABNT-OBIS-1-0-8-29-0-255-REACTIVE-ENERGY-QIV-RC-INCREMENTAL-PERIOD-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reactive energy QIV incremental period 1
aliases:
- OBIS 1-0:8.29.0.255
- value for the load profile - period 1
keywords:
- 1-0:8.29.0.255
- Reactive energy QIV (-Rc) incremental - period 1
- value for the load profile - period 1
- TBL-000084
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Reactive energy QIV incremental period 1

## Definition

Row-level Register object at logical name `1-0:8.29.0.255`. Reactive energy QIV (-Rc) incremental value for the load profile, period 1

## Aliases

- OBIS 1-0:8.29.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:8.29.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "8 reactive energy (Q4/-Rc)",
    "D": "29 incremental period 1",
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
      "section": "Reactive energy QIV incremental period 1 at 1-0:8.29.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about reactive energy qiv (-rc) incremental value for the load profile.",
    "ABNT Appendix 9 describes this object as: reactive energy QIV (-Rc) incremental value for the load profile, period 1."
  ]
}
```

## Notes
