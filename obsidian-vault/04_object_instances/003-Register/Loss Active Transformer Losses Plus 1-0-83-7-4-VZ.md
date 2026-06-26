---
id: KB-OBIS-1-0-83-7-4-VZ-LOSS-4
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Loss active transformer losses plus
aliases:
- OBIS 1-0:83.7.4.VZ
- transformer line loss active transformer losses plus
keywords:
- 1-0:83.7.4.VZ
- loss
- active transformer losses plus
- transformer loss
- line loss
- power_quality
domain_tags:
- cosem_object
- ac_electricity
- power_quality
- loss
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-18
---

# Loss active transformer losses plus

## Definition

Row-level OBIS object for AC electricity No-load active transformer losses, positive (QI+QIV). E=4 (Active transformer losses plus) per Blue Book Table 18. Pattern 1-0:83.7.4.VZ.

## Aliases

- OBIS 1-0:83.7.4.VZ
- transformer line loss active transformer losses plus

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`
- `loss`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-18`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:83.7.4.VZ",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 ac_electricity",
    "B": "0 no channel",
    "C": "83 transformer and line losses",
    "D": "7 instantaneous value",
    "E": "4 active transformer losses plus",
    "F": "VZ wildcard"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 18,
    "title": "Value group E codes - AC electricity - Transformer and line losses"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 18 AC electricity transformer/line losses; C=83, D=7, E=4"
    }
  ],
  "applicable_notes": [
    "C=83 identifies transformer and line loss quantities. E=4 = Active transformer losses plus."
  ]
}
```

## Notes

