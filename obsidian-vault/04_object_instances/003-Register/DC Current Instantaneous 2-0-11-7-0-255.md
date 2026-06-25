---
id: KB-OBIS-2-0-11-7-0-255-DC-CURRENT-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC current instantaneous
aliases:
- DC current 2-0:11.7.0.255
- DC instantaneous current
keywords:
- 2-0:11.7.0.255
- DC current instantaneous
- DC instantaneous current
- current instantaneous DC
domain_tags:
- cosem_object
- dc_electricity
- current
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-26
---

# DC current instantaneous

## Definition

Row-level OBIS object for DC electricity instantaneous current, represented by logical name pattern `2-0:11.7.0.255`.

## Aliases

- DC current 2-0:11.7.0.255
- DC instantaneous current

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `current`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-26`

## Structured Data

```json metadata
{
  "obis_pattern": "2-0:11.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "0 no channel",
    "C": "11 current",
    "D": "7 instantaneous value",
    "E": "0 total/default",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 26,
    "title": "Value group C codes - DC electricity"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 26 DC electricity C=11 current"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 27 DC electricity D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=11 identifies current in the DC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

