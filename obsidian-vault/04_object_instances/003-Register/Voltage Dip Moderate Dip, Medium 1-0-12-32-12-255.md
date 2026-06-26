---
id: KB-OBIS-1-0-12-32-12-255-VOLTAGEDIP-12
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Voltage dip (moderate dip, medium)
aliases:
- OBIS 1-0:12.32.12.255
- voltage dip moderate dip, medium
- UNIPEDE voltage dip
keywords:
- 1-0:12.32.12.255
- voltage dip
- voltage sag
- UNIPEDE
- moderate dip, medium
- power_quality
domain_tags:
- cosem_object
- ac_electricity
- power_quality
- voltage_dip
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-19
---

# Voltage dip (moderate dip, medium)

## Definition

Row-level OBIS object for AC electricity UNIPEDE voltage dip measurement, 15-85% residual, 1-3s duration. E=12 is a matrix code (residual depth x duration) per Blue Book Table 19 / IEC TR 61000-2-8. Pattern 1-0:12.32.12.255.

## Aliases

- OBIS 1-0:12.32.12.255
- voltage dip moderate dip, medium
- UNIPEDE voltage dip

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`
- `voltage_dip`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-19`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:12.32.12.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 ac_electricity",
    "B": "0 no channel",
    "C": "12 L1 voltage",
    "D": "32 voltage dip measurement",
    "E": "12 UNIPEDE dip class",
    "F": "255 current"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 19,
    "title": "Value group E codes - AC electricity - UNIPEDE voltage dips"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 19 AC electricity UNIPEDE voltage dips; C=12, D=32, E=12 (15-85% residual, 1-3s duration)"
    }
  ],
  "applicable_notes": [
    "UNIPEDE dip class E=12: 15-85% residual, 1-3s duration."
  ]
}
```

## Notes

