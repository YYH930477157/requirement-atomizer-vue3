---
id: KB-OBIS-1-0-32-7-0-255-L1-VOLTAGE-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: L1 voltage instantaneous
aliases:
- Phase L1 voltage instantaneous
- OBIS 1-0:32.7.0.255
keywords:
- 1-0:32.7.0.255
- L1 voltage instantaneous
- phase L1 voltage
- voltage instantaneous L1
domain_tags:
- cosem_object
- ac_electricity
- voltage
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# L1 voltage instantaneous

## Definition

Row-level OBIS object for AC electricity phase L1 instantaneous voltage, represented by logical name pattern `1-0:32.7.0.255`.

## Aliases

- Phase L1 voltage instantaneous
- OBIS 1-0:32.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `voltage`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:32.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "32 voltage L1",
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
      "section": "Table 13 AC electricity C=32 voltage L1"
    }
  ],
  "applicable_notes": [
    "C=32 identifies L1 voltage in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

