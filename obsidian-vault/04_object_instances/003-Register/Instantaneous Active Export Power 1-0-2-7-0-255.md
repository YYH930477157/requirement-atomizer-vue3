---
id: KB-OBIS-1-0-2-7-0-255-INSTANTANEOUS-ACTIVE-EXPORT-POWER
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Instantaneous active export power (-P)
aliases:
- Instantaneous active export power
- Active export power -P
- OBIS 1-0:2.7.0.255
keywords:
- 1-0:2.7.0.255
- Instantaneous active export power
- active export power
- -P
domain_tags:
- cosem_object
- ac_electricity
- active_power
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Instantaneous active export power (-P)

## Definition

Row-level OBIS object for AC electricity instantaneous active export power, represented by logical name pattern `1-0:2.7.0.255`.

## Aliases

- Instantaneous active export power
- Active export power -P
- OBIS 1-0:2.7.0.255

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `active_power`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:2.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "2 active power- / active energy export direction",
    "D": "7 instantaneous value",
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
      "section": "Table 13 AC electricity C=2 active power-"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 14 AC electricity D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=2 identifies active power export direction for the aggregate phase system.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes
