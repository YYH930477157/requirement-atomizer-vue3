---
id: KB-OBIS-1-0-1-8-0-255-ACTIVE-ENERGY-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Active energy import total
aliases:
- Positive active energy total
- A+ total energy
- OBIS 1-0:1.8.0.255
keywords:
- 1-0:1.8.0.255
- Active energy import total
- positive active energy total
- A+ total energy
- active energy import
domain_tags:
- cosem_object
- ac_electricity
- active_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Active energy import total

## Definition

Row-level OBIS object for AC electricity positive active energy total import, represented by logical name pattern `1-0:1.8.0.255`.

## Aliases

- Positive active energy total
- A+ total energy
- OBIS 1-0:1.8.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `active_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:1.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "1 active power+ / active energy import direction",
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
      "section": "Table 13 AC electricity C=1; tariff total E=0"
    }
  ],
  "applicable_notes": [
    "C=1 identifies active power/energy import direction for the aggregate phase system.",
    "D=8 is used for time-integral energy quantity families; E=0 identifies total."
  ]
}
```

## Notes

