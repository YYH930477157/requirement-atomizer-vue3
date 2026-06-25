---
id: KB-OBIS-1-0-9-8-0-255-APPARENT-ENERGY-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Apparent energy import total
aliases:
- Apparent energy import total 1-0:9.8.0.255
- VA+ total energy
keywords:
- 1-0:9.8.0.255
- Apparent energy import total
- VA+ total energy
- apparent energy import
domain_tags:
- cosem_object
- ac_electricity
- apparent_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Apparent energy import total

## Definition

Row-level OBIS object for AC electricity positive apparent energy total import, represented by logical name pattern `1-0:9.8.0.255`.

## Aliases

- Apparent energy import total 1-0:9.8.0.255
- VA+ total energy

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `apparent_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:9.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "9 apparent power+ / apparent energy import direction",
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
      "section": "Table 13 AC electricity C=9 apparent power+; D=8 time integral 1; E=0 total"
    }
  ],
  "applicable_notes": [
    "C=9 identifies the positive apparent power/energy direction for the aggregate phase system.",
    "D=8 and E=0 identify a totalized time-integral quantity."
  ]
}
```

## Notes

