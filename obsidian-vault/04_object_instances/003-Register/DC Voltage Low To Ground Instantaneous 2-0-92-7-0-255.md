---
id: KB-OBIS-2-0-92-7-0-255-DC-VOLTAGE-LOW-TO-GROUND
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC voltage low to ground instantaneous
aliases:
- DC voltage low-to-ground 2-0:92.7.0.255
- DC low to ground voltage instantaneous
keywords:
- 2-0:92.7.0.255
- DC voltage low to ground instantaneous
- DC voltage low-to-ground
- low to ground voltage instantaneous
domain_tags:
- cosem_object
- dc_electricity
- voltage
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-26
---

# DC voltage low to ground instantaneous

## Definition

Row-level OBIS object for DC electricity instantaneous voltage from low to ground, represented by logical name pattern `2-0:92.7.0.255`.

## Aliases

- DC voltage low-to-ground 2-0:92.7.0.255
- DC low to ground voltage instantaneous

## Domain Tags

- `cosem_object`
- `dc_electricity`
- `voltage`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-26`

## Structured Data

```json metadata
{
  "obis_pattern": "2-0:92.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "0 no channel",
    "C": "92 voltage low to ground",
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
      "section": "Table 26 DC electricity C=92 voltage low to ground"
    },
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 27 DC electricity D=7 instantaneous value"
    }
  ],
  "applicable_notes": [
    "C=92 identifies DC voltage low-to-ground in the DC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

