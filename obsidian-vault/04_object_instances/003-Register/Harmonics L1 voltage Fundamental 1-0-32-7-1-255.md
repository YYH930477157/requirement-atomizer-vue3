---
id: KB-OBIS-1-0-32-7-1-255-HARMONIC
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: L1 voltage Fundamental (harmonics)
aliases:
- OBIS 1-0:32.7.1.255
- L1 voltage harmonic fundamental
keywords:
- 1-0:32.7.1.255
- harmonics
- fundamental
- l1 voltage
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

# L1 voltage Fundamental (harmonics)

## Definition

Row-level OBIS object for AC electricity harmonic measurement. Fundamental component of L1 voltage. Pattern 1-0:32.7.1.255.

## Aliases

- OBIS 1-0:32.7.1.255
- L1 voltage harmonic fundamental

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
  "obis_pattern": "1-0:32.7.1.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "32 L1 voltage",
    "D": "7 instantaneous value",
    "E": "1 fundamental",
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
      "section": "Table 16 AC electricity harmonics; C=32 L1 voltage, D=7, E=1 Fundamental"
    }
  ],
  "applicable_notes": [
    "E=1 identifies Fundamental per Blue Book Table 16."
  ]
}
```

## Notes

