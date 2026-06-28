---
id: KB-ABNT-OBIS-1-0-91-54-0-255-NEUTRAL-MAXIMUM-CURRENT-PERIOD-2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Neutral Maximum current - period 2
aliases:
- OBIS 1-0:91.54.0.255
keywords:
- 1-0:91.54.0.255
- Neutral Maximum current - period 2
- TBL-000160
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-14
---

# Neutral Maximum current - period 2

## Definition

Row-level Register object at logical name `1-0:91.54.0.255`. Neutral Maximum current - period 2.

## Aliases

- OBIS 1-0:91.54.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-14`
## Structured Data

```json metadata
{
  "obis_pattern": "1-0:91.54.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "91 neutral current",
    "D": "54 maximum - period 2",
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
      "section": "Neutral Maximum current - period 2 at 1-0:91.54.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about neutral maximum current - period 2.",
    "ABNT Appendix 9 describes this object as: Neutral Maximum current - period 2."
  ]
}
```

## Notes
