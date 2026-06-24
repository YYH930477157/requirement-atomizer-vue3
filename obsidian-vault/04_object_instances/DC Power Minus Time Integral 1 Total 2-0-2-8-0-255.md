---
id: KB-OBIS-2-0-2-8-0-255-DC-POWER-EXPORT-INTEGRAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC power minus time integral 1 total
aliases:
- DC power minus integral 2-0:2.8.0.255
- DC export energy total
keywords:
- 2-0:2.8.0.255
- DC power minus time integral 1 total
- DC export energy total
- DC power minus integral
domain_tags:
- cosem_object
- dc_electricity
- active_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-26
---

# DC power minus time integral 1 total

## Definition

Row-level OBIS object for DC electricity negative power time integral 1 total, represented by logical name pattern `2-0:2.8.0.255`.

## Aliases

- DC power minus integral 2-0:2.8.0.255
- DC export energy total

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `active_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-26`

## Structured Data

```json metadata
{
  "obis_pattern": "2-0:2.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "0 no channel",
    "C": "2 power-",
    "D": "8 time integral 1",
    "E": "0 total",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 26,
    "title": "Value group C codes - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 26 DC electricity C=2 power-"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 27 DC electricity D=8 time integral 1"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 28 DC electricity E=0 total"
    }
  ],
  "applicable_notes": [
    "C=2 identifies DC power-.",
    "D=8 is time integral 1 and E=0 identifies total."
  ]
}
```

## Notes

