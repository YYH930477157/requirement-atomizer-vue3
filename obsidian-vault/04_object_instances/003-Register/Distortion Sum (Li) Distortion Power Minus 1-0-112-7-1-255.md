---
id: KB-OBIS-1-0-112-7-1-255-DISTORTION-112-1
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Sum (Li) Distortion Power Minus (distortion)
aliases:
- OBIS 1-0:112.7.1.255
- distortion power sum (li) distortion power minus
keywords:
- 1-0:112.7.1.255
- distortion power
- distortion
- sum (li) distortion power minus
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

# Sum (Li) Distortion Power Minus (distortion)

## Definition

Row-level OBIS object for AC electricity total 3-phase distortion power, negative (QIII+QIV). Distortion power is the imaginary component of apparent power. E=1 per Blue Book Table 20. Pattern 1-0:112.7.1.255.

## Aliases

- OBIS 1-0:112.7.1.255
- distortion power sum (li) distortion power minus

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
  "obis_pattern": "1-0:112.7.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 ac_electricity",
    "B": "0 no channel",
    "C": "112 distortion power",
    "D": "7 instantaneous value",
    "E": "1 minus",
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
      "section": "Table 20 AC electricity distortion power; C=112, D=7, E=1"
    }
  ],
  "applicable_notes": [
    "C=112 identifies sum (Li) distortion power. E=1 = negative (QIII+QIV)."
  ]
}
```

## Notes

