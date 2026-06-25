---
id: KB-OBIS-1-0-13-7-0-255-POWER-FACTOR-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Power factor instantaneous
aliases:
- Instantaneous power factor
- PF instantaneous
- OBIS 1-0:13.7.0.255
keywords:
- 1-0:13.7.0.255
- Power factor instantaneous
- instantaneous power factor
- PF+
domain_tags:
- cosem_object
- ac_electricity
- power_factor
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Power factor instantaneous

## Definition

Row-level OBIS object for AC electricity instantaneous power factor, represented by logical name pattern `1-0:13.7.0.255`.

## Aliases

- Instantaneous power factor
- PF instantaneous
- OBIS 1-0:13.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_factor`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:13.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "13 power factor",
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
      "section": "Table 13 AC electricity C=13 power factor; Table 14 D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=13 identifies aggregate power factor in the AC electricity C-code family.",
    "Blue Book Part 1 Table 13 Note 4 defines power factor in import/export directions from active and apparent power."
  ]
}
```

## Notes

