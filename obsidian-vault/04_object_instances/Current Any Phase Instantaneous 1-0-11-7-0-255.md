---
id: KB-OBIS-1-0-11-7-0-255-CURRENT-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Current any phase instantaneous
aliases:
- Current any phase 1-0:11.7.0.255
- Instantaneous current any phase
keywords:
- 1-0:11.7.0.255
- Current any phase instantaneous
- instantaneous current any phase
- current instantaneous AC
domain_tags:
- cosem_object
- ac_electricity
- current
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Current any phase instantaneous

## Definition

Row-level OBIS object for AC electricity instantaneous current for any phase, represented by logical name pattern `1-0:11.7.0.255`.

## Aliases

- Current any phase 1-0:11.7.0.255
- Instantaneous current any phase

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `current`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

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
    "C": "11 current any phase",
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
      "section": "Table 13 AC electricity C=11 current; D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=11 identifies current in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

