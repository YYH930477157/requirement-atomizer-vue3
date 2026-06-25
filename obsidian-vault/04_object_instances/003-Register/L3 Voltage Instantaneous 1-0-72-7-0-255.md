---
id: KB-OBIS-1-0-72-7-0-255-L3-VOLTAGE-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: L3 voltage instantaneous
aliases:
- Phase L3 voltage instantaneous
- OBIS 1-0:72.7.0.255
keywords:
- 1-0:72.7.0.255
- L3 voltage instantaneous
- phase L3 voltage
- voltage instantaneous L3
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

# L3 voltage instantaneous

## Definition

Row-level OBIS object for AC electricity phase L3 instantaneous voltage, represented by logical name pattern `1-0:72.7.0.255`.

## Aliases

- Phase L3 voltage instantaneous
- OBIS 1-0:72.7.0.255

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
  "obis_pattern": "1-0:72.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "72 voltage L3",
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
      "section": "Table 13 AC electricity C=72 voltage L3; Table 14 D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=72 identifies L3 voltage in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

