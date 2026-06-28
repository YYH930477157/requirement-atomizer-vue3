---
id: KB-ABNT-OBIS-1-0-0-6-4-255-REFERENCE-VOLTAGE-FOR-POWER-QUALITY-MEASUREMENT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reference Voltage for power quality measurement
aliases:
- OBIS 1-0:0.6.4.255
keywords:
- 1-0:0.6.4.255
- Reference Voltage for power quality measurement
- TBL-000131
domain_tags:
- cosem_object
- ac_electricity
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-21
---

# Reference Voltage for power quality measurement

## Definition

Row-level Register object at logical name `1-0:0.6.4.255`. Reference voltage for power-quality measurement

## Aliases

- OBIS 1-0:0.6.4.255

## Domain Tags

- `cosem_object`
- `ac_electricity`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-21`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:0.6.4.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 electricity",
    "B": "0 no channel",
    "C": "0 general and service-entry object",
    "D": "6 maximum demand (current)",
    "E": "4 tariff/rate 4",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 21,
    "title": "OBIS codes for general and service entry objects - AC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 21 OBIS codes for general and service entry objects - AC electricity"
    },
    {
      "source": "ABNT Appendix 9 extracted table",
      "section": "Reference Voltage for power quality measurement at 1-0:0.6.4.255"
    }
  ],
  "applicable_notes": [
    "Use this row when matching requirements about reference voltage for power-quality measurement.",
    "ABNT Appendix 9 describes this object as: reference voltage for power-quality measurement."
  ]
}
```

## Notes
