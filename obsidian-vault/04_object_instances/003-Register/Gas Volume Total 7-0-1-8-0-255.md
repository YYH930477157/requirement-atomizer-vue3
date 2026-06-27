---
id: KB-OBIS-7-0-1-8-0-255-GAS-VOLUME-TOTAL
kb_id: obsidian_energy_metering
type: cosem_object_instance
layer: cosem_object_instance
name: Gas volume total
aliases:
- Gas volume time integral 1 total
- Gas consumption total
- OBIS 7-0:1.8.0.255
keywords:
- 7-0:1.8.0.255
- gas volume total
- gas consumption total
- gas volume time integral
domain_tags:
- cosem_object
- gas
- volume
relations:
- relation: instance_of
  target: KB-L3-IC-3-REGISTER
- relation: defined_by
  target: KB-BLUE-BOOK-OBIS-TABLE-51
---

# Gas volume total

## Definition

Row-level OBIS object for gas volume total, represented by logical name pattern `7-0:1.8.0.255`.

## Aliases

- Gas volume time integral 1 total
- Gas consumption total
- OBIS 7-0:1.8.0.255

## Domain Tags

- `cosem_object`
- `gas`
- `volume`

## Relations

- `instance_of` -> `KB-L3-IC-3-REGISTER`
- `defined_by` -> `KB-BLUE-BOOK-OBIS-TABLE-51`

## Structured Data

```json metadata
{
  "obis_pattern": "7-0:1.8.0.255",
  "likely_interface_class_id": 3,
  "likely_interface_class_name": "Register",
  "medium": "gas",
  "value_group_mapping": {
    "A": "7 gas",
    "B": "0 no channel",
    "C": "1 gas volume",
    "D": "8 time integral 1",
    "E": "0 total",
    "F": "255 current billing period"
  },
  "blue_book_table_ref": {
    "part": 1,
    "table_no": 51,
    "title": "Value group C codes - Gas"
  },
  "source_refs": [
    {
      "source": "Blue Book Part 1 Ed. 16",
      "section": "Table 51 gas C=1 volume"
    }
  ],
  "applicable_notes": [
    "C=1 identifies volume in the gas C-code family.",
    "D=8 is used for time-integral quantities; E=0 identifies total."
  ]
}
```

## Notes

