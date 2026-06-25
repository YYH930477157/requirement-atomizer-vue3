---
id: KB-OBIS-1-0-2-9-0-255-INCREMENTAL-ACTIVE-ENERGY-EXPORT
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Incremental active energy export (-A) - Total
aliases:
- Incremental active energy export
- Active energy export incremental total
- OBIS 1-0:2.9.0.255
keywords:
- 1-0:2.9.0.255
- Incremental active energy export
- active energy export incremental
- -A
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

# Incremental active energy export (-A) - Total

## Definition

Row-level OBIS object for AC electricity incremental active energy export total, represented by logical name pattern `1-0:2.9.0.255`.

## Aliases

- Incremental active energy export
- Active energy export incremental total
- OBIS 1-0:2.9.0.255

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
  "obis_pattern": "1-0:2.9.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "2 active power- / active energy export direction",
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
      "section": "Table 13 AC electricity C=2 active energy export"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 AC electricity D=9 incremental energy"
    }
  ],
  "applicable_notes": [
    "C=2 identifies active energy export direction for the aggregate phase system.",
    "D=9 identifies an incremental energy counter."
  ]
}
```

## Notes
