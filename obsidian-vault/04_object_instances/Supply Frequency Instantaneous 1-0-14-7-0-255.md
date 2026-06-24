---
id: KB-OBIS-1-0-14-7-0-255-SUPPLY-FREQUENCY
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Supply frequency instantaneous
aliases:
- Supply frequency 1-0:14.7.0.255
- Instantaneous supply frequency
keywords:
- 1-0:14.7.0.255
- Supply frequency instantaneous
- instantaneous supply frequency
- AC supply frequency
domain_tags:
- cosem_object
- ac_electricity
- frequency
- power_quality
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-13
---

# Supply frequency instantaneous

## Definition

Row-level OBIS object for AC electricity instantaneous supply frequency, represented by logical name pattern `1-0:14.7.0.255`.

## Aliases

- Supply frequency 1-0:14.7.0.255
- Instantaneous supply frequency

## Domain Tags

- `cosem_object`
- `ac_electricity`
- `frequency`
- `power_quality`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-13`

## Structured Data

```json metadata
{
  "obis_pattern": "1-0:14.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "ac_electricity",
  "value_group_mapping": {
    "A": "1 AC electricity",
    "B": "0 no channel",
    "C": "14 supply frequency",
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
      "section": "Table 13 AC electricity C=14 supply frequency; D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=14 identifies supply frequency in the AC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

