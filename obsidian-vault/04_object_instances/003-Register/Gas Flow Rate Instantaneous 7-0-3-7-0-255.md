---
id: KB-OBIS-7-0-3-7-0-255-GAS-FLOW-RATE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas flow rate instantaneous
aliases:
- Gas instantaneous flow rate
- Gas volume flow rate
- OBIS 7-0:3.7.0.255
keywords:
- 7-0:3.7.0.255
- gas flow rate instantaneous
- gas flow rate
- gas volume flow
domain_tags:
- cosem_object
- gas
- flow
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-51
---

# Gas flow rate instantaneous

## Definition

Row-level OBIS object for gas instantaneous flow rate, represented by logical name pattern `7-0:3.7.0.255`.

## Aliases

- Gas instantaneous flow rate
- Gas volume flow rate
- OBIS 7-0:3.7.0.255

## Domain Tags

- `cosem_object`
- `gas`
- `flow`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-51`

## Structured Data

```json metadata
{
  "obis_pattern": "7-0:3.7.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "0 no channel",
    "C": "3 flow rate",
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
      "section": "Table 51 gas C=3 flow rate"
    }
  ],
  "applicable_notes": [
    "C=3 identifies flow rate in the gas C-code family.",
    "D=7 identifies an instantaneous measurement value."
  ]
}
```

## Notes

