---
id: KB-OBIS-2-0-1-7-0-255-DC
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Dc Active Power Import Instantaneous
aliases:
- OBIS 2-0:1.7.0.255
- DC active power import instantaneous
keywords:
- 2-0:1.7.0.255
- DC active power import instantaneous
- dc
- dc_electricity
domain_tags:
- cosem_object
- dc_electricity
- active_energy
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-27
---

# Dc Active Power Import Instantaneous

## Definition

Row-level OBIS object for DC active power import instantaneous. Pattern 2-0:1.7.0.255.

## Aliases

- OBIS 2-0:1.7.0.255
- DC active power import instantaneous

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `active_energy`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-27`

## Structured Data

```json metadata
{
  "obis_pattern": "2-0:1.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 dc_electricity",
    "B": "0",
    "C": "1",
    "D": "7 instantaneous value",
    "E": "0 total",
    "F": "255"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 27,
    "title": "Value group D codes - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 27 DC electricity D codes; C=1, D=instantaneous"
    }
  ],
  "applicable_notes": [
    "D=7 instantaneous value per Blue Book Table 27."
  ]
}
```

## Notes

