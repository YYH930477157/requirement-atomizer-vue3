---
id: KB-OBIS-1-0-81-7-02-255-PHASEANGLE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Phase angle U(L1) to U(L3)
aliases:
- OBIS 1-0:81.7.02.255
- phase angle 02
keywords:
- 1-0:81.7.02.255
- phase angle
- 02
- power factor
domain_tags:
- cosem_object
- ac_electricity
- power_quality
- phase_angle
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-17
---

# Phase angle U(L1) to U(L3)

## Definition

Row-level OBIS object for AC electricity extended phase angle. E=02: angle of U(L3) referenced to U(L1). Pattern 1-0:81.7.02.255.

## Aliases

- OBIS 1-0:81.7.02.255
- phase angle 02

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`
- `phase_angle`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-17`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:81.7.02.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "81 phase angles",
    "D": "7 instantaneous value",
    "E": "02 phase angle matrix code",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 17,
    "title": "Value group E codes - AC electricity - Extended phase angle measurement"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 17 AC electricity phase angle matrix; C=81, D=7, E=02"
    }
  ],
  "applicable_notes": [
    "E=02 is a matrix code per Blue Book Table 17."
  ]
}
```

## Notes

