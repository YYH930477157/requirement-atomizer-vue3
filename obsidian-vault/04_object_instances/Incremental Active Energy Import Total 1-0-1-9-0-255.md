---
id: KB-OBIS-1-0-1-9-0-255-INCREMENTAL-ACTIVE-ENERGY-IMPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Incremental active energy import (+A) - Total
aliases:
- Incremental active energy import
- Active energy import incremental total
- OBIS 1-0:1.9.0.255
keywords:
- 1-0:1.9.0.255
- Incremental active energy import
- active energy import incremental
- +A
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

# Incremental active energy import (+A) - Total

## Definition

Row-level OBIS object for AC electricity incremental active energy import total, represented by logical name pattern `1-0:1.9.0.255`.

## Aliases

- Incremental active energy import
- Active energy import incremental total
- OBIS 1-0:1.9.0.255

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
  "obis_pattern": "1-0:1.9.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "1 active power+ / active energy import direction",
    "D": "9 incremental energy counter",
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
      "section": "Table 13 AC electricity C=1 active energy import"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 AC electricity D=9 incremental energy"
    }
  ],
  "applicable_notes": [
    "C=1 identifies active energy import direction for the aggregate phase system.",
    "D=9 identifies an incremental energy counter."
  ]
}
```

## Notes
