---
id: KB-ABNT-OBIS-1-0-15-7-0-255-INSTANTANEOUS-ACTIVE-POWER-Q1-Q2-Q3-Q4-L1-L2-L3-SUMM-OF-ALL-PHASES
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)
aliases:
- OBIS 1-0:15.7.0.255
keywords:
- 1-0:15.7.0.255
- Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)
- TBL-000120
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases)

## Definition

Row-level Register object at logical name `1-0:15.7.0.255`. Instantaneous active power (sum Q1-Q4) phase L1

## Aliases

- OBIS 1-0:15.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:15.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "15 active power (sum Q1-Q4) phase L1",
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
      "section": "Instantaneous active power (Q1 + Q2 + Q3 + Q4) (L1 + L2 + L3) (Summ of all phases) at 1-0:15.7.0.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about instantaneous active power (sum Q1-Q4) phase L1.",
    "ABNT Appendix 9 describes this object as: instantaneous active power (sum Q1-Q4) phase L1."
  ]
}
```

## Notes
