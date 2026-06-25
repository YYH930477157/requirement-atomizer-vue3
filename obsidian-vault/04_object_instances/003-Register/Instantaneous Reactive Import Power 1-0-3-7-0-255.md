---
id: KB-OBIS-1-0-3-7-0-255-INSTANTANEOUS-REACTIVE-IMPORT-POWER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous reactive import power (+Q)
aliases:
- Instantaneous reactive import power
- Reactive import power +Q
- OBIS 1-0:3.7.0.255
keywords:
- 1-0:3.7.0.255
- Instantaneous reactive import power
- reactive import power
- +Q
domain_tags:
- cosem_object
- ac_electricity
- reactive_power
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Instantaneous reactive import power (+Q)

## Definition

Row-level OBIS object for AC electricity instantaneous positive reactive import power, represented by logical name pattern `1-0:3.7.0.255`.

## Aliases

- Instantaneous reactive import power
- Reactive import power +Q
- OBIS 1-0:3.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `reactive_power`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:3.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "3 reactive power+",
    "D": "7 instantaneous value",
    "E": "0 total/default",
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
      "section": "Table 13 AC electricity C=3 reactive power+; Table 14 D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=3 identifies positive reactive power in quadrants I and II.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

