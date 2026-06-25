---
id: KB-OBIS-1-0-4-8-0-255-REACTIVE-ENERGY-EXPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Reactive energy export total
aliases:
- Negative reactive energy total
- Reactive energy export
- OBIS 1-0:4.8.0.255
keywords:
- 1-0:4.8.0.255
- Reactive energy export total
- reactive energy export
- negative reactive energy total
domain_tags:
- cosem_object
- ac_electricity
- reactive_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Reactive energy export total

## Definition

Row-level OBIS object for AC electricity negative reactive energy total export, represented by logical name pattern `1-0:4.8.0.255`.

## Aliases

- Negative reactive energy total
- Reactive energy export
- OBIS 1-0:4.8.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `reactive_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:4.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "4 reactive power- / reactive energy export direction",
    "D": "8 time integral 1",
    "E": "0 total",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 13,
    "title": "Value group C codes - AC Electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 13 AC electricity C=4 reactive power-; Table 14 D=8 time integral 1; Table 15 E=0 total"
    }
  ],
  "applicable_notes": [
    "C=4 identifies negative reactive power or reactive energy in quadrants III and IV.",
    "D=8 identifies time integral 1; E=0 identifies total."
  ]
}
```

## Notes

