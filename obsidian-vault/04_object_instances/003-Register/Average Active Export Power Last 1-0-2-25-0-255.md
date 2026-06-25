---
id: KB-OBIS-1-0-2-25-0-255-AVERAGE-ACTIVE-EXPORT-POWER-LAST
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Average active export power (-A) - Last
aliases:
- Average active export power last
- Active export average power last
- OBIS 1-0:2.25.0.255
keywords:
- 1-0:2.25.0.255
- Average active export power
- active export average power
- -A
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

# Average active export power (-A) - Last

## Definition

Row-level OBIS object for AC electricity average active export power for the last period, represented by logical name pattern `1-0:2.25.0.255`.

## Aliases

- Average active export power last
- Active export average power last
- OBIS 1-0:2.25.0.255

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
  "obis_pattern": "1-0:2.25.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "2 active power- / active energy export direction",
    "D": "25 average value last",
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
      "section": "Table 14 AC electricity D=25 average value last"
    }
  ],
  "applicable_notes": [
    "D=25 identifies the previous-average window for the meter's active export trend.",
    "Use this row when requirements refer to the last average active export power."
  ]
}
```

## Notes
