---
id: KB-OBIS-2-0-12-7-0-255-DC-VOLTAGE-INSTANTANEOUS
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: DC voltage instantaneous
aliases:
- DC voltage high to low instantaneous
- OBIS 2-0:12.7.0.255
keywords:
- 2-0:12.7.0.255
- DC voltage instantaneous
- DC voltage high to low
- voltage high to low instantaneous
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

# DC voltage instantaneous

## Definition

Row-level OBIS object for DC electricity instantaneous voltage from high to low, represented by logical name pattern `2-0:12.7.0.255`.

## Aliases

- DC voltage high to low instantaneous
- OBIS 2-0:12.7.0.255

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
  "obis_pattern": "2-0:12.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "dc_electricity",
  "value_group_mapping": {
    "A": "2 DC electricity",
    "B": "0 no channel",
    "C": "12 voltage high to low",
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
      "section": "Table 26 DC electricity C=12 voltage high to low"
    }
  ],
  "applicable_notes": [
    "C=12 identifies DC voltage high-to-low in the DC electricity C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

