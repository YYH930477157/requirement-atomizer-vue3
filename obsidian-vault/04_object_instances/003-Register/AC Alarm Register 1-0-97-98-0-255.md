---
id: KB-OBIS-1-0-97-98-0-255-ALARM-REG-AC
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: AC alarm register
aliases:
- OBIS 1-0:97.98.0.255
- alarm register ac
keywords:
- 1-0:97.98.0.255
- alarm register
- alarm
- 97.98
- ac_electricity
domain_tags:
- cosem_object
- ac_electricity
- alarm
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-9
---

# AC alarm register

## Definition

Row-level OBIS object for AC alarm register. Pattern 1-0:97.98.0.255.

## Aliases

- OBIS 1-0:97.98.0.255
- alarm register ac

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `alarm`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-9`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:97.98.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 ac_electricity",
    "B": "0 no channel",
    "C": "97 error/alarm objects",
    "D": "98 alarm register",
    "E": "0 alarm register instance 0",
    "F": "255 current"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 9,
    "title": "OBIS codes for error registers, alarm registers and alarm filters - Abstract"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 9 error/alarm objects; A=1, C=97, D=98, E=0"
    }
  ],
  "applicable_notes": [
    "Alarm register holds alarm status bits per Blue Book Table 9. E=0..9 available."
  ]
}
```

## Notes

