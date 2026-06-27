---
id: KB-OBIS-7-0-7-7-0-255-GAS-PRESSURE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas pressure instantaneous
aliases:
- Gas instantaneous pressure
- Gas process pressure
- OBIS 7-0:7.7.0.255
keywords:
- 7-0:7.7.0.255
- gas pressure instantaneous
- gas pressure
- gas process pressure
domain_tags:
- cosem_object
- gas
- pressure
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-51
---

# Gas pressure instantaneous

## Definition

Row-level OBIS object for gas instantaneous pressure, represented by logical name pattern `7-0:7.7.0.255`.

## Aliases

- Gas instantaneous pressure
- Gas process pressure
- OBIS 7-0:7.7.0.255

## Domain Tags

- `cosem_object`
- `gas`
- `pressure`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-51`

## Structured Data

```json metadata
{
  "obis_pattern": "7-0:7.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "0 no channel",
    "C": "7 pressure",
    "D": "7 instantaneous value",
    "E": "0 total/default",
    "F": "255 current value"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 51,
    "title": "Value group C codes - Gas"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 51 gas C=7 pressure"
    }
  ],
  "applicable_notes": [
    "C=7 identifies pressure in the gas C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

