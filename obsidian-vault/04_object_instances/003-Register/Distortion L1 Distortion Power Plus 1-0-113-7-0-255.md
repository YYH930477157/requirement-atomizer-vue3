---
id: KB-OBIS-1-0-113-7-0-255-DISTORTION-113-0
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: L1 Distortion Power Plus (distortion)
aliases:
- OBIS 1-0:113.7.0.255
- distortion power l1 distortion power plus
keywords:
- 1-0:113.7.0.255
- distortion power
- distortion
- l1 distortion power plus
- power_quality
domain_tags:
- cosem_object
- ac_electricity
- power_quality
- distortion
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-20
---

# L1 Distortion Power Plus (distortion)

## Definition

Row-level OBIS object for AC electricity L1 distortion power, positive (QI+QII). Distortion power is the imaginary component of apparent power. E=0 per Blue Book Table 20. Pattern 1-0:113.7.0.255.

## Aliases

- OBIS 1-0:113.7.0.255
- distortion power l1 distortion power plus

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`
- `distortion`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-20`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:113.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 ac_electricity",
    "B": "0 no channel",
    "C": "113 distortion power",
    "D": "7 instantaneous value",
    "E": "0 plus",
    "F": "255 current"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 20,
    "title": "Value group E codes for distortion power and energy"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 20 AC electricity distortion power; C=113, D=7, E=0"
    }
  ],
  "applicable_notes": [
    "C=113 identifies L2 distortion power. E=0 = positive (QI+QII)."
  ]
}
```

## Notes

