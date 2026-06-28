---
id: KB-ABNT-OBIS-1-0-6-8-X-255-REACTIVE-ENERGY-QII-RC
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reactive energy QII (+Rc)
aliases:
- OBIS 1-0:6.8.x.255
- Absolute value
keywords:
- 1-0:6.8.x.255
- Reactive energy QII (+Rc)
- Absolute value
- TBL-000081
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-15
---

# Reactive energy QII (+Rc)

## Definition

Row-level Register object at logical name `1-0:6.8.x.255`. Reactive energy QII (+Rc).

## Aliases

- OBIS 1-0:6.8.x.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-15`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:6.8.x.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "6 reactive energy (Q2/+Rc)",
    "D": "8 billing/total",
    "E": "x tariff/rate index (templated)",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 15,
    "title": "Value group E codes - AC electricity - Tariff rates"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 15 Value group E codes - AC electricity - Tariff rates"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Reactive energy QII (+Rc) at 1-0:6.8.x.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about reactive energy qii (+rc).",
    "ABNT Appendix 9 describes this object as: Reactive energy QII (+Rc)."
  ]
}
```

## Notes
