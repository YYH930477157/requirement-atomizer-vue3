---
id: KB-OBIS-7-0-5-4-0-255-GAS-TEMPERATURE-AVERAGE
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas temperature average
aliases:
- Average gas temperature
- Gas process temperature average
- OBIS 7-0:5.4.0.255
keywords:
- 7-0:5.4.0.255
- gas temperature average
- average gas temperature
- gas process temperature average
domain_tags:
- cosem_object
- gas
- temperature
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-51
---

# Gas temperature average

## Definition

Row-level OBIS object for gas average temperature, represented by logical name pattern `7-0:5.4.0.255`.

## Aliases

- Average gas temperature
- Gas process temperature average
- OBIS 7-0:5.4.0.255

## Domain Tags

- `cosem_object`
- `gas`
- `temperature`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-51`

## Structured Data

```json metadata
{
  "obis_pattern": "7-0:5.4.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "0 no channel",
    "C": "5 temperature",
    "D": "4 average value",
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
      "section": "Table 51 gas C=5 temperature"
    }
  ],
  "applicable_notes": [
    "C=5 identifies temperature in the gas C-code family.",
    "D=4 identifies an average measurement value."
  ]
}
```

## Notes

