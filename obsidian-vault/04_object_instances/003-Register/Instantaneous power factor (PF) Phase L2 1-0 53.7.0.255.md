---
id: KB-ABNT-OBIS-1-0-53-7-0-255-INSTANTANEOUS-POWER-FACTOR-PF-PHASE-L2
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous power factor (PF) Phase L2
aliases:
- OBIS 1-0:53.7.0.255
keywords:
- 1-0:53.7.0.255
- Instantaneous power factor (PF) Phase L2
- TBL-000124
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Instantaneous power factor (PF) Phase L2

## Definition

Row-level Register object at logical name `1-0:53.7.0.255`. Instantaneous power factor (PF) phase L2

## Aliases

- OBIS 1-0:53.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:53.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "53 power factor (PF) phase L2",
    "D": "7 instantaneous value",
    "E": "0 no tariff/total value",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 13,
    "title": "Value group C codes - AC Electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 13 Value group C codes - AC Electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Instantaneous power factor (PF) Phase L2 at 1-0:53.7.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about instantaneous power factor (PF) phase L2.",
    "ABNT Appendix 9 describes this object as: instantaneous power factor (PF) phase L2."
  ]
}
```

## Notes
