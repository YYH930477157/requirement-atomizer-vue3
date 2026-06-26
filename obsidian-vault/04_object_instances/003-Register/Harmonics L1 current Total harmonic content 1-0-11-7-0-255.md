---
id: KB-OBIS-1-0-11-7-0-255-HARMONIC
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: L1 current Total harmonic content (harmonics)
aliases:
- OBIS 1-0:11.7.0.255
- L1 current harmonic total harmonic content
keywords:
- 1-0:11.7.0.255
- harmonics
- total harmonic content
- l1 current
domain_tags:
- cosem_object
- ac_electricity
- power_quality
- harmonics
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-16
---

# L1 current Total harmonic content (harmonics)

## Definition

Row-level OBIS object for AC electricity harmonic measurement. Total of L1 current. Pattern 1-0:11.7.0.255.

## Aliases

- OBIS 1-0:11.7.0.255
- L1 current harmonic total harmonic content

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `power_quality`
- `harmonics`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-16`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:11.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "11 L1 current",
    "D": "7 instantaneous value",
    "E": "0 total harmonic content",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 16,
    "title": "Value group E codes - AC electricity - Harmonics"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 16 AC electricity harmonics; C=11 L1 current, D=7, E=0 Total harmonic content"
    }
  ],
  "applicable_notes": [
    "E=0 identifies Total harmonic content per Blue Book Table 16."
  ]
}
```

## Notes

